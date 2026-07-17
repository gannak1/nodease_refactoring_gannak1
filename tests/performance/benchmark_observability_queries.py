"""Synthetic PostgreSQL benchmark for observability query improvements.

The benchmark uses temporary tables and leaves the application schema untouched.
Run from the repository root with the Gateway virtualenv Python.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from typing import Any

from sqlalchemy import text

from apps.shared.db.session import engine


def _explain_ms(connection, sql: str, params: dict[str, Any], iterations: int) -> float:
    connection.execute(text(sql), params).all()
    timings = []
    statement = text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}")
    for _ in range(iterations):
        plan = connection.execute(statement, params).scalar_one()
        timings.append(float(plan[0]["Execution Time"]))
    return statistics.median(timings)


def _wall_ms(connection, sql: str, params: dict[str, Any], iterations: int) -> float:
    connection.execute(text(sql), params).all()
    timings = []
    for _ in range(iterations):
        started = time.perf_counter()
        connection.execute(text(sql), params).all()
        timings.append((time.perf_counter() - started) * 1000)
    return statistics.median(timings)


def _result(before_ms: float, after_ms: float) -> dict[str, float]:
    return {
        "before_ms": round(before_ms, 3),
        "after_ms": round(after_ms, 3),
        "speedup": round(before_ms / after_ms, 2) if after_ms else 0.0,
    }


def run(rows: int, iterations: int) -> dict[str, Any]:
    with engine.connect() as connection, connection.begin():
        connection.execute(
            text(
                """
                CREATE TEMP TABLE benchmark_audit_logs (
                    id BIGINT PRIMARY KEY,
                    occurred_at TIMESTAMPTZ NOT NULL,
                    workflow_run_id UUID,
                    audit_metadata JSONB NOT NULL
                ) ON COMMIT DROP;
                CREATE TEMP TABLE benchmark_traces (
                    id BIGINT PRIMARY KEY,
                    started_at TIMESTAMPTZ NOT NULL,
                    visible BOOLEAN NOT NULL
                ) ON COMMIT DROP;
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO benchmark_audit_logs
                    (id, occurred_at, workflow_run_id, audit_metadata)
                SELECT
                    value,
                    now() - value * interval '1 millisecond',
                    md5((value % 1000)::text)::uuid,
                    jsonb_build_object(
                        'organization_id', md5('org-' || (value % 100)::text)::uuid,
                        'workflow_run_id', md5((value % 1000)::text)::uuid
                    )
                FROM generate_series(1, :rows) AS value;

                INSERT INTO benchmark_traces (id, started_at, visible)
                SELECT
                    value,
                    now() - value * interval '1 millisecond',
                    value % 100 = 0
                FROM generate_series(1, :rows) AS value;
                """
            ),
            {"rows": rows},
        )
        connection.execute(
            text(
                """
                CREATE INDEX benchmark_audit_occurred_id
                    ON benchmark_audit_logs (occurred_at DESC, id DESC);
                CREATE INDEX benchmark_audit_workflow_run
                    ON benchmark_audit_logs (workflow_run_id);
                CREATE INDEX benchmark_trace_started
                    ON benchmark_traces (started_at DESC);
                CREATE INDEX benchmark_trace_visible_started
                    ON benchmark_traces (visible, started_at DESC);
                ANALYZE benchmark_audit_logs;
                ANALYZE benchmark_traces;
                """
            )
        )

        target_uuid = connection.execute(
            text("SELECT md5('42')::uuid")
        ).scalar_one()
        cursor_row = connection.execute(
            text(
                "SELECT occurred_at, id FROM benchmark_audit_logs "
                "ORDER BY occurred_at DESC, id DESC OFFSET :offset LIMIT 1"
            ),
            {"offset": max(rows - 1000, 1)},
        ).mappings().one()
        audit_jsonb = _explain_ms(
            connection,
            "SELECT id FROM benchmark_audit_logs "
            "WHERE audit_metadata ->> 'workflow_run_id' = :target",
            {"target": str(target_uuid)},
            iterations,
        )
        audit_typed = _explain_ms(
            connection,
            "SELECT id FROM benchmark_audit_logs WHERE workflow_run_id = :target",
            {"target": target_uuid},
            iterations,
        )

        audit_offset = _explain_ms(
            connection,
            "SELECT id FROM benchmark_audit_logs "
            "ORDER BY occurred_at DESC, id DESC OFFSET :offset LIMIT 20",
            {"offset": max(rows - 1000, 1)},
            iterations,
        )
        audit_cursor = _explain_ms(
            connection,
            "SELECT id FROM benchmark_audit_logs "
            "WHERE (occurred_at, id) < (:occurred_at, :id) "
            "ORDER BY occurred_at DESC, id DESC LIMIT 20",
            dict(cursor_row),
            iterations,
        )

        trace_fetch_then_filter = _wall_ms(
            connection,
            "SELECT id, visible FROM benchmark_traces "
            "ORDER BY started_at DESC LIMIT 5000",
            {},
            iterations,
        )
        trace_sql_filter = _wall_ms(
            connection,
            "SELECT id, visible FROM benchmark_traces "
            "WHERE visible IS TRUE ORDER BY started_at DESC LIMIT 20",
            {},
            iterations,
        )
    return {
        "rows": rows,
        "iterations": iterations,
        "audit_typed_fk_vs_jsonb": _result(audit_jsonb, audit_typed),
        "audit_cursor_vs_deep_offset": _result(audit_offset, audit_cursor),
        "trace_sql_filter_vs_fetch_5000": _result(
            trace_fetch_then_filter, trace_sql_filter
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--iterations", type=int, default=5)
    args = parser.parse_args()
    if args.rows < 10_000:
        parser.error("--rows must be at least 10000")
    if args.iterations < 1:
        parser.error("--iterations must be positive")
    print(
        json.dumps(
            run(args.rows, args.iterations),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
