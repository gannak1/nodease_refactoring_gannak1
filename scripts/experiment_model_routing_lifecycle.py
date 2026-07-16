"""배포 후 자동 라우팅의 매칭, 검증, 정책 갱신 수명주기를 실제 호출로 검증한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.experiment_enterprise_request_routing import DEFAULT_NODE_ID, _policy_path
from scripts.experiment_fresh_routing_benchmark import (
    DEFAULT_EMAIL,
    DEFAULT_ORGANIZATION_ID,
    DEFAULT_PASSWORD_ENV,
    HIGH_FIXED_MODEL_ID,
    ExperimentClient,
    _create_deployed_clone,
    _execute_case,
    _latest_batch,
    _routing_summary,
    _wait_for_bootstrap_policy,
    _write_json,
    build_auto_cases,
)
from scripts.model_routing_report_charts import write_lifecycle_chart


LIFECYCLE_RUN_COUNT = 80
REFRESH_EVERY_RUNS = 20
CHECKPOINTS = frozenset(range(REFRESH_EVERY_RUNS, LIFECYCLE_RUN_COUNT + 1, REFRESH_EVERY_RUNS))


def _safe_lifecycle_payload(value: Any) -> Any:
    """실험 결과에서 입력 원문과 embedding vector를 제거한다."""
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if key in {"embedding", "centroid_embedding"}:
                continue
            if key == "query":
                normalized = " ".join(str(raw_value or "").split())
                safe["query_sha256"] = hashlib.sha256(
                    normalized.encode("utf-8")
                ).hexdigest()
                continue
            safe[key] = _safe_lifecycle_payload(raw_value)
        return safe
    if isinstance(value, list):
        return [_safe_lifecycle_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_lifecycle_payload(item) for item in value]
    return value


def _policy_marker(policy: dict[str, Any]) -> tuple[Any, ...]:
    refresh = policy.get("refresh") if isinstance(policy.get("refresh"), dict) else {}
    batch = _latest_batch(policy)
    return (
        policy.get("policy_version"),
        refresh.get("last_refresh_at"),
        batch.get("id"),
        batch.get("status"),
    )


def _wait_for_policy_refresh(
    client: ExperimentClient,
    *,
    workflow_id: str,
    previous_policy: dict[str, Any],
    timeout_seconds: int,
) -> tuple[dict[str, Any], bool]:
    previous_marker = _policy_marker(previous_policy)
    deadline = time.monotonic() + timeout_seconds
    last = previous_policy
    observed_change = False
    while time.monotonic() < deadline:
        last = client.get_json(_policy_path(workflow_id, DEFAULT_NODE_ID))
        observed_change = observed_change or _policy_marker(last) != previous_marker
        batch = _latest_batch(last)
        pending = str(last.get("status") or "") == "refreshing" or str(
            batch.get("status") or ""
        ) in {"queued", "pending", "running", "refreshing"}
        if observed_change and not pending:
            return last, True
        time.sleep(3)
    return last, False


def _model_windows(rows: list[Any], *, size: int = 10) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for start in range(0, len(rows), size):
        values = rows[start : start + size]
        windows.append(
            {
                "start": start + 1,
                "end": start + len(values),
                "models": dict(Counter(row.selected_model or "unknown" for row in values)),
            }
        )
    return windows


def _cohort_breakdown(rows: list[Any]) -> dict[str, dict[str, Any]]:
    """입력군별 매칭과 검증 rule 적용 결과를 사람이 읽기 쉬운 집계로 만든다."""
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        expected = str(row.case.expected_cohort_key)
        grouped.setdefault(expected, []).append(row)

    result: dict[str, dict[str, Any]] = {}
    for expected, values in sorted(grouped.items()):
        exact = sum(row.matched_cohort_key == expected for row in values)
        validated_routes = sum(
            row.reason_code == "validated_adaptive_cohort" for row in values
        )
        failures = sum(
            str(row.run_status).lower() != "success"
            or str(row.node_status).lower() != "success"
            for row in values
        )
        result[expected] = {
            "requests": len(values),
            "matched": exact,
            "match_accuracy_pct": exact / len(values) * 100,
            "validated_routes": validated_routes,
            "validated_route_coverage_pct": validated_routes / len(values) * 100,
            "failures": failures,
            "models": dict(Counter(row.selected_model or "unknown" for row in values)),
            "matched_as": dict(
                Counter(
                    row.matched_cohort_key
                    or row.semantic_match_status
                    or "unknown"
                    for row in values
                )
            ),
        }
    return result


def _policy_checkpoint(
    *,
    sequence: int,
    policy: dict[str, Any],
    rows: list[Any],
    refresh_observed: bool | None = None,
) -> dict[str, Any]:
    active = policy.get("active_policy") if isinstance(policy.get("active_policy"), dict) else {}
    adaptive = policy.get("adaptive") if isinstance(policy.get("adaptive"), dict) else {}
    refresh = policy.get("refresh") if isinstance(policy.get("refresh"), dict) else {}
    batch = _latest_batch(policy)
    routing = _routing_summary(rows, policy=policy) if rows else {}
    return {
        "sequence": sequence,
        "status": policy.get("status"),
        "policy_version": policy.get("policy_version"),
        "active_rule_count": len(active.get("rules") or []),
        "default_model_id": active.get("default_model_id"),
        "fallback_model_id": active.get("fallback_model_id"),
        "eligible_runs_since_last_refresh": refresh.get("eligible_runs_since_last_refresh"),
        "last_refresh_result": refresh.get("last_refresh_result"),
        "last_refresh_at": refresh.get("last_refresh_at"),
        "validation_spend_usd": float(adaptive.get("spent_usd") or 0),
        "latest_batch_id": batch.get("id"),
        "latest_batch_status": batch.get("status"),
        "latest_batch_trigger": batch.get("trigger"),
        "refresh_observed": refresh_observed,
        "route_coverage_pct": routing.get("route_coverage_pct", 0),
        "cohort_accuracy_pct": routing.get("cohort_accuracy_pct", 0),
        "models": dict(Counter(row.selected_model or "unknown" for row in rows)),
    }


def _lifecycle_summary(*, rows: list[Any], checkpoints: list[dict[str, Any]]) -> dict[str, Any]:
    routing = _routing_summary(rows)
    versions = {row.get("policy_version") for row in checkpoints if row.get("policy_version")}
    batches = {row.get("latest_batch_id") for row in checkpoints if row.get("latest_batch_id")}
    refresh_observed = len(versions) > 1 or len(batches) > 1 or any(
        row.get("refresh_observed") is True for row in checkpoints
    )
    models = {row.selected_model for row in rows if row.selected_model}
    all_succeeded = bool(rows) and all(
        str(row.run_status).lower() == "success" and str(row.node_status).lower() == "success"
        for row in rows
    )
    cohort_accuracy = float(routing.get("cohort_accuracy_pct") or 0)
    coverage = float(routing.get("route_coverage_pct") or 0)
    criteria_passed = bool(
        all_succeeded
        and cohort_accuracy >= 80
        and coverage >= 25
        and len(models) >= 2
        and refresh_observed
    )
    failure_reasons = Counter(
        row.error_code or "unknown_failure"
        for row in rows
        if str(row.run_status).lower() != "success"
        or str(row.node_status).lower() != "success"
    )
    return {
        "requests": len(rows),
        "success_count": len(rows) - sum(failure_reasons.values()),
        "failure_count": sum(failure_reasons.values()),
        "all_runs_succeeded": all_succeeded,
        "cohort_accuracy_pct": cohort_accuracy,
        "route_coverage_pct": coverage,
        "validated_model_precision_pct": routing.get("validated_model_precision_pct"),
        "high_risk_protection_rate_pct": routing.get("high_risk_protection_rate_pct"),
        "selected_model_count": len(models),
        "models": dict(Counter(row.selected_model or "unknown" for row in rows)),
        "policy_refresh_observed": refresh_observed,
        "cohort_breakdown": _cohort_breakdown(rows),
        "failure_reasons": dict(failure_reasons),
        "criteria_passed": criteria_passed,
    }


def build_report(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    checkpoints = payload["checkpoints"]
    verdict = "통과" if summary["criteria_passed"] else "미통과"
    lines = [
        "# 자동 모델 라우팅 정책 수명주기 실제 Provider 실험",
        "",
        "![정책 수명주기 그래프](routing-lifecycle.png)",
        "",
        "## 결론",
        "",
        f"- 최종 판정: **{verdict}**",
        f"- 실행 성공: **{summary.get('success_count', summary['requests'])}/{summary['requests']}건**",
        f"- 입력군 정확도: **{summary['cohort_accuracy_pct']:.1f}%**",
        f"- 검증 rule 적용 범위: **{summary['route_coverage_pct']:.1f}%**",
        f"- 실제 선택 모델: `{summary['models']}`",
        f"- 자동 정책 갱신 관찰: **{'예' if summary['policy_refresh_observed'] else '아니오'}**",
        "",
        "## 합격 기준",
        "",
        "- 배포 실행 전체 성공",
        "- 입력군 정확도 80% 이상",
        "- 검증된 입력군 rule 적용 범위 25% 이상",
        "- 실제 선택 모델 2개 이상",
        "- 20회 실행 간격의 자동 정책 갱신이 한 번 이상 완료",
        "",
        "## 입력군별 결과",
        "",
        "| 기대 입력군 | 요청 | 정확히 매칭 | 매칭률 | 검증 rule 적용 | 적용률 | 실패 | 실제 모델 | 실제 매칭 결과 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for cohort_key, row in summary.get("cohort_breakdown", {}).items():
        lines.append(
            f"| `{cohort_key}` | {row['requests']} | {row['matched']} | "
            f"{row['match_accuracy_pct']:.1f}% | {row['validated_routes']} | "
            f"{row['validated_route_coverage_pct']:.1f}% | {row['failures']} | "
            f"`{row['models']}` | `{row['matched_as']}` |"
        )
    lines.extend(
        [
            "",
            "## 실행 실패",
            "",
        ]
    )
    failure_reasons = summary.get("failure_reasons") or {}
    if failure_reasons:
        for reason, count in failure_reasons.items():
            lines.append(f"- `{reason}`: {count}건")
    else:
        lines.append("- 실패 없음")
    lines.extend(
        [
            "",
        "## 정책 점검 이력",
        "",
        "| 실행 수 | 정책 버전 | active rule | 누적 검증비 | 최근 결과 | batch trigger/status | 갱신 관찰 |",
        "| ---: | --- | ---: | ---: | --- | --- | --- |",
        ]
    )
    for row in checkpoints:
        lines.append(
            f"| {row['sequence']} | {row.get('policy_version') or '-'} | "
            f"{row.get('active_rule_count') or 0} | ${float(row.get('validation_spend_usd') or 0):.6f} | "
            f"{row.get('last_refresh_result') or '-'} | "
            f"{row.get('latest_batch_trigger') or '-'} / {row.get('latest_batch_status') or '-'} | "
            f"{'예' if row.get('refresh_observed') else '아니오'} |"
        )
    lines.extend(
        [
            "",
            "## 해석 제한",
            "",
            "- 이 실험은 정책이 실제 운영 실행으로 갱신되는지를 검증한다. 세 비교군 경제성은 별도 동결 정책 실험에서 판단한다.",
            "- 합성 입력은 실제 고객 원문을 저장하지 않고 입력군별로 사전에 작성했다.",
            "- 입력 원문, credential, embedding vector는 보고서에 포함하지 않았다.",
            "",
            "## 다음 개선 판단",
            "",
            (
                "- 모든 합격 기준을 충족했다. 다음 단계에서는 이 정책을 동결하고 고가 고정/저가 고정과 경제성을 비교한다."
                if summary["criteria_passed"]
                else "- 합격 기준을 충족하지 못했다. 입력군별 오매칭, 검증 rule 미적용, 실행 실패와 갱신 결과를 원인별로 수정한 뒤 새로운 입력 세트로 다시 검증한다."
            ),
            "- 낮은 비용만으로 합격시키지 않는다. 입력군 정확도와 고위험 요청 보호가 유지되어야 한다.",
            "",
        ]
    )
    return "\n".join(lines)


def execute(args: argparse.Namespace) -> tuple[Path, Path]:
    if not args.confirm_live:
        raise RuntimeError("실제 provider 호출은 --confirm-live를 명시해야 시작됩니다.")
    password = os.getenv(args.password_env)
    if not password:
        raise RuntimeError(f"{args.password_env} 환경변수가 필요합니다.")
    client = ExperimentClient(
        base_url=args.base_url,
        organization_id=args.organization_id,
        email=args.email,
        password=password,
        timeout_seconds=args.timeout_seconds,
    )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_name = args.run_name or f"routing-lifecycle-{stamp}"
    output_dir = args.output_dir / run_name
    state_path = output_dir / "state.json"
    report_path = output_dir / "report.md"
    chart_path = output_dir / "routing-lifecycle.png"
    target = _create_deployed_clone(
        client,
        source_app_id=args.source_app_id,
        name=f"자동 라우팅 정책 수명주기 {stamp}",
        automatic=True,
        model_id=args.high_model_id,
        refresh_every_runs=args.refresh_every_runs,
    )
    policy = _wait_for_bootstrap_policy(
        client,
        workflow_id=target["workflow_id"],
        timeout_seconds=args.bootstrap_timeout_seconds,
    )
    rows: list[Any] = []
    checkpoints = [_policy_checkpoint(sequence=0, policy=policy, rows=[])]
    cases = build_auto_cases(shuffle_seed=args.benchmark_seed)[: args.run_count]
    for sequence, case in enumerate(cases, start=1):
        policy_before_run = client.get_json(_policy_path(target["workflow_id"], DEFAULT_NODE_ID))
        row = _execute_case(
            client,
            target=target,
            case=case,
            sequence=sequence,
            policy=policy_before_run,
            timeout_seconds=args.timeout_seconds,
        )
        rows.append(row)
        print(
            f"[lifecycle {sequence:02d}/{len(cases)}] model={row.selected_model or 'unknown'} "
            f"cohort={row.matched_cohort_key or row.semantic_match_status or 'unknown'}",
            flush=True,
        )
        if sequence % args.refresh_every_runs == 0:
            refreshed, observed = _wait_for_policy_refresh(
                client,
                workflow_id=target["workflow_id"],
                previous_policy=policy_before_run,
                timeout_seconds=args.policy_timeout_seconds,
            )
            checkpoints.append(
                _policy_checkpoint(
                    sequence=sequence,
                    policy=refreshed,
                    rows=rows,
                    refresh_observed=observed,
                )
            )
        _write_json(
            state_path,
            _safe_lifecycle_payload({
                "metadata": {"started_at": datetime.now(timezone.utc).isoformat()},
                "target": target,
                "rows": [asdict(item) for item in rows],
                "checkpoints": checkpoints,
            }),
        )
    final_policy = client.get_json(_policy_path(target["workflow_id"], DEFAULT_NODE_ID))
    summary = _lifecycle_summary(rows=rows, checkpoints=checkpoints)
    payload = {
        "metadata": {
            "run_name": run_name,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "refresh_every_runs": args.refresh_every_runs,
        },
        "target": target,
        "rows": [asdict(item) for item in rows],
        "checkpoints": checkpoints,
        "model_windows": _model_windows(rows),
        "final_policy": final_policy,
        "summary": summary,
    }
    _write_json(state_path, _safe_lifecycle_payload(payload))
    write_lifecycle_chart(chart_path, checkpoints=checkpoints, model_windows=payload["model_windows"])
    report_path.write_text(build_report(payload), encoding="utf-8")
    return state_path, report_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--source-app-id", default="10200000-0000-0000-0000-000000000409")
    parser.add_argument("--organization-id", default=DEFAULT_ORGANIZATION_ID)
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password-env", default=DEFAULT_PASSWORD_ENV)
    parser.add_argument("--high-model-id", default=HIGH_FIXED_MODEL_ID)
    parser.add_argument("--benchmark-seed", type=int, default=381)
    parser.add_argument("--run-count", type=int, default=LIFECYCLE_RUN_COUNT)
    parser.add_argument("--refresh-every-runs", type=int, default=REFRESH_EVERY_RUNS)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--bootstrap-timeout-seconds", type=int, default=1200)
    parser.add_argument("--policy-timeout-seconds", type=int, default=900)
    parser.add_argument("--run-name")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "reports" / "model-routing" / "lifecycle",
    )
    parser.add_argument("--confirm-live", action="store_true")
    args = parser.parse_args()
    try:
        state_path, report_path = execute(args)
        print(f"state={state_path}")
        print(f"report={report_path}")
        return 0
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
