from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from apps.memory.application.public_lifecycle import (
    PublicConversationAdmissionDisposition,
    PublicDeploymentBinding,
)
from apps.memory.application.public_runtime import (
    StartPublicConversationTurnCommand,
    StartPublicConversationTurnUseCase,
)
from apps.memory.domain.conversation import (
    AudienceKind,
    ConversationSession,
    ProtectedContent,
)
from apps.memory.domain.errors import (
    AccessGrantNotUsableError,
    DuplicateRequestConflictError,
    PublicConversationFeatureDisabledError,
)
from apps.memory.domain.public_access import ConversationAccessGrant


def _now() -> datetime:
    return datetime(2026, 7, 22, 13, tzinfo=timezone.utc)


def _binding(**changes) -> PublicDeploymentBinding:
    values = {
        "organization_id": uuid.uuid4(),
        "app_id": uuid.uuid4(),
        "workflow_id": uuid.uuid4(),
        "deployment_id": uuid.uuid4(),
        "deployment_version": 1,
        "mapping_version": "conversation-mapping-v1",
        "memory_policy_version": "memory-policy-v1",
        "memory_contract_version": "conversation-memory-v1",
        "storage_generation": 1,
        "runtime_contract_ready": True,
        "runtime_start_node_id": "start",
        "runtime_input_variable": "question",
        "runtime_llm_node_id": "llm",
        "runtime_answer_node_id": "answer",
        "runtime_output_variable": "answer",
        "runtime_max_turns": 5,
        "runtime_max_context_tokens": 1200,
    }
    values.update(changes)
    return PublicDeploymentBinding(**values)


class _Repository:
    def __init__(self, binding: PublicDeploymentBinding) -> None:
        self.binding = binding
        self.session = ConversationSession.create(
            session_id=uuid.uuid4(),
            organization_id=binding.organization_id,
            app_id=binding.app_id,
            workflow_id=binding.workflow_id,
            deployment_id=binding.deployment_id,
            deployment_version=binding.deployment_version,
            deployment_snapshot_hash=None,
            mapping_version=binding.mapping_version,
            memory_policy_version=binding.memory_policy_version,
            memory_contract_version=binding.memory_contract_version,
            storage_generation=binding.storage_generation,
            audience_kind=AudienceKind.PUBLIC_CHATBOT,
            subject_type=None,
            subject_id=None,
            idle_expires_at=_now() + timedelta(hours=1),
            absolute_expires_at=_now() + timedelta(days=1),
            now=_now(),
        )
        self.grant = ConversationAccessGrant.issue(
            grant_id=uuid.uuid4(),
            organization_id=binding.organization_id,
            session_id=self.session.id,
            deployment_id=binding.deployment_id,
            deployment_version=binding.deployment_version,
            audience_kind=AudienceKind.PUBLIC_CHATBOT,
            verifier_hash="f" * 64,
            verifier_key_version="cap-v1",
            expires_at=_now() + timedelta(hours=1),
            now=_now(),
        )
        self.turns = {}
        self.entries = {}
        self.dispatches = {}

    def resolve_public_deployment(self, url_slug):
        return self.binding if url_slug == "chatbot" else None

    def lock_public_deployment(self, url_slug):
        return self.resolve_public_deployment(url_slug)

    def lock_access_grant(self, *, verifier_candidates):
        return self.grant if ("cap-v1", "f" * 64) in verifier_candidates else None

    def lock_session(self, *, organization_id, session_id):
        if (
            organization_id == self.session.organization_id
            and session_id == self.session.id
        ):
            return self.session
        return None

    def save_session(self, session):
        self.session = session

    def find_turn_by_request(
        self, *, organization_id, session_id, idempotency_key_hash
    ):
        return next(
            (
                turn
                for turn in self.turns.values()
                if turn.organization_id == organization_id
                and turn.session_id == session_id
                and turn.request_identity.idempotency_key_hash
                == idempotency_key_hash
            ),
            None,
        )

    def add_turn(self, turn):
        self.turns[turn.id] = turn

    def add_entry(self, entry):
        self.entries[entry.id] = entry

    def add_dispatch_job(self, dispatch):
        self.dispatches[dispatch.id] = dispatch

    def current_time(self):
        return _now()


class _Uow:
    def begin(self):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass


class _Secrets:
    def access_grant_verifiers(self, raw_value):
        return (("cap-v1", "f" * 64),) if raw_value == "token" else ()


class _Fingerprinter:
    def fingerprint(self, **kwargs):
        input_text = kwargs["input_text"]
        return "admission-v1", ("a" if input_text == "hello" else "b") * 64


class _Cipher:
    def __init__(self):
        self.values = []

    def protect(self, value, *, associated_data):
        self.values.append((value, associated_data))
        return ProtectedContent(
            ciphertext=b"encrypted",
            key_version="content-v1",
            format_version="memory-content-fernet-v1",
            content_digest="c" * 64,
            plaintext_byte_length=len(value.encode("utf-8")),
        )


class _Admission:
    def __init__(self):
        self.calls = []

    def admit(self, **kwargs):
        self.calls.append(kwargs)


class _Publisher:
    def __init__(self):
        self.calls = []

    def publish(self, **kwargs):
        self.calls.append(kwargs)


def _command(input_text="hello") -> StartPublicConversationTurnCommand:
    return StartPublicConversationTurnCommand(
        url_slug="chatbot",
        access_token="token",
        idempotency_key_hash="1" * 64,
        expected_lifecycle_revision=1,
        inputs={"question": input_text},
        network_address="203.0.113.10",
        now=_now(),
    )


def _use_case(repository, *, publisher=None):
    cipher = _Cipher()
    admission = _Admission()
    return (
        StartPublicConversationTurnUseCase(
            repository=repository,
            uow=_Uow(),
            secrets=_Secrets(),
            content_cipher=cipher,
            fingerprinter=_Fingerprinter(),
            admission=admission,
            dispatch_publisher=publisher,
            minimum_worker_capability="memory-runtime-v1",
            max_dispatch_attempts=5,
        ),
        cipher,
        admission,
    )


def test_public_run_starts_exactly_one_grant_bound_turn_and_dispatch() -> None:
    repository = _Repository(_binding())
    use_case, cipher, admission = _use_case(repository)

    result = use_case.execute(_command())

    turn = repository.turns[result.turn_id]
    assert result.replayed is False
    assert result.turn_state.value == "pending_dispatch"
    assert turn.access_grant_id == repository.grant.id
    assert turn.request_fingerprint_key_version == "admission-v1"
    assert repository.dispatches[result.dispatch_id].turn_id == result.turn_id
    assert {
        entry.dependency_proof_version for entry in repository.entries.values()
    } == {"conversation-source-free-v1"}
    assert [value for value, _aad in cipher.values] == ["hello", "hello"]
    assert len(admission.calls) == 1
    assert (
        admission.calls[0]["disposition"]
        is PublicConversationAdmissionDisposition.LOGICAL_REQUEST
    )


def test_dispatch_notification_is_reference_only_and_occurs_after_commit() -> None:
    repository = _Repository(_binding())
    publisher = _Publisher()
    use_case, _cipher, _admission = _use_case(
        repository,
        publisher=publisher,
    )

    result = use_case.execute(_command())

    assert publisher.calls == [
        {
            "organization_id": repository.binding.organization_id,
            "dispatch_id": result.dispatch_id,
            "turn_id": result.turn_id,
            "memory_contract_version": "conversation-memory-v1",
            "storage_generation": 1,
            "minimum_worker_capability": "memory-runtime-v1",
        }
    ]
    assert "input" not in publisher.calls[0]
    assert "grant" not in publisher.calls[0]


def test_same_key_and_input_replays_turn_without_second_content_write() -> None:
    repository = _Repository(_binding())
    use_case, cipher, admission = _use_case(repository)

    first = use_case.execute(_command())
    replay = use_case.execute(_command())

    assert replay.replayed is True
    assert replay.turn_id == first.turn_id
    assert len(repository.turns) == 1
    assert len(repository.dispatches) == 1
    assert len(cipher.values) == 2
    assert admission.calls[-1]["disposition"] is PublicConversationAdmissionDisposition.EXACT_RETRY


def test_same_key_with_different_input_is_conflict_before_new_write() -> None:
    repository = _Repository(_binding())
    use_case, cipher, _admission = _use_case(repository)
    use_case.execute(_command())

    with pytest.raises(DuplicateRequestConflictError):
        use_case.execute(_command("different"))

    assert len(repository.turns) == 1
    assert len(cipher.values) == 2


def test_runtime_requires_explicit_supported_frozen_contract() -> None:
    repository = _Repository(_binding(runtime_contract_ready=False))
    use_case, _cipher, admission = _use_case(repository)

    with pytest.raises(PublicConversationFeatureDisabledError):
        use_case.execute(_command())

    assert repository.turns == {}
    assert admission.calls == []


def test_invalid_or_expired_grant_is_resource_hidden_without_turn() -> None:
    repository = _Repository(_binding())
    repository.grant.expires_at = _now()
    use_case, _cipher, admission = _use_case(repository)

    with pytest.raises(AccessGrantNotUsableError):
        use_case.execute(_command())

    assert repository.turns == {}
    assert admission.calls == []
