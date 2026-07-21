import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from apps.gateway.application.agent_builder.knowledge_recommendation import (
    RecommendationDeadline,
)
from apps.gateway.services.knowledge_recommendation_credentials import (
    RecommendationEmbeddingCredentialResolver,
)


def _model(
    *,
    provider="openai",
    provider_id=None,
    model_id="embedding-model",
    model_uuid=None,
):
    return SimpleNamespace(
        id=model_uuid or uuid.uuid4(),
        provider_id=provider_id or uuid.uuid4(),
        provider_name=provider,
        model_id_for_api_call=model_id,
    )


def _candidate(*, priority, created_at, credential_id=None):
    return SimpleNamespace(
        id=credential_id or uuid.uuid4(),
        priority=priority,
        created_at=created_at,
    )


def _selected_credential(credential_id):
    return SimpleNamespace(
        id=credential_id,
        encrypted_config="protected",
        encryption_key_version=None,
        encryption_algorithm=None,
    )


class TrackingSession:
    def __init__(self, events=None):
        self.events = events if events is not None else []
        self.closed = False

    def rollback(self):
        self.events.append("rollback")

    def close(self):
        self.closed = True
        self.events.append("close")


class StubResolver(RecommendationEmbeddingCredentialResolver):
    def __init__(
        self,
        *,
        models,
        credential_rows=(),
        authorized_ids=(),
        selected_rows=None,
        session=None,
        **kwargs,
    ):
        self.session = session or TrackingSession()
        super().__init__(session_factory=lambda: self.session, **kwargs)
        self.models = list(models)
        self.credential_rows = list(credential_rows)
        self.authorized_ids = set(authorized_ids)
        self.selected_rows = selected_rows or {
            candidate.id: _selected_credential(candidate.id)
            for candidate in self.credential_rows
        }
        self.catalog_calls = []
        self.credential_calls = []
        self.authorization_calls = []
        self.selected_calls = []

    def _active_models(self, db, embedding_model, expires_at_monotonic):
        self.catalog_calls.append((db, embedding_model, expires_at_monotonic))
        return self.models

    def _verified_credentials(
        self,
        db,
        model,
        organization_id,
        expires_at_monotonic,
    ):
        self.credential_calls.append((db, model.id, organization_id))
        return self.credential_rows

    def _authorized_credential_ids(
        self,
        db,
        *,
        actor_id,
        organization_id,
        candidate_ids,
        expires_at_monotonic,
    ):
        self.authorization_calls.append(tuple(candidate_ids))
        return self.authorized_ids.intersection(candidate_ids)

    def _selected_credential(
        self,
        db,
        *,
        model,
        credential_id,
        actor_id,
        organization_id,
        expires_at_monotonic,
    ):
        self.selected_calls.append(credential_id)
        return self.selected_rows.get(credential_id)


def _resolver_for_success(*, monotonic=lambda: 10.0, **kwargs):
    model = _model()
    candidate = _candidate(
        priority=0,
        created_at=datetime.now(timezone.utc),
    )
    kwargs.setdefault(
        "config_loader",
        lambda _row: {"apiKey": "not-returned", "baseUrl": None},
    )
    kwargs.setdefault("client_factory", lambda **_kwargs: object())
    kwargs.setdefault("embedding_invoker", lambda *_args: [0.1, 0.2])
    return StubResolver(
        models=[model],
        credential_rows=[candidate],
        authorized_ids=[candidate.id],
        monotonic=monotonic,
        **kwargs,
    )


def test_same_model_id_across_providers_is_ambiguous_without_credential_access():
    resolver = StubResolver(
        models=[_model(provider="openai"), _model(provider="google")],
    )

    result = resolver.embed_query(
        organization_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        embedding_model="embedding-model",
        safe_query="approved query",
        timeout_seconds=4.0,
    )

    assert result.vector is None
    assert result.failure_reason == "model_ambiguous"
    assert resolver.credential_calls == []


def test_duplicate_model_rows_for_same_provider_are_ambiguous_without_io():
    provider_id = uuid.uuid4()
    loaded = []
    provider_calls = []
    resolver = StubResolver(
        models=[
            _model(provider_id=provider_id),
            _model(provider_id=provider_id),
        ],
        config_loader=lambda credential: loaded.append(credential.id) or {},
        client_factory=lambda **_kwargs: object(),
        embedding_invoker=lambda *_args: provider_calls.append(True) or [0.1, 0.2],
        monotonic=lambda: 10.0,
    )

    result = resolver.embed_query(
        organization_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        embedding_model="embedding-model",
        safe_query="approved query",
        timeout_seconds=4.0,
    )

    assert result.vector is None
    assert result.failure_reason == "model_ambiguous"
    assert resolver.credential_calls == []
    assert loaded == []
    assert provider_calls == []


def test_deterministic_order_selects_first_authorized_verified_credential():
    model = _model()
    now = datetime.now(timezone.utc)
    lowest_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    higher_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    earlier = _candidate(priority=2, created_at=now - timedelta(days=1))
    same_time_low = _candidate(
        priority=1,
        created_at=now,
        credential_id=lowest_id,
    )
    same_time_high = _candidate(
        priority=1,
        created_at=now,
        credential_id=higher_id,
    )
    loaded = []
    clients = []
    resolver = StubResolver(
        models=[model],
        credential_rows=[same_time_high, earlier, same_time_low],
        authorized_ids=[lowest_id, higher_id],
        config_loader=lambda credential: loaded.append(credential.id)
        or {"apiKey": "not-returned", "baseUrl": None},
        client_factory=lambda **kwargs: clients.append(kwargs) or object(),
        embedding_invoker=lambda _client, _query, _timeout: [0.1, 0.2, 0.3],
        monotonic=lambda: 10.0,
    )
    organization_id = uuid.uuid4()

    result = resolver.embed_query(
        organization_id=organization_id,
        actor_id=uuid.uuid4(),
        embedding_model="embedding-model",
        safe_query="approved query",
        timeout_seconds=3.5,
    )

    assert result.vector == (0.1, 0.2, 0.3)
    assert result.failure_reason is None
    assert loaded == [lowest_id]
    assert resolver.selected_calls == [lowest_id]
    assert clients[0]["provider"] == "openai"
    assert clients[0]["model_id"] == "embedding-model"


def test_duplicate_verified_rows_are_deduplicated_before_authorization():
    model = _model()
    now = datetime.now(timezone.utc)
    duplicate_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    other_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    duplicate_high_priority = _candidate(
        priority=5,
        created_at=now,
        credential_id=duplicate_id,
    )
    duplicate_low_priority = _candidate(
        priority=1,
        created_at=now,
        credential_id=duplicate_id,
    )
    other = _candidate(
        priority=1,
        created_at=now + timedelta(seconds=1),
        credential_id=other_id,
    )
    resolver = StubResolver(
        models=[model],
        credential_rows=[duplicate_high_priority, other, duplicate_low_priority],
        authorized_ids=[duplicate_id, other_id],
        config_loader=lambda _credential: {
            "apiKey": "not-returned",
            "baseUrl": None,
        },
        client_factory=lambda **_kwargs: object(),
        embedding_invoker=lambda *_args: [0.1, 0.2],
        monotonic=lambda: 10.0,
    )

    result = resolver.embed_query(
        organization_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        embedding_model="embedding-model",
        safe_query="approved query",
        timeout_seconds=4.0,
    )

    assert result.vector == (0.1, 0.2)
    assert resolver.authorization_calls == [(duplicate_id, other_id)]
    assert resolver.selected_calls == [duplicate_id]


def test_no_use_authorized_credential_returns_typed_unavailable_state():
    model = _model()
    candidate = _candidate(priority=0, created_at=datetime.now(timezone.utc))
    loaded = []
    resolver = StubResolver(
        models=[model],
        credential_rows=[candidate],
        authorized_ids=[],
        config_loader=lambda row: loaded.append(row) or {},
        monotonic=lambda: 10.0,
    )

    result = resolver.embed_query(
        organization_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        embedding_model="embedding-model",
        safe_query="approved query",
        timeout_seconds=4.0,
    )

    assert result.vector is None
    assert result.failure_reason == "credential_unavailable"
    assert loaded == []
    assert resolver.selected_calls == []


def test_provider_timeout_is_redacted_to_typed_provider_unavailable():
    marker = "raw-provider-timeout-must-not-escape"
    resolver = _resolver_for_success(
        embedding_invoker=lambda *_args: (_ for _ in ()).throw(
            TimeoutError(marker)
        ),
    )

    result = resolver.embed_query(
        organization_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        embedding_model="embedding-model",
        safe_query="approved query",
        timeout_seconds=0.01,
    )

    assert result.vector is None
    assert result.failure_reason == "provider_unavailable"
    assert marker not in repr(result)


def test_default_invoker_passes_timeout_to_provider_client():
    calls = []

    class FakeClient:
        def embed_sync(self, query, *, timeout_seconds):
            calls.append((query, timeout_seconds))
            return [0.1, 0.2]

    result = RecommendationEmbeddingCredentialResolver._invoke_with_timeout(
        FakeClient(),
        "approved query",
        3.5,
    )

    assert result == [0.1, 0.2]
    assert calls == [("approved query", 3.5)]


def test_credential_lookup_time_is_subtracted_from_provider_timeout():
    time_values = iter([10.0, 11.25, 11.25])
    invocations = []
    resolver = _resolver_for_success(
        monotonic=lambda: next(time_values),
        embedding_invoker=lambda _client, _query, timeout: invocations.append(timeout)
        or [0.1, 0.2],
    )

    result = resolver.embed_query(
        organization_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        embedding_model="embedding-model",
        safe_query="approved query",
        timeout_seconds=4.0,
    )

    assert result.vector == (0.1, 0.2)
    assert invocations == [2.75]


def test_late_provider_result_is_discarded_against_absolute_deadline():
    time_values = iter([10.0, 10.5, 11.01])
    resolver = _resolver_for_success(monotonic=lambda: next(time_values))
    deadline = RecommendationDeadline.from_timeout_ms(
        1_000,
        now_monotonic=10.0,
    )

    result = resolver.embed_query(
        organization_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        embedding_model="embedding-model",
        safe_query="approved query",
        timeout_seconds=4.0,
        deadline=deadline,
    )

    assert result.vector is None
    assert result.failure_reason == "deadline_exceeded"


def test_dedicated_transaction_ends_before_decrypt_and_provider_io():
    events = []
    session = TrackingSession(events)
    caller_session = TrackingSession()
    model = _model()
    candidate = _candidate(priority=0, created_at=datetime.now(timezone.utc))
    resolver = StubResolver(
        session=session,
        models=[model],
        credential_rows=[candidate],
        authorized_ids=[candidate.id],
        config_loader=lambda _row: events.append("decrypt")
        or {"apiKey": "not-returned", "baseUrl": None},
        client_factory=lambda **_kwargs: object(),
        embedding_invoker=lambda *_args: events.append("provider") or [0.1, 0.2],
        monotonic=lambda: 10.0,
    )

    result = resolver.embed_query(
        organization_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        embedding_model="embedding-model",
        safe_query="approved query",
        timeout_seconds=4.0,
    )

    assert result.vector == (0.1, 0.2)
    assert events == ["rollback", "close", "decrypt", "provider"]
    assert caller_session.events == []


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def scalars(self):
        return self

    def one_or_none(self):
        if len(self.rows) > 1:
            raise RuntimeError("multiple rows returned for one_or_none")
        return self.rows[0] if self.rows else None

    def first(self):
        return self.rows[0] if self.rows else None


class QueryCountingSession(TrackingSession):
    def __init__(self, results):
        super().__init__()
        self.results = iter(results)
        self.selects = []
        self.set_local = []

    def execute(self, statement):
        self.selects.append(statement)
        return FakeResult(next(self.results))

    def connection(self):
        return self

    def exec_driver_sql(self, statement):
        self.set_local.append(statement)


def test_many_credentials_use_four_selects_and_four_set_local_statements():
    model = _model(model_uuid=uuid.UUID(int=1))
    now = datetime.now(timezone.utc)
    candidates = [
        _candidate(priority=index, created_at=now + timedelta(seconds=index))
        for index in range(100)
    ]
    selected_id = candidates[0].id
    selected = _selected_credential(selected_id)
    selected.provider_name = "openai"
    selected.model_id_for_api_call = "embedding-model"
    session = QueryCountingSession(
        results=[
            [model],
            candidates,
            [candidate.id for candidate in candidates],
            [selected],
        ]
    )
    loaded = []
    resolver = RecommendationEmbeddingCredentialResolver(
        session_factory=lambda: session,
        config_loader=lambda credential: loaded.append(credential.id)
        or {"apiKey": "not-returned", "baseUrl": None},
        client_factory=lambda **_kwargs: object(),
        embedding_invoker=lambda *_args: [0.1, 0.2],
    )

    result = resolver.embed_query(
        organization_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        embedding_model="embedding-model",
        safe_query="approved query",
        timeout_seconds=4.0,
    )

    assert result.vector == (0.1, 0.2)
    assert len(session.selects) == 4
    assert len(session.set_local) == 4
    assert all(
        statement.startswith("SET LOCAL statement_timeout = ")
        for statement in session.set_local
    )
    assert loaded == [selected_id]


def test_duplicate_verified_snapshot_rows_do_not_fail_final_selection():
    model = _model(model_uuid=uuid.UUID(int=1))
    now = datetime.now(timezone.utc)
    selected_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    duplicate_high_priority = _candidate(
        priority=4,
        created_at=now,
        credential_id=selected_id,
    )
    duplicate_low_priority = _candidate(
        priority=1,
        created_at=now,
        credential_id=selected_id,
    )
    selected = _selected_credential(selected_id)
    selected.provider_name = "openai"
    selected.model_id_for_api_call = "embedding-model"
    session = QueryCountingSession(
        results=[
            [model],
            [duplicate_high_priority, duplicate_low_priority],
            [selected_id],
            [selected, selected],
        ]
    )
    loaded = []
    resolver = RecommendationEmbeddingCredentialResolver(
        session_factory=lambda: session,
        config_loader=lambda credential: loaded.append(credential.id)
        or {"apiKey": "not-returned", "baseUrl": None},
        client_factory=lambda **_kwargs: object(),
        embedding_invoker=lambda *_args: [0.1, 0.2],
    )

    result = resolver.embed_query(
        organization_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        embedding_model="embedding-model",
        safe_query="approved query",
        timeout_seconds=4.0,
    )

    assert result.vector == (0.1, 0.2)
    assert loaded == [selected_id]
    assert len(session.selects) == 4
