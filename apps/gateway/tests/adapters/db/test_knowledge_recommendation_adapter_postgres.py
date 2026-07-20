"""Opt-in PostgreSQL evidence for score-only parent recommendation retrieval."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from apps.gateway.adapters.db.knowledge_recommendation import (
    PostgresParentRecommendationAdapter,
)
from apps.gateway.application.agent_builder.knowledge_recommendation import (
    EmbeddingResolution,
    KnowledgeRecommendationRetrievalRequest,
)
from apps.shared.db.models.knowledge import (
    Document,
    DocumentChunk,
    DocumentVersion,
    KnowledgeBase,
    SourceType,
)
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.user import User
from apps.shared.tests.helpers.disposable_postgres import (
    DisposablePostgresConfig,
    DisposablePostgresConfigurationError,
    quote_disposable_database_name,
)


ROOT_DIR = Path(__file__).resolve().parents[5]
RUN_ENV = "NODEASE_RUN_DISPOSABLE_DB_TEST"
DB_PREFIX = "mba342_parent"

pytestmark = pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable MBA-342 PostgreSQL evidence",
)


def _run_migrations(database: str, config: DisposablePostgresConfig) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "apps/shared/alembic.ini",
            "upgrade",
            "heads",
        ],
        cwd=ROOT_DIR,
        env=config.subprocess_environment(database=database, root_dir=ROOT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail("disposable PostgreSQL migration failed; output omitted")


@pytest.fixture(scope="module")
def postgres_engine():
    try:
        config = DisposablePostgresConfig.from_environment()
    except DisposablePostgresConfigurationError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL settings are not safely configured",
            pytrace=False,
        ) from None

    database = f"{DB_PREFIX}_{uuid.uuid4().hex[:12]}"
    quoted_database = quote_disposable_database_name(database, prefix=DB_PREFIX)
    admin_engine = create_engine(
        config.database_url(config.maintenance_database),
        isolation_level="AUTOCOMMIT",
    )
    created = False
    engine = None
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f"CREATE DATABASE {quoted_database}"))
        created = True
        extension_engine = create_engine(
            config.database_url(database),
            isolation_level="AUTOCOMMIT",
        )
        try:
            with extension_engine.connect() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        finally:
            extension_engine.dispose()
        _run_migrations(database, config)
        engine = create_engine(config.database_url(database), pool_pre_ping=True)
        yield engine
    except OperationalError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL is unavailable; connection details omitted",
            pytrace=False,
        ) from None
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            try:
                with admin_engine.connect() as connection:
                    connection.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                            "WHERE datname = :database AND pid <> pg_backend_pid()"
                        ),
                        {"database": database},
                    )
                    connection.execute(text(f"DROP DATABASE IF EXISTS {quoted_database}"))
            except OperationalError:
                raise pytest.fail.Exception(
                    "disposable PostgreSQL cleanup failed; details omitted",
                    pytrace=False,
                ) from None
        admin_engine.dispose()


class FixedEmbeddingResolver:
    def __init__(self):
        self.calls = 0

    def embed_query(self, **_kwargs):
        self.calls += 1
        return EmbeddingResolution(vector=(1.0, 0.0, 0.0))


class LockingEmbeddingResolver(FixedEmbeddingResolver):
    def __init__(self, engine):
        super().__init__()
        self.connection = engine.connect()
        self.transaction = None

    def embed_query(self, **kwargs):
        resolution = super().embed_query(**kwargs)
        self.transaction = self.connection.begin()
        self.connection.execute(text("SET LOCAL lock_timeout = '3s'"))
        self.connection.execute(
            text("LOCK TABLE document_chunks IN ACCESS EXCLUSIVE MODE")
        )
        return resolution

    def close(self):
        if self.transaction is not None:
            self.transaction.rollback()
        self.connection.close()


def _seed_parent_fixture(engine):
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    authorized_kb_id = uuid.uuid4()
    outside_request_kb_id = uuid.uuid4()
    versioned_kb_id = uuid.uuid4()
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        session.add(
            User(
                id=user_id,
                email=f"mba342-{user_id}@example.invalid",
                name="MBA-342",
                social_provider="local",
            )
        )
        session.flush()
        session.add(
            Organization(
                id=organization_id,
                name="MBA-342 organization",
                created_by=user_id,
                managed_by=user_id,
                options={},
            )
        )
        session.flush()
        for kb_id in (authorized_kb_id, outside_request_kb_id):
            session.add(
                KnowledgeBase(
                    id=kb_id,
                    organization_id=organization_id,
                    user_id=user_id,
                    name="Knowledge Base",
                    embedding_model="fixture-embedding-model",
                    sync_state="synced",
                    lifecycle_state="active",
                )
            )
            session.flush()
            document = Document(
                id=uuid.uuid4(),
                knowledge_base_id=kb_id,
                filename="fixture.txt",
                source_type=SourceType.FILE,
                status="completed",
                chunk_size=500,
                chunk_overlap=50,
                meta_info={},
            )
            session.add(document)
            session.flush()
            vectors = (
                ([1.0, 0.0, 0.0], "parent"),
                ([0.8, 0.6, 0.0], "parent"),
                ([0.0, 1.0, 0.0], "parent"),
                ([-1.0, 0.0, 0.0], "parent"),
                ([1.0, 0.0, 0.0], "child"),
            )
            for index, (vector, level) in enumerate(vectors):
                session.add(
                    DocumentChunk(
                        id=uuid.uuid4(),
                        document_id=document.id,
                        document_version_id=None,
                        knowledge_base_id=kb_id,
                        content="not projected",
                        embedding=vector,
                        chunk_index=index,
                        chunk_level=level,
                        token_count=1,
                        metadata_={},
                    )
                )

        versioned_kb = KnowledgeBase(
            id=versioned_kb_id,
            organization_id=organization_id,
            user_id=user_id,
            name="Versioned Knowledge Base",
            embedding_model="fixture-embedding-model",
            sync_state="synced",
            lifecycle_state="active",
        )
        session.add(versioned_kb)
        session.flush()
        versioned_document = Document(
            id=uuid.uuid4(),
            knowledge_base_id=versioned_kb_id,
            filename="versioned-fixture.txt",
            source_type=SourceType.FILE,
            status="completed",
            chunk_size=500,
            chunk_overlap=50,
            meta_info={},
        )
        session.add(versioned_document)
        session.flush()
        historical_version = DocumentVersion(
            id=uuid.uuid4(),
            organization_id=organization_id,
            knowledge_base_id=versioned_kb_id,
            legacy_document_id=versioned_document.id,
            version_number=1,
            status="superseded",
            embedding_model="fixture-embedding-model",
        )
        active_version = DocumentVersion(
            id=uuid.uuid4(),
            organization_id=organization_id,
            knowledge_base_id=versioned_kb_id,
            legacy_document_id=versioned_document.id,
            version_number=2,
            status="ready",
            embedding_model="fixture-embedding-model",
        )
        session.add_all([historical_version, active_version])
        session.flush()
        versioned_kb.active_document_version_id = active_version.id
        for index, (version_id, vector, level) in enumerate(
            (
                (historical_version.id, [1.0, 0.0, 0.0], "parent"),
                (active_version.id, [0.0, 1.0, 0.0], "parent"),
                (active_version.id, [1.0, 0.0, 0.0], "child"),
            )
        ):
            session.add(
                DocumentChunk(
                    id=uuid.uuid4(),
                    document_id=versioned_document.id,
                    document_version_id=version_id,
                    knowledge_base_id=versioned_kb_id,
                    content="not projected",
                    embedding=vector,
                    chunk_index=index,
                    chunk_level=level,
                    token_count=1,
                    metadata_={},
                )
            )
        session.commit()
    finally:
        session.close()
    return (
        user_id,
        organization_id,
        authorized_kb_id,
        outside_request_kb_id,
        versioned_kb_id,
    )


def test_parent_cosine_query_is_bounded_and_does_not_pollute_caller_session(
    postgres_engine,
):
    (
        actor_id,
        organization_id,
        candidate_id,
        outside_id,
        versioned_id,
    ) = _seed_parent_fixture(postgres_engine)
    statements = []

    def capture(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(statement.lower())

    event.listen(postgres_engine, "before_cursor_execute", capture)
    caller_session = sessionmaker(bind=postgres_engine, expire_on_commit=False)()
    embedding = FixedEmbeddingResolver()
    try:
        caller_session.execute(
            text(
                "CREATE TEMP TABLE mba342_caller_guard (value INTEGER) "
                "ON COMMIT DROP"
            )
        )
        caller_session.execute(
            text("INSERT INTO mba342_caller_guard (value) VALUES (342)")
        )
        assert caller_session.in_transaction()
        result = PostgresParentRecommendationAdapter(
            caller_session,
            embedding_resolver=embedding,
        ).retrieve(
            KnowledgeRecommendationRetrievalRequest(
                organization_id=organization_id,
                actor_id=actor_id,
                safe_query_topics=("approved topic",),
                candidate_kb_ids=(candidate_id, versioned_id),
                candidate_snapshot_ref="snapshot-1",
            )
        )

        by_id = {score.knowledge_base_id: score for score in result.scores}
        assert set(by_id) == {candidate_id, versioned_id}
        assert outside_id not in by_id
        assert by_id[candidate_id].semantic_state == "available"
        assert by_id[candidate_id].parent_relevance == pytest.approx(0.88)
        assert by_id[versioned_id].semantic_state == "available"
        assert by_id[versioned_id].parent_relevance == pytest.approx(0.0)
        assert embedding.calls == 1
        recommendation_queries = [
            statement
            for statement in statements
            if "from knowledge_bases as kb" in statement
            or "from document_chunks as dc" in statement
        ]
        assert len(recommendation_queries) == 2
        assert "dc.chunk_level = 'parent'" in recommendation_queries[0]
        assert "dc.chunk_level = 'parent'" in recommendation_queries[1]
        assert "dc.content" not in recommendation_queries[1]
        assert caller_session.in_transaction()
        assert (
            caller_session.execute(
                text("SELECT value FROM mba342_caller_guard")
            ).scalar_one()
            == 342
        )
        assert caller_session.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        caller_session.close()
        event.remove(postgres_engine, "before_cursor_execute", capture)


def test_parent_statement_timeout_discards_partial_semantic_score(postgres_engine):
    actor_id, organization_id, candidate_id, *_rest = _seed_parent_fixture(
        postgres_engine
    )
    caller_session = sessionmaker(bind=postgres_engine, expire_on_commit=False)()
    embedding = LockingEmbeddingResolver(postgres_engine)
    try:
        result = PostgresParentRecommendationAdapter(
            caller_session,
            embedding_resolver=embedding,
        ).retrieve(
            KnowledgeRecommendationRetrievalRequest(
                organization_id=organization_id,
                actor_id=actor_id,
                safe_query_topics=("approved topic",),
                candidate_kb_ids=(candidate_id,),
                candidate_snapshot_ref="snapshot-timeout",
            )
        )

        assert len(result.scores) == 1
        assert result.scores[0].semantic_state == "parent_search_timeout"
        assert result.scores[0].parent_relevance is None
        assert result.state == "degraded"
        assert embedding.calls == 1
        assert caller_session.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        embedding.close()
        caller_session.close()


def test_five_thousand_candidate_allowlist_keeps_queries_bounded(postgres_engine):
    actor_id, organization_id, candidate_id, *_rest = _seed_parent_fixture(
        postgres_engine
    )
    candidate_ids = (candidate_id, *[uuid.uuid4() for _ in range(4_999)])
    statements = []

    def capture(_conn, _cursor, statement, _params, _context, _executemany):
        lowered = statement.lower()
        if (
            "from knowledge_bases as kb" in lowered
            or "from document_chunks as dc" in lowered
        ):
            statements.append(lowered)

    event.listen(postgres_engine, "before_cursor_execute", capture)
    caller_session = sessionmaker(bind=postgres_engine, expire_on_commit=False)()
    embedding = FixedEmbeddingResolver()
    try:
        result = PostgresParentRecommendationAdapter(
            caller_session,
            embedding_resolver=embedding,
        ).retrieve(
            KnowledgeRecommendationRetrievalRequest(
                organization_id=organization_id,
                actor_id=actor_id,
                safe_query_topics=("approved topic",),
                candidate_kb_ids=candidate_ids,
                candidate_snapshot_ref="snapshot-5000",
            )
        )

        assert len(result.scores) == 5000
        assert len({score.knowledge_base_id for score in result.scores}) == 5000
        assert embedding.calls == 1
        assert len(statements) == 2
    finally:
        caller_session.close()
        event.remove(postgres_engine, "before_cursor_execute", capture)
