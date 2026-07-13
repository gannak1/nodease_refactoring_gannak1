"""
Shared 데이터베이스 모델 패키지

모든 SQLAlchemy 모델을 import하여 relationship이 올바르게 해결되도록 합니다.
Celery Worker에서 모델을 import할 때 순서 문제를 방지합니다.
"""

# User 모델 먼저 import (다른 모델에서 참조)
# 나머지 모델 import
from apps.shared.db.models.agent_builder import (
    AgentBuilderDraft,
    AgentBuilderRequest,
    AgentBuilderSession,
)
from apps.shared.db.models.app import App
from apps.shared.db.models.audit_log import AuditLog
from apps.shared.db.models.connection import Connection
from apps.shared.db.models.cost_optimizer import (
    CostOptimizerCandidate,
    CostOptimizerExperiment,
)
from apps.shared.db.models.knowledge import (
    Document,
    DocumentChunk,
    DocumentVersion,
    KnowledgeBase,
    KnowledgeCollection,
    KnowledgeCollectionItem,
    KnowledgeIngestionOutbox,
    KnowledgeSourceIdentity,
    RAGAnswerRun,
    SourceAuthorizationProvenance,
    SourcePolicyKBUseGrant,
)
from apps.shared.db.models.llm import (
    LLMCredential,
    LLMModel,
    LLMProvider,
    LLMRelCredentialModel,
    LLMUsageLog,
)
from apps.shared.db.models.llm_node_version import LLMNodeVersion
from apps.shared.db.models.mail_credential import (
    MAIL_CREDENTIAL_ACTIVE,
    MAIL_CREDENTIAL_REVOKED,
    MailCredential,
)
from apps.shared.db.models.mail_processing import (
    MailDraftEffect,
    MailMessageProcessing,
)
from apps.shared.db.models.model_routing_policy import (
    LLMNodeModelRoutingPolicy,
    LLMNodeModelRoutingPolicyRunEvent,
    LLMNodeModelRoutingPolicyUpdate,
)
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.organization_membership import (
    ORGANIZATION_AUTH_MANAGER,
    ORGANIZATION_AUTH_MEMBER,
    ORGANIZATION_MEMBERSHIP_ACTIVE,
    ORGANIZATION_MEMBERSHIP_INVITED,
    ORGANIZATION_MEMBERSHIP_REMOVED,
    ORGANIZATION_MEMBERSHIP_SUSPENDED,
    OrganizationMembership,
)
from apps.shared.db.models.permission_request import (
    PERMISSION_REQUEST_APPROVED,
    PERMISSION_REQUEST_PENDING,
    PERMISSION_REQUEST_REJECTED,
    REQUESTED_PERMISSION_APP_CREATE,
    PermissionRequest,
)
from apps.shared.db.models.schedule import Schedule
from apps.shared.db.models.schedule_dispatch import ScheduleDispatchClaim
from apps.shared.db.models.security_alert import (
    SecurityAlert,
    SecurityAlertAuditEvent,
    SecurityAlertNotificationOutbox,
    SecurityAlertReconciliationWatermark,
)
from apps.shared.db.models.team import (
    Team,
    TeamAssignmentMixin,
    TeamAuditPermission,
    TeamKnowledgeCollectionPermission,
    TeamKnowledgeDomainPermission,
    TeamKnowledgePermission,
    TeamLLMPermission,
    TeamMailCredentialPermission,
    TeamMembership,
    TeamResourcePermissionMixin,
    TeamWorkflowPermission,
    UserKnowledgeCollectionPermission,
    UserKnowledgeDomainPermission,
    UserKnowledgePermission,
    UserLLMPermission,
    UserMailCredentialPermission,
    UserResourcePermissionMixin,
    UserWorkflowPermission,
)
from apps.shared.db.models.user import User
from apps.shared.db.models.user_app_creation_permission import (
    UserAppCreationPermission,
)
from apps.shared.db.models.workflow import Workflow
from apps.shared.db.models.workflow_budget import WorkflowBudget
from apps.shared.db.models.workflow_deployment import WorkflowDeployment
from apps.shared.db.models.workflow_node_effect_attempt import (
    WorkflowNodeEffectAttempt,
)
from apps.shared.db.models.workflow_run import (
    TracePayload,
    TracePayloadAccessEvent,
    TraceRedactionPolicy,
    TraceRetentionPolicy,
    TraceVisibilityPolicy,
    WorkflowNodeRun,
    WorkflowRun,
)

__all__ = [
    "User",
    "App",
    "AuditLog",
    "AgentBuilderDraft",
    "AgentBuilderRequest",
    "AgentBuilderSession",
    "Connection",
    "CostOptimizerExperiment",
    "CostOptimizerCandidate",
    "Document",
    "DocumentChunk",
    "DocumentVersion",
    "KnowledgeCollection",
    "KnowledgeCollectionItem",
    "KnowledgeBase",
    "KnowledgeIngestionOutbox",
    "KnowledgeSourceIdentity",
    "RAGAnswerRun",
    "SourceAuthorizationProvenance",
    "SourcePolicyKBUseGrant",
    "LLMCredential",
    "LLMModel",
    "LLMProvider",
    "LLMRelCredentialModel",
    "LLMUsageLog",
    "MailCredential",
    "MAIL_CREDENTIAL_ACTIVE",
    "MAIL_CREDENTIAL_REVOKED",
    "MailMessageProcessing",
    "MailDraftEffect",
    "LLMNodeVersion",
    "LLMNodeModelRoutingPolicy",
    "LLMNodeModelRoutingPolicyRunEvent",
    "LLMNodeModelRoutingPolicyUpdate",
    "Schedule",
    "ScheduleDispatchClaim",
    "SecurityAlert",
    "SecurityAlertAuditEvent",
    "SecurityAlertNotificationOutbox",
    "SecurityAlertReconciliationWatermark",
    "Organization",
    "OrganizationMembership",
    "ORGANIZATION_MEMBERSHIP_INVITED",
    "ORGANIZATION_MEMBERSHIP_ACTIVE",
    "ORGANIZATION_MEMBERSHIP_SUSPENDED",
    "ORGANIZATION_MEMBERSHIP_REMOVED",
    "ORGANIZATION_AUTH_MEMBER",
    "ORGANIZATION_AUTH_MANAGER",
    "Team",
    "TeamAssignmentMixin",
    "TeamResourcePermissionMixin",
    "UserResourcePermissionMixin",
    "TeamMembership",
    "TeamKnowledgePermission",
    "TeamKnowledgeCollectionPermission",
    "TeamKnowledgeDomainPermission",
    "TeamLLMPermission",
    "TeamMailCredentialPermission",
    "TeamAuditPermission",
    "TeamWorkflowPermission",
    "UserWorkflowPermission",
    "UserLLMPermission",
    "UserMailCredentialPermission",
    "UserKnowledgePermission",
    "UserKnowledgeCollectionPermission",
    "UserKnowledgeDomainPermission",
    "UserAppCreationPermission",
    "PermissionRequest",
    "PERMISSION_REQUEST_PENDING",
    "PERMISSION_REQUEST_APPROVED",
    "PERMISSION_REQUEST_REJECTED",
    "REQUESTED_PERMISSION_APP_CREATE",
    "Workflow",
    "WorkflowBudget",
    "WorkflowDeployment",
    "WorkflowNodeRun",
    "WorkflowRun",
    "WorkflowNodeEffectAttempt",
    "TracePayload",
    "TracePayloadAccessEvent",
    "TraceRedactionPolicy",
    "TraceRetentionPolicy",
    "TraceVisibilityPolicy",
]
