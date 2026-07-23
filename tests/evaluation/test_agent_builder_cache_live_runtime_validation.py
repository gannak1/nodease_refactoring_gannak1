from __future__ import annotations

import pytest

from tests.evaluation.agent_builder_cache_latency_report import ReportValidationError
from tests.evaluation.agent_builder_cache_live_collector import build_live_metadata
from tests.evaluation.run_agent_builder_cache_latency_benchmark import validate_live_rows


def test_development_rows_must_pass_the_cache05_contract_before_local_write() -> None:
    metadata = build_live_metadata(
        dataset_version="agent-builder-cache-latency-v1",
        cache_contract_version="intent-plan-cache-v1",
        run_date="2026-07-23",
        git_sha="a" * 40,
    )

    with pytest.raises(ReportValidationError, match="At least one run row"):
        validate_live_rows((), metadata=metadata)
