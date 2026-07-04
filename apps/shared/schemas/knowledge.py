from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


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
