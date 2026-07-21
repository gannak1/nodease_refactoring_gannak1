from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, exists, literal, or_, select
from sqlalchemy.orm import Session

from apps.gateway.application.agent_builder.knowledge_recommendation import (
    EmbeddingFailureReason,
    EmbeddingResolution,
    RecommendationDeadline,
)
from apps.shared.db.models.llm import (
    LLMCredential,
    LLMModel,
    LLMProvider,
    LLMRelCredentialModel,
)
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.organization_membership import (
    ORGANIZATION_AUTH_MANAGER,
    ORGANIZATION_MEMBERSHIP_ACTIVE,
    OrganizationMembership,
)
from apps.shared.db.models.team import (
    Team,
    TeamLLMPermission,
    TeamMembership,
    UserLLMPermission,
)
from apps.shared.db.models.user import User
from apps.shared.db.session import SessionLocal
from apps.shared.services.llm_client.factory import get_llm_client
from apps.shared.services.llm_credential_config import load_llm_credential_config


MAX_COHORT_EMBEDDING_TIMEOUT_SECONDS = 4.0
_USE_AUTH_STATES = ("operator", "builder", "manager")


@dataclass(frozen=True, slots=True)
class _CredentialCandidate:
    id: UUID
    priority: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class _CredentialConfigSnapshot:
    id: UUID
    encrypted_config: str
    encryption_key_version: str | None
    encryption_algorithm: str | None


class RecommendationEmbeddingCredentialResolver:
    """Resolve one authorized credential without retaining a DB transaction."""

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        *,
        config_loader: Callable[[Any], dict[str, Any]] = load_llm_credential_config,
        client_factory: Callable[..., Any] = get_llm_client,
        embedding_invoker: Callable[[Any, str, float], Sequence[float]] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session_factory = session_factory
        self.config_loader = config_loader
        self.client_factory = client_factory
        self.embedding_invoker = embedding_invoker or self._invoke_with_timeout
        self.monotonic = monotonic

    def embed_query(
        self,
        *,
        organization_id: UUID,
        actor_id: UUID,
        embedding_model: str,
        safe_query: str,
        timeout_seconds: float,
        deadline: RecommendationDeadline | None = None,
    ) -> EmbeddingResolution:
        started_at = self._read_clock()
        expires_at = self._effective_expiry(
            started_at=started_at,
            timeout_seconds=timeout_seconds,
            deadline=deadline,
        )
        if expires_at is None or started_at >= expires_at:
            return EmbeddingResolution.unavailable("deadline_exceeded")

        db: Session | None = None
        failure_reason: EmbeddingFailureReason | None = None
        selected: Any | None = None
        model: Any | None = None
        try:
            db = self.session_factory()
            models = self._active_models(db, embedding_model, expires_at)
            if not models:
                failure_reason = "credential_unavailable"
            elif len(models) != 1:
                failure_reason = "model_ambiguous"
            else:
                model = min(models, key=lambda item: str(item.id))
                candidates = self._deduplicate_verified_credentials(
                    self._verified_credentials(
                        db,
                        model,
                        organization_id,
                        expires_at,
                    )
                )
                if not candidates:
                    failure_reason = "credential_unavailable"
                else:
                    candidate_ids = tuple(candidate.id for candidate in candidates)
                    authorized_ids = self._authorized_credential_ids(
                        db,
                        actor_id=actor_id,
                        organization_id=organization_id,
                        candidate_ids=candidate_ids,
                        expires_at_monotonic=expires_at,
                    )
                    selected_id = next(
                        (
                            candidate.id
                            for candidate in candidates
                            if candidate.id in authorized_ids
                        ),
                        None,
                    )
                    if selected_id is None:
                        failure_reason = "credential_unavailable"
                    else:
                        selected = self._selected_credential(
                            db,
                            model=model,
                            credential_id=selected_id,
                            actor_id=actor_id,
                            organization_id=organization_id,
                            expires_at_monotonic=expires_at,
                        )
                        if selected is None:
                            failure_reason = "credential_unavailable"
        except TimeoutError:
            failure_reason = "deadline_exceeded"
        except Exception:
            failure_reason = "provider_unavailable"
        finally:
            if db is not None and not self._end_owned_session(db):
                failure_reason = "provider_unavailable"

        if failure_reason is not None:
            return EmbeddingResolution.unavailable(failure_reason)
        if selected is None or model is None:
            return EmbeddingResolution.unavailable("provider_unavailable")

        try:
            config = self.config_loader(selected)
            provider_name = self._provider_name(model)
            if not provider_name:
                raise ValueError("embedding provider is unavailable")
            client = self.client_factory(
                provider=provider_name,
                model_id=model.model_id_for_api_call,
                credentials={
                    "apiKey": config.get("apiKey"),
                    "baseUrl": config.get("baseUrl"),
                },
            )
            remaining_seconds = self._remaining_seconds(expires_at)
            vector = self.embedding_invoker(
                client,
                safe_query,
                remaining_seconds,
            )
            completed_at = self._read_clock()
            if completed_at > expires_at:
                return EmbeddingResolution.unavailable("deadline_exceeded")
            normalized_vector = self._normalize_vector(vector)
            return EmbeddingResolution(vector=normalized_vector)
        except Exception:
            reason: EmbeddingFailureReason = (
                "deadline_exceeded"
                if self._deadline_has_passed(expires_at)
                else "provider_unavailable"
            )
            return EmbeddingResolution.unavailable(reason)

    def _active_models(
        self,
        db: Session,
        embedding_model: str,
        expires_at_monotonic: float,
    ) -> list[Any]:
        statement = (
            select(
                LLMModel.id.label("id"),
                LLMModel.provider_id.label("provider_id"),
                LLMModel.model_id_for_api_call.label("model_id_for_api_call"),
                LLMProvider.name.label("provider_name"),
            )
            .join(LLMProvider, LLMProvider.id == LLMModel.provider_id)
            .where(
                LLMModel.model_id_for_api_call == embedding_model,
                LLMModel.type == "embedding",
                LLMModel.is_active.is_(True),
            )
            .order_by(LLMModel.provider_id.asc(), LLMModel.id.asc())
        )
        return list(self._execute_select(db, statement, expires_at_monotonic).all())

    def _verified_credentials(
        self,
        db: Session,
        model: Any,
        organization_id: UUID,
        expires_at_monotonic: float,
    ) -> list[_CredentialCandidate]:
        statement = (
            select(
                LLMCredential.id.label("id"),
                LLMRelCredentialModel.priority.label("priority"),
                LLMCredential.created_at.label("created_at"),
            )
            .join(
                LLMRelCredentialModel,
                LLMRelCredentialModel.credential_id == LLMCredential.id,
            )
            .where(
                LLMCredential.organization_id == organization_id,
                LLMCredential.provider_id == model.provider_id,
                LLMCredential.is_valid.is_(True),
                LLMRelCredentialModel.model_id == model.id,
                LLMRelCredentialModel.is_verified.is_(True),
            )
            .order_by(
                LLMRelCredentialModel.priority.asc(),
                LLMCredential.created_at.asc(),
                LLMCredential.id.asc(),
            )
        )
        rows = self._execute_select(db, statement, expires_at_monotonic).all()
        return [
            _CredentialCandidate(
                id=row.id,
                priority=int(row.priority),
                created_at=self._normalized_created_at(row.created_at),
            )
            for row in rows
        ]

    def _deduplicate_verified_credentials(
        self,
        candidates: Sequence[_CredentialCandidate],
    ) -> list[_CredentialCandidate]:
        candidates_by_id: dict[UUID, _CredentialCandidate] = {}
        for candidate in candidates:
            current = candidates_by_id.get(candidate.id)
            if current is None or self._credential_order_key(
                candidate
            ) < self._credential_order_key(current):
                candidates_by_id[candidate.id] = candidate
        return sorted(candidates_by_id.values(), key=self._credential_order_key)

    def _authorized_credential_ids(
        self,
        db: Session,
        *,
        actor_id: UUID,
        organization_id: UUID,
        candidate_ids: tuple[UUID, ...],
        expires_at_monotonic: float,
    ) -> set[UUID]:
        statement = self._authorized_credential_statement(
            actor_id=actor_id,
            organization_id=organization_id,
        ).where(LLMCredential.id.in_(candidate_ids))
        result = self._execute_select(db, statement, expires_at_monotonic)
        return set(result.scalars().all())

    def _selected_credential(
        self,
        db: Session,
        *,
        model: Any,
        credential_id: UUID,
        actor_id: UUID,
        organization_id: UUID,
        expires_at_monotonic: float,
    ) -> _CredentialConfigSnapshot | None:
        statement = (
            select(
                LLMCredential.id.label("id"),
                LLMCredential.encrypted_config.label("encrypted_config"),
                LLMCredential.encryption_key_version.label("encryption_key_version"),
                LLMCredential.encryption_algorithm.label("encryption_algorithm"),
            )
            .join(
                LLMRelCredentialModel,
                LLMRelCredentialModel.credential_id == LLMCredential.id,
            )
            .join(LLMModel, LLMModel.id == LLMRelCredentialModel.model_id)
            .where(
                LLMCredential.id == credential_id,
                LLMCredential.organization_id == organization_id,
                LLMCredential.provider_id == model.provider_id,
                LLMCredential.is_valid.is_(True),
                LLMRelCredentialModel.model_id == model.id,
                LLMRelCredentialModel.is_verified.is_(True),
                LLMModel.type == "embedding",
                LLMModel.is_active.is_(True),
            )
        )
        statement = self._with_active_authorization(
            statement,
            actor_id=actor_id,
            organization_id=organization_id,
        ).order_by(
            LLMRelCredentialModel.priority.asc(),
            LLMCredential.created_at.asc(),
            LLMCredential.id.asc(),
        ).limit(1)
        row = self._execute_select(
            db,
            statement,
            expires_at_monotonic,
        ).first()
        if row is None:
            return None
        return _CredentialConfigSnapshot(
            id=row.id,
            encrypted_config=row.encrypted_config,
            encryption_key_version=row.encryption_key_version,
            encryption_algorithm=row.encryption_algorithm,
        )

    def _authorized_credential_statement(
        self,
        *,
        actor_id: UUID,
        organization_id: UUID,
    ):
        statement = select(LLMCredential.id)
        return self._with_active_authorization(
            statement,
            actor_id=actor_id,
            organization_id=organization_id,
        )

    @staticmethod
    def _with_active_authorization(
        statement,
        *,
        actor_id: UUID,
        organization_id: UUID,
    ):
        direct_use = exists(
            select(literal(1)).where(
                UserLLMPermission.user_id == actor_id,
                UserLLMPermission.llm_credential_id == LLMCredential.id,
                UserLLMPermission.grantee_organization_id == organization_id,
                UserLLMPermission.auth_state.in_(_USE_AUTH_STATES),
            )
        )
        team_use = exists(
            select(literal(1))
            .select_from(TeamLLMPermission)
            .join(
                TeamMembership,
                TeamMembership.team_id == TeamLLMPermission.team_id,
            )
            .join(Team, Team.id == TeamLLMPermission.team_id)
            .where(
                TeamMembership.user_id == actor_id,
                TeamMembership.grantee_organization_id == organization_id,
                TeamLLMPermission.llm_credential_id == LLMCredential.id,
                TeamLLMPermission.grantee_organization_id == organization_id,
                TeamMembership.grantee_organization_id
                == TeamLLMPermission.grantee_organization_id,
                Team.organization_id == organization_id,
                Team.is_active.is_(True),
                TeamLLMPermission.auth_state.in_(_USE_AUTH_STATES),
            )
        )
        return (
            statement.join(
                OrganizationMembership,
                and_(
                    OrganizationMembership.organization_id == organization_id,
                    OrganizationMembership.user_id == actor_id,
                ),
            )
            .join(Organization, Organization.id == organization_id)
            .join(User, User.id == actor_id)
            .where(
                LLMCredential.organization_id == organization_id,
                LLMCredential.is_valid.is_(True),
                User.deactivated_at.is_(None),
                Organization.is_active.is_(True),
                OrganizationMembership.membership_state
                == ORGANIZATION_MEMBERSHIP_ACTIVE,
                or_(
                    OrganizationMembership.organization_auth_state
                    == ORGANIZATION_AUTH_MANAGER,
                    direct_use,
                    team_use,
                ),
            )
        )

    def _execute_select(
        self,
        db: Session,
        statement,
        expires_at_monotonic: float,
    ):
        self._set_local_statement_timeout(db, expires_at_monotonic)
        result = db.execute(statement)
        if self._deadline_has_passed(expires_at_monotonic):
            raise TimeoutError("credential lookup deadline exceeded")
        return result

    def _set_local_statement_timeout(
        self,
        db: Session,
        expires_at_monotonic: float,
    ) -> None:
        remaining_seconds = self._remaining_seconds(expires_at_monotonic)
        timeout_ms = max(1, int(remaining_seconds * 1000))
        db.connection().exec_driver_sql(
            f"SET LOCAL statement_timeout = {timeout_ms}"
        )

    @staticmethod
    def _credential_order_key(candidate: Any):
        return (
            int(candidate.priority),
            RecommendationEmbeddingCredentialResolver._normalized_created_at(
                candidate.created_at
            ),
            str(candidate.id),
        )

    @staticmethod
    def _normalized_created_at(value: Any) -> datetime:
        if not isinstance(value, datetime):
            return datetime.max.replace(tzinfo=timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @staticmethod
    def _provider_name(model: Any) -> str | None:
        provider_name = getattr(model, "provider_name", None)
        if isinstance(provider_name, str) and provider_name:
            return provider_name
        provider = getattr(model, "provider", None)
        nested_name = getattr(provider, "name", None)
        return nested_name if isinstance(nested_name, str) and nested_name else None

    @staticmethod
    def _invoke_with_timeout(client: Any, safe_query: str, timeout_seconds: float):
        if timeout_seconds <= 0:
            raise TimeoutError("embedding deadline exceeded")
        return client.embed_sync(
            safe_query,
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def _normalize_vector(vector: Any) -> tuple[float, ...]:
        if not isinstance(vector, (list, tuple)) or not vector:
            raise ValueError("embedding unavailable")
        normalized = tuple(float(value) for value in vector)
        if not all(math.isfinite(value) for value in normalized):
            raise ValueError("embedding unavailable")
        return normalized

    def _effective_expiry(
        self,
        *,
        started_at: float,
        timeout_seconds: float,
        deadline: RecommendationDeadline | None,
    ) -> float | None:
        if isinstance(timeout_seconds, bool):
            return None
        try:
            timeout = float(timeout_seconds)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(timeout) or timeout <= 0:
            return None
        expires_at = started_at + min(
            timeout,
            MAX_COHORT_EMBEDDING_TIMEOUT_SECONDS,
        )
        if deadline is not None:
            if not isinstance(deadline, RecommendationDeadline):
                return None
            expires_at = min(expires_at, deadline.expires_at_monotonic)
        return expires_at

    def _remaining_seconds(self, expires_at_monotonic: float) -> float:
        remaining = expires_at_monotonic - self._read_clock()
        if remaining <= 0:
            raise TimeoutError("embedding deadline exceeded")
        return remaining

    def _deadline_has_passed(self, expires_at_monotonic: float) -> bool:
        return self._read_clock() > expires_at_monotonic

    def _read_clock(self) -> float:
        value = float(self.monotonic())
        if not math.isfinite(value):
            raise ValueError("monotonic clock is unavailable")
        return value

    @staticmethod
    def _end_owned_session(db: Session) -> bool:
        succeeded = True
        try:
            db.rollback()
        except Exception:
            succeeded = False
        try:
            db.close()
        except Exception:
            succeeded = False
        return succeeded
