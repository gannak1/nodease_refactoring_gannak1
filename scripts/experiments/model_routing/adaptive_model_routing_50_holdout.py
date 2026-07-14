"""실제 Provider 호출로 적응형 모델 라우팅을 검증하는 재현 가능한 실험.

순서:
1. 기존 policy row와 그 하위 적응형 학습 상태만 초기화한다.
2. 실제 webhook 배포로 40개 discovery 입력을 실행한다.
3. 워커가 후보 모델별 5회 Replay와 LLM Judge를 완료할 때까지 기다린다.
4. 앞 단계에 쓰지 않은 50개 holdout 입력을 실제 배포로 실행한다.

입력/출력 원문, credential, webhook secret, embedding vector는 파일 보고서에 기록하지
않는다. 이 스크립트는 비용이 발생하는 실제 provider 실험이므로 ``--confirm-live`` 없이는
실행되지 않는다.
"""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
import sys
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable

import requests
from sqlalchemy import text


# scripts/experiments/model_routing/ 아래에 두되, imports와 보고서 기본 경로는
# 항상 저장소 루트를 기준으로 계산한다.
ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.shared.db.models.app import App
from apps.shared.db.models.model_routing_cohort import (  # noqa: E402
    LLMNodeModelRoutingCohort,
    LLMNodeModelRoutingModelEvidence,
    LLMNodeModelRoutingValidationBatch,
)
from apps.shared.db.models.model_routing_policy import (  # noqa: E402
    LLMNodeModelRoutingPolicy,
    LLMNodeModelRoutingPolicyUpdate,
)
from apps.shared.db.models.workflow_deployment import WorkflowDeployment  # noqa: E402
from apps.shared.db.session import SessionLocal  # noqa: E402
WORKFLOW_ID = "91000000-0000-0000-0000-000000000002"
DEPLOYMENT_ID = "91000000-0000-0000-0000-000000000003"
ORGANIZATION_ID = "10200000-0000-0000-0000-000000000100"
NODE_ID = "llm-triage"
APP_SLUG = "demo-model-router-ticket-ops"
BASELINE_MODEL_ID = "gpt-4.1"
FALLBACK_MODEL_ID = "gpt-4.1-mini"
ROUTING_ENCODER_MODEL_ID = "text-embedding-3-large"
DISCOVERY_COUNT = 40
HOLDOUT_COUNT = 50


@dataclass(frozen=True)
class ExperimentCase:
    case_id: str
    expected_group: str
    customer_tier: str
    message: str


@dataclass(frozen=True)
class RunObservation:
    case_id: str
    group: str
    phase: str
    workflow_run_id: str | None
    workflow_status: str
    node_status: str | None
    selected_model_id: str | None
    matched_cohort_id: str | None
    matched_rule_id: str | None
    policy_version: str | None
    reason_code: str | None
    fallback_used: bool
    total_cost_usd: float | None


INVOICE_DISCOVERY_MESSAGES = (
    "이번 달 청구서의 회사 정보가 잘못되어 세금계산서를 수정 발행해야 합니다.",
    "결제 영수증의 사업자 번호가 바뀌어 세금계산서를 다시 발급받고 싶습니다.",
    "청구 담당자 이메일 변경 후 세금계산서 수신 주소도 수정해 주세요.",
    "결제 금액과 부가세가 달라서 청구서를 정정 발행해야 합니다.",
    "지난달 청구서를 회계팀 제출용으로 다시 다운로드하고 싶습니다.",
    "법인명 변경으로 이미 발행된 세금계산서의 상호를 고쳐야 합니다.",
    "청구서에 표시된 공급가액이 실제 결제 내역과 달라 재발행이 필요합니다.",
    "세금계산서 PDF를 받지 못해 회계 마감 전에 다시 보내 주세요.",
    "청구서 수신자가 퇴사해서 새 회계 담당자에게 세금계산서를 보내야 합니다.",
    "결제 카드가 바뀐 뒤 영수증의 결제 수단 정보를 확인하고 싶습니다.",
    "사업자등록번호 오기로 발행된 세금계산서를 취소하고 재발행해 주세요.",
    "이번 분기 청구서에 프로젝트 코드가 빠져 있어 정정 문서가 필요합니다.",
    "청구서 발행일을 회계 기준일에 맞춰 조정할 수 있는지 확인해 주세요.",
    "세금계산서 수신 메일이 반송돼 다른 주소로 재발송해야 합니다.",
    "환불 반영 후 청구 금액이 바뀌었는데 수정된 세금계산서를 받고 싶습니다.",
    "해외 법인 명의로 청구서를 발행하려면 어떤 정보를 수정해야 하나요.",
    "청구서의 좌석 수가 실제 계약과 달라 세금계산서 재발행을 요청합니다.",
    "전월 미납 금액이 포함된 청구서를 분리해 다시 발행할 수 있나요.",
    "회계 감사용으로 결제 영수증과 세금계산서를 함께 재발급받고 싶습니다.",
    "세금계산서 발행 상태가 완료인데 파일이 열리지 않아 다시 생성해 주세요.",
)

SLACK_DISCOVERY_MESSAGES = (
    "새 고객 티켓이 지정한 Slack 채널에 전송되지 않아 웹훅 알림을 점검하고 싶습니다.",
    "Slack 채널 알림 카드가 빈 내용으로 표시되어 웹훅 연동 확인이 필요합니다.",
    "webhook URL을 교체한 뒤 Slack 티켓 알림이 멈췄습니다.",
    "Slack 앱 권한을 갱신한 뒤 웹훅 메시지 전송이 실패합니다.",
    "재시도된 티켓 알림이 동일한 Slack 채널에 중복 전송됩니다.",
    "Slack 웹훅이 200 응답을 받지만 실제 채널에는 알림이 보이지 않습니다.",
    "Slack 알림 대상 채널을 변경했는데 새 티켓이 이전 채널로만 전송됩니다.",
    "Slack webhook 서명 검증 오류 때문에 고객 문의 알림이 차단됩니다.",
    "비공개 Slack 채널에 티켓 알림을 보내려면 어떤 권한 설정이 필요한가요.",
    "Slack 메시지 블록 형식 오류로 티켓 알림이 전송되지 않습니다.",
    "Slack 앱을 다시 설치한 뒤 웹훅 연결 테스트가 계속 실패합니다.",
    "특정 업무 시간 이후 Slack 티켓 알림이 지연되어 도착합니다.",
    "Slack 웹훅 토큰을 교체한 뒤 자동 알림이 중단됐습니다.",
    "같은 고객 문의가 Slack 채널에 세 번씩 알림으로 올라옵니다.",
    "Slack 채널 아카이브 후 티켓 알림이 실패한 원인을 알고 싶습니다.",
    "웹훅 알림에는 티켓 제목만 나오고 본문이 누락됩니다.",
    "Slack rate limit 때문에 티켓 알림이 순서대로 전송되지 않습니다.",
    "Slack webhook 연결은 정상인데 멘션 대상 사용자에게 알림이 가지 않습니다.",
    "새 워크스페이스로 Slack 연동을 옮긴 뒤 티켓 알림이 전혀 오지 않습니다.",
    "Slack 알림 실패 시 재시도 횟수와 오류 내역을 확인하고 싶습니다.",
)

INVOICE_HOLDOUT_MESSAGES = (
    "세금계산서에 잘못 들어간 부서명을 수정해서 다시 발행해 주세요.",
    "청구서 수신 주소 변경이 다음 세금계산서에 반영되는지 궁금합니다.",
    "이중 결제된 건의 환불이 반영된 영수증을 새로 받고 싶습니다.",
    "회계 시스템 등록을 위해 지난달 세금계산서를 다시 내려받아야 합니다.",
    "청구 금액의 할인 항목이 누락돼 정정 세금계산서를 요청합니다.",
    "사업자 주소 이전으로 청구서의 회사 주소를 바꿔야 합니다.",
    "세금계산서 발행일이 계약 기간과 달라 수정 가능한지 확인해 주세요.",
    "결제 영수증에 프로젝트 담당자 정보가 표시되도록 재발행할 수 있나요.",
    "청구서 수신 메일을 재무팀 공용 주소로 변경하고 싶습니다.",
    "법인 카드 교체 후 결제 내역이 청구서와 다르게 보입니다.",
    "세금계산서 파일이 손상되어 회계팀에서 다시 보내 달라고 합니다.",
    "중도 해지 후 남은 기간 요금이 반영된 수정 청구서가 필요합니다.",
    "청구서의 사용 기간 표기가 틀려 세금계산서를 정정해야 합니다.",
    "전자세금계산서 수신 여부를 확인할 수 있는 방법을 알려주세요.",
    "분할 결제된 두 건을 하나의 회계 증빙으로 받을 수 있나요.",
    "청구서 번호와 계약 번호를 함께 표기한 재발행 문서가 필요합니다.",
    "다른 법인으로 계약을 이전해 세금계산서 발행 정보를 변경하려고 합니다.",
    "이전 청구서의 결제 통화가 잘못되어 수정 영수증을 요청합니다.",
    "회계 마감 전에 미발송 세금계산서를 다시 보내 주세요.",
    "세금계산서 재발행 요청이 처리됐는지 확인하고 싶습니다.",
)

SLACK_HOLDOUT_MESSAGES = (
    "Slack 티켓 알림이 특정 채널에만 오지 않아 웹훅 설정을 확인하고 싶습니다.",
    "Slack 알림 메시지에 고객 이름이 비어 있어 payload 매핑을 점검해야 합니다.",
    "Slack webhook URL 변경 후에도 이전 채널로 알림이 전송됩니다.",
    "티켓 상태 변경 알림이 Slack에서 두 번씩 표시됩니다.",
    "Slack 앱 권한 부족 오류로 웹훅이 메시지를 올리지 못합니다.",
    "Slack 채널 ID를 바꾼 뒤 고객 문의 알림이 사라졌습니다.",
    "웹훅 재시도 때문에 Slack 알림 순서가 뒤섞여 보입니다.",
    "Slack webhook 테스트 버튼은 성공하지만 실제 티켓은 알림으로 오지 않습니다.",
    "새 Slack 워크스페이스를 연결한 뒤 채널 선택 목록이 비어 있습니다.",
    "Slack 알림 카드의 링크가 잘못된 티켓으로 연결됩니다.",
    "Slack rate limit 발생 후 누락된 티켓 알림을 다시 보내고 싶습니다.",
    "비공개 Slack 채널로 웹훅을 보낼 때 권한 오류가 반복됩니다.",
    "Slack 멘션 알림이 담당자에게 전달되지 않아 확인이 필요합니다.",
    "고객 티켓의 첨부 파일 정보가 Slack 메시지에서 빠집니다.",
    "Slack 웹훅이 시간 초과되어 티켓 알림이 늦게 도착합니다.",
    "Slack 앱 재설치 이후 기존 webhook 연결이 끊어진 것 같습니다.",
    "한 고객 문의가 여러 Slack 채널로 동시에 전송되는 문제를 해결하고 싶습니다.",
    "Slack 알림 메시지 블록이 깨져서 티켓 내용이 읽히지 않습니다.",
    "웹훅 서명 오류 때문에 Slack 연동 로그에 실패가 남습니다.",
    "Slack 티켓 알림을 근무 시간에만 보내도록 설정할 수 있나요.",
)

SAFETY_HOLDOUT_MESSAGES = (
    "SLA 위반 가능성이 있어 고객 보상 여부를 즉시 검토해야 합니다.",
    "고객 개인정보가 권한 없는 사용자에게 노출된 정황이 있습니다.",
    "관리자 계정 탈취가 의심돼 운영 접근을 차단해야 합니다.",
    "결제 API 장애로 다수 고객의 정산이 실패해 긴급 대응이 필요합니다.",
    "법무 검토 전에는 확정 답변을 보내면 안 되는 환불 분쟁입니다.",
    "운영 데이터 유출 가능성이 있어 보안 사고 절차를 시작해야 합니다.",
    "대규모 서비스 중단으로 계약상 SLA 보상 위험이 발생했습니다.",
    "권한 상승 공격 흔적이 있어 민감한 고객 정보를 조사해야 합니다.",
    "규제 기관 보고 기한 전에 개인정보 침해 범위를 확인해야 합니다.",
    "고객 크레딧 보상이 필요한 장애인지 승인 절차를 확인해 주세요.",
)


def _cases(prefix: str, group: str, messages: Iterable[str]) -> list[ExperimentCase]:
    return [
        ExperimentCase(
            case_id=f"{prefix}-{group}-{index:02d}",
            expected_group=group,
            customer_tier="business",
            message=message,
        )
        for index, message in enumerate(messages, start=1)
    ]


def _interleave_discovery_windows() -> tuple[ExperimentCase, ...]:
    """두 review window에 반복 패턴을 각각 10개씩 넣는다.

    자동 발견의 대상은 '고객지원' 같은 넓은 분류가 아니라, 서로 다른 wording에도
    반복되는 세금계산서 재발행과 Slack 웹훅 장애 패턴이다. 각 pattern은 두 window에
    걸쳐 관찰돼야 후보 cohort가 된다.
    """
    invoices = _cases("D", "invoice", INVOICE_DISCOVERY_MESSAGES)
    slack = _cases("D", "slack", SLACK_DISCOVERY_MESSAGES)
    return tuple([*invoices[:10], *slack[:10], *invoices[10:], *slack[10:]])


DISCOVERY_CASES: tuple[ExperimentCase, ...] = _interleave_discovery_windows()

HOLDOUT_CASES: tuple[ExperimentCase, ...] = tuple(
    [
        *_cases("H", "invoice", INVOICE_HOLDOUT_MESSAGES),
        *_cases("H", "slack", SLACK_HOLDOUT_MESSAGES),
        *_cases("H", "safety", SAFETY_HOLDOUT_MESSAGES),
    ]
)

assert len(DISCOVERY_CASES) == DISCOVERY_COUNT
assert len(HOLDOUT_CASES) == HOLDOUT_COUNT


def _reset_adaptive_state() -> None:
    """대상 배포 LLM node의 policy와 하위 adaptive row만 지운다.

    workflow/app/credential/기존 운영 run은 삭제하지 않는다. policy FK의 CASCADE가
    cohort, validation batch, evidence, 월간 예산 row만 함께 지운다.
    """
    with SessionLocal() as db:
        policy = (
            db.query(LLMNodeModelRoutingPolicy)
            .filter(LLMNodeModelRoutingPolicy.workflow_id == uuid.UUID(WORKFLOW_ID))
            .filter(LLMNodeModelRoutingPolicy.deployment_id == uuid.UUID(DEPLOYMENT_ID))
            .filter(LLMNodeModelRoutingPolicy.node_id == NODE_ID)
            .first()
        )
        if policy is not None:
            db.delete(policy)

        deployment = db.get(WorkflowDeployment, uuid.UUID(DEPLOYMENT_ID))
        if deployment is None:
            raise RuntimeError("실험 대상 deployment를 찾지 못했습니다.")
        snapshot = copy.deepcopy(deployment.graph_snapshot or {})
        node = next(
            (
                item
                for item in snapshot.get("nodes", [])
                if isinstance(item, dict) and str(item.get("id")) == NODE_ID
            ),
            None,
        )
        if node is None or not isinstance(node.get("data"), dict):
            raise RuntimeError("실험 대상 LLM node snapshot을 찾지 못했습니다.")
        data = node["data"]
        data["auto_model_routing"] = True
        data["model_id"] = BASELINE_MODEL_ID
        data["fallback_model_id"] = FALLBACK_MODEL_ID
        data["model_routing_policy"] = {
            "refresh": {"refresh_every_runs": 20},
            "validation_budget_usd": 10.0,
        }
        routing_context = data.get("model_routing_context")
        routing_context = routing_context if isinstance(routing_context, dict) else {}
        semantic_router = routing_context.get("semantic_router")
        semantic_router = semantic_router if isinstance(semantic_router, dict) else {}
        # 실제 한국어 고객 문의의 의미상 입력군을 충분히 분리하기 위해 routing만
        # high-resolution encoder를 사용한다. RAG 문서 embedding 모델은 바꾸지 않는다.
        semantic_router["encoder_model_id"] = ROUTING_ENCODER_MODEL_ID
        routing_context["semantic_router"] = semantic_router
        data["model_routing_context"] = routing_context
        deployment.graph_snapshot = snapshot
        db.commit()


def _webhook_secret() -> str:
    with SessionLocal() as db:
        secret = (
            db.query(App.auth_secret)
            .filter(App.url_slug == APP_SLUG)
            .scalar()
        )
    if not secret:
        raise RuntimeError("실험 대상 webhook 인증 정보를 찾지 못했습니다.")
    return str(secret)


def _observation_from_row(row: Any, *, case: ExperimentCase) -> RunObservation:
    output = row["outputs"] if isinstance(row["outputs"], dict) else {}
    trace_root = row["trace_metadata"] if isinstance(row["trace_metadata"], dict) else {}
    trace = trace_root.get("llm") if isinstance(trace_root.get("llm"), dict) else {}
    # WorkflowEngine은 model_routing metadata의 안전한 키만 trace_metadata.llm으로
    # 펼쳐 저장한다. 중첩된 원본 metadata를 기대하면 실제 실행 결과를 놓친다.
    routing = trace
    return RunObservation(
        case_id=case.case_id,
        group=case.expected_group,
        phase="discovery" if case.case_id.startswith("D-") else "holdout",
        workflow_run_id=str(row["id"]),
        workflow_status=str(row["workflow_status"]),
        node_status=str(row["node_status"]) if row["node_status"] is not None else None,
        selected_model_id=str(output.get("model") or routing.get("selected_model") or "") or None,
        matched_cohort_id=str(routing.get("matched_cohort_id") or "") or None,
        matched_rule_id=str(routing.get("matched_rule_id") or "") or None,
        policy_version=str(routing.get("policy_version") or "") or None,
        reason_code=str(routing.get("reason_code") or "") or None,
        fallback_used=bool(routing.get("fallback_used")),
        total_cost_usd=_number(row["total_cost"]),
    )


def _execute_cases(
    cases: Iterable[ExperimentCase],
    *,
    base_url: str,
    experiment_id: str,
    timeout_seconds: int,
    request_batch_size: int,
) -> list[RunObservation]:
    """실제 배포 요청을 제한된 동시성으로 실행하고 terminal node log를 수집한다.

    로컬 Workflow Engine은 gevent worker에서 동기 provider client를 함께 쓸 때
    과도한 동시 호출을 안정적으로 처리하지 못한다. 실험 데이터의 상태 누락을
    막기 위해 기본값은 한 건씩 실행한다.
    """
    cases = list(cases)
    secret = _webhook_secret()
    session = requests.Session()
    if request_batch_size < 1:
        raise ValueError("request_batch_size는 1 이상이어야 합니다.")

    observations: dict[str, RunObservation] = {}
    for offset in range(0, len(cases), request_batch_size):
        batch = cases[offset : offset + request_batch_size]
        # user_input은 trace 정책에 따라 마스킹될 수 있다. 같은 workflow/deployment에
        # 대해 이 batch를 요청하기 직전의 시각도 함께 보관해 ID 마스킹 시 보조
        # 상관관계로 쓴다. 입력/출력 원문은 보관하지 않는다.
        batch_started_after = datetime.now(timezone.utc) - timedelta(seconds=5)
        for case in batch:
            response = session.post(
                f"{base_url.rstrip('/')}/api/v1/hooks/{APP_SLUG}",
                headers={"X-Webhook-Secret": secret},
                json={
                    "message": case.message,
                    "customerTier": case.customer_tier,
                    "adaptiveExperimentId": experiment_id,
                    "adaptiveExperimentCaseId": case.case_id,
                    "adaptiveExperimentPhase": "discovery" if case.case_id.startswith("D-") else "holdout",
                },
                timeout=30,
            )
            if response.status_code not in {200, 202}:
                raise RuntimeError(f"{case.case_id} webhook 요청 실패: HTTP {response.status_code}")

        expected = {case.case_id: case for case in batch}
        deadline = time.monotonic() + timeout_seconds
        completed: dict[str, RunObservation] = {}
        while time.monotonic() < deadline:
            with SessionLocal() as db:
                rows = db.execute(
                    text(
                        """
                        SELECT wr.id, wr.status::text AS workflow_status, wr.total_cost,
                               wr.inputs->>'adaptiveExperimentCaseId' AS case_id,
                               nr.status::text AS node_status, nr.outputs, nr.trace_metadata
                        FROM workflow_runs wr
                        JOIN workflow_node_runs nr
                          ON nr.workflow_run_id=wr.id AND nr.node_id=:node_id
                        WHERE wr.workflow_id=CAST(:workflow_id AS uuid)
                          AND wr.deployment_id=CAST(:deployment_id AS uuid)
                          AND (
                              wr.inputs->>'adaptiveExperimentId'=:experiment_id
                              OR wr.started_at >= :batch_started_after
                          )
                          AND wr.status::text IN ('SUCCESS', 'FAILED')
                          AND nr.status::text IN ('SUCCESS', 'FAILED')
                        ORDER BY wr.started_at ASC
                        """
                    ),
                    {
                        "workflow_id": WORKFLOW_ID,
                        "deployment_id": DEPLOYMENT_ID,
                        "node_id": NODE_ID,
                        "experiment_id": experiment_id,
                        "batch_started_after": batch_started_after,
                    },
                ).mappings().all()
            completed = {
                str(row["case_id"]): _observation_from_row(row, case=expected[str(row["case_id"])])
                for row in rows
                if str(row["case_id"]) in expected
            }
            if len(completed) == len(expected):
                break
            time.sleep(2)
        if len(completed) != len(expected):
            raise TimeoutError(
                f"{len(batch)}개 요청 중 {len(completed)}/{len(batch)}개의 node log를 시간 안에 찾지 못했습니다."
            )
        observations.update(completed)
        for case in batch:
            observation = completed[case.case_id]
            print(
                f"[{observation.phase} {len(observations):02d}/{len(cases):02d}] "
                f"{observation.group} -> {observation.matched_cohort_id or '-'} / "
                f"{observation.selected_model_id or '-'} ({observation.workflow_status})",
                flush=True,
            )
    return [observations[case.case_id] for case in cases]


def _wait_for_refresh_update(*, expected_update_count: int, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            policy = (
                db.query(LLMNodeModelRoutingPolicy)
                .filter(LLMNodeModelRoutingPolicy.workflow_id == uuid.UUID(WORKFLOW_ID))
                .filter(LLMNodeModelRoutingPolicy.deployment_id == uuid.UUID(DEPLOYMENT_ID))
                .filter(LLMNodeModelRoutingPolicy.node_id == NODE_ID)
                .first()
            )
            update_count = (
                db.query(LLMNodeModelRoutingPolicyUpdate)
                .filter(LLMNodeModelRoutingPolicyUpdate.policy_id == policy.id)
                .count()
                if policy is not None
                else 0
            )
        if update_count >= expected_update_count:
            return
        time.sleep(3)
    raise TimeoutError(f"정책 갱신 {expected_update_count}회를 기다리다 시간 초과했습니다.")


def _wait_for_validation_activation(*, timeout_seconds: int) -> dict[str, Any]:
    """첫 또는 후속 검증 batch가 실제 adaptive rule을 활성화할 때까지 기다린다.

    첫 20건에서 이미 두 입력군이 발견되면 그 시점의 batch가 활성화를 끝낼 수 있다.
    따라서 "새 batch"만 기다리면 정상 활성화 결과를 놓친다. 반대로 batch가 단순히
    완료된 것만으로는 충분하지 않으므로 validated evidence와 active adaptive rule을
    모두 확인한다.
    """
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = _adaptive_state()
        batch = last.get("latest_batch") or {}
        if (
            batch.get("status") == "completed"
            and any(item.get("status") == "validated" for item in last.get("evidence") or [])
            and any(
                rule.get("reason_code") == "validated_adaptive_cohort"
                for rule in ((last.get("policy") or {}).get("active_rules") or [])
            )
        ):
            return last
        time.sleep(5)
    raise TimeoutError(
        "후보 모델 Replay/Judge 검증 뒤 active adaptive rule이 시간 안에 생성되지 않았습니다. "
        f"마지막 정책: {last.get('policy')}, batch: {last.get('latest_batch')}"
    )


def _adaptive_state() -> dict[str, Any]:
    with SessionLocal() as db:
        policy = (
            db.query(LLMNodeModelRoutingPolicy)
            .filter(LLMNodeModelRoutingPolicy.workflow_id == uuid.UUID(WORKFLOW_ID))
            .filter(LLMNodeModelRoutingPolicy.deployment_id == uuid.UUID(DEPLOYMENT_ID))
            .filter(LLMNodeModelRoutingPolicy.node_id == NODE_ID)
            .first()
        )
        if policy is None:
            return {"policy": None, "cohorts": [], "evidence": [], "latest_batch": None}
        cohorts = (
            db.query(LLMNodeModelRoutingCohort)
            .filter(LLMNodeModelRoutingCohort.policy_id == policy.id)
            .order_by(LLMNodeModelRoutingCohort.created_at.asc())
            .all()
        )
        evidence = (
            db.query(LLMNodeModelRoutingModelEvidence)
            .join(LLMNodeModelRoutingCohort, LLMNodeModelRoutingCohort.id == LLMNodeModelRoutingModelEvidence.cohort_id)
            .filter(LLMNodeModelRoutingCohort.policy_id == policy.id)
            .order_by(LLMNodeModelRoutingModelEvidence.created_at.asc())
            .all()
        )
        batch = (
            db.query(LLMNodeModelRoutingValidationBatch)
            .filter(LLMNodeModelRoutingValidationBatch.policy_id == policy.id)
            .order_by(LLMNodeModelRoutingValidationBatch.created_at.desc())
            .first()
        )
        return {
            "policy": {
                "id": str(policy.id),
                "status": policy.status,
                "version": policy.policy_version,
                "last_refresh_result": policy.last_refresh_result,
                "refresh_every_runs": policy.refresh_every_runs,
                "validation_budget_usd": _number(policy.validation_budget_usd),
                "active_rule_count": len((policy.active_policy or {}).get("rules") or []),
                "active_default_model": (policy.active_policy or {}).get("default_model_id"),
                "active_rules": _safe_active_rules(policy.active_policy),
            },
            "cohorts": [
                {
                    "key": str(row.cohort_key),
                    "label": str(row.label),
                    "status": str(row.status),
                    "observation_count": int(row.observation_count or 0),
                    "review_window_count": int(row.review_window_count or 0),
                    "safety_protected": bool(row.safety_protected),
                }
                for row in cohorts
            ],
            "evidence": [
                {
                    "cohort_id": str(row.cohort_id),
                    "model_id": str(row.model_id),
                    "status": str(row.status),
                    "sample_count": int(row.sample_count or 0),
                    "reason_code": (row.quality_summary or {}).get("reason_code"),
                    "quality_summary": _safe_evidence_summary(row.quality_summary),
                    "efficiency_summary": _safe_evidence_summary(row.efficiency_summary),
                }
                for row in evidence
            ],
            "latest_batch": (
                {
                    "id": str(batch.id),
                    "status": str(batch.status),
                    "trigger": str(batch.trigger),
                    "total_items": int(batch.total_items or 0),
                    "completed_items": int(batch.completed_items or 0),
                    "reserved_cost_usd": _number(batch.reserved_cost),
                    "spent_cost_usd": _number(batch.spent_cost),
                    "summary": batch.error_summary or {},
                }
                if batch is not None
                else None
            ),
        }


def _safe_evidence_summary(summary: Any) -> dict[str, float | int | None]:
    """보고서에 필요한 수치만 보관한다. 원문 output, trace는 포함하지 않는다."""
    source = summary if isinstance(summary, dict) else {}
    allowed = (
        "success_rate",
        "schema_pass_rate",
        "downstream_pass_rate",
        "quality_delta_average",
        "quality_score_average",
        "quality_score_lower_bound",
        "quality_confidence_average",
        "fallback_rate",
        "candidate_cost_average",
        "baseline_cost_average",
        "net_savings_per_request",
        "net_savings_ratio",
        "candidate_latency_ms_average",
        "baseline_latency_ms_average",
    )
    return {key: _number(source.get(key)) for key in allowed if key in source}


def _safe_active_rules(active_policy: Any) -> list[dict[str, str | int | None]]:
    """저장된 정책에서 라우팅 결정에 필요한 식별자만 보고한다."""
    policy = active_policy if isinstance(active_policy, dict) else {}
    rules: list[dict[str, str | int | None]] = []
    for rule in policy.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        when = rule.get("when") if isinstance(rule.get("when"), dict) else {}
        rules.append(
            {
                "cohort_id": str(when.get("semantic_cohort_id") or "") or None,
                "selected_model_id": str(rule.get("selected_model_id") or "") or None,
                "fallback_model_id": str(rule.get("fallback_model_id") or "") or None,
                "reason_code": str(rule.get("reason_code") or "") or None,
                "priority": int(rule.get("priority")) if isinstance(rule.get("priority"), int) else None,
            }
        )
    return rules


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metrics(observations: list[RunObservation], state: dict[str, Any]) -> dict[str, Any]:
    total = len(observations)
    by_group: dict[str, list[RunObservation]] = defaultdict(list)
    for row in observations:
        by_group[row.group].append(row)
    group_summary = {}
    for group, rows in sorted(by_group.items()):
        matched = [row.matched_cohort_id for row in rows if row.matched_cohort_id]
        group_summary[group] = {
            "runs": len(rows),
            "success": sum(row.workflow_status.lower() == "success" for row in rows),
            "dominant_cohort": Counter(matched).most_common(1)[0][0] if matched else None,
            "cohort_match_rate": len(matched) / len(rows) if rows else 0,
            "models": dict(Counter(row.selected_model_id or "unknown" for row in rows)),
            "fallback_count": sum(row.fallback_used for row in rows),
        }
    selected_models = sorted({row.selected_model_id for row in observations if row.selected_model_id})
    safety_rows = by_group.get("safety", [])
    safety_matches = sum(row.matched_cohort_id == "high_risk" for row in safety_rows)
    return {
        "holdout_count": total,
        "successful_runs": sum(row.workflow_status.lower() == "success" for row in observations),
        "selected_models": selected_models,
        "unique_model_count": len(selected_models),
        "trace_selected_model_present": sum(bool(row.selected_model_id and row.policy_version) for row in observations),
        "safety_route_recall": safety_matches / len(safety_rows) if safety_rows else 0,
        "group_summary": group_summary,
        "policy": state.get("policy"),
    }


def _write_report(
    *,
    output_dir: pathlib.Path,
    experiment_id: str,
    discovery: list[RunObservation],
    holdout: list[RunObservation],
    activation_state: dict[str, Any],
    final_state: dict[str, Any],
) -> tuple[pathlib.Path, pathlib.Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics = _metrics(holdout, final_state)
    payload = {
        "experiment_id": experiment_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "discovery_deployed_calls": len(discovery),
            "candidate_replay_per_model_and_cohort": 5,
            "holdout_deployed_calls": len(holdout),
            "input_or_output_raw_data_stored": False,
        },
        "activation_validation_state": activation_state,
        "final_state": final_state,
        "holdout_metrics": metrics,
        "discovery_runs": [asdict(row) for row in discovery],
        "holdout_runs": [asdict(row) for row in holdout],
    }
    json_path = output_dir / f"{experiment_id}.json"
    markdown_path = output_dir / f"{experiment_id}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 적응형 모델 라우팅 실제 Provider 실험 보고서",
        "",
        f"- 실험 ID: `{experiment_id}`",
        f"- 생성 시각(UTC): `{payload['generated_at']}`",
        "- 입력/출력 원문, webhook secret, credential, embedding vector는 보고서에 저장하지 않았습니다.",
        "- 흐름: 실제 배포 40건으로 입력군 발견 → 후보별 실제 Replay 5회와 LLM Judge → 검증 통과 규칙 활성화 → 새 50건 holdout 실제 배포 실행",
        "",
        "## 검증 상태",
        "",
        f"- 활성화 직후 Policy: `{(activation_state.get('policy') or {}).get('status', '-')}` / 버전 `{(activation_state.get('policy') or {}).get('version', '-')}`",
        f"- 활성화 검증 batch: `{(activation_state.get('latest_batch') or {}).get('status', '-')}` / 완료 `{(activation_state.get('latest_batch') or {}).get('completed_items', 0)}/{(activation_state.get('latest_batch') or {}).get('total_items', 0)}`",
        f"- Holdout 종료 시 Policy: `{(final_state.get('policy') or {}).get('status', '-')}` / 버전 `{(final_state.get('policy') or {}).get('version', '-')}`",
        "",
        "### 발견된 입력군",
        "",
        "| 입력군 키 | 상태 | 관찰 수 | 검토 창 수 | 안전 보호 |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for cohort in activation_state.get("cohorts", []):
        lines.append(
            f"| {cohort['key']} | {cohort['status']} | {cohort['observation_count']} | "
            f"{cohort['review_window_count']} | {'예' if cohort['safety_protected'] else '아니오'} |"
        )
    lines += [
        "",
        "### 후보 모델 Replay 증거",
        "",
        "| 입력군 | 후보 모델 | 상태 | 표본 | Schema | 후속 노드 | 평균 품질 | 품질 하한 | 품질 차이 | 신뢰도 | 평균 후보 비용 | 순절감률 | 결과 코드 |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for evidence in activation_state.get("evidence", []):
        quality = evidence.get("quality_summary") or {}
        efficiency = evidence.get("efficiency_summary") or {}
        lines.append(
            f"| {evidence['cohort_id']} | {evidence['model_id']} | {evidence['status']} | "
            f"{evidence['sample_count']} | {quality.get('schema_pass_rate') if quality.get('schema_pass_rate') is not None else '-'} | "
            f"{quality.get('downstream_pass_rate') if quality.get('downstream_pass_rate') is not None else '-'} | "
            f"{quality.get('quality_score_average') if quality.get('quality_score_average') is not None else '-'} | "
            f"{quality.get('quality_score_lower_bound') if quality.get('quality_score_lower_bound') is not None else '-'} | "
            f"{quality.get('quality_delta_average') if quality.get('quality_delta_average') is not None else '-'} | "
            f"{quality.get('quality_confidence_average') if quality.get('quality_confidence_average') is not None else '-'} | "
            f"{efficiency.get('candidate_cost_average') if efficiency.get('candidate_cost_average') is not None else '-'} | "
            f"{efficiency.get('net_savings_ratio') if efficiency.get('net_savings_ratio') is not None else '-'} | "
            f"{evidence.get('reason_code') or '-'} |"
        )
    lines += [
        "",
        "### 활성 정책 규칙",
        "",
        "| 입력군 | 선택 모델 | Fallback 모델 | 우선순위 | 근거 코드 |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for rule in ((activation_state.get("policy") or {}).get("active_rules") or []):
        lines.append(
            f"| {rule.get('cohort_id') or '기본값'} | {rule.get('selected_model_id') or '-'} | "
            f"{rule.get('fallback_model_id') or '-'} | {rule.get('priority') or '-'} | "
            f"{rule.get('reason_code') or '-'} |"
        )
    lines += [
        "",
        "## 최종 Holdout 50건",
        "",
        f"- 성공: **{metrics['successful_runs']}/{metrics['holdout_count']}**",
        f"- 서로 다른 선택 모델: **{metrics['unique_model_count']}개** (`{', '.join(metrics['selected_models']) or '-'}`)",
        f"- 실행 trace에 선택 모델과 policy version이 있는 run: **{metrics['trace_selected_model_present']}/{metrics['holdout_count']}**",
        f"- 고위험 안전 route recall: **{metrics['safety_route_recall']:.1%}**",
        "",
        "| 기대 입력군 | 실행 | 성공 | dominant cohort | cohort 매칭률 | 실제 모델 분포 | fallback |",
        "| --- | ---: | ---: | --- | ---: | --- | ---: |",
    ]
    for group, summary in metrics["group_summary"].items():
        model_text = ", ".join(f"{model}:{count}" for model, count in summary["models"].items())
        lines.append(
            f"| {group} | {summary['runs']} | {summary['success']} | "
            f"{summary['dominant_cohort'] or '-'} | {summary['cohort_match_rate']:.1%} | "
            f"{model_text or '-'} | {summary['fallback_count']} |"
        )
    lines += [
        "",
        "## 판정 방법",
        "",
        "- 후보 모델은 실제 실행 주체가 사용할 수 있는 모델만 계획에 들어갑니다.",
        "- 후보 하나는 입력군별로 서로 다른 운영 입력 5개를 실제 Replay합니다.",
        "- Schema, 후속 변수 계약, LLM Judge 품질의 95% 보수 하한(70점 이상), 평균 품질 변화(-5점 이내), fallback, 비용/지연, 순절감률(10% 이상) gate를 모두 통과해야 활성 rule이 됩니다.",
        "- 고위험 route는 policy에 저장된 `safety_override`로 보존하고 저비용 후보 자동 검증 대상에서 제외합니다.",
        "- 최종 50건은 discovery와 Replay에서 사용하지 않은 입력만 사용했습니다.",
        "",
        "## Run 요약",
        "",
        "| phase | case | group | workflow | cohort | rule | model | policy | fallback | 비용 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: |",
    ]
    for row in [*discovery, *holdout]:
        lines.append(
            f"| {row.phase} | {row.case_id} | {row.group} | {row.workflow_status} | "
            f"{row.matched_cohort_id or '-'} | {row.matched_rule_id or '-'} | "
            f"{row.selected_model_id or '-'} | {row.policy_version or '-'} | "
            f"{'예' if row.fallback_used else '아니오'} | "
            f"{row.total_cost_usd if row.total_cost_usd is not None else '-'} |"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--validation-timeout-seconds", type=int, default=1800)
    parser.add_argument(
        "--request-batch-size",
        type=int,
        default=1,
        help="동시에 webhook으로 보낼 최대 요청 수. 실제 Provider 실험은 1을 권장합니다.",
    )
    parser.add_argument("--output-dir", type=pathlib.Path, default=ROOT / "reports" / "model-routing")
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--reset-adaptive-state", action="store_true")
    args = parser.parse_args()
    if not args.confirm_live:
        parser.error("실제 provider 비용이 발생합니다. --confirm-live를 명시하세요.")
    if not args.reset_adaptive_state:
        parser.error("재현 가능한 검증에는 --reset-adaptive-state가 필요합니다.")

    # 숫자로만 이어진 시간 문자열은 trace redaction 정책에서 전화번호/식별자처럼
    # 처리될 수 있다. UUID hex는 실험 상관관계용 불투명 식별자이며 입력 원문이 아니다.
    experiment_id = "adaptive-routing-run-" + uuid.uuid4().hex
    print("실제 provider 모델 라우팅 실험을 시작합니다. 입력/출력 원문은 보고서에 저장하지 않습니다.")
    _reset_adaptive_state()
    # 정책 갱신 기준이 20회이므로 첫 review window를 끝낸 뒤 갱신 task가
    # 실제로 생성되는지 확인한다. 이어지는 20건은 갱신 이후 정책과 후보
    # 검증 흐름을 관찰하기 위한 별도 window다.
    discovery = _execute_cases(
        DISCOVERY_CASES[:20],
        base_url=args.base_url,
        experiment_id=experiment_id,
        timeout_seconds=args.timeout_seconds,
        request_batch_size=args.request_batch_size,
    )
    _wait_for_refresh_update(expected_update_count=1, timeout_seconds=args.validation_timeout_seconds)
    discovery.extend(
        _execute_cases(
            DISCOVERY_CASES[20:],
            base_url=args.base_url,
            experiment_id=experiment_id,
            timeout_seconds=args.timeout_seconds,
            request_batch_size=args.request_batch_size,
        )
    )
    activation_state = _wait_for_validation_activation(
        timeout_seconds=args.validation_timeout_seconds,
    )
    if (activation_state.get("latest_batch") or {}).get("status") != "completed":
        raise RuntimeError(f"후보 검증이 완료되지 않았습니다: {activation_state}")
    holdout = _execute_cases(
        HOLDOUT_CASES,
        base_url=args.base_url,
        experiment_id=experiment_id,
        timeout_seconds=args.timeout_seconds,
        request_batch_size=args.request_batch_size,
    )
    json_path, markdown_path = _write_report(
        output_dir=args.output_dir,
        experiment_id=experiment_id,
        discovery=discovery,
        holdout=holdout,
        activation_state=activation_state,
        final_state=_adaptive_state(),
    )
    print(f"json_report={json_path}")
    print(f"markdown_report={markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
