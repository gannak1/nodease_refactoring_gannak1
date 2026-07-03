"""Seed/reset the final demo database state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import text

from apps.shared.db.base import Base
from apps.shared.db.demo_seed import (
    demo_summary,
    reset_demo_data,
    reset_test_data,
    seed_demo_data,
    seed_test_data,
)
from apps.shared.db.session import SessionLocal, engine
import apps.shared.db.models  # noqa: F401


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
        help="Skip Base.metadata.create_all. Use when migrations already prepared the DB.",
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
    summary = demo_summary(args.profile)

    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if not args.skip_schema:
        ensure_schema(drop_existing_data=args.drop_existing_data)

    db = SessionLocal()
    try:
        if args.drop_existing_data:
            if args.profile == "test":
                seed_test_data(db)
            else:
                seed_demo_data(db)
            print(
                f"✅ Existing local DB data dropped and {args.profile} profile recreated."
            )
        elif args.reset:
            if args.profile == "test":
                reset_test_data(db)
            else:
                reset_demo_data(db)
            print(f"✅ {args.profile} profile reset complete.")
        else:
            if args.profile == "test":
                seed_test_data(db)
            else:
                seed_demo_data(db)
            print(f"✅ {args.profile} profile seed upsert complete.")

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
