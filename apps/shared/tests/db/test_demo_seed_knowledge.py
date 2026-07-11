import gzip
import json

import pytest
from apps.shared.db import demo_seed
from scripts import seed_demo as seed_demo_script


class FakeSchemaInspector:
    def __init__(self, columns_by_table, *, alembic_revisions=None):
        self.columns_by_table = columns_by_table
        self.bind = FakeAlembicBind(alembic_revisions or [])

    def has_table(self, table_name):
        return table_name in self.columns_by_table

    def get_columns(self, table_name):
        return [{"name": name} for name in self.columns_by_table[table_name]]


class FakeAlembicBind:
    def __init__(self, revisions):
        self.revisions = revisions

    def execute(self, _stmt):
        return self

    def fetchall(self):
        return [(revision,) for revision in self.revisions]


class FailingSchemaInspector:
    def has_table(self, table_name):
        raise RuntimeError("secret raw database failure")


def write_minimal_demo_fixture(
    fixture_path,
    *,
    omitted_document_key=None,
    malformed_embedding_key=None,
):
    embedding = [0.0] * demo_seed.DEMO_EMBEDDING_DIMENSION
    specs = [
        spec
        for spec in demo_seed.DEMO_DOCUMENT_SPECS
        if spec.key != omitted_document_key
    ]
    with gzip.open(fixture_path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(
                {
                    "record_type": "header",
                    "fixture_version": demo_seed.DEMO_SEED_VERSION,
                    "embedding_model": demo_seed.DEMO_EMBEDDING_MODEL,
                    "embedding_dimension": demo_seed.DEMO_EMBEDDING_DIMENSION,
                    "document_keys": [spec.key for spec in specs],
                },
                ensure_ascii=False,
            )
        )
        handle.write("\n")
        for spec in specs:
            handle.write(
                json.dumps(
                    {
                        "record_type": "document",
                        "key": spec.key,
                        "filename": spec.filename,
                        "content_hash": f"hash-{spec.key}",
                        "chunking_mode": "flat",
                        "chunking_fingerprint_hash": f"fingerprint-{spec.key}",
                    },
                    ensure_ascii=False,
                )
            )
            handle.write("\n")
            handle.write(
                json.dumps(
                    {
                        "record_type": "chunk",
                        "document_key": spec.key,
                        "chunk_index": 0,
                        "content": "fixture chunk",
                        "embedding": [0.0]
                        if spec.key == malformed_embedding_key
                        else embedding,
                        "token_count": 2,
                        "metadata": {},
                        "chunk_level": "flat",
                    },
                    ensure_ascii=False,
                )
            )
            handle.write("\n")


def test_resolve_legal_pdf_picks_latest_effective_date(tmp_path, monkeypatch):
    old_pdf = tmp_path / "채용절차의 공정화에 관한 법률(법률)(제12326호)(20140121).pdf"
    latest_pdf = tmp_path / "채용절차의 공정화에 관한 법률(법률)(제17326호)(20200526).pdf"
    old_pdf.write_bytes(b"%PDF-1.4\n")
    latest_pdf.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(demo_seed, "DEMO_LEGAL_DOCS_LABOR_DIR", tmp_path)

    spec = next(
        item
        for item in demo_seed.LEGAL_DOCUMENT_SPECS
        if item.key == "legal_fair_hiring"
    )

    assert demo_seed._resolve_legal_pdf(spec) == latest_pdf


def test_hr_bot_graph_references_seeded_rag_kbs():
    graph = demo_seed._hr_bot_graph()
    llm_node = next(node for node in graph["nodes"] if node["id"] == "llm-answer")
    kb_ids = {item["id"] for item in llm_node["data"]["knowledgeBases"]}

    assert llm_node["data"]["model_id"] == demo_seed.DEMO_CHAT_MINI_MODEL
    assert llm_node["data"]["scoreThreshold"] == 0.3
    assert llm_node["data"]["topK"] == 4
    assert str(demo_seed.KB_IDS["internal_leave_attendance"]) in kb_ids
    assert str(demo_seed.KB_IDS["internal_privacy_hr_records"]) in kb_ids
    assert str(demo_seed.KB_IDS["internal_developer_commit_convention"]) in kb_ids
    assert str(demo_seed.KB_IDS["internal_developer_compensation_band"]) in kb_ids
    assert str(demo_seed.KB_IDS["internal_compensation_access_policy"]) in kb_ids
    assert str(demo_seed.KB_IDS["legal_labor_standards"]) in kb_ids
    assert str(demo_seed.KB_IDS["legal_equal_employment"]) in kb_ids


def test_demo_summary_reports_seeded_knowledge_documents():
    summary = demo_seed.demo_summary("demo")

    assert summary["knowledge_documents"] == {
        "public_law_pdfs": 7,
        "internal_markdown_docs": 10,
        "embedding_model": demo_seed.DEMO_EMBEDDING_MODEL,
        "fixture": demo_seed.DEMO_KNOWLEDGE_FIXTURE_PATH.as_posix(),
    }


def test_demo_seed_prerequisites_use_precomputed_fixture_without_openai(
    tmp_path, monkeypatch
):
    fixture_path = tmp_path / "demo_knowledge_chunks.jsonl.gz"
    write_minimal_demo_fixture(fixture_path)

    monkeypatch.setattr(demo_seed, "DEMO_KNOWLEDGE_FIXTURE_PATH", fixture_path)
    monkeypatch.setattr(demo_seed, "DEMO_LEGAL_DOCS_LABOR_DIR", tmp_path / "missing")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv(demo_seed.DEMO_REGENERATE_KNOWLEDGE_FIXTURE_ENV, raising=False)
    monkeypatch.delenv(
        demo_seed.DEMO_ENABLE_RUNTIME_OPENAI_CREDENTIAL_ENV,
        raising=False,
    )
    monkeypatch.setenv("ENCRYPTION_KEY", "present-only")

    demo_seed.validate_demo_seed_prerequisites()


def test_demo_fixture_rejects_missing_document(tmp_path, monkeypatch):
    fixture_path = tmp_path / "demo_knowledge_chunks.jsonl.gz"
    missing_key = demo_seed.DEMO_DOCUMENT_SPECS[0].key
    write_minimal_demo_fixture(fixture_path, omitted_document_key=missing_key)

    monkeypatch.setattr(demo_seed, "DEMO_KNOWLEDGE_FIXTURE_PATH", fixture_path)

    with pytest.raises(ValueError, match="document 누락"):
        demo_seed._read_demo_knowledge_fixture()


def test_demo_fixture_rejects_wrong_embedding_dimension(tmp_path, monkeypatch):
    fixture_path = tmp_path / "demo_knowledge_chunks.jsonl.gz"
    malformed_key = demo_seed.DEMO_DOCUMENT_SPECS[0].key
    write_minimal_demo_fixture(
        fixture_path,
        malformed_embedding_key=malformed_key,
    )

    monkeypatch.setattr(demo_seed, "DEMO_KNOWLEDGE_FIXTURE_PATH", fixture_path)

    with pytest.raises(ValueError, match="embedding 차원 오류"):
        demo_seed._read_demo_knowledge_fixture()


def test_demo_seed_runtime_credential_opt_in_requires_openai_key(
    tmp_path, monkeypatch
):
    fixture_path = tmp_path / "demo_knowledge_chunks.jsonl.gz"
    write_minimal_demo_fixture(fixture_path)

    monkeypatch.setattr(demo_seed, "DEMO_KNOWLEDGE_FIXTURE_PATH", fixture_path)
    monkeypatch.setattr(demo_seed, "_load_seed_env", lambda: None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ENCRYPTION_KEY", "present-only")
    monkeypatch.setenv(demo_seed.DEMO_ENABLE_RUNTIME_OPENAI_CREDENTIAL_ENV, "1")

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        demo_seed.validate_demo_seed_prerequisites()


def test_demo_runtime_credential_grants_agent_builder_user_permission(monkeypatch):
    upserts = []

    def capture_upsert(_db, model, row_id, values):
        upserts.append((model, row_id, values))

    monkeypatch.setattr(demo_seed, "_upsert_by_id", capture_upsert)

    demo_seed._seed_runtime_llm_permissions(object())

    user_permissions = {
        values["user_id"]: values
        for model, _row_id, values in upserts
        if model is demo_seed.UserLLMPermission
    }
    assert set(user_permissions) == {
        demo_seed.USER_IDS["author"],
        demo_seed.USER_IDS["tester_builder"],
    }
    assert user_permissions[demo_seed.USER_IDS["tester_builder"]]["auth_state"] == (
        "operator"
    )


def test_demo_seed_chat_models_use_gpt_5_4_family():
    assert demo_seed.DEMO_CHAT_MODEL == "gpt-5.4"
    assert demo_seed.DEMO_CHAT_MINI_MODEL == "gpt-5.4-mini"
    assert set(demo_seed.CREDENTIAL_MODEL_REL_IDS) == {
        demo_seed.DEMO_CHAT_MODEL,
        demo_seed.DEMO_CHAT_MINI_MODEL,
        demo_seed.DEMO_MODEL_ROUTER_BASE_MODEL,
        demo_seed.DEMO_MODEL_ROUTER_FALLBACK_MODEL,
        demo_seed.DEMO_MODEL_ROUTER_CHEAP_MODEL,
        demo_seed.DEMO_MODEL_ROUTER_BALANCED_MODEL,
        demo_seed.DEMO_EMBEDDING_MODEL,
    }


def test_schema_readiness_reports_stale_demo_db_columns():
    gaps = seed_demo_script.schema_readiness_gaps(
        FakeSchemaInspector(
            {
                "knowledge_bases": {"id", "name", "user_id"},
                "documents": {"id", "knowledge_base_id", "filename"},
            }
        ),
        required_columns={
            "knowledge_bases": {
                "id",
                "name",
                "organization_id",
                "embedding_model",
                "sync_state",
                "user_id",
            },
            "documents": {"id", "knowledge_base_id", "filename", "embedding_model"},
            "document_chunks": {"id", "document_id", "embedding"},
        },
    )

    assert gaps == {
        "missing_tables": ["document_chunks"],
        "missing_columns": {
            "documents": ["embedding_model"],
            "knowledge_bases": [
                "embedding_model",
                "organization_id",
                "sync_state",
            ],
        },
        "reason": None,
    }

    message = seed_demo_script.format_schema_readiness_error(gaps)
    assert "Base.metadata.create_all() creates missing tables but does not ALTER" in message
    assert "knowledge_bases: embedding_model, organization_id, sync_state" in message
    assert "alembic -c apps/shared/alembic.ini upgrade heads" in message
    assert "--profile demo --reset --drop-existing-data --yes" in message


def test_schema_readiness_reports_safe_reason_on_introspection_failure():
    gaps = seed_demo_script.schema_readiness_gaps(
        FailingSchemaInspector(),
        required_columns={"knowledge_bases": {"id", "sync_state"}},
    )

    assert gaps == {
        "missing_tables": [],
        "missing_columns": {},
        "reason": "schema_introspection_failed",
    }

    message = seed_demo_script.format_schema_readiness_error(gaps)
    assert "Readiness check failed: schema_introspection_failed" in message
    assert "secret raw database failure" not in message


def test_alembic_readiness_reports_missing_version_table():
    gaps = seed_demo_script.alembic_readiness_gaps(
        FakeSchemaInspector({"knowledge_bases": {"id"}}),
        code_heads=["head-1"],
        known_revisions=["head-1"],
    )

    assert gaps["ready"] is False
    assert gaps["missing_version_table"] is True

    message = seed_demo_script.format_schema_readiness_error(
        {
            "missing_tables": [],
            "missing_columns": {},
            "reason": None,
            "migration": gaps,
        }
    )
    assert "alembic_version table is missing" in message


def test_alembic_readiness_reports_database_behind_code_head():
    gaps = seed_demo_script.alembic_readiness_gaps(
        FakeSchemaInspector(
            {"alembic_version": {"version_num"}},
            alembic_revisions=["head-1"],
        ),
        code_heads=["head-2"],
        known_revisions=["head-1", "head-2"],
    )

    assert gaps["ready"] is False
    assert gaps["database_behind"] is True

    message = seed_demo_script.format_schema_readiness_error(
        {
            "missing_tables": [],
            "missing_columns": {},
            "reason": None,
            "migration": gaps,
        }
    )
    assert "DB revision does not match code head" in message
    assert "db=head-1" in message
    assert "code=head-2" in message


def test_alembic_readiness_reports_split_code_heads():
    gaps = seed_demo_script.alembic_readiness_gaps(
        FakeSchemaInspector(
            {"alembic_version": {"version_num"}},
            alembic_revisions=["head-1"],
        ),
        code_heads=["head-1", "head-2"],
        known_revisions=["head-1", "head-2"],
    )

    assert gaps["ready"] is False
    assert gaps["split_heads"] is True

    message = seed_demo_script.format_schema_readiness_error(
        {
            "missing_tables": [],
            "missing_columns": {},
            "reason": None,
            "migration": gaps,
        }
    )
    assert "multiple code heads" in message


def test_knowledge_safe_metadata_migration_is_preserved_in_the_single_merged_head():
    script = seed_demo_script._alembic_script_directory()

    safe_metadata_revision = script.get_revision("fa7c8d9e0f12")
    merged_revision = script.get_revision("ff4b5c6d7e89")
    hardened_revision = script.get_revision("ff5c6d7e8f90")

    assert safe_metadata_revision.down_revision == "fa7b8c9d0e12"
    assert set(merged_revision.down_revision) == {"fa7c8d9e0f12", "ff3a4b5c6d78"}
    assert hardened_revision.down_revision == "ff4b5c6d7e89"
    assert script.get_heads() == ["ff5c6d7e8f90"]


def test_demo_knowledge_seed_contract_has_ids_and_permission_specs():
    document_keys = {spec.key for spec in demo_seed.DEMO_DOCUMENT_SPECS}
    public_keys = {
        spec.key
        for spec in demo_seed.DEMO_DOCUMENT_SPECS
        if spec.source_tier == "public"
    }
    private_keys = document_keys - public_keys

    assert document_keys <= set(demo_seed.KB_IDS)
    assert document_keys <= set(demo_seed.DOCUMENT_IDS)
    assert document_keys <= set(demo_seed.COLLECTION_ITEM_IDS)
    assert all(
        spec.collection_key == "legal_public"
        for spec in demo_seed.DEMO_DOCUMENT_SPECS
        if spec.source_tier == "public"
    )
    assert all(
        spec.collection_key == "internal_onboarding"
        for spec in demo_seed.DEMO_DOCUMENT_SPECS
        if spec.source_tier != "public"
    )

    permission_specs = set(demo_seed._demo_team_knowledge_permission_specs())
    for key in public_keys:
        assert (key, "platform_admin", "manager") in permission_specs
        assert (key, "customer_support_ops", "operator") in permission_specs
    for key in private_keys:
        assert (key, "platform_admin", "manager") in permission_specs
    assert (
        "internal_developer_compensation_band",
        "ai_builder_onboarding",
        "operator",
    ) in permission_specs
    assert (
        "internal_compensation_access_policy",
        "ai_builder_onboarding",
        "operator",
    ) in permission_specs
    assert (
        "internal_privacy_hr_records",
        "ai_builder_onboarding",
        "operator",
    ) not in permission_specs
    assert (
        "internal_privacy_hr_records",
        "platform_admin",
        "manager",
    ) in permission_specs
    assert (
        "internal_privacy_hr_records",
        "hr_knowledge_users",
        "operator",
    ) in permission_specs
    for key in (
        "internal_onboarding",
        "internal_leave_attendance",
        "internal_benefits",
    ):
        assert (key, "tester_builder", "operator") in permission_specs

    collection_permission_specs = set(
        demo_seed._demo_team_knowledge_collection_permission_specs()
    )
    assert ("legal_public", "ai_builder_onboarding", "route") in collection_permission_specs
    assert (
        "internal_onboarding",
        "customer_support_ops",
        "read",
    ) in collection_permission_specs
    assert (
        "internal_onboarding",
        "tester_builder",
        "read",
    ) in collection_permission_specs
    assert (
        "internal_onboarding",
        "tester_builder",
        "route",
    ) in collection_permission_specs


def test_demo_knowledge_seed_excludes_personal_salary_records():
    document_keys = {spec.key for spec in demo_seed.DEMO_DOCUMENT_SPECS}
    filenames = {spec.filename for spec in demo_seed.DEMO_DOCUMENT_SPECS}

    assert "internal_developer_compensation_band" in document_keys
    assert "internal_compensation_access_policy" in document_keys
    assert all("개인별 실제 연봉" not in filename for filename in filenames)
    assert all("personal_salary" not in key for key in document_keys)


def test_committed_knowledge_fixture_matches_demo_seed_contract():
    fixture = demo_seed._read_demo_knowledge_fixture()
    document_keys = {spec.key for spec in demo_seed.DEMO_DOCUMENT_SPECS}
    chunk_total = sum(len(chunks) for chunks in fixture["chunks_by_document"].values())

    assert set(fixture["documents"]) == document_keys
    assert set(fixture["chunks_by_document"]) == document_keys
    assert chunk_total >= len(document_keys)
    assert fixture["documents"]["legal_fair_hiring"]["filename"] == (
        "채용절차의 공정화에 관한 법률(법률)(제17326호)(20200526).pdf"
    )
    for document_key, chunks in fixture["chunks_by_document"].items():
        assert chunks, document_key
        assert len(chunks[0]["embedding"]) == demo_seed.DEMO_EMBEDDING_DIMENSION


def test_committed_knowledge_fixture_does_not_contain_secret_like_values():
    with gzip.open(
        demo_seed.DEMO_KNOWLEDGE_FIXTURE_PATH,
        "rt",
        encoding="utf-8",
    ) as handle:
        for line in handle:
            assert "sk-" not in line
            assert "OPENAI_API_KEY" not in line
            assert "ENCRYPTION_KEY" not in line
