import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


SourceAclState = Literal[
    "fresh",
    "stale",
    "unmapped",
    "ambiguous",
    "unverified",
    "revoked",
    "not_source_managed",
]
RequesterSourceAuthorization = Literal[
    "allowed",
    "denied",
    "unknown",
    "not_applicable",
]
ResourceVisibility = Literal["visible", "resource_hidden", "hidden", "admin_visible"]
RuntimeAvailability = Literal["available", "warning", "unavailable", "unknown"]
KnowledgeCandidateType = Literal["knowledge_base", "collection"]
KnowledgeCandidateResolutionMode = Literal["explicit_kb", "auto_collection"]
KnowledgeCandidatePurpose = Literal[
    "builder_suggestion",
    "deployment_preflight",
    "runtime_preview",
]
KnowledgeRAGRecommendationMode = Literal["auto", "explicit_kb", "auto_collection"]
KnowledgeRAGRecommendationResolvedMode = Literal["explicit_kb", "auto_collection"]
KnowledgeRAGHighRiskDomain = Literal["none", "policy", "legal", "compliance"]
KnowledgeRAGCandidateType = Literal["knowledge_base"]
KnowledgeRAGQueryRewriteMode = Literal["off", "template"]
KnowledgeRAGEvidenceSufficiencyPolicy = Literal["minimum_evidence", "strict_citation"]
KnowledgeRAGFailurePolicy = Literal["safe_no_result", "fail_node"]
KnowledgeRAGSourceTierPolicy = Literal["tie_break", "off"]
KnowledgeCollectionAction = Literal["read", "route", "manage", "sync"]
KnowledgeCollectionVisibility = Literal["private", "public"]
KnowledgeCollectionLifecycleState = Literal["active", "archived", "deleted"]

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+")


class KnowledgePermissionDecision(BaseModel):
    allowed: bool
    resource_visibility: ResourceVisibility = "resource_hidden"
    effective_auth_state: str = "none"
    source_acl_state: SourceAclState = "not_source_managed"
    requester_source_authorization: RequesterSourceAuthorization = "not_applicable"
    freshness_epoch: int = 0
    reason_code: str = "resource.hidden"
    external_reason_code: str = "resource.hidden"
    safe_metadata: dict = Field(default_factory=dict)


class KnowledgeCandidate(BaseModel):
    candidate_id: UUID
    candidate_type: KnowledgeCandidateType
    permission: KnowledgePermissionDecision
    runtime_availability: RuntimeAvailability = "unknown"
    safe_label: str | None = None
    safe_metadata: dict = Field(default_factory=dict)


class KnowledgeCandidateResolution(BaseModel):
    candidates: list[KnowledgeCandidate] = Field(default_factory=list)
    hidden_candidate_count_bucket: str = "0"
    unavailable_candidate_count_bucket: str = "0"
    reason_code: str | None = None


class KnowledgeCandidateResolveRequest(BaseModel):
    mode: KnowledgeCandidateResolutionMode
    knowledge_base_ids: list[UUID] = Field(default_factory=list)
    collection_ids: list[UUID] | None = None
    intended_execution_subject_id: UUID | None = None
    purpose: KnowledgeCandidatePurpose = "builder_suggestion"
    max_collections: int = Field(default=20, ge=1, le=100)
    max_candidate_kbs: int = Field(default=5000, ge=1, le=5000)


class KnowledgeCollectionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    safe_metadata: dict = Field(default_factory=dict)


class KnowledgeCollectionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    safe_metadata: dict | None = None


class KnowledgeCollectionResponse(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    description: str | None = None
    is_system_managed: bool = False
    sync_state: str = "manual"
    lifecycle_state: KnowledgeCollectionLifecycleState = "active"
    visibility: KnowledgeCollectionVisibility = "private"
    linked_kb_count_bucket: str = "0"
    active_kb_count_bucket: str = "0"
    can_read: bool = False
    can_route: bool = False
    can_manage: bool = False
    can_sync: bool = False
    safe_metadata: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class KnowledgeCollectionListResponse(BaseModel):
    collections: list[KnowledgeCollectionResponse] = Field(default_factory=list)
    can_create_collection: bool = False
    can_change_public_visibility: bool = False


class KnowledgeCollectionItemLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_base_id: UUID
    rank: int = Field(default=0, ge=0)


class KnowledgeCollectionItemResponse(BaseModel):
    item_id: UUID
    knowledge_base_id: UUID
    safe_label: str | None = None
    lifecycle_state: str = "active"
    sync_state: str = "manual"
    rank: int = 0
    can_manage_kb: bool = False
    can_use_kb: bool = False


class KnowledgeCollectionItemsResponse(BaseModel):
    items: list[KnowledgeCollectionItemResponse] = Field(default_factory=list)


class KnowledgeCollectionItemReorderEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: UUID
    rank: int = Field(ge=0)


class KnowledgeCollectionItemReorderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[KnowledgeCollectionItemReorderEntry] = Field(
        ..., min_length=1, max_length=500
    )


class KnowledgeCollectionLinkCandidate(BaseModel):
    knowledge_base_id: UUID
    safe_label: str | None = None
    disabled: bool = False
    safe_reason_code: str | None = None


class KnowledgeCollectionLinkCandidatesResponse(BaseModel):
    candidates: list[KnowledgeCollectionLinkCandidate] = Field(default_factory=list)


class KnowledgeCollectionPermissionGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_type: Literal["team", "user"]
    subject_id: UUID
    permission_action: KnowledgeCollectionAction


class KnowledgeCollectionPermissionResponse(BaseModel):
    permission_id: UUID
    subject_type: Literal["team", "user"]
    subject_id: UUID
    subject_safe_label: str | None = None
    permission_action: KnowledgeCollectionAction


class KnowledgeCollectionPermissionsResponse(BaseModel):
    permissions: list[KnowledgeCollectionPermissionResponse] = Field(
        default_factory=list
    )


class KnowledgeCollectionVisibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: KnowledgeCollectionVisibility
    acknowledged_public_runtime_exposure: bool = False


class KnowledgeCollectionVisibilityResponse(BaseModel):
    collection: KnowledgeCollectionResponse
    public_runtime_effect: str = "anonymous_public_only_candidate"
    linked_kb_count_bucket: str = "0"
    active_kb_count_bucket: str = "0"
    sensitive_content_warning: str = "unknown_or_present"


def normalize_recommendation_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _CONTROL_CHAR_RE.sub(" ", value)
    normalized = " ".join(normalized.split())
    return normalized


class KnowledgeRAGRecommendationRequest(BaseModel):
    workflow_intent: str = Field(..., min_length=1, max_length=4000)
    node_purpose: str | None = Field(default=None, max_length=1000)
    mode: KnowledgeRAGRecommendationMode = "auto"
    collection_ids: list[UUID] = Field(default_factory=list)
    knowledge_base_ids: list[UUID] = Field(default_factory=list)
    intended_execution_subject_id: UUID | None = None
    max_recommendations: int = Field(default=5, ge=1, le=20)
    max_collections: int = Field(default=20, ge=1, le=100)
    max_candidate_kbs: int = Field(default=5000, ge=1, le=5000)
    high_risk_domain: KnowledgeRAGHighRiskDomain = "none"
    allow_query_rewrite: bool = True

    @field_validator("workflow_intent", "node_purpose")
    @classmethod
    def normalize_raw_text(cls, value: str | None) -> str | None:
        normalized = normalize_recommendation_text(value)
        if normalized is None:
            return None
        if not normalized:
            raise ValueError("text must not be empty")
        return normalized


class KnowledgeBaseOptionRef(BaseModel):
    id: UUID
    name: str = "Knowledge Base"


class KnowledgeRAGRecommendedOptions(BaseModel):
    queryRewriteMode: KnowledgeRAGQueryRewriteMode = "off"
    queryRewriteTemplate: str | None = Field(default=None, max_length=512)
    evidenceSufficiencyPolicy: KnowledgeRAGEvidenceSufficiencyPolicy = (
        "minimum_evidence"
    )
    ragFailurePolicy: KnowledgeRAGFailurePolicy = "safe_no_result"
    sourceTierPolicy: KnowledgeRAGSourceTierPolicy = "tie_break"
    scoreThreshold: float = Field(default=0.5, ge=0.0, le=1.0)
    topK: int = Field(default=3, ge=1, le=8)


class KnowledgeSourceCollectionSummary(BaseModel):
    collection_id: UUID | None = None
    safe_label: str | None = None
    route_scope_type: str | None = None
    linked_kb_count_bucket: str | None = None


class KnowledgeRAGRecommendationProvenance(BaseModel):
    recommendation_strategy: str = "metadata_keyword_v1"
    safe_reason_code: str
    used_signals: list[str] = Field(default_factory=list)
    matched_safe_terms: list[str] = Field(default_factory=list)
    candidate_count_bucket: str = "0"
    warning_count_bucket: str = "0"


class KnowledgeRAGRecommendation(BaseModel):
    recommendation_id: str
    recommendation_mode: KnowledgeRAGRecommendationResolvedMode
    candidate_type: KnowledgeRAGCandidateType = "knowledge_base"
    candidate_id: UUID
    safe_label: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    safe_reason_code: str
    recommended_options: KnowledgeRAGRecommendedOptions
    materialized_knowledge_bases: list[KnowledgeBaseOptionRef] = Field(
        default_factory=list
    )
    source_collection_summary: KnowledgeSourceCollectionSummary | None = None
    provenance: KnowledgeRAGRecommendationProvenance
    runtime_availability: RuntimeAvailability = "unknown"
    warnings: list[str] = Field(default_factory=list)


class KnowledgeRAGRecommendationSummary(BaseModel):
    candidate_count_bucket: str = "0"
    recommendation_count_bucket: str = "0"
    hidden_or_unavailable_count_bucket: str = "0"
    recommendation_strategy: str = "metadata_keyword_v1"
    warning_count_bucket: str = "0"


class KnowledgeRAGRecommendationResponse(BaseModel):
    recommendations: list[KnowledgeRAGRecommendation] = Field(default_factory=list)
    summary: KnowledgeRAGRecommendationSummary = Field(
        default_factory=KnowledgeRAGRecommendationSummary
    )
    reason_code: str | None = None
