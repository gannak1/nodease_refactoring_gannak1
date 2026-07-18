from __future__ import annotations

import copy
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet, InvalidToken

from apps.memory.application.public_lifecycle import (
    ClosePublicConversationUseCase,
    CreatePublicConversationCommand,
    CreatePublicConversationUseCase,
    DeletePublicConversationUseCase,
    GetPublicPurgeStatusUseCase,
    GetPublicTranscriptUseCase,
    IdempotencyReservation,
    IssuedSecret,
    LifecycleCommand,
    PublicConversationPolicy,
    PublicDeploymentBinding,
    ResetPublicConversationUseCase,
    SecretCiphertext,
    _secret_replay_associated_data_digest,
)
from apps.memory.domain.conversation import ConversationPurgeJob, ConversationSession
from apps.memory.domain.errors import (
    AccessGrantNotUsableError,
    DuplicateRequestConflictError,
    MemoryAdapterUnavailableError,
    SecretReplayExpiredError,
)
from apps.memory.domain.public_access import (
    ConversationAccessGrant,
    ConversationIdempotency,
    EncryptedSecretReplay,
)


def _now() -> datetime:
    return datetime(2026, 7, 18, 11, 0, tzinfo=timezone.utc)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class _Repository:
    binding: PublicDeploymentBinding

    def __post_init__(self) -> None:
        self.sessions: dict[uuid.UUID, ConversationSession] = {}
        self.grants: dict[tuple[str, str], ConversationAccessGrant] = {}
        self.idempotency: dict[tuple[uuid.UUID, str, str, str], ConversationIdempotency] = {}
        self.replays: dict[uuid.UUID, EncryptedSecretReplay] = {}
        self.purge_jobs: dict[uuid.UUID, ConversationPurgeJob] = {}

    def resolve_public_deployment(self, url_slug: str):
        return self.binding if url_slug == "public-chatbot" else None

    def reserve_idempotency(self, record: ConversationIdempotency):
        key = (
            record.organization_id,
            record.operation,
            record.scope_digest,
            record.idempotency_key_hash,
        )
        existing = self.idempotency.get(key)
        if existing is not None:
            return IdempotencyReservation(existing, created=False)
        self.idempotency[key] = record
        return IdempotencyReservation(record, created=True)

    def save_idempotency(self, record: ConversationIdempotency) -> None:
        self.idempotency[
            (
                record.organization_id,
                record.operation,
                record.scope_digest,
                record.idempotency_key_hash,
            )
        ] = record

    def add_session(self, session: ConversationSession) -> None:
        self.sessions[session.id] = session

    def lock_session(self, *, organization_id: uuid.UUID, session_id: uuid.UUID):
        session = self.sessions.get(session_id)
        if session is None or session.organization_id != organization_id:
            return None
        return session

    def save_session(self, session: ConversationSession) -> None:
        self.sessions[session.id] = session

    def add_access_grant(self, grant: ConversationAccessGrant) -> None:
        self.grants[(grant.verifier_key_version, grant.verifier_hash)] = grant

    def lock_access_grant(self, *, verifier_key_version: str, verifier_hash: str):
        return self.grants.get((verifier_key_version, verifier_hash))

    def save_access_grant(self, grant: ConversationAccessGrant) -> None:
        self.add_access_grant(grant)

    def add_secret_replay(self, replay: EncryptedSecretReplay) -> None:
        self.replays[replay.id] = replay

    def get_secret_replay(self, *, organization_id: uuid.UUID, replay_id: uuid.UUID):
        replay = self.replays.get(replay_id)
        if replay is None or replay.organization_id != organization_id:
            return None
        return replay

    def add_purge_job(self, job: ConversationPurgeJob) -> None:
        self.purge_jobs[job.id] = job

    def find_purge_job(self, *, verifier_key_version: str, verifier_hash: str):
        for job in self.purge_jobs.values():
            if (
                job.receipt_verifier_key_version == verifier_key_version
                and job.receipt_verifier_hash == verifier_hash
            ):
                return job
        return None

    def lock_purge_job_by_id(
        self, *, organization_id: uuid.UUID, purge_job_id: uuid.UUID
    ):
        job = self.purge_jobs.get(purge_job_id)
        if job is None or job.organization_id != organization_id:
            return None
        return job


class _UnitOfWork:
    def __init__(self, repository: _Repository) -> None:
        self.repository = repository
        self._snapshot = None

    def begin(self) -> None:
        self._snapshot = copy.deepcopy(
            (
                self.repository.sessions,
                self.repository.grants,
                self.repository.idempotency,
                self.repository.replays,
                self.repository.purge_jobs,
            )
        )

    def commit(self) -> None:
        self._snapshot = None

    def rollback(self) -> None:
        assert self._snapshot is not None
        (
            self.repository.sessions,
            self.repository.grants,
            self.repository.idempotency,
            self.repository.replays,
            self.repository.purge_jobs,
        ) = self._snapshot
        self._snapshot = None


class _Secrets:
    def __init__(self) -> None:
        self._key = secrets.token_bytes(32)

    def _issue(self, prefix: str, purpose: str) -> IssuedSecret:
        raw = f"{prefix}_v1_{secrets.token_urlsafe(32)}"
        return IssuedSecret(
            raw_value=raw,
            verifier_hash=self._digest(purpose, raw),
            verifier_key_version="hmac-v1",
        )

    def _verify(self, prefix: str, purpose: str, raw: str):
        if not raw.startswith(f"{prefix}_v1_") or len(raw) < 48:
            return None
        return "hmac-v1", self._digest(purpose, raw)

    def _digest(self, purpose: str, value: str) -> str:
        return hmac.new(
            self._key,
            f"test:{purpose}:{value}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def issue_access_grant(self) -> IssuedSecret:
        return self._issue("cag", "access")

    def access_grant_verifier(self, raw_value: str):
        return self._verify("cag", "access", raw_value)

    def issue_purge_receipt(self) -> IssuedSecret:
        return self._issue("cpr", "purge")

    def purge_receipt_verifier(self, raw_value: str):
        return self._verify("cpr", "purge", raw_value)


class _Cipher:
    def __init__(self) -> None:
        self._fernet = Fernet(Fernet.generate_key())

    def encrypt(self, raw_value: str, *, associated_data_digest: str) -> SecretCiphertext:
        payload = f"{associated_data_digest}:{raw_value}".encode("utf-8")
        return SecretCiphertext(self._fernet.encrypt(payload), "fernet-test-v1")

    def decrypt(
        self,
        ciphertext: bytes,
        *,
        key_version: str,
        associated_data_digest: str,
    ) -> str | None:
        if key_version != "fernet-test-v1":
            return None
        try:
            payload = self._fernet.decrypt(ciphertext).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError):
            return None
        prefix = f"{associated_data_digest}:"
        return payload[len(prefix) :] if payload.startswith(prefix) else None


class _Audit:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def record(self, **event):
        self.events.append(event)


def _binding() -> PublicDeploymentBinding:
    return PublicDeploymentBinding(
        organization_id=uuid.uuid4(),
        app_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        deployment_id=uuid.uuid4(),
        deployment_version=2,
        mapping_version="mapping-v1",
        memory_policy_version="memory-v1",
        memory_contract_version="conversation-memory-v1",
        storage_generation=1,
    )


def _application(*, policy: PublicConversationPolicy | None = None):
    repository = _Repository(_binding())
    return (
        repository,
        _UnitOfWork(repository),
        _Secrets(),
        _Cipher(),
        _Audit(),
        policy or PublicConversationPolicy(),
    )


def _use_case(cls, components, *, admission=None):
    repository, uow, secrets_port, cipher, audit, policy = components
    return cls(
        repository=repository,
        uow=uow,
        secrets=secrets_port,
        replay_cipher=cipher,
        audit=audit,
        policy=policy,
        admission=admission,
    )


class _Admission:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict] = []

    def admit(self, **kwargs) -> None:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error


def _create_command(*, now: datetime = _now(), suffix: str = "one"):
    return CreatePublicConversationCommand(
        url_slug="public-chatbot",
        idempotency_key_hash=_hash(f"create-key-{suffix}"),
        request_fingerprint=_hash("create-request"),
        now=now,
    )


def _lifecycle_command(
    token: str,
    *,
    now: datetime = _now(),
    suffix: str = "one",
    expected_revision: int = 1,
):
    return LifecycleCommand(
        url_slug="public-chatbot",
        access_token=token,
        idempotency_key_hash=_hash(f"lifecycle-key-{suffix}"),
        request_fingerprint=_hash("empty-json"),
        expected_lifecycle_revision=expected_revision,
        now=now,
    )


def test_create_replays_the_same_bounded_access_token_without_storing_raw_value():
    components = _application()
    repository = components[0]
    use_case = _use_case(CreatePublicConversationUseCase, components)
    command = _create_command()

    first = use_case.execute(command)
    replay = use_case.execute(command)

    assert replay.replayed is True
    assert replay.access_token == first.access_token
    assert all("token" not in grant.__dataclass_fields__ for grant in repository.grants.values())
    assert all(first.access_token.encode("utf-8") not in value.ciphertext for value in repository.replays.values())
    record = next(iter(repository.idempotency.values()))
    assert record.retention_expires_at == _now() + timedelta(hours=24)


def test_create_replay_restores_the_initial_response_after_the_session_closes():
    components = _application()
    create = _use_case(CreatePublicConversationUseCase, components)
    close = _use_case(ClosePublicConversationUseCase, components)
    command = _create_command()
    first = create.execute(command)
    close.execute(
        _lifecycle_command(first.access_token, suffix="close-before-create-replay")
    )

    replay = create.execute(command)

    assert replay.replayed is True
    assert (
        replay.lifecycle,
        replay.lifecycle_revision,
        replay.memory_contract_version,
        replay.expires_at,
    ) == (
        first.lifecycle,
        first.lifecycle_revision,
        first.memory_contract_version,
        first.expires_at,
    )


def test_public_results_report_the_earliest_access_expiry_and_replay_it_stably():
    policy = replace(
        PublicConversationPolicy(),
        idle_lifetime=timedelta(hours=12),
        access_grant_lifetime=timedelta(hours=18),
    )
    components = _application(policy=policy)
    create = _use_case(CreatePublicConversationUseCase, components)
    reset = _use_case(ResetPublicConversationUseCase, components)
    close = _use_case(ClosePublicConversationUseCase, components)
    transcript = _use_case(GetPublicTranscriptUseCase, components)
    create_command = _create_command()

    created = create.execute(create_command)
    created_replay = create.execute(create_command)
    reset_command = _lifecycle_command(created.access_token, suffix="expiry-reset")
    replacement = reset.execute(reset_command)
    close_command = _lifecycle_command(
        replacement.access_token,
        suffix="expiry-close",
    )
    closed = close.execute(close_command)
    replacement_replay = reset.execute(reset_command)
    closed_replay = close.execute(close_command)
    visible = transcript.execute(
        url_slug="public-chatbot",
        access_token=replacement.access_token,
        now=_now(),
    )

    expected_expiry = _now() + timedelta(hours=12)
    assert created.expires_at == expected_expiry
    assert created_replay.expires_at == expected_expiry
    assert replacement.expires_at == expected_expiry
    assert replacement_replay.expires_at == expected_expiry
    assert closed.expires_at == expected_expiry
    assert closed_replay.expires_at == expected_expiry
    assert visible.expires_at == expected_expiry
    assert visible.content_revision == 0
    assert visible.turns == ()


@pytest.mark.parametrize(
    ("field", "replacement_value"),
    (
        ("scope_digest", "d" * 64),
        ("idempotency_key_hash", "e" * 64),
        ("request_fingerprint", "f" * 64),
    ),
)
def test_secret_replay_ciphertext_is_bound_to_immutable_idempotency_identity(
    field: str,
    replacement_value: str,
):
    now = _now()
    record = ConversationIdempotency.pending(
        record_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        operation="conversation.create",
        scope_digest=_hash("scope"),
        idempotency_key_hash=_hash("idempotency-key"),
        request_fingerprint=_hash("request"),
        retention_expires_at=now + timedelta(days=1),
        now=now,
    )
    cipher = _Cipher()
    purpose = "access-grant"
    associated_data_digest = _secret_replay_associated_data_digest(
        record=record,
        purpose=purpose,
    )
    encrypted = cipher.encrypt(
        "bounded-secret",
        associated_data_digest=associated_data_digest,
    )
    retargeted_record = replace(record, **{field: replacement_value})

    assert (
        cipher.decrypt(
            encrypted.ciphertext,
            key_version=encrypted.key_version,
            associated_data_digest=_secret_replay_associated_data_digest(
                record=retargeted_record,
                purpose=purpose,
            ),
        )
        is None
    )


def test_secret_replay_rejects_a_stored_associated_data_digest_mismatch():
    components = _application()
    repository = components[0]
    use_case = _use_case(CreatePublicConversationUseCase, components)
    command = _create_command()
    use_case.execute(command)
    replay = next(iter(repository.replays.values()))
    tampered_digest = "f" * 64
    if replay.associated_data_digest == tampered_digest:
        tampered_digest = "e" * 64
    repository.replays[replay.id] = replace(
        replay,
        associated_data_digest=tampered_digest,
    )

    with pytest.raises(MemoryAdapterUnavailableError):
        use_case.execute(command)


def test_close_makes_grant_transcript_only_and_does_not_duplicate_audit_event():
    components = _application()
    create = _use_case(CreatePublicConversationUseCase, components)
    close = _use_case(ClosePublicConversationUseCase, components)
    transcript = _use_case(GetPublicTranscriptUseCase, components)
    reset = _use_case(ResetPublicConversationUseCase, components)
    first = create.execute(_create_command())
    command = _lifecycle_command(first.access_token)

    closed = close.execute(command)
    replay = close.execute(command)
    visible = transcript.execute(
        url_slug="public-chatbot", access_token=first.access_token, now=_now()
    )

    assert closed.lifecycle.value == "closed"
    assert replay.replayed is True
    assert visible.turns == ()
    with pytest.raises(AccessGrantNotUsableError):
        reset.execute(_lifecycle_command(first.access_token, suffix="different"))
    assert [event["action"] for event in components[4].events] == [
        "memory.session.created",
        "memory.grant.issued",
        "memory.session.closed",
    ]


def test_close_replay_restores_the_closed_response_after_privacy_delete():
    components = _application()
    create = _use_case(CreatePublicConversationUseCase, components)
    close = _use_case(ClosePublicConversationUseCase, components)
    delete = _use_case(DeletePublicConversationUseCase, components)
    first = create.execute(_create_command())
    close_command = _lifecycle_command(first.access_token, suffix="close-snapshot")
    closed = close.execute(close_command)
    delete.execute(
        _lifecycle_command(
            first.access_token,
            suffix="delete-after-close-snapshot",
            expected_revision=closed.lifecycle_revision,
        )
    )

    replay = close.execute(close_command)

    assert replay.replayed is True
    assert (
        replay.lifecycle,
        replay.lifecycle_revision,
        replay.memory_contract_version,
        replay.expires_at,
    ) == (
        closed.lifecycle,
        closed.lifecycle_revision,
        closed.memory_contract_version,
        closed.expires_at,
    )


def test_same_lifecycle_key_with_a_different_precondition_fingerprint_conflicts():
    components = _application()
    create = _use_case(CreatePublicConversationUseCase, components)
    close = _use_case(ClosePublicConversationUseCase, components)
    first = create.execute(_create_command())
    command = _lifecycle_command(first.access_token)

    close.execute(command)

    with pytest.raises(DuplicateRequestConflictError):
        close.execute(
            replace(
                command,
                expected_lifecycle_revision=2,
                request_fingerprint=_hash("empty-json-with-revision-2"),
            )
        )


def test_reset_revokes_old_grant_but_matching_retry_returns_one_replacement():
    components = _application()
    create = _use_case(CreatePublicConversationUseCase, components)
    reset = _use_case(ResetPublicConversationUseCase, components)
    first = create.execute(_create_command())
    command = _lifecycle_command(first.access_token)

    replacement = reset.execute(command)
    replay = reset.execute(command)

    assert replacement.access_token != first.access_token
    assert replacement.previous_lifecycle_revision == 2
    assert replay.replayed is True
    assert replay.access_token == replacement.access_token
    assert replay.previous_lifecycle_revision == 2
    with pytest.raises(AccessGrantNotUsableError):
        reset.execute(_lifecycle_command(first.access_token, suffix="other"))
    assert [event["action"] for event in components[4].events] == [
        "memory.session.created",
        "memory.grant.issued",
        "memory.session.reset",
        "memory.grant.revoked",
        "memory.session.created",
        "memory.grant.issued",
    ]
    assert [event["target_type"] for event in components[4].events] == [
        "conversation_session",
        "conversation_access_grant",
        "conversation_session",
        "conversation_access_grant",
        "conversation_session",
        "conversation_access_grant",
    ]
    assert components[4].events[2]["target_id"] != components[4].events[4]["target_id"]


def test_reset_replay_restores_the_initial_replacement_response_after_close():
    components = _application()
    create = _use_case(CreatePublicConversationUseCase, components)
    reset = _use_case(ResetPublicConversationUseCase, components)
    close = _use_case(ClosePublicConversationUseCase, components)
    first = create.execute(_create_command())
    reset_command = _lifecycle_command(first.access_token, suffix="reset-snapshot")
    replacement = reset.execute(reset_command)
    close.execute(
        _lifecycle_command(
            replacement.access_token,
            suffix="close-replacement",
            expected_revision=replacement.lifecycle_revision,
        )
    )

    replay = reset.execute(reset_command)

    assert replay.replayed is True
    assert replay.access_token == replacement.access_token
    assert (
        replay.lifecycle,
        replay.lifecycle_revision,
        replay.memory_contract_version,
        replay.expires_at,
        replay.previous_lifecycle,
        replay.previous_lifecycle_revision,
    ) == (
        replacement.lifecycle,
        replacement.lifecycle_revision,
        replacement.memory_contract_version,
        replacement.expires_at,
        replacement.previous_lifecycle,
        replacement.previous_lifecycle_revision,
    )


def test_close_replays_after_original_grant_and_session_expire_but_new_key_fails():
    policy = replace(
        PublicConversationPolicy(),
        idle_lifetime=timedelta(minutes=1),
        access_grant_lifetime=timedelta(minutes=1),
    )
    components = _application(policy=policy)
    repository = components[0]
    admission = _Admission()
    create = _use_case(CreatePublicConversationUseCase, components)
    close = _use_case(
        ClosePublicConversationUseCase,
        components,
        admission=admission,
    )
    first = create.execute(_create_command())
    command = _lifecycle_command(first.access_token)
    closed = close.execute(command)

    replay = close.execute(replace(command, now=_now() + timedelta(minutes=2)))

    assert replay.replayed is True
    assert replay.lifecycle_revision == closed.lifecycle_revision
    record_count = len(repository.idempotency)
    with pytest.raises(AccessGrantNotUsableError):
        close.execute(
            _lifecycle_command(
                first.access_token,
                now=_now() + timedelta(minutes=2),
                suffix="new-after-expiry",
                expected_revision=2,
            )
        )
    assert len(repository.idempotency) == record_count
    assert len(admission.calls) == 1


def test_reset_replays_replacement_secret_after_original_scope_expires():
    policy = replace(
        PublicConversationPolicy(),
        idle_lifetime=timedelta(minutes=1),
        access_grant_lifetime=timedelta(minutes=1),
    )
    components = _application(policy=policy)
    create = _use_case(CreatePublicConversationUseCase, components)
    reset = _use_case(ResetPublicConversationUseCase, components)
    first = create.execute(_create_command())
    command = _lifecycle_command(first.access_token)
    replacement = reset.execute(command)

    replay = reset.execute(replace(command, now=_now() + timedelta(minutes=2)))

    assert replay.replayed is True
    assert replay.access_token == replacement.access_token


def test_delete_replays_receipt_after_original_scope_expires():
    policy = replace(
        PublicConversationPolicy(),
        idle_lifetime=timedelta(minutes=1),
        access_grant_lifetime=timedelta(minutes=1),
    )
    components = _application(policy=policy)
    create = _use_case(CreatePublicConversationUseCase, components)
    delete = _use_case(DeletePublicConversationUseCase, components)
    first = create.execute(_create_command())
    command = _lifecycle_command(first.access_token)
    deleted = delete.execute(command)

    replay = delete.execute(replace(command, now=_now() + timedelta(minutes=2)))

    assert replay.replayed is True
    assert replay.purge_receipt == deleted.purge_receipt


def test_delete_replay_restores_the_initial_revision_after_terminal_progress():
    components = _application()
    repository = components[0]
    create = _use_case(CreatePublicConversationUseCase, components)
    delete = _use_case(DeletePublicConversationUseCase, components)
    first = create.execute(_create_command())
    command = _lifecycle_command(first.access_token, suffix="delete-snapshot")
    deleted = delete.execute(command)
    session = next(iter(repository.sessions.values()))
    session.mark_deleted(
        expected_lifecycle_revision=deleted.lifecycle_revision,
        now=_now() + timedelta(minutes=1),
    )

    replay = delete.execute(command)

    assert replay.replayed is True
    assert replay.lifecycle == deleted.lifecycle
    assert replay.lifecycle_revision == deleted.lifecycle_revision
    assert replay.purge_job_id == deleted.purge_job_id
    assert replay.purge_receipt == deleted.purge_receipt


def test_delete_revokes_conversation_grant_and_replays_receipt_only_until_ttl():
    components = _application(
        policy=replace(
            PublicConversationPolicy(),
            idle_lifetime=timedelta(days=2),
            access_grant_lifetime=timedelta(days=2),
        )
    )
    repository = components[0]
    create = _use_case(CreatePublicConversationUseCase, components)
    delete = _use_case(DeletePublicConversationUseCase, components)
    purge_status = _use_case(GetPublicPurgeStatusUseCase, components)
    first = create.execute(_create_command())
    command = _lifecycle_command(first.access_token)

    deleted = delete.execute(command)
    replay = delete.execute(command)
    status = purge_status.execute(
        url_slug="public-chatbot", purge_receipt=deleted.purge_receipt, now=_now()
    )

    assert replay.replayed is True
    assert replay.purge_receipt == deleted.purge_receipt
    assert status.status.value == "pending"
    with pytest.raises(AccessGrantNotUsableError):
        delete.execute(_lifecycle_command(first.access_token, suffix="other"))
    with pytest.raises(SecretReplayExpiredError):
        delete.execute(
            _lifecycle_command(
                first.access_token,
                now=_now() + timedelta(hours=24),
            )
        )
    purge_job = repository.purge_jobs[deleted.purge_job_id]
    repository.sessions.pop(purge_job.session_id)
    purge_job.session_id = None
    status_after_physical_session_delete = purge_status.execute(
        url_slug="public-chatbot",
        purge_receipt=deleted.purge_receipt,
        now=_now(),
    )
    assert status_after_physical_session_delete.status.value == "pending"
    assert [event["action"] for event in components[4].events] == [
        "memory.session.created",
        "memory.grant.issued",
        "memory.session.delete_requested",
        "memory.grant.revoked",
    ]
    assert [event["target_type"] for event in components[4].events[-2:]] == [
        "conversation_session",
        "conversation_access_grant",
    ]


def test_closed_conversation_can_request_privacy_delete_but_cannot_reset():
    components = _application()
    create = _use_case(CreatePublicConversationUseCase, components)
    close = _use_case(ClosePublicConversationUseCase, components)
    reset = _use_case(ResetPublicConversationUseCase, components)
    delete = _use_case(DeletePublicConversationUseCase, components)
    first = create.execute(_create_command())
    close.execute(_lifecycle_command(first.access_token, suffix="close"))

    with pytest.raises(AccessGrantNotUsableError):
        reset.execute(
            _lifecycle_command(
                first.access_token,
                suffix="reset-after-close",
                expected_revision=2,
            )
        )

    result = delete.execute(
        _lifecycle_command(
            first.access_token,
            suffix="delete-after-close",
            expected_revision=2,
        )
    )

    assert result.lifecycle.value == "delete_pending"


def test_mutation_admission_runs_once_for_new_request_not_for_idempotency_replay():
    components = _application()
    admission = _Admission()
    create = _use_case(
        CreatePublicConversationUseCase,
        components,
        admission=admission,
    )
    command = _create_command()

    create.execute(command)
    create.execute(command)

    assert len(admission.calls) == 1
    assert admission.calls[0]["operation"] == "conversation.create"


def test_admission_unavailable_rolls_back_pending_create_idempotency_record():
    components = _application()
    repository = components[0]
    create = _use_case(
        CreatePublicConversationUseCase,
        components,
        admission=_Admission(MemoryAdapterUnavailableError()),
    )

    with pytest.raises(MemoryAdapterUnavailableError):
        create.execute(_create_command())

    assert repository.sessions == {}
    assert repository.idempotency == {}
