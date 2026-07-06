import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from apps.gateway.services.knowledge_candidate_resolver import (
    DEFAULT_MAX_CANDIDATE_KBS,
    DEFAULT_MAX_COLLECTIONS,
    KnowledgeCandidateResolver,
    bucket_count,
)
from apps.shared.schemas.knowledge import (
    KnowledgeBaseOptionRef,
    KnowledgeCandidate,
    KnowledgeRAGRecommendedOptions,
    KnowledgeRAGRecommendation,
    KnowledgeRAGRecommendationProvenance,
    KnowledgeRAGRecommendationRequest,
    KnowledgeRAGRecommendationResponse,
    KnowledgeRAGRecommendationSummary,
    KnowledgeSourceCollectionSummary,
)
from apps.shared.services.knowledge_permission_service import KnowledgePermissionHelper
from apps.shared.services.rag_source_tier import source_tier_priority


RECOMMENDATION_STRATEGY = "metadata_keyword_v1"
GENERIC_KB_LABEL = "Knowledge Base"
SAFE_TEMPLATE_FOR_POLICY = "{query} 관련 정책 근거 절차 기준"
MAX_MATERIALIZED_KBS = 20
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")

_AVAILABILITY_ORDER = {
    "available": 3,
    "warning": 2,
    "unknown": 1,
    "unavailable": 0,
}
_FRESH_SYNC_STATES = {"synced", "fresh", "ready"}


class KnowledgeRAGRecommendationService:
    """Workflow Builder용 RAG option recommendation service.

    권한 판단은 반드시 KnowledgeCandidateResolver/PermissionHelper 경계에서 끝낸다.
    이 service는 safe candidate metadata만 받아 ranking과 LLM node option
    materialization을 수행한다.
    """

    def __init__(
        self,
        db: Session,
        *,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
        resolver: KnowledgeCandidateResolver | None = None,
    ) -> None:
        self.db = db
        self.user_id = user_id
        self.organization_id = organization_id
        self.resolver = resolver

    def recommend_for_builder(
        self,
        request: KnowledgeRAGRecommendationRequest,
    ) -> KnowledgeRAGRecommendationResponse:
        resolver = self.resolver or self._resolver_for_request(request)
        recommendation_mode = self._resolved_mode(request)
        resolution = self._resolve_candidates(resolver, request, recommendation_mode)

        ranked = self._rank_candidates(resolution.candidates, request)
        limited = ranked[: request.max_recommendations]
        recommendations = [
            self._recommendation(candidate, score, matched_terms, used_signals, request)
            for candidate, score, matched_terms, used_signals in limited
        ]

        warning_count = sum(1 for item in recommendations if item.warnings)
        return KnowledgeRAGRecommendationResponse(
            recommendations=recommendations,
            summary=KnowledgeRAGRecommendationSummary(
                candidate_count_bucket=bucket_count(len(resolution.candidates)),
                recommendation_count_bucket=bucket_count(len(recommendations)),
                hidden_or_unavailable_count_bucket=self._merge_buckets(
                    resolution.hidden_candidate_count_bucket,
                    resolution.unavailable_candidate_count_bucket,
                ),
                recommendation_strategy=RECOMMENDATION_STRATEGY,
                warning_count_bucket=bucket_count(warning_count),
            ),
            reason_code=None if recommendations else resolution.reason_code or "no_candidate",
        )

    def _resolver_for_request(
        self,
        request: KnowledgeRAGRecommendationRequest,
    ) -> KnowledgeCandidateResolver:
        runtime_permission_helper = None
        if request.intended_execution_subject_id:
            runtime_permission_helper = KnowledgePermissionHelper(
                self.db,
                user_id=request.intended_execution_subject_id,
                organization_id=self.organization_id,
            )
        return KnowledgeCandidateResolver(
            self.db,
            user_id=self.user_id,
            organization_id=self.organization_id,
            runtime_permission_helper=runtime_permission_helper,
        )

    def _resolve_candidates(
        self,
        resolver: KnowledgeCandidateResolver,
        request: KnowledgeRAGRecommendationRequest,
        recommendation_mode: str,
    ):
        if recommendation_mode == "explicit_kb":
            return resolver.resolve_explicit_kbs(request.knowledge_base_ids)
        return resolver.resolve_auto_collection_candidates(
            collection_ids=request.collection_ids or None,
            max_collections=min(request.max_collections, DEFAULT_MAX_COLLECTIONS),
            max_candidate_kbs=min(request.max_candidate_kbs, DEFAULT_MAX_CANDIDATE_KBS),
        )

    def _resolved_mode(self, request: KnowledgeRAGRecommendationRequest) -> str:
        if request.mode in {"explicit_kb", "auto_collection"}:
            return request.mode
        if request.knowledge_base_ids:
            return "explicit_kb"
        return "auto_collection"

    def _rank_candidates(
        self,
        candidates: list[KnowledgeCandidate],
        request: KnowledgeRAGRecommendationRequest,
    ) -> list[tuple[KnowledgeCandidate, float, list[str], list[str]]]:
        terms = self._terms(request.workflow_intent, request.node_purpose)
        ranked: list[tuple[KnowledgeCandidate, float, list[str], list[str]]] = []
        for candidate in candidates:
            matched_terms = self._matched_terms(candidate, terms)
            source_priority = self._source_tier_priority(candidate)
            availability = _AVAILABILITY_ORDER.get(candidate.runtime_availability, 1)
            freshness = self._freshness_bonus(candidate)

            keyword_score = min(1.0, len(matched_terms) / max(1, len(terms)))
            score = (
                keyword_score * 0.45
                + (source_priority / 100) * 0.15
                + (availability / 3) * 0.15
                + freshness * 0.05
            )
            if request.high_risk_domain != "none":
                score += 0.05
            used_signals = self._used_signals(
                matched_terms=matched_terms,
                source_priority=source_priority,
                availability=candidate.runtime_availability,
                freshness=freshness,
            )
            ranked.append(
                (
                    candidate,
                    min(score, 0.99),
                    matched_terms,
                    used_signals,
                )
            )

        return sorted(
            ranked,
            key=lambda item: (
                -item[1],
                -_AVAILABILITY_ORDER.get(item[0].runtime_availability, 1),
                -self._source_tier_priority(item[0]),
                0 if item[0].safe_label else 1,
                str(item[0].candidate_id),
            ),
        )

    def _recommendation(
        self,
        candidate: KnowledgeCandidate,
        score: float,
        matched_terms: list[str],
        used_signals: list[str],
        request: KnowledgeRAGRecommendationRequest,
    ) -> KnowledgeRAGRecommendation:
        safe_label = candidate.safe_label
        kb_label = safe_label or GENERIC_KB_LABEL
        options = self._recommended_options(request)
        warnings = self._warnings(candidate, safe_label)
        materialized_refs = [
            KnowledgeBaseOptionRef(
                id=candidate.candidate_id,
                name=kb_label,
            )
        ][:MAX_MATERIALIZED_KBS]
        safe_reason_code = self._safe_reason_code(matched_terms, request)
        return KnowledgeRAGRecommendation(
            recommendation_id=self._recommendation_id(candidate),
            recommendation_mode=self._resolved_mode(request),
            candidate_id=candidate.candidate_id,
            safe_label=safe_label,
            confidence=round(score, 4),
            safe_reason_code=safe_reason_code,
            recommended_options=options,
            materialized_knowledge_bases=materialized_refs,
            source_collection_summary=self._source_collection_summary(candidate),
            provenance=KnowledgeRAGRecommendationProvenance(
                recommendation_strategy=RECOMMENDATION_STRATEGY,
                safe_reason_code=safe_reason_code,
                used_signals=used_signals,
                matched_safe_terms=matched_terms[:10],
                candidate_count_bucket="1",
                warning_count_bucket=bucket_count(len(warnings)),
            ),
            runtime_availability=candidate.runtime_availability,
            warnings=warnings,
        )

    def _recommendation_id(self, candidate: KnowledgeCandidate) -> str:
        # 추천 ID는 candidate_id를 직접 인코딩하지 않는 opaque 값으로 만든다.
        # candidate_id 자체는 허용된 KB로 응답에 포함되지만, 별도 식별자는 문서 계약상 opaque여야 한다.
        stable_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            (
                f"{RECOMMENDATION_STRATEGY}:"
                f"{self.organization_id}:"
                f"{candidate.candidate_id}"
            ),
        )
        return f"rec-{stable_id}"

    def _recommended_options(
        self,
        request: KnowledgeRAGRecommendationRequest,
    ) -> KnowledgeRAGRecommendedOptions:
        high_risk = request.high_risk_domain != "none"
        rewrite_mode = "template" if high_risk and request.allow_query_rewrite else "off"
        return KnowledgeRAGRecommendedOptions(
            queryRewriteMode=rewrite_mode,
            queryRewriteTemplate=SAFE_TEMPLATE_FOR_POLICY
            if rewrite_mode == "template"
            else None,
            evidenceSufficiencyPolicy="strict_citation"
            if high_risk
            else "minimum_evidence",
            ragFailurePolicy="safe_no_result",
            sourceTierPolicy="tie_break",
            scoreThreshold=0.5,
            topK=5 if high_risk else 3,
        )

    def _warnings(
        self,
        candidate: KnowledgeCandidate,
        safe_label: str | None,
    ) -> list[str]:
        warnings: list[str] = []
        if candidate.runtime_availability == "unknown":
            warnings.append("runtime_availability_unknown")
        elif candidate.runtime_availability != "available":
            warnings.append("runtime_availability_not_available")
        if safe_label is None:
            warnings.append("safe_label_unavailable")
        return warnings

    def _safe_reason_code(
        self,
        matched_terms: list[str],
        request: KnowledgeRAGRecommendationRequest,
    ) -> str:
        if request.high_risk_domain != "none":
            return "high_risk_domain_requires_citation"
        if matched_terms:
            return "intent_matches_safe_metadata"
        return "safe_candidate_available"

    def _source_collection_summary(
        self,
        candidate: KnowledgeCandidate,
    ) -> KnowledgeSourceCollectionSummary | None:
        metadata = candidate.safe_metadata or {}
        raw_collection_id = metadata.get("collection_id")
        collection_id = self._uuid_or_none(raw_collection_id)
        safe_label = self._string_or_none(metadata.get("collection_safe_label"))
        route_scope_type = self._string_or_none(metadata.get("route_scope_type"))
        count_bucket = self._string_or_none(metadata.get("linked_kb_count_bucket"))
        if not any((collection_id, safe_label, route_scope_type, count_bucket)):
            return None
        return KnowledgeSourceCollectionSummary(
            collection_id=collection_id,
            safe_label=safe_label,
            route_scope_type=route_scope_type,
            linked_kb_count_bucket=count_bucket,
        )

    def _matched_terms(
        self,
        candidate: KnowledgeCandidate,
        terms: list[str],
    ) -> list[str]:
        if not terms:
            return []
        haystack = self._candidate_text(candidate)
        return [term for term in terms if term in haystack][:10]

    def _candidate_text(self, candidate: KnowledgeCandidate) -> str:
        values: list[str] = []
        if candidate.safe_label:
            values.append(candidate.safe_label)
        for value in (candidate.safe_metadata or {}).values():
            if isinstance(value, str):
                values.append(value)
            elif isinstance(value, (list, tuple, set)):
                values.extend(str(item) for item in value if isinstance(item, str))
        return " ".join(values).lower()

    def _terms(self, *values: str | None) -> list[str]:
        terms: list[str] = []
        for value in values:
            if not value:
                continue
            for token in _TOKEN_RE.findall(value.lower()):
                if len(token) < 2:
                    continue
                if token not in terms:
                    terms.append(token)
        return terms[:50]

    def _source_tier_priority(self, candidate: KnowledgeCandidate) -> int:
        metadata = candidate.safe_metadata or {}
        return source_tier_priority(metadata.get("source_tier"))

    def _freshness_bonus(self, candidate: KnowledgeCandidate) -> float:
        metadata = candidate.safe_metadata or {}
        sync_state = str(metadata.get("sync_state") or "").lower()
        source_acl_state = candidate.permission.source_acl_state
        if sync_state in _FRESH_SYNC_STATES or source_acl_state in {
            "fresh",
            "not_source_managed",
        }:
            return 1.0
        return 0.0

    def _used_signals(
        self,
        *,
        matched_terms: list[str],
        source_priority: int,
        availability: str,
        freshness: float,
    ) -> list[str]:
        signals: list[str] = []
        if matched_terms:
            signals.append("safe_keyword_match")
        if source_priority:
            signals.append("source_tier")
        if availability != "unknown":
            signals.append("runtime_availability")
        if freshness:
            signals.append("freshness")
        return signals or ["safe_candidate"]

    def _merge_buckets(self, *buckets: str) -> str:
        values = [self._bucket_floor(bucket) for bucket in buckets]
        return bucket_count(sum(values))

    def _bucket_floor(self, bucket: str | None) -> int:
        if bucket in {None, "0"}:
            return 0
        if bucket == "1":
            return 1
        if bucket == "2-10":
            return 2
        if bucket == "11-100":
            return 11
        return 101

    def _uuid_or_none(self, value: Any) -> uuid.UUID | None:
        if value is None:
            return None
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError):
            return None

    def _string_or_none(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value or None
