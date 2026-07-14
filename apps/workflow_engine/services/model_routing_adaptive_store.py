"""적응형 모델 라우팅 입력군의 DB 저장과 policy projection.

운영 입력은 embedding provider에 일시적으로 전달될 수 있지만, 이 저장소에는
원문 대신 SHA-256 해시, 벡터, 시간, cohort 매칭 결과만 저장한다.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Iterable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.shared.db.models.model_routing_cohort import (
    LLMNodeModelRoutingCohort,
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
    # text-embedding-3-large의 실제 한국어 운영 입력 분포에서는 같은 업무 의도의
    # 표현이 넓게 퍼질 수 있다. 0.50은 반복되는 표현군을 묶으면서 서로 다른
    # 업무군이 합쳐지기 시작하는 0.40보다 높은 경계다. 임계값은 입력군의 대표
    # 중심점과 신규 입력을 비교할 때도 동일하게 사용한다.
    SIMILARITY_THRESHOLD = 0.50

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
        matched = cls._match(vector, cohorts)
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
            similarity_threshold=cls.SIMILARITY_THRESHOLD,
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
        label: str,
        cohort_key: str,
        representative_query: str,
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

        vector = cls._embedding(embed, normalized_query)
        if not vector:
            raise ValueError("model_routing.cohort_embedding_failed")

        now = datetime.now(timezone.utc)
        cohort = LLMNodeModelRoutingCohort(
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
            centroid_embedding=vector,
            node_config_fingerprint=llm_node_config_fingerprint(node_data),
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(cohort)
        db.flush()

        from apps.shared.db.models.model_routing_cohort import (
            LLMNodeModelRoutingCohortExample,
        )

        db.add(
            LLMNodeModelRoutingCohortExample(
                cohort_id=cohort.id,
                synthetic_text=normalized_query,
                embedding=vector,
                ordinal=1,
            )
        )
        db.flush()
        return cohort

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
        return AdaptiveModelRoutingPolicyService.build_runtime_catalog(
            encoder_model_id=encoder_model_id,
            input_paths=cls._input_paths(node_data),
            routes=[
                AdaptiveCohortRoute(
                    cohort_id=str(cohort.cohort_key),
                    label=str(cohort.label),
                    status=str(cohort.status),
                    validated=True,
                    centroid_embedding=tuple(cohort.centroid_embedding or ()),
                    safety_override=bool(cohort.safety_protected),
                    threshold=cls.SIMILARITY_THRESHOLD,
                )
                for cohort in cohorts
            ],
            preserved_safety_routes=cls._preserved_safety_routes(policy),
        )

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
    ) -> LLMNodeModelRoutingCohort | None:
        winner = None
        winner_score = float("-inf")
        for cohort in cohorts:
            if cohort.status == "retired":
                continue
            score = cls._cosine(vector, cohort.centroid_embedding or [])
            if score >= cls.SIMILARITY_THRESHOLD and score > winner_score:
                winner = cohort
                winner_score = score
        return winner

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
