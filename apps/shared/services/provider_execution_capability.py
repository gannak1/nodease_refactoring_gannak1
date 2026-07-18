"""Credential-policy resolution and opaque provider execution capabilities.

The module is intentionally owned by the LLM Credentials domain.  It resolves
the credential only from a server-managed deployment policy; workflow graphs,
execution subjects and public callers cannot select or replace it.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal
from typing import Any

from sqlalchemy.orm import Session

from apps.shared.db.models.app import App
from apps.shared.db.models.llm import (
    LLMCredential,
    LLMDeploymentCredentialPolicy,
    LLMModel,
    LLMProvider,
    LLMRelCredentialModel,
    ProviderExecutionCapabilityRecord,
)
from apps.shared.db.models.organization_membership import OrganizationMembership
from apps.shared.db.models.team import (
    Team,
    TeamLLMPermission,
    TeamMembership,
    UserLLMPermission,
)
from apps.shared.db.models.workflow import Workflow
from apps.shared.db.models.workflow_deployment import WorkflowDeployment
from apps.shared.domain.provider_execution_capability import (
    CapabilityBindingError,
    CapabilityPurpose,
    ProviderExecutionBinding,
    ProviderExecutionCapability,
    RuntimeIdentityContext,
    RuntimePrincipal,
)
from apps.shared.services.permissions import (
    get_effective_llm_credential_auth_state,
    has_llm_credential_permission,
    has_organization_manager_permission,
)


CAPABILITY_TTL = timedelta(minutes=5)
_LLM_NODE_TYPES = {"llmnode", "llm"}
_DIRECT_CREDENTIAL_FIELDS = {
    "credential_id",
    "credentialId",
    "llm_credential_id",
    "llmCredentialId",
}


class ProviderExecutionPolicyError(ValueError):
    """A sanitized reason suitable for an API or runtime boundary."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class DeploymentCredentialPolicyCommand:
    organization_id: uuid.UUID
    deployment_id: uuid.UUID
    node_id: str
    model_id: uuid.UUID
    credential_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ProviderExecutionCapabilityIssueCommand:
    binding: ProviderExecutionBinding
    execution_subject: RuntimePrincipal
    billing_principal: RuntimePrincipal
    audit_actor: RuntimePrincipal
    input_token_cap: int
    output_token_cap: int
    cost_cap_microusd: int


@dataclass(frozen=True, slots=True)
class ProviderExecutionCapabilityAdmissionCommand:
    capability_id: uuid.UUID
    capability_revision: int
    binding: ProviderExecutionBinding
    requested_input_tokens: int
    requested_output_tokens: int


@dataclass(frozen=True, slots=True)
class ProviderExecutionCredentialLease:
    """Internal-only provider client materialization input.

    ``credential`` is deliberately not serializable and must never cross an
    HTTP response, trace or audit boundary.
    """

    capability: ProviderExecutionCapability
    credential: LLMCredential
    model: LLMModel
    provider: LLMProvider


@dataclass(frozen=True, slots=True)
class DeploymentCredentialPolicyView:
    id: uuid.UUID
    deployment_id: uuid.UUID
    deployment_version: int
    node_id: str
    model_id: uuid.UUID
    credential_id: uuid.UUID
    policy_revision: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


def deployment_llm_node_model_id(graph_snapshot: Any, node_id: str) -> str:
    """Return the only graph-owned LLM selection: its model API identifier.

    The policy layer does not silently normalize legacy direct credential
    fields.  A capability-required deployment must be unambiguous before an
    external provider can be reached.
    """

    if not isinstance(graph_snapshot, dict) or not node_id:
        raise ProviderExecutionPolicyError("configuration_required")
    nodes = graph_snapshot.get("nodes")
    if not isinstance(nodes, list):
        raise ProviderExecutionPolicyError("configuration_required")

    candidates = [
        node
        for node in nodes
        if isinstance(node, dict) and str(node.get("id") or "") == node_id
    ]
    if len(candidates) != 1:
        raise ProviderExecutionPolicyError("configuration_required")

    node = candidates[0]
    node_type = str(node.get("type") or "").strip().lower()
    data = node.get("data")
    if node_type not in _LLM_NODE_TYPES or not isinstance(data, dict):
        raise ProviderExecutionPolicyError("configuration_required")
    if any(field in data for field in _DIRECT_CREDENTIAL_FIELDS):
        raise ProviderExecutionPolicyError("configuration_required")
    if data.get("auto_model_routing") or data.get("fallback_model_id"):
        raise ProviderExecutionPolicyError("configuration_required")

    model_id = str(data.get("model_id") or "").strip()
    if not model_id:
        raise ProviderExecutionPolicyError("configuration_required")
    return model_id


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_json_value(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, tuple):
        return [_safe_json_value(item) for item in value]
    if isinstance(value, list):
        return [_safe_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe_json_value(item) for key, item in value.items()}
    return value


def _revision_digest(value: Any) -> str:
    encoded = json.dumps(
        _safe_json_value(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ProviderExecutionCapabilityService:
    """Issue and admit short-lived provider scopes from immutable deployments."""

    @classmethod
    def replace_deployment_policy(
        cls,
        db: Session,
        *,
        actor_id: uuid.UUID,
        command: DeploymentCredentialPolicyCommand,
    ) -> DeploymentCredentialPolicyView:
        deployment, app, workflow = cls._canonical_deployment(
            db,
            organization_id=command.organization_id,
            deployment_id=command.deployment_id,
            lock=True,
        )
        if not has_organization_manager_permission(
            db, actor_id, command.organization_id
        ):
            raise ProviderExecutionPolicyError("permission_denied")

        model, credential, _provider, _relation = cls._resolve_policy_selection(
            db,
            deployment=deployment,
            app=app,
            workflow=workflow,
            organization_id=command.organization_id,
            node_id=command.node_id,
            model_id=command.model_id,
            credential_id=command.credential_id,
            credential_principal_user_id=actor_id,
        )

        active_rows = (
            db.query(LLMDeploymentCredentialPolicy)
            .filter(
                LLMDeploymentCredentialPolicy.organization_id
                == command.organization_id,
                LLMDeploymentCredentialPolicy.deployment_id == deployment.id,
                LLMDeploymentCredentialPolicy.deployment_version == deployment.version,
                LLMDeploymentCredentialPolicy.node_id == command.node_id,
                LLMDeploymentCredentialPolicy.is_active.is_(True),
            )
            .with_for_update()
            .all()
        )
        if len(active_rows) > 1:
            raise ProviderExecutionPolicyError("selection_ambiguous")

        if active_rows:
            active_rows[0].is_active = False
            next_revision = active_rows[0].policy_revision + 1
            # The partial unique index covers only active rows.  Flush the
            # superseded row before inserting its replacement so a repeat
            # PUT cannot depend on ORM statement ordering.
            db.flush()
        else:
            next_revision = 1

        policy = LLMDeploymentCredentialPolicy(
            organization_id=command.organization_id,
            workflow_id=workflow.id,
            deployment_id=deployment.id,
            deployment_version=deployment.version,
            node_id=command.node_id,
            model_id=model.id,
            credential_id=credential.id,
            credential_principal_user_id=actor_id,
            policy_revision=next_revision,
            is_active=True,
        )
        db.add(policy)
        db.flush()
        return cls._policy_view(policy)


    @classmethod
    def list_deployment_policies(
        cls,
        db: Session,
        *,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        deployment_id: uuid.UUID,
    ) -> list[DeploymentCredentialPolicyView]:
        deployment, _app, _workflow = cls._canonical_deployment(
            db,
            organization_id=organization_id,
            deployment_id=deployment_id,
        )
        if not has_organization_manager_permission(db, actor_id, organization_id):
            raise ProviderExecutionPolicyError("permission_denied")
        rows = (
            db.query(LLMDeploymentCredentialPolicy)
            .filter(
                LLMDeploymentCredentialPolicy.organization_id == organization_id,
                LLMDeploymentCredentialPolicy.deployment_id == deployment.id,
                LLMDeploymentCredentialPolicy.deployment_version == deployment.version,
                LLMDeploymentCredentialPolicy.is_active.is_(True),
            )
            .order_by(LLMDeploymentCredentialPolicy.node_id.asc())
            .all()
        )
        return [cls._policy_view(row) for row in rows]

    @classmethod
    def issue_capability(
        cls,
        db: Session,
        *,
        command: ProviderExecutionCapabilityIssueCommand,
        now: datetime | None = None,
    ) -> ProviderExecutionCapability:
        now = now or _utc_now()
        cls._validate_nonnegative_caps(
            command.input_token_cap,
            command.output_token_cap,
            command.cost_cap_microusd,
        )
        binding = command.binding
        deployment, app, workflow = cls._canonical_deployment(
            db,
            organization_id=binding.organization_id,
            deployment_id=binding.deployment_id,
        )
        cls._assert_binding_matches_deployment(
            binding,
            deployment=deployment,
            workflow=workflow,
        )
        policy = cls._active_policy_for_binding(db, binding)
        cls._validate_issue_principals(
            command,
            credential_principal_user_id=policy.credential_principal_user_id,
        )
        model, credential, provider, relation = cls._resolve_policy_selection(
            db,
            deployment=deployment,
            app=app,
            workflow=workflow,
            organization_id=binding.organization_id,
            node_id=binding.node_id,
            model_id=policy.model_id,
            credential_id=policy.credential_id,
            credential_principal_user_id=policy.credential_principal_user_id,
        )
        revisions = cls._current_revisions(
            db,
            organization_id=binding.organization_id,
            credential=credential,
            credential_principal_user_id=policy.credential_principal_user_id,
            relation=relation,
            model=model,
            provider=provider,
        )

        existing = (
            db.query(ProviderExecutionCapabilityRecord)
            .filter(
                ProviderExecutionCapabilityRecord.organization_id
                == binding.organization_id,
                ProviderExecutionCapabilityRecord.provider_attempt_id
                == binding.provider_attempt_id,
                ProviderExecutionCapabilityRecord.purpose == binding.purpose.value,
            )
            .with_for_update()
            .one_or_none()
        )
        if existing is not None:
            existing_capability = cls._domain_capability(existing)
            try:
                existing_capability.require_usable(
                    binding=binding,
                    revision=existing.capability_revision,
                    now=now,
                )
            except CapabilityBindingError as exc:
                raise ProviderExecutionPolicyError("capability_stale") from exc
            if (
                existing.input_token_cap != command.input_token_cap
                or existing.output_token_cap != command.output_token_cap
                or existing.cost_cap_microusd != command.cost_cap_microusd
            ):
                raise ProviderExecutionPolicyError("capability_attempt_reused")
            if not cls._record_matches_issue_identity(existing, command):
                raise ProviderExecutionPolicyError("capability_attempt_reused")
            if (
                existing.policy_id != policy.id
                or existing.policy_revision != policy.policy_revision
                or existing.model_id != model.id
                or existing.credential_id != credential.id
                or existing.provider_id != provider.id
                or existing.credential_principal_user_id
                != policy.credential_principal_user_id
                or any(
                    getattr(existing, f"{name}_revision") != revision
                    for name, revision in revisions.items()
                )
            ):
                raise ProviderExecutionPolicyError("capability_stale")
            return existing_capability

        record = ProviderExecutionCapabilityRecord(
            organization_id=binding.organization_id,
            policy_id=policy.id,
            workflow_id=binding.workflow_id,
            deployment_id=binding.deployment_id,
            deployment_version=binding.deployment_version,
            node_id=binding.node_id,
            node_invocation_id=binding.node_invocation_id,
            execution_admission_id=binding.execution_admission_id,
            provider_attempt_id=binding.provider_attempt_id,
            purpose=binding.purpose.value,
            provider_id=provider.id,
            model_id=model.id,
            credential_id=credential.id,
            credential_principal_user_id=policy.credential_principal_user_id,
            execution_subject_kind=command.execution_subject.kind.value,
            execution_subject_id=command.execution_subject.reference_id,
            billing_principal_kind=command.billing_principal.kind.value,
            billing_principal_id=command.billing_principal.reference_id,
            audit_actor_kind=command.audit_actor.kind.value,
            audit_actor_id=command.audit_actor.reference_id,
            capability_revision=1,
            policy_revision=policy.policy_revision,
            permission_revision=revisions["permission"],
            relation_revision=revisions["relation"],
            egress_revision=revisions["egress"],
            pricing_revision=revisions["pricing"],
            input_token_cap=command.input_token_cap,
            output_token_cap=command.output_token_cap,
            cost_cap_microusd=command.cost_cap_microusd,
            state="active",
            expires_at=now + CAPABILITY_TTL,
        )
        db.add(record)
        db.flush()
        return cls._domain_capability(record)

    @classmethod
    def admit_capability(
        cls,
        db: Session,
        *,
        command: ProviderExecutionCapabilityAdmissionCommand,
        now: datetime | None = None,
    ) -> ProviderExecutionCredentialLease:
        now = now or _utc_now()
        cls._validate_nonnegative_caps(
            command.requested_input_tokens,
            command.requested_output_tokens,
        )
        deployment, app, workflow = cls._canonical_deployment(
            db,
            organization_id=command.binding.organization_id,
            deployment_id=command.binding.deployment_id,
        )
        cls._assert_binding_matches_deployment(
            command.binding,
            deployment=deployment,
            workflow=workflow,
        )
        policy = cls._active_policy_for_binding(db, command.binding)
        record = (
            db.query(ProviderExecutionCapabilityRecord)
            .filter(ProviderExecutionCapabilityRecord.id == command.capability_id)
            .with_for_update()
            .one_or_none()
        )
        if record is None:
            raise ProviderExecutionPolicyError("capability_stale")
        capability = cls._domain_capability(record)
        try:
            capability.require_usable(
                binding=command.binding,
                revision=command.capability_revision,
                now=now,
            )
        except CapabilityBindingError as exc:
            raise ProviderExecutionPolicyError("capability_stale") from exc
        if (
            command.requested_input_tokens > capability.input_token_cap
            or command.requested_output_tokens > capability.output_token_cap
        ):
            raise ProviderExecutionPolicyError("capability_stale")
        if (
            policy.id != record.policy_id
            or policy.policy_revision != record.policy_revision
        ):
            raise ProviderExecutionPolicyError("capability_stale")
        model, credential, provider, relation = cls._resolve_policy_selection(
            db,
            deployment=deployment,
            app=app,
            workflow=workflow,
            organization_id=command.binding.organization_id,
            node_id=command.binding.node_id,
            model_id=policy.model_id,
            credential_id=policy.credential_id,
            credential_principal_user_id=policy.credential_principal_user_id,
        )
        if (
            record.model_id != model.id
            or record.credential_id != credential.id
            or record.provider_id != provider.id
            or record.credential_principal_user_id
            != policy.credential_principal_user_id
        ):
            raise ProviderExecutionPolicyError("capability_stale")
        revisions = cls._current_revisions(
            db,
            organization_id=command.binding.organization_id,
            credential=credential,
            credential_principal_user_id=policy.credential_principal_user_id,
            relation=relation,
            model=model,
            provider=provider,
        )
        if any(
            getattr(record, f"{name}_revision") != revision
            for name, revision in revisions.items()
        ):
            raise ProviderExecutionPolicyError("capability_stale")
        requested_cost_microusd = cls._request_cost_microusd(
            model,
            input_tokens=command.requested_input_tokens,
            output_tokens=command.requested_output_tokens,
        )
        if requested_cost_microusd > capability.cost_cap_microusd:
            raise ProviderExecutionPolicyError("capability_stale")
        return ProviderExecutionCredentialLease(
            capability=capability,
            credential=credential,
            model=model,
            provider=provider,
        )

    @staticmethod
    def _policy_view(
        policy: LLMDeploymentCredentialPolicy,
    ) -> DeploymentCredentialPolicyView:
        return DeploymentCredentialPolicyView(
            id=policy.id,
            deployment_id=policy.deployment_id,
            deployment_version=policy.deployment_version,
            node_id=policy.node_id,
            model_id=policy.model_id,
            credential_id=policy.credential_id,
            policy_revision=policy.policy_revision,
            is_active=policy.is_active,
            created_at=policy.created_at,
            updated_at=policy.updated_at,
        )

    @staticmethod
    def _validate_nonnegative_caps(*caps: int) -> None:
        if any(
            isinstance(cap, bool) or not isinstance(cap, int) or cap < 0
            for cap in caps
        ):
            raise ProviderExecutionPolicyError("configuration_required")

    @staticmethod
    def _request_cost_microusd(
        model: LLMModel,
        *,
        input_tokens: int,
        output_tokens: int,
    ) -> int:
        if model.input_price_1k is None or model.output_price_1k is None:
            raise ProviderExecutionPolicyError("configuration_required")
        try:
            input_price = Decimal(str(model.input_price_1k))
            output_price = Decimal(str(model.output_price_1k))
        except Exception as exc:
            raise ProviderExecutionPolicyError("configuration_required") from exc
        if input_price < 0 or output_price < 0:
            raise ProviderExecutionPolicyError("configuration_required")
        microusd = (
            (Decimal(input_tokens) * input_price)
            + (Decimal(output_tokens) * output_price)
        ) * Decimal(1_000_000) / Decimal(1_000)
        return int(microusd.to_integral_value(rounding=ROUND_CEILING))

    @staticmethod
    def _validate_issue_principals(
        command: ProviderExecutionCapabilityIssueCommand,
        *,
        credential_principal_user_id: uuid.UUID,
    ) -> None:
        try:
            RuntimeIdentityContext(
                execution_subject=command.execution_subject,
                credential_principal=RuntimePrincipal.user(
                    credential_principal_user_id
                ),
                billing_principal=command.billing_principal,
                audit_actor=command.audit_actor,
            )
        except ValueError as exc:
            raise ProviderExecutionPolicyError("permission_denied") from exc
        if (
            command.billing_principal.reference_id
            != command.binding.organization_id
        ):
            raise ProviderExecutionPolicyError("permission_denied")

    @staticmethod
    def _record_matches_issue_identity(
        record: ProviderExecutionCapabilityRecord,
        command: ProviderExecutionCapabilityIssueCommand,
    ) -> bool:
        return (
            record.execution_subject_kind
            == command.execution_subject.kind.value
            and record.execution_subject_id == command.execution_subject.reference_id
            and record.billing_principal_kind
            == command.billing_principal.kind.value
            and record.billing_principal_id == command.billing_principal.reference_id
            and record.audit_actor_kind == command.audit_actor.kind.value
            and record.audit_actor_id == command.audit_actor.reference_id
        )

    @staticmethod
    def _canonical_deployment(
        db: Session,
        *,
        organization_id: uuid.UUID,
        deployment_id: uuid.UUID,
        lock: bool = False,
    ) -> tuple[WorkflowDeployment, App, Workflow]:
        deployment_query = db.query(WorkflowDeployment).filter(
            WorkflowDeployment.id == deployment_id
        )
        if lock:
            deployment_query = deployment_query.with_for_update()
        deployment = deployment_query.one_or_none()
        if deployment is None:
            raise ProviderExecutionPolicyError("resource_not_found")
        app = db.query(App).filter(App.id == deployment.app_id).one_or_none()
        if app is None or app.organization_id != organization_id:
            raise ProviderExecutionPolicyError("resource_not_found")
        workflow = (
            db.query(Workflow).filter(Workflow.id == app.workflow_id).one_or_none()
        )
        if workflow is None or workflow.organization_id != organization_id:
            raise ProviderExecutionPolicyError("resource_not_found")
        return deployment, app, workflow

    @staticmethod
    def _assert_binding_matches_deployment(
        binding: ProviderExecutionBinding,
        *,
        deployment: WorkflowDeployment,
        workflow: Workflow,
    ) -> None:
        if (
            binding.deployment_version != deployment.version
            or binding.workflow_id != workflow.id
        ):
            raise ProviderExecutionPolicyError("configuration_required")

    @classmethod
    def _active_policy_for_binding(
        cls,
        db: Session,
        binding: ProviderExecutionBinding,
    ) -> LLMDeploymentCredentialPolicy:
        rows = (
            db.query(LLMDeploymentCredentialPolicy)
            .filter(
                LLMDeploymentCredentialPolicy.organization_id
                == binding.organization_id,
                LLMDeploymentCredentialPolicy.deployment_id == binding.deployment_id,
                LLMDeploymentCredentialPolicy.deployment_version
                == binding.deployment_version,
                LLMDeploymentCredentialPolicy.workflow_id == binding.workflow_id,
                LLMDeploymentCredentialPolicy.node_id == binding.node_id,
                LLMDeploymentCredentialPolicy.is_active.is_(True),
            )
            .with_for_update()
            .all()
        )
        if not rows:
            raise ProviderExecutionPolicyError("configuration_required")
        if len(rows) != 1:
            raise ProviderExecutionPolicyError("selection_ambiguous")
        return rows[0]

    @classmethod
    def _resolve_policy_selection(
        cls,
        db: Session,
        *,
        deployment: WorkflowDeployment,
        app: App,
        workflow: Workflow,
        organization_id: uuid.UUID,
        node_id: str,
        model_id: uuid.UUID,
        credential_id: uuid.UUID,
        credential_principal_user_id: uuid.UUID,
    ) -> tuple[LLMModel, LLMCredential, LLMProvider, LLMRelCredentialModel]:
        if (
            app.organization_id != organization_id
            or workflow.organization_id != organization_id
            or workflow.id != app.workflow_id
            or deployment.app_id != app.id
        ):
            raise ProviderExecutionPolicyError("resource_not_found")
        graph_model_id = deployment_llm_node_model_id(
            deployment.graph_snapshot,
            node_id,
        )
        model = db.query(LLMModel).filter(LLMModel.id == model_id).one_or_none()
        if (
            model is None
            or not model.is_active
            or model.model_id_for_api_call != graph_model_id
        ):
            raise ProviderExecutionPolicyError("configuration_required")
        provider = (
            db.query(LLMProvider).filter(LLMProvider.id == model.provider_id).one_or_none()
        )
        credential = (
            db.query(LLMCredential)
            .filter(
                LLMCredential.id == credential_id,
                LLMCredential.organization_id == organization_id,
                LLMCredential.is_valid.is_(True),
                LLMCredential.provider_id == model.provider_id,
            )
            .one_or_none()
        )
        if provider is None or credential is None:
            raise ProviderExecutionPolicyError("configuration_required")
        relations = (
            db.query(LLMRelCredentialModel)
            .filter(
                LLMRelCredentialModel.credential_id == credential.id,
                LLMRelCredentialModel.model_id == model.id,
                LLMRelCredentialModel.is_verified.is_(True),
            )
            .all()
        )
        if len(relations) != 1:
            raise ProviderExecutionPolicyError("relation_unavailable")
        if not has_llm_credential_permission(
            db,
            credential_principal_user_id,
            credential.id,
            "use",
            organization_id=organization_id,
        ):
            raise ProviderExecutionPolicyError("permission_denied")
        return model, credential, provider, relations[0]

    @classmethod
    def _current_revisions(
        cls,
        db: Session,
        *,
        organization_id: uuid.UUID,
        credential: LLMCredential,
        credential_principal_user_id: uuid.UUID,
        relation: LLMRelCredentialModel,
        model: LLMModel,
        provider: LLMProvider,
    ) -> dict[str, str]:
        return {
            "permission": cls._permission_revision(
                db,
                organization_id=organization_id,
                credential_id=credential.id,
                credential_principal_user_id=credential_principal_user_id,
            ),
            "relation": _revision_digest(
                {
                    "credential": {
                        "id": credential.id,
                        "organization_id": credential.organization_id,
                        "provider_id": credential.provider_id,
                        "is_valid": credential.is_valid,
                        "updated_at": credential.updated_at,
                    },
                    "relation": {
                        "id": relation.id,
                        "credential_id": relation.credential_id,
                        "model_id": relation.model_id,
                        "is_verified": relation.is_verified,
                        "priority": relation.priority,
                        "created_at": relation.created_at,
                    },
                    "model": {
                        "id": model.id,
                        "provider_id": model.provider_id,
                        "model_id_for_api_call": model.model_id_for_api_call,
                        "is_active": model.is_active,
                        "updated_at": model.updated_at,
                    },
                }
            ),
            "egress": _revision_digest(
                {
                    "provider_id": provider.id,
                    "provider_name": provider.name,
                    "base_url": provider.base_url,
                    "updated_at": provider.updated_at,
                }
            ),
            "pricing": _revision_digest(
                {
                    "model_id": model.id,
                    "input_price_1k": model.input_price_1k,
                    "output_price_1k": model.output_price_1k,
                    "updated_at": model.updated_at,
                }
            ),
        }

    @staticmethod
    def _permission_revision(
        db: Session,
        *,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
        credential_principal_user_id: uuid.UUID,
    ) -> str:
        """Fingerprint all rows that can affect a credential-use decision.

        Admission still calls ``has_llm_credential_permission`` through the
        canonical resolver.  This digest additionally rejects a capability
        when a permitted principal's source changes but remains permissive.
        """

        membership = (
            db.query(OrganizationMembership)
            .filter(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.user_id == credential_principal_user_id,
            )
            .one_or_none()
        )
        direct_rows = (
            db.query(UserLLMPermission)
            .filter(
                UserLLMPermission.grantee_organization_id == organization_id,
                UserLLMPermission.user_id == credential_principal_user_id,
                UserLLMPermission.llm_credential_id == credential_id,
            )
            .all()
        )
        team_rows = (
            db.query(TeamLLMPermission, TeamMembership, Team)
            .join(
                TeamMembership,
                TeamMembership.team_id == TeamLLMPermission.team_id,
            )
            .join(Team, Team.id == TeamLLMPermission.team_id)
            .filter(
                TeamLLMPermission.grantee_organization_id == organization_id,
                TeamLLMPermission.llm_credential_id == credential_id,
                TeamMembership.grantee_organization_id == organization_id,
                TeamMembership.user_id == credential_principal_user_id,
                Team.organization_id == organization_id,
            )
            .all()
        )
        effective_state = get_effective_llm_credential_auth_state(
            db,
            credential_principal_user_id,
            credential_id,
            organization_id=organization_id,
        )
        return _revision_digest(
            {
                "effective_state": effective_state,
                "membership": None
                if membership is None
                else {
                    "id": membership.id,
                    "membership_state": membership.membership_state,
                    "organization_auth_state": membership.organization_auth_state,
                    "updated_at": membership.updated_at,
                    "flags": membership.flags,
                },
                "direct": sorted(
                    (
                        {
                            "id": row.id,
                            "auth_state": row.auth_state,
                            "assigned_at": row.assigned_at,
                            "flags": row.flags,
                        }
                        for row in direct_rows
                    ),
                    key=lambda row: str(row["id"]),
                ),
                "team": sorted(
                    (
                        {
                            "permission_id": permission.id,
                            "permission_auth_state": permission.auth_state,
                            "permission_assigned_at": permission.assigned_at,
                            "permission_flags": permission.flags,
                            "membership_id": member.id,
                            "membership_assigned_at": member.assigned_at,
                            "membership_flags": member.flags,
                            "team_id": team.id,
                            "team_active": team.is_active,
                            "team_updated_at": team.updated_at,
                        }
                        for permission, member, team in team_rows
                    ),
                    key=lambda row: (str(row["permission_id"]), str(row["membership_id"])),
                ),
            }
        )

    @staticmethod
    def _domain_capability(
        record: ProviderExecutionCapabilityRecord,
    ) -> ProviderExecutionCapability:
        try:
            purpose = CapabilityPurpose(record.purpose)
            capability = ProviderExecutionCapability.issue(
                capability_id=record.id,
                revision=record.capability_revision,
                binding=ProviderExecutionBinding(
                    organization_id=record.organization_id,
                    workflow_id=record.workflow_id,
                    deployment_id=record.deployment_id,
                    deployment_version=record.deployment_version,
                    node_id=record.node_id,
                    node_invocation_id=record.node_invocation_id,
                    execution_admission_id=record.execution_admission_id,
                    provider_attempt_id=record.provider_attempt_id,
                    purpose=purpose,
                ),
                policy_id=record.policy_id,
                credential_id=record.credential_id,
                model_id=record.model_id,
                provider_id=record.provider_id,
                credential_principal=RuntimePrincipal.user(
                    record.credential_principal_user_id
                ),
                permission_revision=record.permission_revision,
                relation_revision=record.relation_revision,
                egress_revision=record.egress_revision,
                pricing_revision=record.pricing_revision,
                input_token_cap=record.input_token_cap,
                output_token_cap=record.output_token_cap,
                cost_cap_microusd=record.cost_cap_microusd,
                expires_at=record.expires_at,
                now=record.created_at,
            )
        except (TypeError, ValueError) as exc:
            raise ProviderExecutionPolicyError("capability_stale") from exc
        if record.state != "active":
            return capability.revoke(now=record.revoked_at or record.updated_at)
        return capability


__all__ = [
    "CAPABILITY_TTL",
    "DeploymentCredentialPolicyCommand",
    "DeploymentCredentialPolicyView",
    "ProviderExecutionCapabilityAdmissionCommand",
    "ProviderExecutionCapabilityIssueCommand",
    "ProviderExecutionCapabilityService",
    "ProviderExecutionCredentialLease",
    "ProviderExecutionPolicyError",
    "deployment_llm_node_model_id",
]
