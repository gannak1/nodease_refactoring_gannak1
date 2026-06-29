import uuid
import re
from typing import Any, Optional

from sqlalchemy.orm import Session

from apps.shared.db.models.llm import LLMCredential
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.team import (
    Team,
    TeamLLMPermission,
    TeamMembership,
    TeamWorkflowPermission,
    UserLLMPermission,
    UserWorkflowPermission,
)
from apps.shared.db.models.workflow import Workflow
from apps.shared.permissions import (
    AUTH_STATE_MANAGER,
    AUTH_STATE_NONE,
    llm_credential_auth_state_allows,
    normalize_resource_auth_state,
    stronger_resource_auth_state,
    workflow_auth_state_allows,
)


def coerce_uuid(value: Any) -> Optional[uuid.UUID]:
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _same_uuid(left: Any, right: Any) -> bool:
    left_uuid = coerce_uuid(left)
    right_uuid = coerce_uuid(right)
    return left_uuid is not None and left_uuid == right_uuid


def _organization_manager_state(
    db: Session,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> Optional[str]:
    organization = (
        db.query(Organization).filter(Organization.id == organization_id).first()
    )
    return _manager_state_for_organization(organization, user_id)


def _manager_state_for_organization(
    organization: Optional[Organization],
    user_id: uuid.UUID,
) -> Optional[str]:
    if not organization or not organization.is_active:
        return None
    if _same_uuid(organization.created_by, user_id) or _same_uuid(
        organization.managed_by, user_id
    ):
        return AUTH_STATE_MANAGER
    return None


def has_organization_manager_permission(
    db: Session,
    user_id: Any,
    organization_id: Any,
) -> bool:
    user_uuid = coerce_uuid(user_id)
    organization_uuid = coerce_uuid(organization_id)
    if user_uuid is None or organization_uuid is None:
        return False
    return (
        _organization_manager_state(db, user_uuid, organization_uuid)
        == AUTH_STATE_MANAGER
    )


def has_organization_scope_access(
    db: Session,
    user_id: Any,
    organization_id: Any,
) -> bool:
    user_uuid = coerce_uuid(user_id)
    organization_uuid = coerce_uuid(organization_id)
    if user_uuid is None or organization_uuid is None:
        return False

    organization = (
        db.query(Organization).filter(Organization.id == organization_uuid).first()
    )
    if not organization or not organization.is_active:
        return False
    if _manager_state_for_organization(organization, user_uuid):
        return True

    return (
        db.query(TeamMembership)
        .join(Team, Team.id == TeamMembership.team_id)
        .filter(
            TeamMembership.user_id == user_uuid,
            TeamMembership.grantee_organization_id == organization_uuid,
            TeamMembership.grantee_organization_id == Team.organization_id,
            Team.is_active.is_(True),
        )
        .first()
        is not None
    )


def _workflow_scope(
    db: Session,
    workflow_id: Any,
    organization_id: Any = None,
) -> tuple[Optional[Workflow], Optional[uuid.UUID]]:
    workflow_uuid = coerce_uuid(workflow_id)
    requested_organization_uuid = coerce_uuid(organization_id)
    if workflow_uuid is None:
        return None, None

    workflow = db.query(Workflow).filter(Workflow.id == workflow_uuid).first()
    if not workflow:
        return None, None

    workflow_organization_uuid = coerce_uuid(workflow.organization_id)
    if (
        workflow_organization_uuid is not None
        and requested_organization_uuid is not None
        and workflow_organization_uuid != requested_organization_uuid
    ):
        return workflow, None

    return workflow, workflow_organization_uuid or requested_organization_uuid


def _llm_credential_scope(
    db: Session,
    llm_credential_id: Any,
    organization_id: Any = None,
) -> tuple[Optional[LLMCredential], Optional[uuid.UUID]]:
    credential_uuid = coerce_uuid(llm_credential_id)
    requested_organization_uuid = coerce_uuid(organization_id)
    if credential_uuid is None:
        return None, None

    credential = (
        db.query(LLMCredential).filter(LLMCredential.id == credential_uuid).first()
    )
    if not credential:
        return None, None

    credential_organization_uuid = coerce_uuid(credential.organization_id)
    if (
        credential_organization_uuid is not None
        and requested_organization_uuid is not None
        and credential_organization_uuid != requested_organization_uuid
    ):
        # Fails closed when a credential is addressed from another organization MBA-43
        return None, None

    return credential, credential_organization_uuid or requested_organization_uuid


def _auth_state_from_row(row: Any) -> Any:
    row_mapping = getattr(row, "_mapping", None)
    if row_mapping is not None:
        if "auth_state" in row_mapping:
            return row_mapping["auth_state"]
        return next(iter(row_mapping.values()), row)
    if isinstance(row, tuple):
        return row[0]
    return row


def _strongest_auth_state(rows: list[Any], current: str) -> str:
    result = current
    for row in rows:
        auth_state = _auth_state_from_row(row)
        result = stronger_resource_auth_state(result, auth_state)
    return result


def _model_policy_patterns(options: Any) -> list[str]:
    # Extracts model deny patterns from options for model restriction checks MBA-43
    if not isinstance(options, dict):
        return []
    model_policy = options.get("model_policy")
    if not isinstance(model_policy, dict):
        return []
    raw_patterns = model_policy.get("unallowed_model_patterns")
    if not isinstance(raw_patterns, list):
        return []
    return [
        str(pattern).strip().lower()
        for pattern in raw_patterns
        if str(pattern).strip()
    ]


def model_id_matches_pattern(model_id: Any, pattern: Any) -> bool:
    # Matches provider model ids with exact-or-wildcard glob semantics MBA-43
    normalized_model_id = str(model_id or "").strip().lower()
    normalized_pattern = str(pattern or "").strip().lower()
    if not normalized_model_id or not normalized_pattern:
        return False
    escaped_pattern = re.escape(normalized_pattern).replace(r"\*", ".*")
    return re.fullmatch(escaped_pattern, normalized_model_id) is not None


def is_llm_model_blocked_by_policy(
    db: Session,
    user_id: Any,
    organization_id: Any,
    model_id: Any,
) -> bool:
    # Checks team and membership model restriction policy for one runtime model MBA-43
    user_uuid = coerce_uuid(user_id)
    organization_uuid = coerce_uuid(organization_id)
    if user_uuid is None or organization_uuid is None:
        return False

    normalized_model_id = str(model_id or "").lower()
    if not normalized_model_id:
        return False

    rows = (
        db.query(Team.options, TeamMembership.options)
        .join(TeamMembership, TeamMembership.team_id == Team.id)
        .filter(
            TeamMembership.user_id == user_uuid,
            TeamMembership.grantee_organization_id == organization_uuid,
            TeamMembership.grantee_organization_id == Team.organization_id,
            Team.organization_id == organization_uuid,
            Team.is_active.is_(True),
        )
        .all()
    )

    for team_options, membership_options in rows:
        patterns = _model_policy_patterns(team_options)
        patterns.extend(_model_policy_patterns(membership_options))
        if any(
            model_id_matches_pattern(normalized_model_id, pattern)
            for pattern in patterns
        ):
            return True
    return False


def get_effective_workflow_auth_state(
    db: Session,
    user_id: Any,
    workflow_id: Any,
    organization_id: Any = None,
) -> str:
    user_uuid = coerce_uuid(user_id)
    workflow, organization_uuid = _workflow_scope(db, workflow_id, organization_id)
    if user_uuid is None or workflow is None or organization_uuid is None:
        return AUTH_STATE_NONE

    organization = (
        db.query(Organization).filter(Organization.id == organization_uuid).first()
    )
    if not organization or not organization.is_active:
        return AUTH_STATE_NONE

    manager_state = _manager_state_for_organization(organization, user_uuid)
    if manager_state:
        return manager_state

    team_rows = (
        db.query(TeamWorkflowPermission.auth_state)
        .join(TeamMembership, TeamMembership.team_id == TeamWorkflowPermission.team_id)
        .join(Team, Team.id == TeamWorkflowPermission.team_id)
        .filter(
            TeamMembership.user_id == user_uuid,
            TeamWorkflowPermission.workflow_id == workflow.id,
            Team.is_active.is_(True),
            TeamMembership.grantee_organization_id == organization_uuid,
            TeamWorkflowPermission.grantee_organization_id == organization_uuid,
            TeamMembership.grantee_organization_id
            == TeamWorkflowPermission.grantee_organization_id,
            Team.organization_id == organization_uuid,
        )
        .all()
    )
    direct_rows = (
        db.query(UserWorkflowPermission.auth_state)
        .filter(
            UserWorkflowPermission.user_id == user_uuid,
            UserWorkflowPermission.workflow_id == workflow.id,
            UserWorkflowPermission.grantee_organization_id == organization_uuid,
        )
        .all()
    )

    effective_state = _strongest_auth_state(team_rows, AUTH_STATE_NONE)
    return _strongest_auth_state(direct_rows, effective_state)


def has_workflow_permission(
    db: Session,
    user_id: Any,
    workflow_id: Any,
    action: str,
    organization_id: Any = None,
) -> bool:
    auth_state = get_effective_workflow_auth_state(
        db, user_id, workflow_id, organization_id=organization_id
    )
    return workflow_auth_state_allows(auth_state, action)


def get_effective_llm_credential_auth_state(
    db: Session,
    user_id: Any,
    llm_credential_id: Any,
    organization_id: Any = None,
) -> str:
    user_uuid = coerce_uuid(user_id)
    credential, organization_uuid = _llm_credential_scope(
        db, llm_credential_id, organization_id
    )
    if user_uuid is None or credential is None:
        return AUTH_STATE_NONE

    if organization_uuid is None:
        if _same_uuid(credential.user_id, user_uuid):
            return AUTH_STATE_MANAGER
        return AUTH_STATE_NONE

    organization = (
        db.query(Organization).filter(Organization.id == organization_uuid).first()
    )
    if not organization or not organization.is_active:
        return AUTH_STATE_NONE

    manager_state = _manager_state_for_organization(organization, user_uuid)
    if manager_state:
        return manager_state

    team_rows = (
        db.query(TeamLLMPermission.auth_state)
        .join(TeamMembership, TeamMembership.team_id == TeamLLMPermission.team_id)
        .join(Team, Team.id == TeamLLMPermission.team_id)
        .filter(
            TeamMembership.user_id == user_uuid,
            TeamLLMPermission.llm_credential_id == credential.id,
            Team.is_active.is_(True),
            TeamMembership.grantee_organization_id == organization_uuid,
            TeamLLMPermission.grantee_organization_id == organization_uuid,
            TeamMembership.grantee_organization_id
            == TeamLLMPermission.grantee_organization_id,
            Team.organization_id == organization_uuid,
        )
        .all()
    )
    direct_rows = (
        db.query(UserLLMPermission.auth_state)
        .filter(
            UserLLMPermission.user_id == user_uuid,
            UserLLMPermission.llm_credential_id == credential.id,
            UserLLMPermission.grantee_organization_id == organization_uuid,
        )
        .all()
    )

    effective_state = _strongest_auth_state(team_rows, AUTH_STATE_NONE)
    return _strongest_auth_state(direct_rows, effective_state)


def has_llm_credential_permission(
    db: Session,
    user_id: Any,
    llm_credential_id: Any,
    action: str,
    organization_id: Any = None,
) -> bool:
    auth_state = get_effective_llm_credential_auth_state(
        db,
        user_id,
        llm_credential_id,
        organization_id=organization_id,
    )
    return llm_credential_auth_state_allows(auth_state, action)


def canonical_effective_auth_state(auth_state: Any) -> str:
    return normalize_resource_auth_state(auth_state)
