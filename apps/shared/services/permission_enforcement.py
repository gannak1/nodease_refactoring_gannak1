from uuid import UUID

from sqlalchemy.orm import Session

from apps.shared.db.models.team import (
    Team,
    TeamLLMPermission,
    TeamMembership,
    TeamWorkflowPermission,
    UserLLMPermission,
    UserWorkflowPermission,
)
from apps.shared.schemas.permission import LLM_AUTH_STATE_RANK, WORKFLOW_AUTH_STATE_RANK


class PermissionEnforcementService:
    """Reusable RBAC enforcement helpers for API and runtime code."""

    @staticmethod
    def normalize_workflow_auth_state(auth_state: str | None) -> str:
        value = str(auth_state or "none").lower()
        if value not in WORKFLOW_AUTH_STATE_RANK:
            return "none"
        return value

    @staticmethod
    def normalize_llm_auth_state(auth_state: str | None) -> str:
        value = str(auth_state or "none").lower()
        if value not in LLM_AUTH_STATE_RANK:
            return "none"
        return value

    @classmethod
    def get_workflow_auth_state(
        cls,
        db: Session,
        organization_id: UUID,
        workflow_id: UUID,
        user_id: UUID,
    ) -> str:
        team_permissions = (
            db.query(TeamWorkflowPermission)
            .join(
                TeamMembership,
                TeamMembership.team_id == TeamWorkflowPermission.team_id,
            )
            .join(Team, Team.id == TeamWorkflowPermission.team_id)
            .filter(
                TeamMembership.user_id == user_id,
                TeamWorkflowPermission.workflow_id == workflow_id,
                TeamWorkflowPermission.grantee_organization_id == organization_id,
                TeamMembership.grantee_organization_id
                == TeamWorkflowPermission.grantee_organization_id,
                Team.organization_id == TeamWorkflowPermission.grantee_organization_id,
                Team.is_active.is_(True),
            )
            .all()
        )
        user_permissions = (
            db.query(UserWorkflowPermission)
            .filter(
                UserWorkflowPermission.user_id == user_id,
                UserWorkflowPermission.workflow_id == workflow_id,
                UserWorkflowPermission.grantee_organization_id == organization_id,
            )
            .all()
        )

        best_state = "none"
        best_rank = WORKFLOW_AUTH_STATE_RANK[best_state]
        for permission in [*team_permissions, *user_permissions]:
            state = cls.normalize_workflow_auth_state(permission.auth_state)
            rank = WORKFLOW_AUTH_STATE_RANK[state]
            if rank > best_rank:
                best_state = state
                best_rank = rank

        return best_state

    @classmethod
    def get_llm_credential_auth_state(
        cls,
        db: Session,
        organization_id: UUID,
        credential_id: UUID,
        user_id: UUID,
    ) -> str:
        team_permissions = (
            db.query(TeamLLMPermission)
            .join(
                TeamMembership,
                TeamMembership.team_id == TeamLLMPermission.team_id,
            )
            .join(Team, Team.id == TeamLLMPermission.team_id)
            .filter(
                TeamMembership.user_id == user_id,
                TeamLLMPermission.llm_credential_id == credential_id,
                TeamLLMPermission.grantee_organization_id == organization_id,
                TeamMembership.grantee_organization_id
                == TeamLLMPermission.grantee_organization_id,
                Team.organization_id == TeamLLMPermission.grantee_organization_id,
                Team.is_active.is_(True),
            )
            .all()
        )
        user_permissions = (
            db.query(UserLLMPermission)
            .filter(
                UserLLMPermission.user_id == user_id,
                UserLLMPermission.llm_credential_id == credential_id,
                UserLLMPermission.grantee_organization_id == organization_id,
            )
            .all()
        )

        best_state = "none"
        best_rank = LLM_AUTH_STATE_RANK[best_state]
        for permission in [*team_permissions, *user_permissions]:
            state = cls.normalize_llm_auth_state(permission.auth_state)
            rank = LLM_AUTH_STATE_RANK[state]
            if rank > best_rank:
                best_state = state
                best_rank = rank

        return best_state

    @classmethod
    def has_workflow_manage_permission(
        cls,
        db: Session,
        organization_id: UUID,
        workflow_id: UUID,
        user_id: UUID,
    ) -> bool:
        auth_state = cls.get_workflow_auth_state(
            db,
            organization_id,
            workflow_id,
            user_id,
        )
        return WORKFLOW_AUTH_STATE_RANK[auth_state] >= WORKFLOW_AUTH_STATE_RANK["manager"]

    @classmethod
    def has_llm_credential_manage_permission(
        cls,
        db: Session,
        organization_id: UUID,
        credential_id: UUID,
        user_id: UUID,
    ) -> bool:
        auth_state = cls.get_llm_credential_auth_state(
            db,
            organization_id,
            credential_id,
            user_id,
        )
        return LLM_AUTH_STATE_RANK[auth_state] >= LLM_AUTH_STATE_RANK["manager"]
