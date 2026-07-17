"""Prepare local-only benchmark corpora without disclosing acquisition secrets."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.evaluation.corpus_authoring import (
    load_question_blueprints,
    load_synthetic_package,
    prepare_corpus,
    prepare_synthetic_package,
)
from tests.evaluation.law_open_data import (
    LawOpenDataClient,
    LawOpenDataError,
    load_law_source_catalog,
)
from tests.evaluation.law_question_authoring import prepare_law_question_draft


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LOCAL_DATA_ROOT = REPOSITORY_ROOT / "local" / "evaluation-data" / "mba-279"
SAFE_SNAPSHOT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _safe_status(*, stream=None, **values) -> None:
    print(
        json.dumps(values, ensure_ascii=True, sort_keys=True),
        file=stream or sys.stdout,
    )


def _load_local_environment() -> None:
    load_dotenv(REPOSITORY_ROOT / ".env", override=False)


def _snapshot_path(track: str, snapshot_id: str) -> Path:
    if SAFE_SNAPSHOT_PATTERN.fullmatch(snapshot_id) is None:
        raise ValueError("invalid_snapshot_id")
    return LOCAL_DATA_ROOT / track / snapshot_id


def _probe_law_access(args: argparse.Namespace) -> None:
    _load_local_environment()
    catalog = load_law_source_catalog(args.catalog)
    target_count = LawOpenDataClient.from_environment().probe_catalog(catalog)
    _safe_status(status="law_access_ready", target_count=target_count)


def _collect_law(args: argparse.Namespace) -> None:
    _load_local_environment()
    catalog = load_law_source_catalog(args.catalog)
    collected = LawOpenDataClient.from_environment().collect_catalog(catalog)
    output = _snapshot_path("kr-law", args.snapshot_id)
    summary = prepare_corpus(
        corpus_id=catalog.catalog_id,
        content_class="public",
        sources=collected.sources,
        questions=(),
        output_dir=output,
        license_ref=catalog.license_ref,
        source_files=collected.source_files,
        provenance_rows=collected.provenance_rows,
    )
    _safe_status(
        status="law_snapshot_prepared",
        source_count=summary.source_count,
        canonical_child_count=summary.canonical_child_count,
        review_state=summary.review_state,
    )


def _prepare_synthetic(args: argparse.Namespace) -> None:
    corpus = load_synthetic_package(args.corpus)
    questions = load_question_blueprints(args.questions)
    output = _snapshot_path("enterprise-policy", args.snapshot_id)
    summary = prepare_synthetic_package(
        corpus=corpus,
        question_blueprints=questions,
        output_dir=output,
    )
    _safe_status(
        status="synthetic_snapshot_prepared",
        source_count=summary.source_count,
        canonical_child_count=summary.canonical_child_count,
        question_count=summary.question_count,
        review_state=summary.review_state,
    )


def _draft_law_development(args: argparse.Namespace) -> None:
    catalog = load_law_source_catalog(args.catalog)
    summary = prepare_law_question_draft(
        base_snapshot_dir=_snapshot_path("kr-law", args.snapshot_id),
        base_snapshot_id=args.snapshot_id,
        catalog=catalog,
        bundle_id=args.bundle_id,
        output_dir=_snapshot_path("kr-law-development", args.bundle_id),
    )
    _safe_status(
        status="law_development_questions_drafted",
        question_count=summary.question_count,
        sampling_cluster_count=summary.sampling_cluster_count,
        review_state=summary.review_state,
        structural_pilot_ready=summary.structural_pilot_ready,
        quality_pilot_ready=summary.quality_pilot_ready,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare local Flat/Hierarchical RAG benchmark corpora"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe-law-access")
    probe.add_argument("--catalog", required=True)
    probe.set_defaults(handler=_probe_law_access)

    collect = subparsers.add_parser("collect-law")
    collect.add_argument("--catalog", required=True)
    collect.add_argument("--snapshot-id", required=True)
    collect.set_defaults(handler=_collect_law)

    synthetic = subparsers.add_parser("prepare-synthetic")
    synthetic.add_argument("--corpus", required=True)
    synthetic.add_argument("--questions", required=True)
    synthetic.add_argument("--snapshot-id", required=True)
    synthetic.set_defaults(handler=_prepare_synthetic)

    law_questions = subparsers.add_parser("draft-law-development")
    law_questions.add_argument("--catalog", required=True)
    law_questions.add_argument("--snapshot-id", required=True)
    law_questions.add_argument("--bundle-id", required=True)
    law_questions.set_defaults(handler=_draft_law_development)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        args.handler(args)
    except LawOpenDataError as exc:
        _safe_status(status="error", reason=exc.code, stream=sys.stderr)
        raise SystemExit(2) from None
    except Exception:
        _safe_status(
            status="error",
            reason="corpus_preparation_failed",
            stream=sys.stderr,
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
