"""적응형 모델 라우팅 입력군의 DB 저장과 policy projection.

운영 입력은 embedding provider에 일시적으로 전달될 수 있지만, 이 저장소에는
원문 대신 SHA-256 해시, 벡터, 시간, cohort 매칭 결과만 저장한다.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Iterable, Mapping, Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.shared.db.models.model_routing_cohort import (
    LLMNodeModelRoutingCohort,
    LLMNodeModelRoutingCohortExample,
    LLMNodeModelRoutingModelEvidence,
    LLMNodeModelRoutingObservation,
)
from apps.shared.db.models.model_routing_policy import LLMNodeModelRoutingPolicy
from apps.shared.db.models.workflow_run import WorkflowNodeRun, WorkflowRun
from apps.shared.services.node_config_fingerprint import llm_node_config_fingerprint
from apps.workflow_engine.services.model_router import ModelRouter
from apps.workflow_engine.services.model_routing_adaptive_cohorts import (
    AdaptiveCohortService,
    CohortObservation,
    CohortState,
)
from apps.workflow_engine.services.model_routing_adaptive_policy import (
    AdaptiveCohortRoute,
    AdaptiveModelRoutingPolicyService,
)


EmbeddingFunction = Callable[[str], list[float]]


class AdaptiveModelRoutingCohortStore:
    """관찰 기록, 자동 발견, 수명 주기, runtime catalog를 일관되게 관리한다."""

    DEFAULT_MAX_COHORTS = 6
    MAX_PROPOSED_OR_VALIDATING = 4
    DISCOVERY_WINDOW_SIZE = 40
    MIN_DISTINCT_INPUTS = 5
    MIN_REVIEW_WINDOWS = 2
    MAX_RUNTIME_REPRESENTATIVES = 8
    # 자동 발견 단계는 표현이 다양한 신규 트렌드를 놓치지 않도록 0.50으로
    # 군집화한다. 실제 관찰 저장과 runtime 라우팅은 다른 업무 문의가 섞이지
    # 않도록 더 보수적인 0.55를 사용한다.
    DISCOVERY_SIMILARITY_THRESHOLD = 0.50
    AUTO_MATCH_SIMILARITY_THRESHOLD = 0.55
    MANUAL_SIMILARITY_THRESHOLD = 0.60
    DEFAULT_MATCH_MIN_MARGIN = 0.05
    MAX_REPRESENTATIVE_EXAMPLES = 5

    @classmethod
    def record_observation(
        cls,
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        workflow_run: WorkflowRun,
        node_run: WorkflowNodeRun,
        node_data: dict[str, Any],
        encoder_model_id: str,
        embed: EmbeddingFunction,
    ) -> LLMNodeModelRoutingObservation | None:
        """성공한 배포 LLM node 실행 하나를 non-reversible observation으로 기록한다."""
        query_text = cls._query_text(node_run.inputs, node_data)
        if not query_text:
            return None
        vector = cls._embedding(embed, query_text)
        if not vector:
            return None

        input_hash = hashlib.sha256(query_text.encode("utf-8")).hexdigest()
        existing = (
            db.query(LLMNodeModelRoutingObservation)
            .filter(LLMNodeModelRoutingObservation.policy_id == policy.id)
            .filter(LLMNodeModelRoutingObservation.workflow_node_run_id == node_run.id)
            .first()
        )
        if existing is not None:
            return existing

        cohorts = cls._live_cohorts(db, policy_id=policy.id)
        example_embeddings_by_cohort = cls._example_embeddings_by_cohort(
            db,
            cohorts=cohorts,
        )
        matched = cls._match(
            vector,
            cohorts,
            min_margin=cls._match_min_margin(policy, node_data),
            example_embeddings_by_cohort=example_embeddings_by_cohort,
        )
        observation_count = (
            db.query(LLMNodeModelRoutingObservation)
            .filter(LLMNodeModelRoutingObservation.policy_id == policy.id)
            .count()
        )
        observation = LLMNodeModelRoutingObservation(
            policy_id=policy.id,
            workflow_run_id=workflow_run.id,
            workflow_node_run_id=node_run.id,
            input_hash=input_hash,
            # policy version은 검증/갱신 실패 때 바뀌지 않을 수 있으므로, 관찰 순번으로
            # review window를 만든다. 그래야 서로 다른 점검 구간에서 반복된 입력군만
            # 자동 제안된다.
            review_window_key=f"window-{observation_count // max(1, int(policy.refresh_every_runs or 20))}",
            encoder_model_id=encoder_model_id,
            embedding=vector,
            matched_cohort_id=getattr(matched, "id", None),
            match_status=("matched" if matched is not None else "unmatched"),
            observed_at=cls._observed_at(node_run),
        )
        try:
            with db.begin_nested():
                db.add(observation)
                db.flush()
                if matched is not None:
                    matched.observation_count = int(matched.observation_count or 0) + 1
                    matched.last_seen_at = observation.observed_at
            return observation
        except IntegrityError:
            return (
                db.query(LLMNodeModelRoutingObservation)
                .filter(LLMNodeModelRoutingObservation.policy_id == policy.id)
                .filter(LLMNodeModelRoutingObservation.workflow_node_run_id == node_run.id)
                .first()
            )

    @classmethod
    def discover_and_advance(
        cls,
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        node_data: dict[str, Any],
        now: datetime | None = None,
    ) -> list[LLMNodeModelRoutingCohort]:
        """최근 관찰값을 기준으로 입력군을 제안하고 기존 군의 수명 주기를 갱신한다."""
        now = now or datetime.now(timezone.utc)
        observations = (
            db.query(LLMNodeModelRoutingObservation)
            .filter(LLMNodeModelRoutingObservation.policy_id == policy.id)
            .order_by(LLMNodeModelRoutingObservation.observed_at.desc())
            .limit(cls.DISCOVERY_WINDOW_SIZE)
            .all()
        )
        observations = list(reversed(observations))
        cohorts = cls._live_cohorts(db, policy_id=policy.id)
        cls._advance_existing_lifecycles(cohorts, observations=observations, now=now)

        unmatched = [
            observation
            for observation in observations
            if observation.match_status == "unmatched"
        ]
        windows = {
            value: index
            for index, value in enumerate(
                sorted({str(item.review_window_key) for item in unmatched})
            )
        }
        discovered = AdaptiveCohortService.discover(
            [
                CohortObservation(
                    input_hash=str(item.input_hash),
                    embedding=tuple(item.embedding or ()),
                    review_window=windows.get(str(item.review_window_key), 0),
                    observed_at=item.observed_at,
                )
                for item in unmatched
            ],
            minimum_distinct_inputs=cls.MIN_DISTINCT_INPUTS,
            minimum_review_windows=cls.MIN_REVIEW_WINDOWS,
            similarity_threshold=cls.DISCOVERY_SIMILARITY_THRESHOLD,
        )

        existing_keys = {str(cohort.cohort_key) for cohort in cohorts}
        capacity = cls.available_cohort_slots(
            cohorts,
            max_cohorts=getattr(policy, "max_cohorts", cls.DEFAULT_MAX_COHORTS),
            proposed_or_validating_cap=cls.MAX_PROPOSED_OR_VALIDATING,
        )
        created: list[LLMNodeModelRoutingCohort] = []
        fingerprint = llm_node_config_fingerprint(node_data)
        for candidate in discovered[:capacity]:
            cohort_key = cls._cohort_key(candidate.member_input_hashes)
            if cohort_key in existing_keys:
                continue
            ordinal = len(cohorts) + len(created) + 1
            row = LLMNodeModelRoutingCohort(
                policy_id=policy.id,
                cohort_key=cohort_key,
                label=f"자동 발견 입력군 {ordinal}",
                label_en=f"auto_cohort_{ordinal}",
                source="auto",
                status="proposed",
                # 안전군은 기존 policy의 명시적인 safety_override rule이 소유한다.
                # 자동 발견군이 vector 중심점만으로 safety 상태를 상속하면 일반
                # 문의도 고위험군처럼 오분류될 수 있으므로 여기서는 승격하지 않는다.
                required=False,
                safety_protected=False,
                encoder_model_id=cls._encoder_model_id(observations),
                centroid_embedding=list(candidate.centroid),
                observation_count=candidate.distinct_input_count,
                review_window_count=len(candidate.review_windows),
                node_config_fingerprint=fingerprint,
                first_seen_at=now,
                last_seen_at=now,
            )
            db.add(row)
            db.flush()
            member_hashes = set(candidate.member_input_hashes)
            for observation in unmatched:
                if observation.input_hash not in member_hashes:
                    continue
                observation.matched_cohort_id = row.id
                observation.match_status = "matched"
            created.append(row)
        db.flush()
        return created

    @classmethod
    def available_cohort_slots(
        cls,
        cohorts: Iterable[Any],
        *,
        max_cohorts: int | None,
        proposed_or_validating_cap: int | None = None,
    ) -> int:
        """현재 routing/검증에 참여하는 입력군만 최대 개수에 포함한다.

        dormant와 retired는 예전 트렌드를 보관하는 상태다. 이들이 새 트렌드 발견을
        막으면 입력군 수 제한이 시간이 지날수록 영구적으로 소진되므로 제외한다.
        """
        maximum = max(1, int(max_cohorts or cls.DEFAULT_MAX_COHORTS))
        rows = list(cohorts)
        occupied = sum(
            str(getattr(row, "status", ""))
            in {"proposed", "validating", "validated_waiting", "active"}
            for row in rows
        )
        remaining = max(0, maximum - occupied)
        if proposed_or_validating_cap is None:
            return remaining
        pending = sum(
            str(getattr(row, "status", ""))
            in {"proposed", "validating", "validated_waiting"}
            for row in rows
        )
        return min(remaining, max(0, int(proposed_or_validating_cap) - pending))

    @classmethod
    def create_manual_cohort(
        cls,
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        node_data: dict[str, Any],
        cohort_id: Any | None = None,
        label: str,
        cohort_key: str,
        representative_query: str,
        representative_examples: Sequence[str] | None = None,
        fixed: bool,
        encoder_model_id: str,
        embed: EmbeddingFunction,
    ) -> LLMNodeModelRoutingCohort:
        """사용자가 등록한 대표 문의를 저장 가능한 입력군으로 만든다.

        이 row는 즉시 저비용 모델을 실행하지 않는다. 운영 실행에서 같은 입력군의
        관찰값이 다섯 개 이상 모이고 Replay 검증을 통과해야만 active route가 된다.
        """
        normalized_label = " ".join(str(label or "").split())[:255]
        normalized_key = str(cohort_key or "").strip().lower()[:128]
        normalized_query = " ".join(str(representative_query or "").split())[:2000]
        if not normalized_label or not normalized_key or not normalized_query:
            raise ValueError("model_routing.cohort_invalid")

        cohorts = cls._live_cohorts(db, policy_id=policy.id)
        if any(str(item.cohort_key) == normalized_key for item in cohorts):
            raise ValueError("model_routing.cohort_key_exists")
        if cls.available_cohort_slots(
            cohorts,
            max_cohorts=getattr(policy, "max_cohorts", cls.DEFAULT_MAX_COHORTS),
            proposed_or_validating_cap=None,
        ) <= 0:
            raise ValueError("model_routing.cohort_limit_reached")

        examples = cls._normalize_representative_examples(
            normalized_query,
            representative_examples,
        )
        vectors = [cls._embedding(embed, text) for text in examples]
        if any(not vector for vector in vectors):
            raise ValueError("model_routing.cohort_embedding_failed")
        centroid = cls._average_vectors(vectors)

        now = datetime.now(timezone.utc)
        cohort = LLMNodeModelRoutingCohort(
            id=cohort_id or uuid.uuid4(),
            policy_id=policy.id,
            cohort_key=normalized_key,
            label=normalized_label,
            label_en=normalized_key,
            source="manual",
            status="proposed",
            # 고정 입력군만 저빈도여도 자동 휴면/종료 처리하지 않는다. 직접 등록한
            # 입력군이라도 고정을 해제하면 실제 traffic 변화에 따라 lifecycle을 따른다.
            required=bool(fixed),
            safety_protected=False,
            encoder_model_id=str(encoder_model_id),
            centroid_embedding=centroid,
            node_config_fingerprint=llm_node_config_fingerprint(node_data),
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(cohort)
        db.flush()

        from apps.shared.db.models.model_routing_cohort import (
            LLMNodeModelRoutingCohortExample,
        )

        for ordinal, (text, vector) in enumerate(zip(examples, vectors), start=1):
            db.add(
                LLMNodeModelRoutingCohortExample(
                    cohort_id=cohort.id,
                    synthetic_text=text,
                    embedding=vector,
                    ordinal=ordinal,
                )
            )
        db.flush()
        return cohort

    @classmethod
    def update_manual_cohort(
        cls,
        db: Session,
        *,
        cohort: LLMNodeModelRoutingCohort,
        policy: LLMNodeModelRoutingPolicy,
        node_data: dict[str, Any],
        label: str,
        cohort_key: str,
        representative_query: str,
        representative_examples: Sequence[str] | None = None,
        fixed: bool,
        encoder_model_id: str,
        embed: EmbeddingFunction,
    ) -> LLMNodeModelRoutingCohort:
        """직접 등록 입력군을 새 의미 기준으로 다시 검증 대기 상태로 만든다.

        대표 문의를 바꾸면 centroid와 기존 품질 증거가 더 이상 같은 입력군을
        설명하지 않는다. 따라서 기존 route/evidence를 즉시 사용하지 않고,
        운영 관찰과 Replay 검증을 다시 거치도록 상태를 초기화한다.
        """
        if cohort.source != "manual":
            raise ValueError("model_routing.cohort_auto_read_only")

        normalized_label = " ".join(str(label or "").split())[:255]
        normalized_key = str(cohort_key or "").strip().lower()[:128]
        normalized_query = " ".join(str(representative_query or "").split())[:2000]
        if not normalized_label or not normalized_key or not normalized_query:
            raise ValueError("model_routing.cohort_invalid")

        cohorts = cls._live_cohorts(db, policy_id=policy.id)
        if any(
            item.id != cohort.id and str(item.cohort_key) == normalized_key
            for item in cohorts
        ):
            raise ValueError("model_routing.cohort_key_exists")

        examples = cls._normalize_representative_examples(
            normalized_query,
            representative_examples,
        )
        vectors = [cls._embedding(embed, text) for text in examples]
        if any(not vector for vector in vectors):
            raise ValueError("model_routing.cohort_embedding_failed")
        centroid = cls._average_vectors(vectors)

        now = datetime.now(timezone.utc)
        cohort.cohort_key = normalized_key
        cohort.label = normalized_label
        cohort.label_en = normalized_key
        cohort.required = bool(fixed)
        cohort.encoder_model_id = str(encoder_model_id)
        cohort.centroid_embedding = centroid
        cohort.status = "proposed"
        cohort.observation_count = 0
        cohort.review_window_count = 0
        cohort.low_share_streak = 0
        cohort.last_traffic_share = Decimal("0")
        cohort.node_config_fingerprint = llm_node_config_fingerprint(node_data)
        cohort.last_seen_at = now
        cohort.dormant_since = None
        cohort.retired_at = None

        existing_examples = (
            db.query(LLMNodeModelRoutingCohortExample)
            .filter(LLMNodeModelRoutingCohortExample.cohort_id == cohort.id)
            .order_by(LLMNodeModelRoutingCohortExample.ordinal.asc())
            .all()
        )
        existing_by_ordinal = {int(item.ordinal): item for item in existing_examples}
        for ordinal, (text, vector) in enumerate(zip(examples, vectors), start=1):
            example = existing_by_ordinal.pop(ordinal, None)
            if example is None:
                db.add(
                    LLMNodeModelRoutingCohortExample(
                        cohort_id=cohort.id,
                        synthetic_text=text,
                        embedding=vector,
                        ordinal=ordinal,
                    )
                )
            else:
                example.synthetic_text = text
                example.embedding = vector
        for obsolete in existing_by_ordinal.values():
            db.delete(obsolete)

        for evidence in (
            db.query(LLMNodeModelRoutingModelEvidence)
            .filter(LLMNodeModelRoutingModelEvidence.cohort_id == cohort.id)
            .all()
        ):
            evidence.status = "expired"
            evidence.expires_at = now
        # 수정 전 대표 문의에 매칭됐던 운영 관찰값은 새 입력군의 품질 증거가 아니다.
        # 유지하면 validation planner가 과거 문의로 새 정의를 바로 검증해 버린다.
        (
            db.query(LLMNodeModelRoutingObservation)
            .filter(LLMNodeModelRoutingObservation.policy_id == policy.id)
            .filter(LLMNodeModelRoutingObservation.matched_cohort_id == cohort.id)
            .update(
                {
                    "matched_cohort_id": None,
                    "match_status": "unmatched",
                },
                synchronize_session=False,
            )
        )
        db.flush()
        return cohort

    @classmethod
    def convert_auto_cohort_to_manual(
        cls,
        db: Session,
        *,
        cohort: LLMNodeModelRoutingCohort,
        policy: LLMNodeModelRoutingPolicy,
        node_data: dict[str, Any],
        label: str,
        cohort_key: str,
        representative_query: str,
        representative_examples: Sequence[str] | None = None,
        fixed: bool,
        encoder_model_id: str,
        embed: EmbeddingFunction,
    ) -> LLMNodeModelRoutingCohort:
        """자동 발견 row를 유지한 채 사용자가 관리하는 입력군으로 전환한다."""
        if cohort.source != "auto":
            raise ValueError("model_routing.cohort_not_auto")
        cohort.source = "manual"
        return cls.update_manual_cohort(
            db,
            cohort=cohort,
            policy=policy,
            node_data=node_data,
            label=label,
            cohort_key=cohort_key,
            representative_query=representative_query,
            representative_examples=representative_examples,
            fixed=fixed,
            encoder_model_id=encoder_model_id,
            embed=embed,
        )

    @classmethod
    def build_runtime_catalog(
        cls,
        db: Session,
        *,
        policy_id: Any,
        policy: LLMNodeModelRoutingPolicy,
        node_data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """검증되어 active인 cohort를 기존 semantic matcher의 catalog로 투영한다."""
        cohorts = (
            db.query(LLMNodeModelRoutingCohort)
            .filter(LLMNodeModelRoutingCohort.policy_id == policy_id)
            .filter(LLMNodeModelRoutingCohort.status == "active")
            .order_by(LLMNodeModelRoutingCohort.cohort_key.asc())
            .all()
        )
        if not cohorts:
            return None
        encoder_model_id = str(cohorts[0].encoder_model_id or "").strip()
        if not encoder_model_id:
            return None
        routes = [
            AdaptiveCohortRoute(
                cohort_id=str(cohort.cohort_key),
                label=str(cohort.label),
                status=str(cohort.status),
                validated=True,
                centroid_embedding=tuple(cohort.centroid_embedding or ()),
                representative_embeddings=cls._runtime_representative_embeddings(
                    db,
                    policy_id=policy_id,
                    cohort=cohort,
                ),
                safety_override=bool(cohort.safety_protected),
                threshold=(
                    cls.MANUAL_SIMILARITY_THRESHOLD
                    if str(getattr(cohort, "source", "")) == "manual"
                    else cls.AUTO_MATCH_SIMILARITY_THRESHOLD
                ),
            )
            for cohort in cohorts
        ]
        return AdaptiveModelRoutingPolicyService.build_runtime_catalog(
            encoder_model_id=encoder_model_id,
            input_paths=cls._input_paths(node_data),
            routes=routes,
            preserved_safety_routes=cls._preserved_safety_routes(policy),
        )

    @classmethod
    def _runtime_representative_embeddings(
        cls,
        db: Session,
        *,
        policy_id: Any,
        cohort: LLMNodeModelRoutingCohort,
    ) -> tuple[tuple[float, ...], ...]:
        """대표 문의와 최근 매칭 입력의 비가역 벡터를 bounded set으로 만든다."""
        examples = (
            db.query(LLMNodeModelRoutingCohortExample)
            .filter(LLMNodeModelRoutingCohortExample.cohort_id == cohort.id)
            .order_by(LLMNodeModelRoutingCohortExample.ordinal.asc())
            .limit(cls.MAX_RUNTIME_REPRESENTATIVES)
            .all()
        )
        remaining = max(0, cls.MAX_RUNTIME_REPRESENTATIVES - len(examples))
        observations = []
        if remaining:
            observations = (
                db.query(LLMNodeModelRoutingObservation)
                .filter(LLMNodeModelRoutingObservation.policy_id == policy_id)
                .filter(LLMNodeModelRoutingObservation.matched_cohort_id == cohort.id)
                .order_by(LLMNodeModelRoutingObservation.observed_at.desc())
                .limit(remaining)
                .all()
            )
        if str(getattr(cohort, "source", "")) == "manual" and observations:
            anchors = [
                list(getattr(example, "embedding", None) or [])
                for example in examples
                if getattr(example, "embedding", None)
            ] or [list(cohort.centroid_embedding or [])]
            # 직접 정의 입력군도 실제 표현 변형을 학습할 수는 있어야 한다.
            # 다만 대표 문의와 60% 이상 가까운 관찰만 허용해 오분류가 다음
            # 정책에서 새로운 대표값으로 강화되는 피드백 오류를 막는다.
            observations = [
                observation
                for observation in observations
                if max(
                    (
                        cls._cosine(observation.embedding or [], anchor)
                        for anchor in anchors
                    ),
                    default=0.0,
                )
                >= cls.MANUAL_SIMILARITY_THRESHOLD
            ]

        expected_size = len(cohort.centroid_embedding or [])
        vectors: list[tuple[float, ...]] = []
        seen: set[tuple[float, ...]] = set()
        for row in [*examples, *observations]:
            try:
                vector = tuple(float(value) for value in (row.embedding or []))
            except (TypeError, ValueError):
                continue
            if (
                not vector
                or (expected_size and len(vector) != expected_size)
                or not all(math.isfinite(value) for value in vector)
                or not any(value != 0 for value in vector)
                or vector in seen
            ):
                continue
            seen.add(vector)
            vectors.append(vector)
        if not vectors and cohort.centroid_embedding:
            vectors.append(tuple(float(value) for value in cohort.centroid_embedding))
        return tuple(vectors)

    @staticmethod
    def _preserved_safety_routes(policy: LLMNodeModelRoutingPolicy) -> list[dict[str, Any]]:
        active = policy.active_policy if isinstance(policy.active_policy, dict) else {}
        semantic = active.get("semantic_router") if isinstance(active, dict) else {}
        routes = semantic.get("routes") if isinstance(semantic, dict) else []
        return [
            dict(route)
            for route in routes
            if isinstance(route, dict) and route.get("safety_override") is True
        ]

    @classmethod
    def _advance_existing_lifecycles(
        cls,
        cohorts: Iterable[LLMNodeModelRoutingCohort],
        *,
        observations: list[LLMNodeModelRoutingObservation],
        now: datetime,
    ) -> None:
        total = max(1, len(observations))
        for cohort in cohorts:
            matched_count = sum(
                1
                for observation in observations
                if observation.matched_cohort_id == cohort.id
            )
            share = matched_count / total
            next_state = AdaptiveCohortService.advance_lifecycle(
                CohortState(
                    status=str(cohort.status),
                    required=bool(cohort.required),
                    safety_protected=bool(cohort.safety_protected),
                    low_share_streak=int(cohort.low_share_streak or 0),
                    last_seen_at=cohort.last_seen_at,
                    dormant_since=cohort.dormant_since,
                ),
                current_share=share,
                now=now,
            )
            cohort.status = next_state.status
            cohort.low_share_streak = next_state.low_share_streak
            cohort.dormant_since = next_state.dormant_since
            cohort.last_seen_at = next_state.last_seen_at
            cohort.last_traffic_share = Decimal(str(share))
            if next_state.status == "retired":
                cohort.retired_at = now

    @classmethod
    def _live_cohorts(
        cls,
        db: Session,
        *,
        policy_id: Any,
    ) -> list[LLMNodeModelRoutingCohort]:
        return (
            db.query(LLMNodeModelRoutingCohort)
            .filter(LLMNodeModelRoutingCohort.policy_id == policy_id)
            .filter(LLMNodeModelRoutingCohort.status != "retired")
            .order_by(LLMNodeModelRoutingCohort.created_at.asc())
            .all()
        )

    @classmethod
    def _match(
        cls,
        vector: list[float],
        cohorts: Iterable[LLMNodeModelRoutingCohort],
        *,
        min_margin: float | None = None,
        example_embeddings_by_cohort: Mapping[str, Sequence[Sequence[float]]] | None = None,
    ) -> LLMNodeModelRoutingCohort | None:
        scored_cohorts: list[tuple[float, LLMNodeModelRoutingCohort]] = []
        for cohort in cohorts:
            if cohort.status == "retired":
                continue
            representatives = list(
                (example_embeddings_by_cohort or {}).get(str(cohort.id), ())
            )
            if not representatives:
                representatives = [cohort.centroid_embedding or []]
            similarities = sorted(
                (cls._cosine(vector, item) for item in representatives),
                reverse=True,
            )[:2]
            score = sum(similarities) / len(similarities) if similarities else 0.0
            scored_cohorts.append((score, cohort))

        if not scored_cohorts:
            return None

        scored_cohorts.sort(
            key=lambda item: (-item[0], str(getattr(item[1], "id", "")))
        )
        winner_score, winner = scored_cohorts[0]
        threshold = (
            cls.MANUAL_SIMILARITY_THRESHOLD
            if str(getattr(winner, "source", "")) == "manual"
            else cls.AUTO_MATCH_SIMILARITY_THRESHOLD
        )
        if winner_score < threshold:
            return None

        runner_up_score = (
            scored_cohorts[1][0] if len(scored_cohorts) > 1 else None
        )
        required_margin = (
            cls.DEFAULT_MATCH_MIN_MARGIN if min_margin is None else float(min_margin)
        )
        if runner_up_score is not None and winner_score - runner_up_score < required_margin:
            return None
        return winner

    @classmethod
    def _example_embeddings_by_cohort(
        cls,
        db: Session,
        *,
        cohorts: Sequence[LLMNodeModelRoutingCohort],
    ) -> dict[str, list[list[float]]]:
        cohort_ids = [cohort.id for cohort in cohorts]
        if not cohort_ids:
            return {}
        examples = (
            db.query(LLMNodeModelRoutingCohortExample)
            .filter(LLMNodeModelRoutingCohortExample.cohort_id.in_(cohort_ids))
            .order_by(
                LLMNodeModelRoutingCohortExample.cohort_id.asc(),
                LLMNodeModelRoutingCohortExample.ordinal.asc(),
            )
            .all()
        )
        result: dict[str, list[list[float]]] = {}
        for example in examples:
            embedding = [float(value) for value in (example.embedding or [])]
            if embedding:
                result.setdefault(str(example.cohort_id), []).append(embedding)
        return result

    @classmethod
    def _normalize_representative_examples(
        cls,
        representative_query: str,
        representative_examples: Sequence[str] | None,
    ) -> list[str]:
        normalized: list[str] = []
        for raw in [representative_query, *(representative_examples or ())]:
            text = " ".join(str(raw or "").split())[:2000]
            if text and text not in normalized:
                normalized.append(text)
            if len(normalized) >= cls.MAX_REPRESENTATIVE_EXAMPLES:
                break
        return normalized

    @staticmethod
    def _average_vectors(vectors: Sequence[Sequence[float]]) -> list[float]:
        dimensions = {len(vector) for vector in vectors}
        if not vectors or len(dimensions) != 1 or dimensions == {0}:
            raise ValueError("model_routing.cohort_embedding_failed")
        return [
            sum(float(vector[index]) for vector in vectors) / len(vectors)
            for index in range(len(vectors[0]))
        ]

    @classmethod
    def _match_min_margin(
        cls,
        policy: LLMNodeModelRoutingPolicy,
        node_data: dict[str, Any],
    ) -> float:
        """관찰 저장도 active policy의 semantic router 경계를 따른다."""
        active_policy = policy.active_policy if isinstance(policy.active_policy, dict) else {}
        semantic_router = active_policy.get("semantic_router")
        if not isinstance(semantic_router, dict):
            context = node_data.get("model_routing_context")
            context = context if isinstance(context, dict) else {}
            semantic_router = context.get("semantic_router")
        semantic_router = semantic_router if isinstance(semantic_router, dict) else {}
        try:
            value = float(semantic_router.get("min_margin", cls.DEFAULT_MATCH_MIN_MARGIN))
        except (TypeError, ValueError):
            return cls.DEFAULT_MATCH_MIN_MARGIN
        return value if math.isfinite(value) and value >= 0 else cls.DEFAULT_MATCH_MIN_MARGIN

    @staticmethod
    def _embedding(embed: EmbeddingFunction, text: str) -> list[float]:
        try:
            vector = [float(value) for value in embed(text)]
        except Exception:
            return []
        if not vector or not all(math.isfinite(value) for value in vector):
            return []
        if not any(value != 0 for value in vector):
            return []
        return vector

    @classmethod
    def _query_text(cls, inputs: Any, node_data: dict[str, Any]) -> str:
        routing_source = {"input_paths": cls._input_paths(node_data)}
        text = ModelRouter.semantic_query_text(
            inputs if isinstance(inputs, dict) else {},
            routing_source,
        )
        # 원문은 DB에 보관하지 않는다. embedding 요청도 현재 node가 처리할 수 있는
        # 현실적인 크기로 제한한다.
        return " ".join(str(text or "").split())[:6000]

    @staticmethod
    def _input_paths(node_data: dict[str, Any]) -> list[str]:
        context = node_data.get("model_routing_context")
        context = context if isinstance(context, dict) else {}
        semantic = context.get("semantic_router")
        semantic = semantic if isinstance(semantic, dict) else {}
        raw_paths = semantic.get("input_paths", context.get("input_paths", []))
        if not isinstance(raw_paths, list):
            return []
        paths: list[str] = []
        for raw_path in raw_paths:
            path = str(raw_path or "").strip()
            if path and path not in paths:
                paths.append(path)
        return paths[:8]

    @staticmethod
    def _encoder_model_id(observations: list[LLMNodeModelRoutingObservation]) -> str:
        return str(observations[-1].encoder_model_id) if observations else ""

    @staticmethod
    def _cohort_key(hashes: Iterable[str]) -> str:
        digest = hashlib.sha256("|".join(sorted(hashes)).encode("utf-8")).hexdigest()
        return f"auto-{digest[:20]}"

    @staticmethod
    def _observed_at(node_run: WorkflowNodeRun) -> datetime:
        value = getattr(node_run, "finished_at", None) or getattr(node_run, "started_at", None)
        return value if isinstance(value, datetime) else datetime.now(timezone.utc)

    @staticmethod
    def _cosine(left: Iterable[float], right: Iterable[float]) -> float:
        left_vector = [float(value) for value in left]
        right_vector = [float(value) for value in right]
        if not left_vector or len(left_vector) != len(right_vector):
            return float("-inf")
        numerator = sum(a * b for a, b in zip(left_vector, right_vector))
        left_norm = math.sqrt(sum(value * value for value in left_vector))
        right_norm = math.sqrt(sum(value * value for value in right_vector))
        if left_norm == 0 or right_norm == 0:
            return float("-inf")
        return numerator / (left_norm * right_norm)
