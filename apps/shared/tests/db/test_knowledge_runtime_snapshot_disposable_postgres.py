import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID, uuid4

import pytest
from apps.shared.domain.knowledge_runtime_candidates import (
    AnonymousPublicAudience,
    KnowledgeRuntimeCandidateRequest,
)
from apps.shared.tests.helpers.disposable_postgres import (
    DisposablePostgresConfig,
    DisposablePostgresConfigurationError,
    quote_disposable_database_name,
)
from apps.workflow_engine.adapters.knowledge_runtime_candidates import (
    KnowledgeRuntimeCandidateSnapshotError,
    PostgresKnowledgeRuntimeCandidateSnapshotAdapter,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

RUN_ENV = "NODEASE_RUN_DISPOSABLE_DB_TEST"
DB_PREFIX = "nodease_knowledge_snapshot_test"


def _create_schema(engine) -> None:
    statements = (
        """
        CREATE TABLE organization (
            id UUID PRIMARY KEY,
            is_active BOOLEAN NOT NULL
        )
        """,
        """
        CREATE TABLE knowledge_collections (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL,
            lifecycle_state VARCHAR(50) NOT NULL,
            sync_state VARCHAR(50) NOT NULL,
            is_system_managed BOOLEAN NOT NULL,
            safe_metadata JSONB NOT NULL
        )
        """,
        """
        CREATE TABLE knowledge_collection_items (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL,
            collection_id UUID NOT NULL,
            knowledge_base_id UUID NOT NULL,
            rank INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """,
        """
        CREATE TABLE knowledge_bases (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL,
            active_document_version_id UUID NULL,
            source_identity_id UUID NULL,
            sync_state VARCHAR(50) NOT NULL,
            lifecycle_state VARCHAR(50) NOT NULL
        )
        """,
        """
        CREATE TABLE document_versions (
            id UUID PRIMARY KEY,
            organization_id UUID NOT NULL,
            knowledge_base_id UUID NOT NULL,
            status VARCHAR(32) NOT NULL
        )
        """,
        """
        CREATE TABLE documents (
            id UUID PRIMARY KEY,
            knowledge_base_id UUID NOT NULL,
            status VARCHAR(50) NOT NULL
        )
        """,
        """
        CREATE TABLE document_chunks (
            id UUID PRIMARY KEY,
            document_id UUID NOT NULL,
            document_version_id UUID NULL,
            knowledge_base_id UUID NOT NULL
        )
        """,
        """
        CREATE TABLE snapshot_write_probe (
            id UUID PRIMARY KEY
        )
        """,
    )
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _seed_ready_public_collection(engine):
    organization_id = uuid4()
    collection_id = uuid4()
    knowledge_base_id = uuid4()
    version_id = uuid4()
    item_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO organization (id, is_active) "
                "VALUES (:organization_id, true)"
            ),
            {"organization_id": organization_id},
        )
        connection.execute(
            text(
                "INSERT INTO knowledge_collections "
                "(id, organization_id, lifecycle_state, sync_state, "
                "is_system_managed, safe_metadata) "
                "VALUES (:collection_id, :organization_id, 'active', "
                "'manual', false, '{\"visibility\": \"public\"}'::jsonb)"
            ),
            {
                "collection_id": collection_id,
                "organization_id": organization_id,
            },
        )
        connection.execute(
            text(
                "INSERT INTO knowledge_bases "
                "(id, organization_id, active_document_version_id, "
                "source_identity_id, sync_state, lifecycle_state) "
                "VALUES (:knowledge_base_id, :organization_id, :version_id, "
                "NULL, 'manual', 'active')"
            ),
            {
                "knowledge_base_id": knowledge_base_id,
                "organization_id": organization_id,
                "version_id": version_id,
            },
        )
        connection.execute(
            text(
                "INSERT INTO document_versions "
                "(id, organization_id, knowledge_base_id, status) "
                "VALUES (:version_id, :organization_id, "
                ":knowledge_base_id, 'ready')"
            ),
            {
                "version_id": version_id,
                "organization_id": organization_id,
                "knowledge_base_id": knowledge_base_id,
            },
        )
        connection.execute(
            text(
                "INSERT INTO knowledge_collection_items "
                "(id, organization_id, collection_id, knowledge_base_id, "
                "rank, created_at) "
                "VALUES (:item_id, :organization_id, :collection_id, "
                ":knowledge_base_id, 0, clock_timestamp())"
            ),
            {
                "item_id": item_id,
                "organization_id": organization_id,
                "collection_id": collection_id,
                "knowledge_base_id": knowledge_base_id,
            },
        )
    return organization_id, collection_id, knowledge_base_id


@pytest.fixture
def disposable_snapshot_database():
    try:
        config = DisposablePostgresConfig.from_environment()
    except DisposablePostgresConfigurationError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL connection settings are not safely configured",
            pytrace=False,
        ) from None

    database = f"{DB_PREFIX}_{uuid4().hex[:12]}"
    quoted_database = quote_disposable_database_name(database, prefix=DB_PREFIX)
    admin_engine = create_engine(
        config.database_url(config.maintenance_database),
        isolation_level="AUTOCOMMIT",
    )
    engine = None
    database_created = False
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f"CREATE DATABASE {quoted_database}"))
        database_created = True
        engine = create_engine(config.database_url(database), pool_size=2)
        _create_schema(engine)
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if database_created:
            with admin_engine.connect() as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) "
                        "FROM pg_stat_activity "
                        "WHERE datname = :database "
                        "AND pid <> pg_backend_pid()"
                    ),
                    {"database": database},
                )
                connection.execute(text(f"DROP DATABASE {quoted_database}"))
        admin_engine.dispose()


class _PausingSnapshotAdapter(PostgresKnowledgeRuntimeCandidateSnapshotAdapter):
    def __init__(self, *, session_factory, snapshot_started, writer_finished):
        super().__init__(session_factory=session_factory)
        self.snapshot_started = snapshot_started
        self.writer_finished = writer_finished
        self.isolation_level = None
        self.transaction_read_only = None

    def _load_selected_collections(
        self,
        db,
        organization_id,
        collection_ids,
    ):
        self.isolation_level = db.execute(
            text("SHOW transaction_isolation")
        ).scalar_one()
        self.transaction_read_only = db.execute(
            text("SHOW transaction_read_only")
        ).scalar_one()
        self.snapshot_started.set()
        if not self.writer_finished.wait(timeout=15):
            raise RuntimeError("writer_timeout")
        return super()._load_selected_collections(
            db,
            organization_id,
            collection_ids,
        )


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable Knowledge snapshot evidence",
)
def test_repeatable_read_snapshot_does_not_mix_concurrent_membership_change(
    disposable_snapshot_database,
):
    engine = disposable_snapshot_database
    organization_id, collection_id, knowledge_base_id = (
        _seed_ready_public_collection(engine)
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    snapshot_started = Event()
    writer_finished = Event()
    adapter = _PausingSnapshotAdapter(
        session_factory=session_factory,
        snapshot_started=snapshot_started,
        writer_finished=writer_finished,
    )
    request = KnowledgeRuntimeCandidateRequest(
        audience=AnonymousPublicAudience(organization_id=organization_id),
        collection_ids=(collection_id,),
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(adapter.load_snapshot, request)
        assert snapshot_started.wait(timeout=15)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM knowledge_collection_items "
                    "WHERE organization_id = :organization_id "
                    "AND collection_id = :collection_id"
                ),
                {
                    "organization_id": organization_id,
                    "collection_id": collection_id,
                },
            )
        writer_finished.set()
        first_snapshot = future.result(timeout=15)

    assert adapter.isolation_level == "repeatable read"
    assert adapter.transaction_read_only == "on"
    assert first_snapshot.collection_streams[0].eligible_kb_ids == (
        knowledge_base_id,
    )

    next_snapshot = PostgresKnowledgeRuntimeCandidateSnapshotAdapter(
        session_factory=session_factory
    ).load_snapshot(request)
    assert next_snapshot.collection_streams[0].eligible_kb_ids == ()

    probe_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO snapshot_write_probe (id) VALUES (:probe_id)"),
            {"probe_id": probe_id},
        )
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT id FROM snapshot_write_probe WHERE id = :probe_id"),
            {"probe_id": probe_id},
        ).scalar_one() == probe_id


class _WriteAttemptSnapshotAdapter(PostgresKnowledgeRuntimeCandidateSnapshotAdapter):
    def _organization_is_active(self, db, organization_id: UUID) -> bool:
        del organization_id
        db.execute(
            text("INSERT INTO snapshot_write_probe (id) VALUES (:probe_id)"),
            {"probe_id": uuid4()},
        )
        return True


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable Knowledge read-only evidence",
)
def test_snapshot_transaction_rejects_write_and_returns_fixed_error(
    disposable_snapshot_database,
):
    engine = disposable_snapshot_database
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    adapter = _WriteAttemptSnapshotAdapter(session_factory=session_factory)
    request = KnowledgeRuntimeCandidateRequest(
        audience=AnonymousPublicAudience(organization_id=uuid4()),
    )

    with pytest.raises(KnowledgeRuntimeCandidateSnapshotError) as exc_info:
        adapter.load_snapshot(request)

    assert exc_info.value.reason_code == "snapshot_read_failed"
    assert exc_info.value.__cause__ is None
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM snapshot_write_probe")
        ).scalar_one() == 0
