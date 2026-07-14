import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from apps.gateway.services.knowledge_candidate_resolver import (
    DEFAULT_MAX_CANDIDATE_KBS,
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
from apps.shared.services.knowledge_safe_text import extract_safe_terms
from apps.shared.services.rag_source_tier import source_tier_priority


RECOMMENDATION_STRATEGY = "structured_kb_relevance_v2"
RECOMMENDATION_HANDLE_NAMESPACE = "metadata_keyword_v1"
GENERIC_KB_LABEL = "Knowledge Base"
SAFE_TEMPLATE_FOR_POLICY = "{query} 관련 정책 근거 절차 기준"
MAX_MATERIALIZED_KBS = 20
_KB_KEYWORD_STRING_METADATA_KEYS = (
    "kb_safe_description",
    "safe_description",
    "safe_display_description",
)
_KB_KEYWORD_LIST_METADATA_KEYS = (
    "kb_safe_topics",
    "safe_topics",
)

_AVAILABILITY_ORDER = {
    "available": 3,
    "warning": 2,
    "unknown": 1,
    "unavailable": 0,
}
_FRESH_SYNC_STATES = {"synced", "fresh", "ready"}
_SAFE_QUERY_STOP_TERMS = frozenset(
    {
        "kb",
        "knowledge",
        "base",
        "rag",
        "llm",
        "workflow",
        "webhook",
        "node",
        "input",
        "output",
        "create",
        "build",
        "make",
        "generate",
        "지식베이스",
        "워크플로우",
        "웹훅",
        "챗봇",
        "노드",
        "입력",
        "출력",
        "생성",
        "만들어줘",
        "만들어",
        "받는",
        "받아",
        "답변",
        "검색",
        "찾아",
        "요약",
        "분석",
    }
)
_WHITESPACE_RE = re.compile(r"\s+")


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
        *,
        include_materialized_refs: bool = False,
        allow_unready_candidates: bool = False,
    ) -> KnowledgeRAGRecommendationResponse:
        resolver = self.resolver or self._resolver_for_request(request)
        recommendation_mode = self._resolved_mode(request)
        try:
            resolution = self._resolve_candidates(
                resolver,
                request,
                recommendation_mode,
                allow_unready_candidates=allow_unready_candidates,
            )
        except Exception:
            return self._adapter_unavailable_response(request)
        try:
            ranked = self._rank_candidates(resolution.candidates, request)
        except Exception:
            return self._adapter_unavailable_response(request, resolution.candidates)

        limited = ranked[: request.max_recommendations]
        recommendations = [
            self._recommendation(candidate, score, matched_terms, used_signals, request)
            for candidate, score, matched_terms, used_signals in limited
        ]
        if not include_materialized_refs:
            for item in recommendations:
                item.materialized_knowledge_bases = []
        clarification_options = self._clarification_options_from_recommendations(
            recommendations
        )

        warning_count = sum(1 for item in recommendations if item.warnings)
        return KnowledgeRAGRecommendationResponse(
            status="recommended" if recommendations else "no_candidate",
            resolution_id=request.pending_resolution_ref,
            requirement_id=(request.knowledge_requirement or {}).get("requirement_id")
            if request.knowledge_requirement
            else None,
            recommendations=recommendations,
            clarification_options=clarification_options,
            fallback_reason=None if recommendations else "no_candidate",
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

    def safe_intent_candidates_for_builder(
        self,
        workflow_intent: str,
        *,
        max_candidates: int = 20,
    ) -> list[dict[str, Any]]:
        """Return a bounded, permission-filtered KB projection for intent planning."""
        limit = max(1, min(int(max_candidates), 20))
        request = KnowledgeRAGRecommendationRequest(
            workflow_intent=workflow_intent,
            node_purpose=workflow_intent,
            intended_execution_subject_id=self.user_id,
            mode="auto",
            max_recommendations=limit,
        )
        resolver = self.resolver or self._resolver_for_request(request)
        try:
            resolution = self._resolve_candidates(
                resolver,
                request,
                "auto_collection",
                allow_unready_candidates=True,
            )
            ranked = self._rank_candidates(resolution.candidates, request)[:limit]
        except Exception:
            return []

        result: list[dict[str, Any]] = []
        for candidate, score, _matched_terms, _used_signals in ranked:
            metadata = candidate.safe_metadata or {}
            raw_topics = metadata.get("kb_safe_topics")
            safe_topics = []
            if isinstance(raw_topics, (list, tuple, set)):
                for value in raw_topics:
                    if not isinstance(value, str):
                        continue
                    topic = value.strip()[:128]
                    if topic and topic not in safe_topics:
                        safe_topics.append(topic)
                    if len(safe_topics) >= 10:
                        break
            safe_description = metadata.get("kb_safe_description")
            result.append(
                {
                    "candidate_handle": self._recommendation_id(candidate),
                    "safe_label": (
                        candidate.safe_label.strip()[:255]
                        if isinstance(candidate.safe_label, str)
                        and candidate.safe_label.strip()
                        else None
                    ),
                    "safe_topics": safe_topics,
                    "safe_description": (
                        safe_description.strip()[:500]
                        if isinstance(safe_description, str)
                        and safe_description.strip()
                        else None
                    ),
                    "runtime_availability": candidate.runtime_availability,
                    "relevance_score": round(max(0.0, min(score, 0.99)), 4),
                }
            )
        return result

    def materialize_candidate_handles_for_builder(
        self,
        request: KnowledgeRAGRecommendationRequest,
        candidate_handles: set[str],
    ) -> list[dict[str, str]]:
        """Resolve previously issued safe handles to authorized runtime KB refs.

        This path is for apply/save materialization. It does not depend on
        top-N ranking; a still-authorized handle can be materialized even if
        current recommendation ordering changed.
        """
        if not candidate_handles:
            return []
        resolver = self.resolver or self._resolver_for_request(request)
        recommendation_mode = self._resolved_mode(request)
        try:
            resolution = self._resolve_candidates(
                resolver,
                request,
                recommendation_mode,
                allow_unready_candidates=True,
            )
        except Exception:
            return []

        materialized: list[dict[str, str]] = []
        for candidate in resolution.candidates:
            handle = self._recommendation_id(candidate)
            if handle not in candidate_handles:
                continue
            materialized.append(
                {
                    "safe_handle": handle,
                    "knowledge_base_id": str(candidate.candidate_id),
                    "name": candidate.safe_label or GENERIC_KB_LABEL,
                }
            )
        return materialized

    def _adapter_unavailable_response(
        self,
        request: KnowledgeRAGRecommendationRequest,
        candidates: list[KnowledgeCandidate] | None = None,
    ) -> KnowledgeRAGRecommendationResponse:
        safe_options = [
            {
                "candidate_id": self._recommendation_id(candidate),
                "safe_label": candidate.safe_label or GENERIC_KB_LABEL,
                "candidate_type": candidate.candidate_type,
                "runtime_availability": candidate.runtime_availability,
                "confidence": "low",
                "score": 0.0,
                "reason_category": "adapter_unavailable",
                "threshold_result": "adapter_unavailable",
            }
            for candidate in (candidates or [])[: request.max_recommendations]
        ]
        return KnowledgeRAGRecommendationResponse(
            status="clarification_required" if safe_options else "unavailable",
            resolution_id=request.pending_resolution_ref,
            requirement_id=(request.knowledge_requirement or {}).get("requirement_id")
            if request.knowledge_requirement
            else None,
            recommendations=[],
            clarification_options=safe_options,
            fallback_reason="adapter_unavailable",
            reason_code="adapter_unavailable",
            user_safe_warning="Knowledge Base 추천을 사용할 수 없어 사용자 확인이 필요합니다.",
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
        *,
        allow_unready_candidates: bool = False,
    ):
        if recommendation_mode == "explicit_kb":
            return resolver.resolve_explicit_kbs(
                request.knowledge_base_ids,
                allow_unready_candidates=allow_unready_candidates,
            )
        return resolver.resolve_auto_collection_candidates(
            collection_ids=self._collection_scope(request),
            max_collections=request.max_collections,
            max_candidate_kbs=min(request.max_candidate_kbs, DEFAULT_MAX_CANDIDATE_KBS),
            allow_unready_candidates=allow_unready_candidates,
        )

    def _collection_scope(
        self,
        request: KnowledgeRAGRecommendationRequest,
    ) -> list[uuid.UUID] | None:
        # collection_ids를 생략한 경우만 "route 가능한 전체 scope"로 해석한다.
        # 명시적으로 []를 보낸 경우는 사용자가 scope를 비운 것이므로 후보 없음으로 유지한다.
        if "collection_ids" in request.model_fields_set:
            return request.collection_ids
        return None

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
        terms, query_source = self._ranking_terms(candidates, request)
        ranked: list[tuple[KnowledgeCandidate, float, list[str], list[str]]] = []
        for candidate in candidates:
            matched_terms = self._matched_terms(candidate, terms)
            source_priority = self._source_tier_priority(candidate)
            availability = _AVAILABILITY_ORDER.get(candidate.runtime_availability, 1)
            freshness = self._sync_freshness_score(candidate)
            kb_relevance = self._kb_relevance(candidate, terms, matched_terms)
            score = 0.0
            if kb_relevance > 0:
                score = (
                    kb_relevance * 0.70
                    + (source_priority / 100) * 0.10
                    + (availability / 3) * 0.10
                    + freshness * 0.10
                )
            used_signals = self._used_signals(
                matched_terms=matched_terms,
                source_priority=source_priority,
                availability=candidate.runtime_availability,
                freshness=freshness,
                structured_query=query_source == "structured",
                fallback_query=query_source == "fallback",
            )
            ranked.append(
                (
                    candidate,
                    max(0.0, min(score, 0.99)),
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
        safe_reason_code = self._safe_reason_code(
            matched_terms,
            request,
            structured_query="structured_safe_query" in used_signals,
        )
        recommendation_id = self._recommendation_id(candidate)
        threshold_result = (
            "high_confidence" if score >= 0.65 else "close_score" if score >= 0.45 else "below_threshold"
        )
        confidence_label = (
            "high" if score >= 0.65 else "medium" if score >= 0.45 else "low"
        )
        return KnowledgeRAGRecommendation(
            recommendation_id=recommendation_id,
            recommendation_mode=self._resolved_mode(request),
            candidate_id=recommendation_id,
            candidate_handle=recommendation_id,
            safe_label=safe_label,
            confidence=confidence_label,
            confidence_label=confidence_label,
            score=round(score, 4),
            reason_category=safe_reason_code,
            threshold_result=threshold_result,
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
        # Agent Builder-facing IDs must be opaque safe handles; the runtime KB
        # UUID remains available only in materialized_knowledge_bases.
        # Keep the handle namespace stable so existing preview drafts can still
        # materialize after ranking strategy changes.
        stable_id = uuid.uuid5(
            uuid.NAMESPACE_URL,
            (
                f"{RECOMMENDATION_HANDLE_NAMESPACE}:"
                f"{self.organization_id}:"
                f"{candidate.candidate_id}"
            ),
        )
        return f"rec-{stable_id}"

    def _clarification_options_from_recommendations(
        self,
        recommendations: list[KnowledgeRAGRecommendation],
    ) -> list[dict[str, Any]]:
        return [
            {
                "type": "knowledge_base",
                "candidate_id": item.candidate_handle or item.recommendation_id,
                "label": item.safe_label or GENERIC_KB_LABEL,
                "safe_label": item.safe_label,
                "confidence": item.confidence,
                "score": item.score,
                "reason_category": item.reason_category or item.safe_reason_code,
                "threshold_result": item.threshold_result,
                "runtime_availability": item.runtime_availability,
            }
            for item in recommendations
        ]

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
        sync_state = str((candidate.safe_metadata or {}).get("sync_state") or "").lower()
        if sync_state in {"stale", "failed"}:
            warnings.append(f"kb_sync_state_{sync_state}")
        if safe_label is None:
            warnings.append("safe_label_unavailable")
        return warnings

    def _safe_reason_code(
        self,
        matched_terms: list[str],
        request: KnowledgeRAGRecommendationRequest,
        *,
        structured_query: bool,
    ) -> str:
        if request.high_risk_domain != "none":
            return "high_risk_domain_requires_citation"
        if matched_terms:
            if structured_query:
                return "structured_intent_matches_safe_metadata"
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
        haystack, compact_haystack = self._candidate_texts(candidate)
        matched: list[str] = []
        for term in terms:
            if self._term_matches_text(term, haystack, compact_haystack):
                matched.append(term)
            if len(matched) >= 10:
                break
        return matched

    def _kb_relevance(
        self,
        candidate: KnowledgeCandidate,
        terms: list[str],
        matched_terms: list[str],
    ) -> float:
        if not terms:
            return 0.0
        match_ratio = len(matched_terms) / len(terms)
        if self._has_primary_structured_match(candidate, terms):
            return min(1.0, max(0.80, 0.75 + match_ratio * 0.25))
        return min(1.0, match_ratio)

    def _has_primary_structured_match(
        self,
        candidate: KnowledgeCandidate,
        terms: list[str],
    ) -> bool:
        primary_values: list[str] = []
        if candidate.safe_label:
            primary_values.append(candidate.safe_label)
        metadata = candidate.safe_metadata or {}
        for key in _KB_KEYWORD_LIST_METADATA_KEYS:
            value = metadata.get(key)
            if isinstance(value, (list, tuple, set)):
                primary_values.extend(str(item) for item in value if isinstance(item, str))
        haystack = self._normalize_match_text(" ".join(primary_values))
        compact_haystack = self._compact_match_text(haystack)
        return any(
            self._term_matches_text(term, haystack, compact_haystack)
            for term in terms
        )

    def _candidate_text(self, candidate: KnowledgeCandidate) -> str:
        return self._candidate_texts(candidate)[0]

    def _candidate_texts(self, candidate: KnowledgeCandidate) -> tuple[str, str]:
        values: list[str] = []
        if candidate.safe_label:
            values.append(candidate.safe_label)
        metadata = candidate.safe_metadata or {}
        for key in _KB_KEYWORD_STRING_METADATA_KEYS:
            value = metadata.get(key)
            if isinstance(value, str):
                values.append(value)
        for key in _KB_KEYWORD_LIST_METADATA_KEYS:
            value = metadata.get(key)
            if isinstance(value, (list, tuple, set)):
                values.extend(str(item) for item in value if isinstance(item, str))
        haystack = self._normalize_match_text(" ".join(values))
        return haystack, self._compact_match_text(haystack)

    def _query_terms(self, request: KnowledgeRAGRecommendationRequest) -> list[str]:
        if request.safe_query_topics:
            return self._structured_terms(request.safe_query_topics)
        return self._filtered_terms(request.workflow_intent, request.node_purpose)

    def _ranking_terms(
        self,
        candidates: list[KnowledgeCandidate],
        request: KnowledgeRAGRecommendationRequest,
    ) -> tuple[list[str], str]:
        structured_terms = self._query_terms(request)
        if not request.safe_query_topics:
            return structured_terms, "intent"
        if any(self._matched_terms(candidate, structured_terms) for candidate in candidates):
            return structured_terms, "structured"

        fallback_terms = self._filtered_terms(
            request.workflow_intent,
            request.node_purpose,
        )
        if fallback_terms:
            return fallback_terms, "fallback"
        return structured_terms, "structured"

    def _structured_terms(self, values: list[str]) -> list[str]:
        terms: list[str] = []
        for value in values:
            normalized = self._normalize_match_text(value)
            if not normalized or self._is_stop_term(normalized):
                continue
            if normalized not in terms:
                terms.append(normalized)
            if len(terms) >= 20:
                break
        return terms

    def _filtered_terms(self, *values: str | None) -> list[str]:
        return [
            term
            for term in self._terms(*values)
            if not self._is_stop_term(term)
        ]

    def _term_matches_text(
        self,
        term: str,
        haystack: str,
        compact_haystack: str,
    ) -> bool:
        normalized = self._normalize_match_text(term)
        if not normalized or self._is_stop_term(normalized):
            return False
        compact = self._compact_match_text(normalized)
        if normalized in haystack or (compact and compact in compact_haystack):
            return True
        tokens = [
            token
            for token in extract_safe_terms(normalized, limit=10)
            if not self._is_stop_term(token)
        ]
        return bool(tokens) and all(
            token in haystack or self._compact_match_text(token) in compact_haystack
            for token in tokens
        )

    def _normalize_match_text(self, value: object) -> str:
        return _WHITESPACE_RE.sub(" ", str(value or "").lower()).strip()

    def _compact_match_text(self, value: str) -> str:
        return _WHITESPACE_RE.sub("", value)

    def _is_stop_term(self, value: str) -> bool:
        normalized = self._normalize_match_text(value)
        compact = self._compact_match_text(normalized)
        return normalized in _SAFE_QUERY_STOP_TERMS or compact in _SAFE_QUERY_STOP_TERMS

    def _terms(self, *values: str | None) -> list[str]:
        return extract_safe_terms(*values, limit=50)

    def _source_tier_priority(self, candidate: KnowledgeCandidate) -> int:
        metadata = candidate.safe_metadata or {}
        return source_tier_priority(metadata.get("source_tier"))

    def _sync_freshness_score(self, candidate: KnowledgeCandidate) -> float:
        metadata = candidate.safe_metadata or {}
        sync_state = str(metadata.get("sync_state") or "").lower()
        if sync_state in {"stale", "failed"}:
            return 0.0
        source_acl_state = candidate.permission.source_acl_state
        if sync_state in _FRESH_SYNC_STATES or source_acl_state in {
            "fresh",
            "not_source_managed",
        }:
            return 1.0
        return 0.0

    def _freshness_bonus(self, candidate: KnowledgeCandidate) -> float:
        return self._sync_freshness_score(candidate)

    def _sync_state_penalty(self, candidate: KnowledgeCandidate) -> float:
        sync_state = str((candidate.safe_metadata or {}).get("sync_state") or "").lower()
        if sync_state in {"stale", "failed"}:
            return 0.1
        return 0.0

    def _used_signals(
        self,
        *,
        matched_terms: list[str],
        source_priority: int,
        availability: str,
        freshness: float,
        structured_query: bool = False,
        fallback_query: bool = False,
    ) -> list[str]:
        signals: list[str] = []
        if structured_query:
            signals.append("structured_safe_query")
        elif fallback_query:
            signals.append("fallback_safe_query")
        if matched_terms:
            signals.append("kb_relevance_match")
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
