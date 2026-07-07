"""Seed/reset the final demo database state."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import inspect, text

from apps.shared.db.base import Base
from apps.shared.db.demo_seed import (
    DEMO_ENABLE_RUNTIME_OPENAI_CREDENTIAL_ENV,
    demo_summary,
    reset_demo_data,
    reset_test_data,
    seed_demo_data,
    seed_test_data,
    DEMO_REGENERATE_KNOWLEDGE_FIXTURE_ENV,
    validate_demo_seed_prerequisites,
)
from apps.shared.db.session import SessionLocal, engine
import apps.shared.db.models  # noqa: F401


REQUIRED_DEMO_SCHEMA_COLUMNS: dict[str, set[str]] = {
    "knowledge_bases": {
        "id",
        "organization_id",
        "name",
        "embedding_model",
        "top_k",
        "similarity_threshold",
        "active_document_version_id",
        "source_identity_id",
        "sync_state",
        "lifecycle_state",
        "user_id",
    },
    "knowledge_collections": {
        "id",
        "organization_id",
        "name",
        "source_identity_id",
        "source_connector_ref",
        "is_system_managed",
        "sync_state",
        "lifecycle_state",
        "safe_metadata",
        "created_by",
    },
    "knowledge_collection_items": {
        "id",
        "organization_id",
        "collection_id",
        "knowledge_base_id",
        "safe_source_path_ref",
        "rank",
        "safe_metadata",
    },
    "documents": {
        "id",
        "knowledge_base_id",
        "filename",
        "file_path",
        "source_type",
        "content_hash",
        "status",
        "chunk_size",
        "chunk_overlap",
        "meta_info",
        "embedding_model",
    },
    "document_versions": {
        "id",
        "organization_id",
        "knowledge_base_id",
        "legacy_document_id",
        "source_identity_id",
        "version_number",
        "status",
        "content_hash",
        "chunking_fingerprint",
        "embedding_model",
        "safe_metadata",
    },
    "document_chunks": {
        "id",
        "document_id",
        "document_version_id",
        "knowledge_base_id",
        "content",
        "embedding",
        "chunk_index",
        "parent_chunk_id",
        "chunk_level",
        "section_path",
        "heading",
        "token_count",
        "metadata",
    },
    "team_knowledge_permissions": {
        "id",
        "grantee_organization_id",
        "team_id",
        "knowledge_base_id",
        "auth_state",
        "assigned_by",
        "assigned_at",
        "options",
        "flags",
    },
    "team_knowledge_collection_permissions": {
        "id",
        "grantee_organization_id",
        "team_id",
        "knowledge_collection_id",
        "permission_action",
        "assigned_by",
        "assigned_at",
        "options",
        "flags",
    },
    "llm_providers": {
        "id",
        "name",
        "type",
        "auth_type",
        "doc_url",
    },
    "llm_models": {
        "id",
        "provider_id",
        "model_id_for_api_call",
        "name",
        "type",
        "context_window",
        "input_price_1k",
        "output_price_1k",
        "is_active",
        "metadata",
    },
}


class DemoSchemaReadinessError(RuntimeError):
    """Raised when an existing local DB schema is stale for demo seed."""


def ensure_schema(*, drop_existing_data: bool = False) -> None:
    """Create local schema objects when running against an empty dev database."""
    if drop_existing_data:
        with engine.begin() as connection:
            # apps.workflow_id와 workflows.app_id는 순환 FK라 SQLAlchemy drop_all이
            # 삭제 순서를 정할 수 없다. 전체 초기화는 로컬 public schema를 재생성한다.
            connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=engine)


def schema_readiness_gaps(
    schema_inspector,
    *,
    required_columns: Mapping[str, set[str]] | None = None,
) -> dict[str, object]:
    """Return missing table/column gaps for the current demo seed contract."""
    required = required_columns or REQUIRED_DEMO_SCHEMA_COLUMNS
    missing_tables: list[str] = []
    missing_columns: dict[str, list[str]] = {}

    for table_name in sorted(required):
        if not schema_inspector.has_table(table_name):
            missing_tables.append(table_name)
            continue

        actual_columns = {
            column["name"] for column in schema_inspector.get_columns(table_name)
        }
        missing = sorted(required[table_name] - actual_columns)
        if missing:
            missing_columns[table_name] = missing

    return {
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
    }


def _schema_has_gaps(gaps: Mapping[str, object]) -> bool:
    return bool(gaps["missing_tables"] or gaps["missing_columns"])


def format_schema_readiness_error(gaps: Mapping[str, object]) -> str:
    """Build a user-facing stale schema remediation message."""
    lines = [
        "[ERROR] Local demo DB schema is not ready for the current demo seed.",
        "Base.metadata.create_all() creates missing tables but does not ALTER stale tables.",
        "Seed was stopped before demo data writes so the API does not appear seeded while later failing with 500.",
    ]
    missing_tables = gaps["missing_tables"]
    if missing_tables:
        lines.append("")
        lines.append("Missing tables:")
        for table_name in missing_tables:
            lines.append(f"- {table_name}")

    missing_columns = gaps["missing_columns"]
    if missing_columns:
        lines.append("")
        lines.append("Missing columns:")
        for table_name, columns in missing_columns.items():
            lines.append(f"- {table_name}: {', '.join(columns)}")

    lines.extend(
        [
            "",
            "Resolve with one of the following:",
            "1. Preserve local data and apply migrations:",
            "   apps/gateway/.venv/Scripts/python.exe -m alembic -c apps/shared/alembic.ini upgrade heads",
            "2. Recreate disposable local demo data:",
            "   apps/gateway/.venv/Scripts/python.exe scripts/seed_demo.py --profile demo --reset --drop-existing-data --yes",
        ]
    )
    return "\n".join(lines)


def check_demo_schema_readiness() -> None:
    gaps = schema_readiness_gaps(inspect(engine))
    if _schema_has_gaps(gaps):
        raise DemoSchemaReadinessError(format_schema_readiness_error(gaps))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed Nodease final demo data into the local database."
    )
    parser.add_argument(
        "--profile",
        choices=("demo", "test"),
        default="demo",
        help="Seed profile to apply. demo is final presentation data; test is mutable QA data.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete selected profile seed rows and recreate that profile state.",
    )
    parser.add_argument(
        "--drop-existing-data",
        action="store_true",
        help=(
            "Drop all mapped local tables before recreating the demo seed. "
            "Must be used with --reset --yes."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm destructive operations such as --drop-existing-data.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned demo seed summary without touching the database.",
    )
    parser.add_argument(
        "--skip-schema",
        action="store_true",
        help=(
            "Skip Base.metadata.create_all. Schema readiness is still checked "
            "before demo data is written."
        ),
    )
    parser.add_argument(
        "--regenerate-knowledge-fixture",
        action="store_true",
        help=(
            "Regenerate demo Knowledge chunk/embedding fixture from local legal docs "
            "and OPENAI_API_KEY instead of using the precomputed fixture."
        ),
    )
    parser.add_argument(
        "--enable-runtime-openai-credential",
        action="store_true",
        help=(
            "Seed repo root .env OPENAI_API_KEY as the local demo runtime "
            "OpenAI credential. Use only for disposable demo databases."
        ),
    )
    args = parser.parse_args()
    if args.drop_existing_data and not args.reset:
        parser.error("--drop-existing-data must be used with --reset.")
    if args.drop_existing_data and not args.yes:
        parser.error("--drop-existing-data requires --yes.")
    if args.drop_existing_data and args.skip_schema:
        parser.error("--drop-existing-data cannot be used with --skip-schema.")
    return args


def main() -> None:
    args = parse_args()
    if args.regenerate_knowledge_fixture:
        os.environ[DEMO_REGENERATE_KNOWLEDGE_FIXTURE_ENV] = "1"
    if args.enable_runtime_openai_credential:
        os.environ[DEMO_ENABLE_RUNTIME_OPENAI_CREDENTIAL_ENV] = "1"
    summary = demo_summary(args.profile)

    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if args.profile == "demo":
        validate_demo_seed_prerequisites()

    if not args.skip_schema:
        ensure_schema(drop_existing_data=args.drop_existing_data)

    if args.profile == "demo":
        try:
            check_demo_schema_readiness()
        except DemoSchemaReadinessError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(2) from exc

    db = SessionLocal()
    try:
        if args.drop_existing_data:
            if args.profile == "test":
                seed_test_data(db)
            else:
                seed_demo_data(db)
            print(
                f"[OK] Existing local DB data dropped and {args.profile} profile recreated."
            )
        elif args.reset:
            if args.profile == "test":
                reset_test_data(db)
            else:
                reset_demo_data(db)
            print(f"[OK] {args.profile} profile reset complete.")
        else:
            if args.profile == "test":
                seed_test_data(db)
            else:
                seed_demo_data(db)
            print(f"[OK] {args.profile} profile seed upsert complete.")

        print(f"- profile: {summary['profile']}")
        print(f"- organization: {summary['organization']}")
        print("- password: 123123")
        print("- accounts:")
        for email in summary["users"]:
            print(f"  - {email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
