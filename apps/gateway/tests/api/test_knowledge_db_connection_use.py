from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.gateway.api.v1.endpoints import knowledge as knowledge_endpoint
from apps.gateway.api.v1.endpoints import rag as rag_endpoint
from apps.shared.db.models.connection import Connection
from apps.shared.db.models.user import User
from apps.shared.schemas.rag import DocumentPreviewRequest


@pytest.fixture
def db_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    User.__table__.create(engine)
    Connection.__table__.create(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _insert_user(session: Session, user_id: uuid.UUID) -> None:
    session.execute(
        User.__table__.insert().values(
            id=user_id,
            email=f"{user_id}@example.test",
            name="Test User",
            social_provider="local",
        )
    )


def _insert_connection(
    session: Session,
    *,
    connection_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> None:
    session.execute(
        Connection.__table__.insert().values(
            id=connection_id,
            user_id=owner_id,
            name="sensitive-connection-label",
            type="postgres",
            host="db.internal.example",
            port=5432,
            database="application",
            username="service-user",
            encrypted_password="opaque-ciphertext",
            use_ssh=False,
        )
    )
    session.commit()


def _request() -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(request_id="request-id"))


def _document(connection_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        source_type="DB",
        chunk_size=500,
        chunk_overlap=50,
        meta_info={"connection_id": str(connection_id), "chunking_mode": "flat"},
        file_path=None,
    )


def _preview_request(connection_id: object, **extra_db_config) -> DocumentPreviewRequest:
    return DocumentPreviewRequest(
        source_type="DB",
        db_config={
            "connection_id": connection_id,
            "selections": [{"table_name": "safe_table", "columns": ["id"]}],
            **extra_db_config,
        },
    )


def _assert_resource_hidden(exc: HTTPException) -> None:
    assert exc.status_code == 404
    assert exc.detail["error"]["code"] == "resource.hidden"
    serialized = repr(exc.detail)
    assert "sensitive-connection-label" not in serialized
    assert "db.internal.example" not in serialized
    assert "service-user" not in serialized
    assert "opaque-ciphertext" not in serialized


def test_rag_db_source_rejects_other_users_connection(db_session: Session) -> None:
    owner_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    connection_id = uuid.uuid4()
    _insert_user(db_session, owner_id)
    _insert_user(db_session, actor_id)
    _insert_connection(
        db_session,
        connection_id=connection_id,
        owner_id=owner_id,
    )

    with pytest.raises(HTTPException) as exc_info:
        rag_endpoint._prepare_db_source(
            _request(),
            db_session,
            SimpleNamespace(id=actor_id),
            connection_id,
        )

    _assert_resource_hidden(exc_info.value)


def test_rag_upload_hides_malformed_connection_reference(
    db_session: Session,
    monkeypatch,
) -> None:
    test_app = FastAPI()
    test_app.include_router(rag_endpoint.router, prefix="/rag")
    test_app.dependency_overrides[rag_endpoint.get_db] = lambda: db_session
    test_app.dependency_overrides[rag_endpoint.get_current_user] = lambda: SimpleNamespace(
        id=uuid.uuid4()
    )
    monkeypatch.setattr("apps.gateway.utils.audit.record_audit", lambda **_event: None)

    response = TestClient(test_app).post(
        "/rag/upload",
        data={
            "sourceType": "DB",
            "connectionId": "not-a-uuid",
        },
        headers={"X-Organization-Id": str(uuid.uuid4())},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "resource.hidden"


def test_rag_db_source_persists_only_opaque_reference(db_session: Session) -> None:
    owner_id = uuid.uuid4()
    connection_id = uuid.uuid4()
    _insert_user(db_session, owner_id)
    _insert_connection(
        db_session,
        connection_id=connection_id,
        owner_id=owner_id,
    )

    file_path, filename, meta_info = rag_endpoint._prepare_db_source(
        _request(),
        db_session,
        SimpleNamespace(id=owner_id),
        connection_id,
    )

    assert file_path is None
    assert filename == "Database source"
    assert meta_info == {"connection_id": str(connection_id)}


@pytest.mark.asyncio
async def test_process_rejects_other_users_connection_before_mutation(
    db_session: Session,
    monkeypatch,
) -> None:
    owner_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    connection_id = uuid.uuid4()
    _insert_user(db_session, owner_id)
    _insert_user(db_session, actor_id)
    _insert_connection(
        db_session,
        connection_id=connection_id,
        owner_id=owner_id,
    )
    document = _document(connection_id)
    original_meta = dict(document.meta_info)
    monkeypatch.setattr(
        knowledge_endpoint,
        "_authorized_knowledge_document",
        lambda *args, **kwargs: (
            SimpleNamespace(
                embedding_model="embedding-model",
                organization_id=uuid.uuid4(),
            ),
            document,
        ),
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "mark_document_processing_queued",
        lambda *_args: pytest.fail("document status must not be mutated"),
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "IngestionService",
        lambda *_args, **_kwargs: pytest.fail("background service must not start"),
    )

    with pytest.raises(HTTPException) as exc_info:
        await knowledge_endpoint.process_document.__wrapped__(
            kb_id=uuid.uuid4(),
            document_id=document.id,
            preview_request=_preview_request(connection_id),
            request=_request(),
            background_tasks=BackgroundTasks(),
            x_organization_id=str(uuid.uuid4()),
            db=db_session,
            current_user=SimpleNamespace(id=actor_id),
        )

    _assert_resource_hidden(exc_info.value)
    assert document.meta_info == original_meta


def test_preview_rejects_malformed_connection_before_processor(
    db_session: Session,
    monkeypatch,
) -> None:
    actor_id = uuid.uuid4()
    document = _document(uuid.uuid4())
    monkeypatch.setattr(
        knowledge_endpoint,
        "_authorized_knowledge_document",
        lambda *args, **kwargs: (SimpleNamespace(), document),
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "IngestionService",
        lambda *_args, **_kwargs: pytest.fail("processor must not start"),
    )

    with pytest.raises(HTTPException) as exc_info:
        knowledge_endpoint.preview_document_chunking(
            kb_id=uuid.uuid4(),
            document_id=document.id,
            preview_request=_preview_request("not-a-uuid"),
            request=_request(),
            x_organization_id=str(uuid.uuid4()),
            db=db_session,
            current_user=SimpleNamespace(id=actor_id),
        )

    _assert_resource_hidden(exc_info.value)


@pytest.mark.asyncio
async def test_process_normalizes_owned_connection_reference(
    db_session: Session,
    monkeypatch,
) -> None:
    owner_id = uuid.uuid4()
    connection_id = uuid.uuid4()
    _insert_user(db_session, owner_id)
    _insert_connection(
        db_session,
        connection_id=connection_id,
        owner_id=owner_id,
    )
    document = _document(connection_id)
    document.meta_info.update(
        {
            "database": "must-not-be-stored-legacy-database",
            "port": 15432,
            "type": "postgres",
            "use_ssh": True,
            "ssh": {"password": "must-not-be-stored-ssh-password"},
            "ssh_port": 10022,
            "ssh_auth_type": "password",
        }
    )
    background_process = Mock()
    ingestion_service = SimpleNamespace(process_document=background_process)
    monkeypatch.setattr(
        knowledge_endpoint,
        "_authorized_knowledge_document",
        lambda *args, **kwargs: (
            SimpleNamespace(
                embedding_model="embedding-model",
                organization_id=uuid.uuid4(),
            ),
            document,
        ),
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "mark_document_processing_queued",
        lambda doc: setattr(doc, "status", "pending"),
    )
    monkeypatch.setattr(
        knowledge_endpoint,
        "IngestionService",
        Mock(return_value=ingestion_service),
    )

    response = await knowledge_endpoint.process_document.__wrapped__(
        kb_id=uuid.uuid4(),
        document_id=document.id,
        preview_request=_preview_request(
            connection_id,
            host="must-not-be-stored.example",
            port=15432,
            database="must-not-be-stored-database",
            username="must-not-be-stored",
            password="must-not-be-stored",
            type="postgres",
            use_ssh=True,
            ssh_host="must-not-be-stored-ssh.example",
            ssh_port=10022,
            ssh_username="must-not-be-stored-ssh-user",
            ssh_auth_type="password",
            join_config={
                "enabled": False,
                "password": "must-not-be-stored-nested",
            },
        ),
        request=_request(),
        background_tasks=BackgroundTasks(),
        x_organization_id=str(uuid.uuid4()),
        db=db_session,
        current_user=SimpleNamespace(id=owner_id),
    )

    assert response["status"] == "processing"
    assert document.meta_info["connection_id"] == str(connection_id)
    assert "connection_id" not in document.meta_info["db_config"]
    serialized = repr(document.meta_info)
    assert "must-not-be-stored" not in serialized
