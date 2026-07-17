"""Compile prior-guided model decisions into a persisted runtime policy."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping

from sqlalchemy.orm import Session

from apps.shared.db.models.llm import LLMModel
from apps.workflow_engine.services.model_router import NodeRunProfile
from apps.workflow_engine.services.model_routing_global_profiles import (
    ModelRoutingDifficultyDistribution,
    ModelRoutingGlobalProfileStore,
)
from apps.workflow_engine.services.model_routing_constraint_difficulty import (
    PRIOR_GUIDED_STRATEGY_ID,
    ConstraintDifficultyFeatureExtractor,
    ConstraintDifficultyRequest,
    ConstraintModelCandidate,
    ConstraintModelPrior,
    ConstraintRoutingUnavailableError,
    ConstraintValidationEvidence,
    PriorGuidedAdaptiveRouter,
)


@dataclass(frozen=True)
class PriorGuidedPolicyCompileResult:
    active_policy: dict[str, Any]
    summary: dict[str, Any]


class PriorGuidedModelCatalog:
    """Convert provider model rows into safe routing candidates and priors."""

    @classmethod
    def collect(
        cls,
        db: Session,
        *,
        available_model_ids: Iterable[str],
    ) -> tuple[tuple[ConstraintModelCandidate, ...], tuple[ConstraintModelPrior, ...]]:
        available = {cls._normalize(item) for item in available_model_ids if item}
        if not available:
            return (), ()
        rows = db.query(LLMModel).filter(LLMModel.is_active.is_(True)).all()
        global_profiles = ModelRoutingGlobalProfileStore.resolve_available_profiles(
            db,
            available_model_ids=available,
            materialize_missing=True,
        )
        balanced_difficulty = ModelRoutingDifficultyDistribution(balanced=1.0)
        candidates: list[ConstraintModelCandidate] = []
        priors: list[ConstraintModelPrior] = []
        seen: set[str] = set()
        for row in rows:
            normalized = cls._normalize(row.model_id_for_api_call)
            if normalized not in available or normalized in seen:
                continue
            seen.add(normalized)
            metadata = (
                row.model_metadata if isinstance(row.model_metadata, dict) else {}
            )
            global_profile = global_profiles.get(normalized)
            if global_profile is None:
                continue
            candidates.append(
                ConstraintModelCandidate(
                    model_id=normalized,
                    context_window=max(int(row.context_window or 0), 1),
                    input_price_1k=cls._number(row.input_price_1k),
                    output_price_1k=cls._number(row.output_price_1k),
                    capability_tier=global_profile.capability_tier,
                    supports_strict_structured_output=(
                        cls._supports_strict_output(normalized, metadata)
                    ),
                )
            )
            priors.append(
                ConstraintModelPrior(
                    model_id=normalized,
                    quality_mean=global_profile.expected_quality(
                        balanced_difficulty
                    ),
                    quality_uncertainty=global_profile.expected_uncertainty(
                        balanced_difficulty
                    ),
                    expected_latency_ms=global_profile.expected_latency_ms("medium"),
                    fallback_rate=global_profile.fallback_rate,
                    prior_strength=global_profile.prior_strength,
                    source=global_profile.source,
                )
            )
        return tuple(candidates), tuple(priors)

    @staticmethod
    def _supports_strict_output(
        model_id: str,
        metadata: Mapping[str, Any],
    ) -> bool:
        explicit = metadata.get("supports_strict_structured_output")
        if isinstance(explicit, bool):
            return explicit
        return model_id.startswith(("gpt-", "o3"))

    @staticmethod
    def _normalize(model_id: Any) -> str:
        return str(model_id or "").strip().lower().removeprefix("models/")

    @staticmethod
    def _number(value: Any) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None

class PriorGuidedEvidenceAdapter:
    """Project safe operational aggregates into router evidence."""

    @staticmethod
    def for_signature(
        profile: NodeRunProfile,
        *,
        signature,
    ) -> tuple[ConstraintValidationEvidence, ...]:
        evidence: list[ConstraintValidationEvidence] = []
        for model_id, performance in profile.model_performance.items():
            if performance.run_count <= 0 or performance.success_rate is None:
                continue
            contract_scores = [performance.success_rate]
            if performance.schema_pass_rate is not None:
                contract_scores.append(performance.schema_pass_rate)
            if performance.downstream_success_rate is not None:
                contract_scores.append(performance.downstream_success_rate)
            evidence.append(
                ConstraintValidationEvidence(
                    model_id=model_id,
                    signature=signature,
                    sample_count=performance.run_count,
                    success_rate=performance.success_rate,
                    schema_pass_rate=performance.schema_pass_rate,
                    downstream_success_rate=performance.downstream_success_rate,
                    fallback_rate=performance.fallback_rate or 0.0,
                    quality_score=min(contract_scores),
                )
            )
        return tuple(evidence)


class PriorGuidedPolicyCompiler:
    """입력군이나 임베딩 없이 일반 제약 기반 정책 규칙을 만든다."""

    _INPUT_PROFILES = (
        ("short", 256, {"message": "short request"}),
        ("medium", 2_000, {"message": "medium request"}),
        ("long", 12_000, {"message": "long request"}),
    )

    @classmethod
    def compile(
        cls,
        *,
        node_data: Mapping[str, Any],
        candidates: Iterable[ConstraintModelCandidate],
        priors: Iterable[ConstraintModelPrior],
        evidence: Iterable[ConstraintValidationEvidence],
        available_model_ids: set[str],
        safe_default_model_id: str,
        profile: NodeRunProfile | None = None,
    ) -> PriorGuidedPolicyCompileResult:
        router = PriorGuidedAdaptiveRouter()
        candidate_rows = tuple(candidates)
        prior_rows = tuple(priors)
        supplied_evidence = tuple(evidence)
        safe_node_data = dict(node_data)
        # 정책 생성용 입력 구간은 실제 노드 입력이 아니다. 변수 누락 검사는
        # 모델 순위 계산이 아니라 실제 실행 검증 단계에서 수행한다.
        safe_node_data["referenced_variables"] = []
        rules: list[dict[str, Any]] = []
        decision_profiles: list[dict[str, Any]] = []

        for profile_name, estimated_tokens, inputs in cls._INPUT_PROFILES:
            request = ConstraintDifficultyRequest(
                node_data=safe_node_data,
                inputs=inputs,
                available_model_ids=available_model_ids,
                downstream_requirements=cls._downstream_requirements(safe_node_data),
                estimated_input_tokens=estimated_tokens,
            )
            features = ConstraintDifficultyFeatureExtractor.extract(request)
            profile_evidence = supplied_evidence
            if profile is not None:
                segment = profile.segment_performance.get(profile_name)
                segment_models = (
                    segment.get("model_performance")
                    if isinstance(segment, dict)
                    and isinstance(segment.get("model_performance"), dict)
                    else None
                )
                if segment_models:
                    evidence_profile = NodeRunProfile(
                        operational_usable_runs=sum(
                            item.run_count for item in segment_models.values()
                        ),
                        model_performance=segment_models,
                    )
                elif profile.segment_performance:
                    # 다른 입력 길이에서 얻은 성적을 이 구간의 증거로 재사용하지 않는다.
                    evidence_profile = NodeRunProfile()
                else:
                    # 구형 호출자는 segment 없이 모델 전체 집계만 전달할 수 있다.
                    evidence_profile = profile
                profile_priors = cls._priors_with_observed_latency(
                    prior_rows,
                    evidence_profile,
                )
                profile_evidence = (
                    *profile_evidence,
                    *PriorGuidedEvidenceAdapter.for_signature(
                        evidence_profile,
                        signature=features.signature,
                    ),
                )
            try:
                decision = router.route(
                    request=request,
                    candidates=candidate_rows,
                    evidence=profile_evidence,
                    priors=(profile_priors if profile is not None else prior_rows),
                    safe_default_model_id=safe_default_model_id,
                )
                selected_model_id = decision.selected_model_id
                reason_code = decision.reason_code
                candidate_scores = {
                    model_id: score.as_metadata()
                    for model_id, score in decision.candidate_scores.items()
                }
                excluded_models = {
                    model_id: list(reasons)
                    for model_id, reasons in decision.excluded_models.items()
                }
                constraint_signature = decision.matched_signature.as_metadata()
            except ConstraintRoutingUnavailableError:
                # 한 입력 구간에서 후보가 없더라도 다른 구간의 정책까지 버리지 않는다.
                # 해당 구간은 사용자가 정한 안전 모델로 닫고 이유를 기록한다.
                selected_model_id = safe_default_model_id
                reason_code = "prior_guided_constraints_safe_default"
                candidate_scores = {}
                excluded_models = {}
                constraint_signature = features.signature.as_metadata()
            rule = {
                "id": f"prior-guided-{profile_name}",
                "when": {"input_length_bucket": profile_name},
                "selected_model_id": selected_model_id,
                "fallback_model_id": safe_default_model_id,
                "priority": 100,
                "reason_code": reason_code,
            }
            rules.append(rule)
            decision_profiles.append(
                {
                    "profile": profile_name,
                    "selected_model_id": selected_model_id,
                    "fallback_model_id": safe_default_model_id,
                    "reason_code": reason_code,
                    "constraint_signature": constraint_signature,
                    "candidate_scores": candidate_scores,
                    "excluded_models": excluded_models,
                }
            )

        active_policy = {
            "strategy": "prior_guided_adaptive",
            "strategy_id": PRIOR_GUIDED_STRATEGY_ID,
            "default_model_id": safe_default_model_id,
            "fallback_model_id": safe_default_model_id,
            "rules": rules,
            "decision_profiles": decision_profiles,
        }
        return PriorGuidedPolicyCompileResult(
            active_policy=active_policy,
            summary={
                "strategy_id": PRIOR_GUIDED_STRATEGY_ID,
                "profile_count": len(decision_profiles),
                "candidate_count": len(candidate_rows),
                "uses_semantic_cohorts": False,
                "judge_called": False,
            },
        )

    @staticmethod
    def _priors_with_observed_latency(
        priors: tuple[ConstraintModelPrior, ...],
        profile: NodeRunProfile,
    ) -> tuple[ConstraintModelPrior, ...]:
        """같은 입력 구간의 운영 지연이 있으면 catalog 예상 지연을 보정한다."""
        adjusted: list[ConstraintModelPrior] = []
        for prior in priors:
            performance = profile.model_performance.get(prior.model_id)
            observed_latency = (
                performance.avg_latency_ms if performance is not None else None
            )
            if observed_latency is None or observed_latency <= 0:
                adjusted.append(prior)
                continue
            adjusted.append(
                replace(
                    prior,
                    expected_latency_ms=max(1, round(observed_latency)),
                    source=f"{prior.source}+operational_latency",
                )
            )
        return tuple(adjusted)

    @staticmethod
    def _downstream_requirements(
        node_data: Mapping[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        output_format = node_data.get("output_format")
        if not isinstance(output_format, Mapping):
            return ()
        schema = output_format.get("schema")
        if str(output_format.get("type") or "text").lower() != "json" or not schema:
            return ()
        return ({"required": True, "type": "json_schema"},)


def compile_prior_guided_policy_from_db(
    db: Session,
    *,
    node_data: Mapping[str, Any],
    available_model_ids: Iterable[str],
    safe_default_model_id: str,
    profile: NodeRunProfile,
) -> PriorGuidedPolicyCompileResult:
    normalized_available = {
        str(item or "").strip().lower().removeprefix("models/")
        for item in available_model_ids
        if item
    }
    candidates, priors = PriorGuidedModelCatalog.collect(
        db,
        available_model_ids=normalized_available,
    )
    if not candidates:
        raise ConstraintRoutingUnavailableError(
            "No model catalog candidate is available for prior-guided routing."
        )
    normalized_safe_default = (
        str(safe_default_model_id or "").strip().lower().removeprefix("models/")
    )
    if normalized_safe_default not in normalized_available:
        raise ConstraintRoutingUnavailableError(
            "The safe default model is not available for prior-guided routing."
        )
    return PriorGuidedPolicyCompiler.compile(
        node_data=node_data,
        candidates=candidates,
        priors=priors,
        evidence=(),
        available_model_ids=normalized_available,
        safe_default_model_id=normalized_safe_default,
        profile=profile,
    )
