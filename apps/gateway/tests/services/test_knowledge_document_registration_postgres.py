import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from apps.gateway.services.knowledge_document_registration_service import (
    KnowledgeDocumentRegistrationHidden,
    KnowledgeDocumentRegistrationService,
    KnowledgeDocumentSlotOccupied,
)
from apps.shared.db.models.knowledge import Document, KnowledgeBase, SourceType
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.user import User
from apps.shared.tests.helpers.disposable_postgres import (
    DisposablePostgresConfig,
    DisposablePostgresConfigurationError,
    quote_disposable_database_name,
)

ROOT_DIR = Path(__file__).resolve().parents[4]
RUN_ENV = "NODEASE_RUN_DISPOSABLE_DB_TEST"
DB_PREFIX = "mbased_knowledge_registration"

pytestmark = pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable PostgreSQL registration integration",
)


def _run_alembic(database: str, config: DisposablePostgresConfig) -> None:
    env = config.subprocess_environment(database=database, root_dir=ROOT_DIR)
    result = subprocess.run(
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
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            f"alembic failed with exit code {result.returncode}; "
            "stdout/stderr omitted to avoid leaking local configuration"
        )


@pytest.fixture(scope="module")
def postgres_session_factory():
    try:
        config = DisposablePostgresConfig.from_environment()
    except DisposablePostgresConfigurationError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL connection settings are not safely configured",
            pytrace=False,
        ) from None

    database = f"{DB_PREFIX}_{uuid.uuid4().hex[:12]}"
    quoted_database = quote_disposable_database_name(database, prefix=DB_PREFIX)
    admin_engine = create_engine(
        config.database_url(config.maintenance_database),
        isolation_level="AUTOCOMMIT",
    )
    database_created = False
    engine = None

    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE {quoted_database}"))
        database_created = True

        engine = create_engine(config.database_url(database))
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        engine.dispose()
        engine = None

        _run_alembic(database, config)
        engine = create_engine(config.database_url(database), pool_size=4)
        yield sessionmaker(bind=engine, expire_on_commit=False)
    except OperationalError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL is unavailable or rejected the connection; "
            "connection details omitted",
            pytrace=False,
        ) from None
    finally:
        if engine is not None:
            engine.dispose()
        if database_created:
            try:
                with admin_engine.connect() as conn:
                    conn.execute(
                        text(
                            """
                            SELECT pg_terminate_backend(pid)
                            FROM pg_stat_activity
                            WHERE datname = :database
                              AND pid <> pg_backend_pid()
                            """
                        ),
                        {"database": database},
                    )
                    conn.execute(text(f"DROP DATABASE IF EXISTS {quoted_database}"))
            except OperationalError:
                raise pytest.fail.Exception(
                    "disposable PostgreSQL cleanup could not connect; "
                    "connection details omitted",
                    pytrace=False,
                ) from None
        admin_engine.dispose()


def _create_empty_knowledge_base(session_factory):
    owner_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()
    with session_factory() as setup_db:
        setup_db.add(
            User(
                id=owner_id,
                email=f"owner-{owner_id}@example.test",
                name="Owner",
                social_provider="local",
            )
        )
        setup_db.flush()
        setup_db.add(
            Organization(
                id=organization_id,
                name=f"Registration organization {organization_id}",
                created_by=owner_id,
            )
        )
        setup_db.flush()
        setup_db.add(
            KnowledgeBase(
                id=knowledge_base_id,
                organization_id=organization_id,
                user_id=owner_id,
                name=f"Registration integration KB {knowledge_base_id}",
                sync_state="manual",
                lifecycle_state="active",
            )
        )
        setup_db.commit()
    return organization_id, knowledge_base_id


def _register_document(
    session_factory,
    *,
    organization_id,
    knowledge_base_id,
    filename,
):
    with session_factory() as db:
        return KnowledgeDocumentRegistrationService(db).register_initial_document(
            knowledge_base_id=knowledge_base_id,
            organization_id=organization_id,
            filename=filename,
            file_path=None,
            chunk_size=500,
            chunk_overlap=50,
            source_type=SourceType.FILE,
        )


def test_concurrent_initial_registration_creates_exactly_one_document(
    postgres_session_factory,
):
    organization_id, knowledge_base_id = _create_empty_knowledge_base(
        postgres_session_factory
    )
    barrier = Barrier(2)

    def register(index: int) -> str:
        barrier.wait(timeout=10)
        try:
            _register_document(
                postgres_session_factory,
                organization_id=organization_id,
                knowledge_base_id=knowledge_base_id,
                filename=f"policy-{index}.txt",
            )
        except KnowledgeDocumentSlotOccupied:
            return "occupied"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(register, (1, 2)))

    assert sorted(results) == ["created", "occupied"]
    with postgres_session_factory() as verification_db:
        documents = (
            verification_db.query(Document)
            .filter(Document.knowledge_base_id == knowledge_base_id)
            .all()
        )
        assert len(documents) == 1
        assert documents[0].status == "pending"


def test_registration_hides_knowledge_base_from_another_organization(
    postgres_session_factory,
):
    organization_id, knowledge_base_id = _create_empty_knowledge_base(
        postgres_session_factory
    )
    other_organization_id = uuid.uuid4()
    with postgres_session_factory() as setup_db:
        owner_id = (
            setup_db.query(KnowledgeBase.user_id)
            .filter(KnowledgeBase.id == knowledge_base_id)
            .scalar()
        )
        setup_db.add(
            Organization(
                id=other_organization_id,
                name=f"Other registration organization {other_organization_id}",
                created_by=owner_id,
            )
        )
        setup_db.commit()

    assert other_organization_id != organization_id

    with pytest.raises(KnowledgeDocumentRegistrationHidden):
        _register_document(
            postgres_session_factory,
            organization_id=other_organization_id,
            knowledge_base_id=knowledge_base_id,
            filename="cross-organization.txt",
        )

    with postgres_session_factory() as verification_db:
        assert (
            verification_db.query(Document)
            .filter(Document.knowledge_base_id == knowledge_base_id)
            .count()
            == 0
        )


def test_committed_document_delete_reopens_initial_registration_slot(
    postgres_session_factory,
):
    organization_id, knowledge_base_id = _create_empty_knowledge_base(
        postgres_session_factory
    )
    first_document_id = _register_document(
        postgres_session_factory,
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
        filename="first.txt",
    )

    with postgres_session_factory() as delete_db:
        deleted = (
            delete_db.query(Document)
            .filter(Document.id == first_document_id)
            .delete(synchronize_session=False)
        )
        assert deleted == 1
        delete_db.commit()

    replacement_document_id = _register_document(
        postgres_session_factory,
        organization_id=organization_id,
        knowledge_base_id=knowledge_base_id,
        filename="replacement.txt",
    )

    assert replacement_document_id != first_document_id
    with postgres_session_factory() as verification_db:
        documents = (
            verification_db.query(Document)
            .filter(Document.knowledge_base_id == knowledge_base_id)
            .all()
        )
        assert [document.filename for document in documents] == ["replacement.txt"]
