"""Judge-first 자동 모델 라우팅의 80회 경제성 실험.

같은 enterprise ticket workflow의 LLM 노드를 세 방식으로 실제 실행한다.

* ``automatic``: 배포된 ``judge_bootstrap_incremental_v1`` 정책을 사용한다.
* ``high_fixed``: 고가 모델 ``gpt-5.4``를 고정한다.
* ``low_fixed``: 저가 모델 ``gpt-4o-mini``를 고정한다.

모든 실행은 실제 ``WorkflowEngine``과 provider credential을 사용한다. 품질은
실행 모델이 아닌 별도 Judge가 익명화된 세 출력을 한 번에 평가한다. 품질 Judge
비용은 제품 운영비가 아니라 실험 측정 비용으로 분리해 보고한다.

기본 모드는 provider를 호출하지 않는 ``--dry-run``이다. 실제 비용이 발생하는
실험은 반드시 ``--execute``를 붙여야 한다.
"""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
import random
import statistics
import sys
import time
import uuid
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

ROOT = pathlib.Path(__file__).resolve().parents[1]
PARENT_OF_ROOT = ROOT.parent
for path in (ROOT, PARENT_OF_ROOT):
    if str(path) not in sys.path:
        sys.path.append(str(path))

from apps.log_system import tasks as log_tasks
from apps.shared.celery_app import celery_app
from apps.shared.db.models.app import App
from apps.shared.db.models.llm import LLMModel, LLMUsageLog
from apps.shared.db.models.model_routing_policy import LLMNodeModelRoutingPolicy
from apps.shared.db.models.workflow import Workflow
from apps.shared.db.models.workflow_deployment import DeploymentType, WorkflowDeployment
from apps.shared.db.models.workflow_run import WorkflowNodeRun
from apps.shared.db.session import SessionLocal
from apps.workflow_engine.services.llm_service import (
    LLMCredentialNotAvailableError,
    LLMService,
)
from apps.workflow_engine.services.model_routing_policy_store import (
    ModelRoutingPolicyStore,
)
from apps.workflow_engine.workflow.core.workflow_engine import WorkflowEngine
from scripts.model_routing_benchmark_cases_v22 import V22_HOLDOUT_CASE_POOLS
from scripts.verify_model_router_demo import _ticket_ops_graph


ORG_ID = uuid.UUID("10200000-0000-0000-0000-000000000100")
USER_ID = uuid.UUID("10200000-0000-0000-0000-000000000001")
APP_ID = uuid.UUID("98000000-0000-0000-0000-000000000001")
WORKFLOW_ID = uuid.UUID("98000000-0000-0000-0000-000000000002")
AUTO_DEPLOYMENT_ID = uuid.UUID("98000000-0000-0000-0000-000000000003")
HIGH_DEPLOYMENT_ID = uuid.UUID("98000000-0000-0000-0000-000000000004")
LOW_DEPLOYMENT_ID = uuid.UUID("98000000-0000-0000-0000-000000000005")
NAMESPACE = uuid.UUID("98000000-0000-0000-0000-000000000100")
NODE_ID = "llm-triage"

AUTO_ARM = "automatic"
HIGH_ARM = "high_fixed"
LOW_ARM = "low_fixed"
ARMS = (AUTO_ARM, HIGH_ARM, LOW_ARM)
HIGH_MODEL = "gpt-5.4"
LOW_MODEL = "gpt-4o-mini"
ROUTING_JUDGE_MODEL = "gpt-5-mini"
LOCAL_CONFIDENCE_THRESHOLD = 0.78


@dataclass(frozen=True)
class ExperimentCase:
    case_id: str
    category: str
    expected_difficulty: str
    customer_tier: str
    message: str


@dataclass
class ArmResult:
    arm: str
    selected_model: str | None
    task_cost_usd: float
    task_latency_ms: int | None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    output_text: str
    schema_pass: bool
    workflow_success: bool
    error: str | None
    routing: dict[str, Any]
    routing_judge_cost_usd: float = 0.0
    routing_judge_tokens: int = 0
    routing_judge_latency_ms: int | None = None


EXTRA_CASES: tuple[tuple[str, str, str, str], ...] = (
    ("service_reliability", "balanced", "enterprise", "배포 직후 일부 고객만 주문 조회 API에서 502를 받고 있습니다. 최근 설정 변경과 지역별 트래픽 차이를 함께 확인해 우선 조치를 정리해 주세요."),
    ("service_reliability", "advanced", "enterprise", "결제 승인 지연과 메시지 큐 적체가 동시에 발생했습니다. 데이터 정합성을 훼손하지 않는 복구 순서와 고객 공지 초안을 제안해 주세요."),
    ("service_reliability", "balanced", "business", "주간 백업은 성공으로 표시됐지만 복구 점검 결과 일부 첨부 파일이 누락됐습니다. 영향 범위를 확인하기 위한 절차가 필요합니다."),
    ("service_reliability", "advanced", "enterprise", "두 리전에 걸친 장애 때문에 SLA 위반 가능성이 있습니다. 보상 승인 전에 반드시 확인해야 할 사실과 임시 고객 안내를 분리해 주세요."),
    ("data_governance", "advanced", "enterprise", "삭제 요청을 받은 고객의 데이터가 분석용 집계와 백업 보존 정책에 동시에 남아 있습니다. 법무 검토가 필요한 지점과 처리 순서를 정리해 주세요."),
    ("data_governance", "balanced", "business", "새로운 데이터 보존 기간 정책이 적용됐는데 기존 보고서 다운로드가 가능한지 운영팀이 문의했습니다. 확인할 항목을 안내해 주세요."),
    ("data_governance", "advanced", "enterprise", "외부 분석 도구에 전송되는 이벤트에서 식별자 일부가 가명 처리되지 않은 정황이 있습니다. 즉시 차단 여부와 조사 계획을 제시해 주세요."),
    ("data_governance", "balanced", "business", "월간 사용량 CSV를 내려받을 때 팀별 합계와 전체 합계가 다릅니다. 고객 답변 전에 확인할 데이터 검증 절차를 알려 주세요."),
    ("contract_compliance", "advanced", "enterprise", "계약서에는 EU 내 처리만 허용돼 있는데 지원 요청 해결을 위해 미국 리전 로그를 조회해야 할 수 있습니다. 가능한 대응 범위와 승인 필요 여부를 판단해 주세요."),
    ("contract_compliance", "advanced", "enterprise", "고객이 사고 보상과 서비스 크레딧을 동시에 요구했습니다. 원인 확정 전 약속하면 안 되는 표현을 피하면서 회신 초안을 작성해 주세요."),
    ("contract_compliance", "balanced", "business", "계약 갱신일이 다가오는데 현재 사용량이 약정 한도를 넘었는지 어디에서 확인하는지 안내해 주세요."),
    ("contract_compliance", "advanced", "enterprise", "개인정보 처리 위탁사 변경과 관련해 고객별 동의 상태가 다릅니다. 일괄 전환 전에 어떤 위험을 검토해야 하는지 정리해 주세요."),
    ("analytics_reporting", "balanced", "business", "경영 대시보드의 이번 달 활성 사용자 수가 지난주 보고서보다 작습니다. 지표 정의 변경 여부를 먼저 확인하는 점검 순서를 알려 주세요."),
    ("analytics_reporting", "advanced", "enterprise", "분기별 매출 분석에서 환불·크레딧·환율 조정이 서로 다른 기준일로 반영된 것 같습니다. 숫자를 확정하기 전 검증 계획을 작성해 주세요."),
    ("analytics_reporting", "balanced", "business", "팀장이 이번 주 실행 실패율만 빠르게 확인하고 싶어 합니다. 화면에서 확인할 위치와 해석 방법을 짧게 안내해 주세요."),
    ("analytics_reporting", "advanced", "enterprise", "보안 감사용 보고서에 접근 권한 변경, credential 사용, 배포 이력을 하나의 타임라인으로 제출해야 합니다. 누락 위험이 큰 항목을 우선순위로 정리해 주세요."),
    ("integration_support", "balanced", "business", "웹훅 요청은 200을 받았는데 후속 워크플로우가 실행되지 않습니다. 고객에게 요청할 재현 정보와 내부 확인 순서를 안내해 주세요."),
    ("integration_support", "advanced", "enterprise", "파트너 연동이 중복 결제를 유발했을 가능성이 있습니다. 재시도 로그, idempotency key, 정산 상태를 어떤 순서로 조사해야 하는지 작성해 주세요."),
    ("integration_support", "balanced", "business", "Slack 알림은 오는데 담당자 멘션이 빠집니다. 사용자가 바로 확인할 수 있는 설정 항목을 간단히 설명해 주세요."),
    ("integration_support", "advanced", "enterprise", "서로 다른 고객사의 OAuth 연결이 같은 서비스 계정을 공유한 정황이 있습니다. 토큰 회수와 서비스 영향 최소화를 함께 고려한 조치안을 제시해 주세요."),
    ("product_guidance", "economy", "startup", "내 모듈 목록에서 내가 수정 가능한 워크플로우만 보고 싶습니다. 가장 짧은 안내 문장으로 답해 주세요."),
    ("product_guidance", "economy", "business", "테스트 실행 결과에서 비용이 어디에 표시되는지 알려 주세요."),
    ("product_guidance", "economy", "startup", "지식 베이스 문서 업로드가 끝난 뒤 상태를 확인하는 방법이 궁금합니다."),
    ("product_guidance", "economy", "business", "배포된 모듈의 URL을 팀원에게 전달하려면 어디에서 복사하나요?"),
    ("product_guidance", "economy", "startup", "워크플로우 캔버스 확대 비율을 기본값으로 되돌리는 방법만 알려 주세요."),
    ("product_guidance", "economy", "business", "사용하지 않는 초안 워크플로우를 삭제하기 전에 확인할 점이 있나요?"),
    ("product_guidance", "economy", "startup", "실행 로그에서 성공한 결과만 필터링하는 메뉴가 어디인지 알려 주세요."),
    ("product_guidance", "economy", "business", "LLM credential 동기화 상태가 실패로 보일 때 가장 먼저 무엇을 확인하나요?"),
    ("risk_triage", "advanced", "enterprise", "의심스러운 파일이 지식 베이스에 업로드된 뒤 여러 워크플로우가 해당 문서를 참조했습니다. 실행 중지 여부, 영향 범위, 고객 공지를 동시에 결정해야 합니다."),
    ("risk_triage", "advanced", "enterprise", "한 고객의 데이터 삭제 요청과 법적 보존 명령이 충돌합니다. 자동 삭제를 중단해야 하는지와 담당 부서 승인 흐름을 정리해 주세요."),
    ("risk_triage", "balanced", "business", "계정 권한 변경 요청이 들어왔지만 요청자가 팀 리더인지 확인되지 않습니다. 필요한 확인 정보와 보류 안내를 작성해 주세요."),
    ("risk_triage", "advanced", "enterprise", "생산 환경에서 비정상적으로 많은 API 키가 발급됐고 같은 시간대에 대량 데이터 다운로드도 있었습니다. 즉시 대응과 증거 보존을 구분해 주세요."),
)


def build_cases() -> list[ExperimentCase]:
    """80개 고정 데이터셋을 만들고 순서만 재현 가능하게 섞는다."""

    pool_specs = (
        ("routine_usage_guidance", "economy"),
        ("account_access_request", "balanced"),
        ("finance_closing_approval", "advanced"),
        ("security_privacy_incident", "advanced"),
    )
    cases: list[ExperimentCase] = []
    for category, difficulty in pool_specs:
        for message, _team, role in V22_HOLDOUT_CASE_POOLS[category]:
            cases.append(
                ExperimentCase(
                    case_id=f"{category}-{len(cases) + 1:02d}",
                    category=category,
                    expected_difficulty=difficulty,
                    customer_tier=("enterprise" if difficulty == "advanced" else "business"),
                    message=message,
                )
            )
    for category, difficulty, customer_tier, message in EXTRA_CASES:
        cases.append(
            ExperimentCase(
                case_id=f"{category}-{len(cases) + 1:02d}",
                category=category,
                expected_difficulty=difficulty,
                customer_tier=customer_tier,
                message=message,
            )
        )
    if len(cases) != 80:
        raise AssertionError(f"expected 80 cases, got {len(cases)}")
    random.Random(20260717).shuffle(cases)
    return cases


def _json_from_text(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        start = str(text or "").find("{")
        end = str(text or "").rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            parsed = json.loads(str(text)[start : end + 1])
        except json.JSONDecodeError:
            return {}
    return parsed if isinstance(parsed, dict) else {}


def _usage(row: LLMUsageLog | None) -> tuple[int, int, int, float, int | None]:
    if row is None:
        return 0, 0, 0, 0.0, None
    prompt_tokens = int(row.prompt_tokens or 0)
    completion_tokens = int(row.completion_tokens or 0)
    return (
        prompt_tokens,
        completion_tokens,
        prompt_tokens + completion_tokens,
        float(row.total_cost or 0),
        int(row.latency_ms) if row.latency_ms is not None else None,
    )


def _schema_pass(text: str) -> bool:
    payload = _json_from_text(text)
    return (
        isinstance(payload.get("분류"), str)
        and isinstance(payload.get("우선순위"), str)
        and isinstance(payload.get("승인필요"), bool)
        and isinstance(payload.get("대응계획"), list)
        and isinstance(payload.get("답변초안"), str)
    )


def _node_data(*, auto_routing: bool, model_id: str, fallback_model_id: str | None) -> dict[str, Any]:
    return {
        "provider": "openai",
        "model_id": model_id,
        "fallback_model_id": fallback_model_id,
        "auto_model_routing": auto_routing,
        "model_routing_policy": {
            # 이번 실험은 정책 refresh가 아니라 Judge label을 받은 local router의
            # 전환 시점을 측정한다. 80회 안에 별도 refresh가 정책을 교체하지 않도록
            # refresh 주기를 실험 범위 밖으로 둔다.
            "refresh": {"refresh_every_runs": 100},
        },
        "system_prompt": (
            "당신은 기업용 AI 워크플로우의 요청 처리 노드입니다. 고객 또는 내부 운영 요청을 "
            "분류하고 위험도와 승인 필요 여부를 판단하세요. 반드시 JSON object 하나만 반환하세요. "
            "필수 필드는 분류(string), 우선순위(low|medium|high|critical), 승인필요(boolean), "
            "대응계획(string 배열), 답변초안(string)입니다. 보안, 개인정보, 보상, 법무, 결제, "
            "장애는 사실이 불명확하면 보수적으로 설명하되 근거 없는 확정 약속은 하지 마세요."
        ),
        "user_prompt": "고객 등급: {{ customerTier }}\n요청: {{ message }}",
        "referenced_variables": [
            {"name": "customerTier", "value_selector": ["webhook-ticket", "customerTier"]},
            {"name": "message", "value_selector": ["webhook-ticket", "message"]},
        ],
        "knowledgeBases": [],
        "parameters": {
            "temperature": 0,
            # gpt-5.4 계열은 reasoning token도 출력 한도에 포함한다. 420은
            # 실제 JSON을 만들기 전에 incomplete가 될 수 있어 모든 arm에 같은
            # 충분한 상한을 준다. 짧은 응답은 모델이 스스로 일찍 끝낸다.
            "max_tokens": 1400,
            "response_format": {"type": "json_object"},
        },
        "output_format": {
            "type": "json",
            "schema": {
                "type": "object",
                "required": ["분류", "우선순위", "승인필요", "대응계획", "답변초안"],
            },
        },
    }


def graph_for_arm(arm: str) -> dict[str, Any]:
    graph = copy.deepcopy(_ticket_ops_graph())
    for node in graph["nodes"]:
        if node["id"] == NODE_ID:
            if arm == AUTO_ARM:
                node["data"].update(
                    _node_data(
                        auto_routing=True,
                        model_id=ROUTING_JUDGE_MODEL,
                        fallback_model_id="gpt-4.1",
                    )
                )
            elif arm == HIGH_ARM:
                node["data"].update(
                    _node_data(auto_routing=False, model_id=HIGH_MODEL, fallback_model_id=None)
                )
            else:
                node["data"].update(
                    _node_data(auto_routing=False, model_id=LOW_MODEL, fallback_model_id=None)
                )
            node["data"]["title"] = "기업 요청 처리 및 위험 판단"
            node["data"]["description"] = "다양한 기업 운영 요청을 JSON 계약으로 처리합니다."
    # 기존 demo extractor가 실험 output 계약과 일치하도록 맞춘다.
    for node in graph["nodes"]:
        if node["id"] == "extract-ticket":
            node["data"]["mappings"] = [
                {"name": "approvalRequired", "json_path": "승인필요"},
                {"name": "mailDraft", "json_path": "답변초안"},
            ]
    return graph


def _deployment_id_for(arm: str) -> uuid.UUID:
    return {
        AUTO_ARM: AUTO_DEPLOYMENT_ID,
        HIGH_ARM: HIGH_DEPLOYMENT_ID,
        LOW_ARM: LOW_DEPLOYMENT_ID,
    }[arm]


def _run_id(arm: str, case_id: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"judge-first-economics:{arm}:{case_id}")


def _ensure_runtime_models(db) -> list[str]:
    available = LLMService.get_runtime_available_model_ids_for_user(
        db, user_id=USER_ID, organization_id=ORG_ID
    )
    wanted = [
        "gpt-4o-mini",
        "gpt-4.1-mini",
        "gpt-4.1",
        "gpt-5-mini",
        "gpt-5.4-mini",
        "gpt-5.4",
    ]
    selected = [model_id for model_id in wanted if model_id in available]
    required = {HIGH_MODEL, LOW_MODEL, ROUTING_JUDGE_MODEL}
    missing = required - set(selected)
    if missing:
        raise RuntimeError(f"실험에 필요한 실행 가능 모델이 없습니다: {sorted(missing)}")
    for model_id in selected:
        LLMService.get_runtime_client_for_user(db, USER_ID, model_id, ORG_ID)
    return selected


def _upsert_workflow_and_deployments(db, available_models: list[str]) -> None:
    auto_graph = graph_for_arm(AUTO_ARM)
    app = db.get(App, APP_ID)
    if app is None:
        app = App(
            id=APP_ID,
            organization_id=ORG_ID,
            name="Judge-first 자동 모델 라우팅 경제성 실험",
            description="동일한 기업 요청 처리 workflow를 자동·고가·저가 고정 방식으로 비교합니다.",
            icon={"type": "emoji", "content": "🧪", "background_color": "#E0F2FE"},
            url_slug="judge-first-routing-economics-80",
            auth_secret="experiment-routing-economics-secret",
            is_api_enabled=True,
            api_req_per_minute=600,
            api_req_per_hour=3600,
            is_market=False,
            created_by=USER_ID,
        )
        db.add(app)
        db.flush()

    workflow = db.get(Workflow, WORKFLOW_ID)
    if workflow is None:
        workflow = Workflow(
            id=WORKFLOW_ID,
            organization_id=ORG_ID,
            app_id=APP_ID,
            graph=auto_graph,
            features={},
            env_variables=[],
            runtime_variables=[],
            created_by=USER_ID,
            updated_by=USER_ID,
        )
        db.add(workflow)
    else:
        workflow.organization_id = ORG_ID
        workflow.app_id = APP_ID
        workflow.graph = auto_graph
        workflow.updated_by = USER_ID
        workflow.updated_at = datetime.now(timezone.utc)
    # apps.workflow_id는 workflows.id를 참조한다. 새 workflow를 먼저 flush하지
    # 않으면 PostgreSQL이 아직 없는 workflow를 가리키는 UPDATE를 거절한다.
    db.flush()
    app.workflow_id = WORKFLOW_ID

    for arm in ARMS:
        deployment_id = _deployment_id_for(arm)
        deployment = db.get(WorkflowDeployment, deployment_id)
        graph = graph_for_arm(arm)
        if deployment is None:
            deployment = WorkflowDeployment(
                id=deployment_id,
                app_id=APP_ID,
                version=1,
                type=DeploymentType.WEBHOOK,
                graph_snapshot=graph,
                config={"experiment": "judge-first-economics-80", "arm": arm},
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                description=f"80회 경제성 실험: {arm}",
                created_by=USER_ID,
                is_active=True,
            )
            db.add(deployment)
        else:
            deployment.app_id = APP_ID
            deployment.graph_snapshot = graph
            deployment.config = {"experiment": "judge-first-economics-80", "arm": arm}
            deployment.is_active = True

    db.flush()
    app.active_deployment_id = AUTO_DEPLOYMENT_ID

    policy = (
        db.query(LLMNodeModelRoutingPolicy)
        .filter(LLMNodeModelRoutingPolicy.workflow_id == WORKFLOW_ID)
        .filter(LLMNodeModelRoutingPolicy.deployment_id == AUTO_DEPLOYMENT_ID)
        .filter(LLMNodeModelRoutingPolicy.node_id == NODE_ID)
        .first()
    )
    active_policy = {
        "strategy_id": "judge_bootstrap_incremental_v1",
        "default_model_id": ROUTING_JUDGE_MODEL,
        "fallback_model_id": "gpt-4.1",
        "judge_model_id": ROUTING_JUDGE_MODEL,
        "global_profile_catalog": {
            "candidates": [{"model_id": model_id} for model_id in available_models]
        },
        "learning": {
            "mode": "judge_first",
            "judged_request_count": 0,
            "selected_model_ids": [],
            "local_confidence_threshold": LOCAL_CONFIDENCE_THRESHOLD,
        },
    }
    if policy is None:
        policy = LLMNodeModelRoutingPolicy(
            organization_id=ORG_ID,
            workflow_id=WORKFLOW_ID,
            deployment_id=AUTO_DEPLOYMENT_ID,
            node_id=NODE_ID,
            enabled=True,
            status="active",
            policy_version="judge-first-economics-v1",
            active_policy=active_policy,
            refresh_every_runs=100,
            judge_user_id=USER_ID,
            execution_subject_user_id=USER_ID,
            validation_budget_usd=3,
        )
        db.add(policy)
    else:
        policy.enabled = True
        policy.status = "active"
        policy.policy_version = "judge-first-economics-v1"
        policy.active_policy = active_policy
        policy.eligible_runs_since_last_refresh = 0
        policy.refresh_requested_at = None
        policy.last_refresh_result = None
        policy.judge_user_id = USER_ID
        policy.execution_subject_user_id = USER_ID
    db.flush()


def _clear_prior_experiment_runs(db) -> None:
    from apps.shared.db.models.workflow_run import WorkflowRun

    run_ids = [
        row[0]
        for row in db.query(WorkflowRun.id)
        .filter(WorkflowRun.workflow_id == WORKFLOW_ID)
        .all()
    ]
    db.query(LLMUsageLog).filter(LLMUsageLog.workflow_id == WORKFLOW_ID).delete(
        synchronize_session=False
    )
    if run_ids:
        db.query(WorkflowNodeRun).filter(
            WorkflowNodeRun.workflow_run_id.in_(run_ids)
        ).delete(synchronize_session=False)
        db.query(WorkflowRun).filter(WorkflowRun.id.in_(run_ids)).delete(
            synchronize_session=False
        )
    db.flush()


@contextmanager
def synchronous_experiment_tasks():
    """실험 중 log task는 동기 반영하고 background policy refresh는 막는다."""

    original_send_task = celery_app.send_task
    task_map = {
        "log.create_run": log_tasks.create_run_log,
        "log.update_run_finish": log_tasks.update_run_log_finish,
        "log.update_run_error": log_tasks.update_run_log_error,
        "log.create_node": log_tasks.create_node_log,
        "log.update_node_finish": log_tasks.update_node_log_finish,
        "log.update_node_error": log_tasks.update_node_log_error,
    }

    def send_task(task_name, args=None, kwargs=None, **options):
        if task_name in task_map:
            value = task_map[task_name].run(*(args or []), **(kwargs or {}))
            return type("SyncTaskResult", (), {"get": lambda self, timeout=None: value})()
        if task_name.startswith("workflow.model_routing."):
            return type("SkippedTaskResult", (), {"get": lambda self, timeout=None: {"status": "skipped"}})()
        return original_send_task(task_name, args=args, kwargs=kwargs, **options)

    celery_app.send_task = send_task
    try:
        yield
    finally:
        celery_app.send_task = original_send_task


def _execute_case(arm: str, case: ExperimentCase) -> ArmResult:
    graph = graph_for_arm(arm)
    run_id = _run_id(arm, case.case_id)
    engine = WorkflowEngine(
        graph=graph,
        user_input={"customerTier": case.customer_tier, "message": case.message},
        execution_context={
            "workflow_id": str(WORKFLOW_ID),
            "workflow_run_id": str(run_id),
            "app_id": str(APP_ID),
            "deployment_id": str(_deployment_id_for(arm)),
            "workflow_version": 1,
            "user_id": str(USER_ID),
            "organization_id": str(ORG_ID),
            "trigger_mode": "webhook",
            "execution_subject": {"subject_type": "user", "subject_id": str(USER_ID)},
        },
        is_deployed=True,
        workflow_timeout=120,
    )
    try:
        engine.execute()
    except Exception as exc:  # workflow error is a measured outcome, not a script abort.
        engine_error = f"{type(exc).__name__}: {exc}"
    else:
        engine_error = None
    finally:
        engine.cleanup()

    db = SessionLocal()
    try:
        # WorkflowEngine의 마지막 gevent log write가 execute() 반환 직후에
        # 완료될 수 있다. 저장 전 읽으면 실제 호출했어도 비용/모델이 0으로
        # 기록되므로, terminal node와 task usage가 보일 때까지 짧게 기다린다.
        node_run = None
        task_usage = None
        for _attempt in range(30):
            db.expire_all()
            node_run = (
                db.query(WorkflowNodeRun)
                .filter(WorkflowNodeRun.workflow_run_id == run_id)
                .filter(WorkflowNodeRun.node_id == NODE_ID)
                .first()
            )
            task_usage = (
                db.query(LLMUsageLog)
                .filter(LLMUsageLog.workflow_run_id == run_id)
                .filter(LLMUsageLog.node_id == NODE_ID)
                .order_by(LLMUsageLog.created_at.desc())
                .first()
            )
            if node_run is not None and (task_usage is not None or engine_error is not None):
                break
            time.sleep(0.2)
        judge_usage = (
            db.query(LLMUsageLog)
            .filter(LLMUsageLog.workflow_run_id == run_id)
            .filter(LLMUsageLog.node_id == f"{NODE_ID}:routing_judge")
            .order_by(LLMUsageLog.created_at.desc())
            .first()
        )
        prompt_tokens, completion_tokens, total_tokens, task_cost, task_latency = _usage(task_usage)
        _jp, _jc, judge_tokens, judge_cost, judge_latency = _usage(judge_usage)
        outputs = node_run.outputs if node_run is not None and isinstance(node_run.outputs, dict) else {}
        output_text = str(outputs.get("text") or "")
        trace = node_run.trace_metadata if node_run is not None and isinstance(node_run.trace_metadata, dict) else {}
        llm_trace = trace.get("llm") if isinstance(trace.get("llm"), dict) else {}
        output_metadata = outputs.get("metadata") if isinstance(outputs.get("metadata"), dict) else {}
        routing = (
            llm_trace.get("model_routing")
            if isinstance(llm_trace.get("model_routing"), dict)
            else output_metadata.get("model_routing")
            if isinstance(output_metadata.get("model_routing"), dict)
            else llm_trace
            if "decision_source" in llm_trace
            else {}
        )
        if not task_latency:
            task_latency = (
                int(llm_trace.get("latency_ms") or 0)
                or int(float(node_run.duration or 0) * 1000)
                if node_run is not None
                else None
            )
        if not judge_latency:
            judge_latency = int(
                (routing.get("judge") or {}).get("latency_ms") or 0
            ) or None
        selected_model = str(
            routing.get("selected_model")
            or (outputs.get("model") if isinstance(outputs, dict) else "")
            or (task_usage.model.model_id_for_api_call if task_usage and task_usage.model else "")
        ) or None
        success = engine_error is None and node_run is not None and str(node_run.status).lower().endswith("success")
        return ArmResult(
            arm=arm,
            selected_model=selected_model,
            task_cost_usd=task_cost,
            task_latency_ms=task_latency,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            output_text=output_text,
            schema_pass=_schema_pass(output_text),
            workflow_success=success,
            error=engine_error,
            routing=routing,
            routing_judge_cost_usd=judge_cost,
            routing_judge_tokens=judge_tokens,
            routing_judge_latency_ms=judge_latency,
        )
    finally:
        db.close()


def _record_automatic_operational_result(case: ExperimentCase) -> None:
    """실제 배포 완료 훅과 같은 방식으로 auto arm의 학습/성적을 누적한다.

    Celery task 자체는 실험 중 policy refresh를 예약하지 않도록 막아 두지만,
    이 기록 단계는 생략하지 않는다. 생략하면 Judge label은 저장되어도 운영 성공률과
    JSON 계약 통과율이 policy에 반영되지 않아 local-first 전환을 측정할 수 없다.
    """

    db = SessionLocal()
    try:
        ModelRoutingPolicyStore.record_completed_deployed_run(
            db,
            workflow_run_id=_run_id(AUTO_ARM, case.case_id),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _quality_judge(case: ExperimentCase, results: dict[str, ArmResult]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """모델명을 숨긴 한 번의 비교 평가로 세 arm 품질을 공정하게 비교한다."""

    mapping = list(ARMS)
    random.Random(case.case_id).shuffle(mapping)
    anonymous = {
        f"output_{index + 1}": results[arm].output_text
        for index, arm in enumerate(mapping)
    }
    prompt = {
        "task": "기업 운영 요청 처리 workflow의 세 JSON 출력을 품질만으로 비교하세요.",
        "input": {"customerTier": case.customer_tier, "message": case.message},
        "required_contract": {
            "fields": ["분류", "우선순위", "승인필요", "대응계획", "답변초안"],
            "rules": [
                "분류와 우선순위는 요청 내용에 맞아야 합니다.",
                "보안, 개인정보, 결제, SLA, 법무 위험은 과도한 확정 약속 없이 보수적으로 처리해야 합니다.",
                "대응계획은 실행 가능한 단계여야 합니다.",
                "답변초안은 사용자가 이해할 수 있어야 합니다.",
                "비용, 속도, 출력 순서, 모델 이름을 평가에 반영하지 마세요.",
            ],
        },
        "anonymous_outputs": anonymous,
        "response_schema": {
            key: {"quality_score": "0..100", "contract_pass": "boolean", "reason": "short Korean"}
            for key in anonymous
        },
    }
    db = SessionLocal()
    try:
        selection = LLMService.get_runtime_client_for_user(
            db, USER_ID, ROUTING_JUDGE_MODEL, ORG_ID
        )
        started = datetime.now(timezone.utc)
        response = selection.client.invoke_sync(
            [
                {"role": "system", "content": "당신은 엄격하고 공정한 workflow output 품질 평가자입니다. 반드시 JSON object 하나만 반환하세요."},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            temperature=0,
            # 세 arm의 긴 JSON 출력을 함께 읽는 평가다. Judge 자신의 추론 토큰과
            # 세 결과 score를 충분히 남기기 위해 task output보다 넉넉히 둔다.
            max_tokens=800,
            response_format={"type": "json_object"},
        )
        elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        payload = _json_from_text(str(response.get("choices", [{}])[0].get("message", {}).get("content", "")))
        usage = response.get("usage") if isinstance(response, dict) else {}
        prompt_tokens = int((usage or {}).get("prompt_tokens") or 0)
        completion_tokens = int((usage or {}).get("completion_tokens") or 0)
        cost = LLMService.calculate_cost(db, ROUTING_JUDGE_MODEL, prompt_tokens, completion_tokens)
    except Exception as exc:
        error_code = f"{type(exc).__name__}:{str(exc)[:180]}"
        return ({arm: {"quality_score": 0.0, "contract_pass": False, "reason": f"quality_judge_error:{error_code}"} for arm in ARMS}, {"error": error_code})
    finally:
        db.close()

    judged: dict[str, dict[str, Any]] = {}
    for index, arm in enumerate(mapping):
        anonymous_key = f"output_{index + 1}"
        row = payload.get(anonymous_key) if isinstance(payload, dict) else None
        row = row if isinstance(row, dict) else {}
        try:
            score = max(0.0, min(100.0, float(row.get("quality_score"))))
        except (TypeError, ValueError):
            score = 0.0
        judged[arm] = {
            "quality_score": score,
            "contract_pass": bool(row.get("contract_pass")),
            "reason": str(row.get("reason") or "품질 Judge 응답 없음")[:240],
        }
    return judged, {
        "model": ROUTING_JUDGE_MODEL,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "cost_usd": cost,
        "latency_ms": elapsed_ms,
    }


def _mean(values: Iterable[float | int | None]) -> float | None:
    normalized = [float(value) for value in values if value is not None]
    return statistics.mean(normalized) if normalized else None


def _p95(values: Iterable[float | int | None]) -> float | None:
    normalized = sorted(float(value) for value in values if value is not None)
    if not normalized:
        return None
    return normalized[min(len(normalized) - 1, max(0, round((len(normalized) - 1) * 0.95)))]


def _arm_summary(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    arm_rows = [row["arms"][arm] for row in rows]
    task_cost = sum(float(item["task_cost_usd"] or 0) for item in arm_rows)
    route_cost = sum(float(item["routing_judge_cost_usd"] or 0) for item in arm_rows)
    return {
        "run_count": len(arm_rows),
        "task_cost_usd": task_cost,
        "routing_judge_cost_usd": route_cost,
        "total_product_cost_usd": task_cost + route_cost,
        "average_task_latency_ms": _mean(item["task_latency_ms"] for item in arm_rows),
        "average_end_to_end_latency_ms": _mean(
            (item["task_latency_ms"] or 0) + (item["routing_judge_latency_ms"] or 0)
            for item in arm_rows
        ),
        "p95_task_latency_ms": _p95(item["task_latency_ms"] for item in arm_rows),
        "total_tokens": sum(int(item["total_tokens"] or 0) for item in arm_rows),
        "schema_pass_rate": sum(1 for item in arm_rows if item["schema_pass"]) / len(arm_rows),
        "workflow_success_rate": sum(1 for item in arm_rows if item["workflow_success"]) / len(arm_rows),
        "quality_score_average": _mean(row["quality"][arm]["quality_score"] for row in rows),
        "quality_pass_rate": sum(1 for row in rows if row["quality"][arm]["contract_pass"]) / len(rows),
        "model_distribution": dict(Counter(item["selected_model"] or "unknown" for item in arm_rows)),
        "runtime_judge_call_count": sum(1 for item in arm_rows if item["routing_judge_tokens"] > 0),
    }


def _learning_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    auto_rows = [row["arms"][AUTO_ARM] for row in rows]
    confidences = [
        float(item["routing"].get("judge", {}).get("confidence"))
        for item in auto_rows
        if isinstance(item["routing"].get("judge"), dict)
        and item["routing"].get("judge", {}).get("confidence") is not None
    ]
    sources = Counter(str(item["routing"].get("decision_source") or "unknown") for item in auto_rows)
    local_rows = [item for item in auto_rows if item["routing"].get("decision_source") == "local_router"]
    uncertain_rows = [item for item in auto_rows if item["routing"].get("reason_code") == "local_router_uncertain"]
    selected = [item["selected_model"] for item in auto_rows if item["selected_model"]]
    return {
        "judge_label_count": sum(1 for item in auto_rows if item["routing_judge_tokens"] > 0),
        "distinct_selected_model_count": len(set(selected)),
        "selected_models": dict(Counter(selected)),
        "decision_source_distribution": dict(sources),
        "local_router_takeover_count": len(local_rows),
        "local_router_uncertain_count": len(uncertain_rows),
        "local_confidence_threshold": LOCAL_CONFIDENCE_THRESHOLD,
        "judge_confidence_average": _mean(confidences),
        "judge_confidence_p95": _p95(confidences),
        "interpretation": (
            "local_router_takeover_count가 0이면, 현재 학습 표본 또는 confidence가 "
            "임계값에 도달하지 않아 모든 요청이 Runtime Judge로 처리된 것입니다."
        ),
    }


def _persisted_learning_state() -> dict[str, Any]:
    """실행별 trace가 아닌 policy row의 최종 학습 상태도 보고서에 남긴다."""

    db = SessionLocal()
    try:
        policy = (
            db.query(LLMNodeModelRoutingPolicy)
            .filter(LLMNodeModelRoutingPolicy.deployment_id == AUTO_DEPLOYMENT_ID)
            .filter(LLMNodeModelRoutingPolicy.node_id == NODE_ID)
            .first()
        )
        active_policy = policy.active_policy if policy is not None else {}
        learning = (
            active_policy.get("learning")
            if isinstance(active_policy, dict) and isinstance(active_policy.get("learning"), dict)
            else {}
        )
        artifact = learning.get("local_router_artifact") if isinstance(learning, dict) else {}
        return {
            "policy_status": policy.status if policy is not None else None,
            "policy_version": policy.policy_version if policy is not None else None,
            "learning_mode": learning.get("mode"),
            "judged_request_count": learning.get("judged_request_count"),
            "operational_run_count": learning.get("operational_run_count"),
            "selected_model_ids": learning.get("selected_model_ids") or [],
            "artifact_kind": artifact.get("kind") if isinstance(artifact, dict) else None,
            "artifact_encoder": artifact.get("encoder_model_id") if isinstance(artifact, dict) else None,
            "artifact_label_models": artifact.get("selected_model_ids") if isinstance(artifact, dict) else [],
            "artifact_trained_example_count": artifact.get("trained_example_count") if isinstance(artifact, dict) else 0,
            "last_learning_error": learning.get("last_learning_error"),
        }
    finally:
        db.close()


def _money(value: float | None) -> str:
    return "-" if value is None else f"${value:.6f}"


def _percent(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["arm_summary"]
    automatic = summary[AUTO_ARM]
    high = summary[HIGH_ARM]
    low = summary[LOW_ARM]
    auto_vs_high = high["total_product_cost_usd"] - automatic["total_product_cost_usd"]
    auto_vs_low_quality = automatic["quality_score_average"] - low["quality_score_average"]
    lines = [
        "# Judge-first 자동 모델 라우팅 80회 경제성 실험 보고서",
        "",
        "## 한눈에 보는 결론",
        "",
        "이 실험은 같은 기업 요청 처리 워크플로우를 80개의 서로 다른 요청으로 실행해, 자동 모델 라우팅이 비싼 모델만 고정하는 경우보다 돈을 아끼는지, 싼 모델만 고정하는 경우보다 결과 품질을 지키는지 확인한 결과입니다.",
        "",
        f"- 자동 라우팅 총 제품 비용: {_money(automatic['total_product_cost_usd'])}",
        f"- 고가 고정 대비 자동 라우팅 순절감: {_money(auto_vs_high)} ({'절감' if auto_vs_high >= 0 else '추가 비용'})",
        f"- 저가 고정 대비 자동 라우팅 평균 품질 차이: {auto_vs_low_quality:+.2f}점",
        f"- 자동 라우팅에서 Runtime Judge가 실제 호출된 횟수: {automatic['runtime_judge_call_count']}/80",
        "",
        "자동 라우팅 비용에는 요청 처리 모델 비용과 Runtime Judge 비용을 모두 포함했습니다. 실험의 품질 평가 Judge 비용은 제품 기능의 런타임 비용이 아니므로 별도로 표시합니다.",
        "",
        "## 실험 조건",
        "",
        f"- 실행 시각: {report['executed_at']}",
        f"- workflow: `{report['workflow_id']}` / LLM node: `{NODE_ID}`",
        "- 실행 방식: 실제 WorkflowEngine, 실제 OpenAI provider 호출, 실제 배포 run/node run/usage log 기록",
        "- 자동 라우팅 전략: `judge_bootstrap_incremental_v1`",
        f"- 자동 라우팅 후보: {', '.join(report['available_models'])}",
        f"- 고가 고정 모델: `{HIGH_MODEL}` / 저가 고정 모델: `{LOW_MODEL}`",
        f"- 라우팅 Judge 및 품질 평가 Judge: `{ROUTING_JUDGE_MODEL}`",
        "- RAG: 미사용. 이번 비교에서는 KB 검색 품질 변수를 빼고 모델 라우팅 자체의 비용·속도·출력 품질만 측정했습니다.",
        "- 정책 refresh: 100회. 80회 실험 동안 정책 교체를 막고, Judge label을 누적한 local router의 전환만 측정했습니다.",
        "",
        "## 데이터셋",
        "",
        "80개 요청은 고객 사용 안내, 계정·접근 권한, 재무 결산·승인, 보안·개인정보 사고, 장애·신뢰성, 데이터 거버넌스, 계약·규정, 분석 보고, 연동 지원, 위험 분류를 섞었습니다. 동일 문장을 반복하지 않았고 실행 순서는 고정 난수로 섞어 특정 범주가 초반에 몰리지 않게 했습니다.",
        "",
        "| 예상 난이도 | 건수 |",
        "| --- | ---: |",
    ]
    for difficulty, count in sorted(Counter(row["expected_difficulty"] for row in report["runs"]).items()):
        lines.append(f"| {difficulty} | {count} |")
    lines.extend([
        "",
        "## 비용·속도·품질 비교",
        "",
        "| 방식 | 처리 모델 비용 | 라우팅 Judge 비용 | 총 제품 비용 | 평균 LLM 노드 시간 | 평균 전체 시간 | 평균 품질 점수 | JSON 계약 통과 | 품질 통과 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    labels = {AUTO_ARM: "자동 라우팅", HIGH_ARM: f"고가 고정 ({HIGH_MODEL})", LOW_ARM: f"저가 고정 ({LOW_MODEL})"}
    for arm in ARMS:
        item = summary[arm]
        lines.append(
            f"| {labels[arm]} | {_money(item['task_cost_usd'])} | {_money(item['routing_judge_cost_usd'])} | "
            f"{_money(item['total_product_cost_usd'])} | {item['average_task_latency_ms'] or 0:.0f}ms | "
            f"{item['average_end_to_end_latency_ms'] or 0:.0f}ms | {item['quality_score_average'] or 0:.2f} | "
            f"{_percent(item['schema_pass_rate'])} | {_percent(item['quality_pass_rate'])} |"
        )
    lines.extend([
        "",
        "## 자동 라우팅이 실제로 고른 모델",
        "",
    ])
    for model_id, count in sorted(automatic["model_distribution"].items()):
        lines.append(f"- `{model_id}`: {count}회")
    lines.extend([
        "",
        "## 로컬 라우터 학습 수준",
        "",
    ])
    learning = report["learning_summary"]
    lines.extend([
        f"- Judge label 누적: {learning['judge_label_count']}건",
        f"- 실제 선택 모델 종류: {learning['distinct_selected_model_count']}개 ({learning['selected_models']})",
        f"- 처리 출처 분포: {learning['decision_source_distribution']}",
        f"- 로컬 라우터가 Judge 없이 직접 선택한 횟수: {learning['local_router_takeover_count']}회",
        f"- 로컬 라우터가 자신 없어 Judge로 되돌린 횟수: {learning['local_router_uncertain_count']}회",
        f"- Judge 신뢰도 평균 / P95: {(learning['judge_confidence_average'] or 0):.3f} / {(learning['judge_confidence_p95'] or 0):.3f}",
        f"- 로컬 takeover 최소 신뢰도: {learning['local_confidence_threshold']:.2f}",
        f"- 최종 저장 정책 학습 모드: {learning['persisted']['learning_mode'] or '없음'}",
        f"- 최종 저장 학습 표본: Judge {learning['persisted']['judged_request_count'] or 0}건 / 운영 완료 {learning['persisted']['operational_run_count'] or 0}건",
        f"- 학습 artifact: {learning['persisted']['artifact_kind'] or '없음'} ({learning['persisted']['artifact_encoder'] or '-'})",
        f"- artifact 학습 예시 수: {learning['persisted']['artifact_trained_example_count'] or 0}건 / artifact 모델 label: {learning['persisted']['artifact_label_models']}",
        "",
        "이 수치는 로컬 모델이 단순히 label을 저장했는지뿐 아니라, 실제로 충분한 자신감을 얻어 Judge 호출을 대신했는지를 보여 줍니다. takeover가 낮으면 현재 학습 구조가 비용 절감에는 불리하다는 뜻이며, 이 경우 Judge-first를 제품의 장기 기본값으로 두면 안 됩니다.",
        "",
        "## 실험 평가 비용",
        "",
        f"- 독립 품질 Judge 총비용: {_money(report['quality_judge_total_cost_usd'])}",
        f"- 독립 품질 Judge 총호출: {report['quality_judge_call_count']}회",
        "- 이 비용은 세 방식의 결과를 공정하게 비교하기 위한 측정 비용이며 제품 운영비 비교에는 포함하지 않았습니다.",
        "",
        "## 요청별 결과",
        "",
        "| # | 주제 | 예상 난이도 | 자동 선택 모델 | 자동 품질 | 고가 품질 | 저가 품질 | 자동 총비용 | 고가 비용 | 저가 비용 |",
        "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for index, row in enumerate(report["runs"], start=1):
        auto = row["arms"][AUTO_ARM]
        high_row = row["arms"][HIGH_ARM]
        low_row = row["arms"][LOW_ARM]
        lines.append(
            f"| {index} | {row['category']} | {row['expected_difficulty']} | {auto['selected_model'] or '-'} | "
            f"{row['quality'][AUTO_ARM]['quality_score']:.1f} | {row['quality'][HIGH_ARM]['quality_score']:.1f} | "
            f"{row['quality'][LOW_ARM]['quality_score']:.1f} | "
            f"{_money(auto['task_cost_usd'] + auto['routing_judge_cost_usd'])} | "
            f"{_money(high_row['task_cost_usd'])} | {_money(low_row['task_cost_usd'])} |"
        )
    lines.extend([
        "",
        "## 해석 시 주의점",
        "",
        "- 품질 점수는 독립 Judge가 동일한 계약으로 평가한 상대 지표입니다. 실제 고객 만족도나 사람 검수 결과를 완전히 대체하지는 않습니다.",
        "- 자동 라우팅의 전체 시간에는 Judge 호출 시간이 포함됩니다. 처리 모델 시간만 보면 절감돼도 전체 시간은 늘어날 수 있습니다.",
        "- JSON 계약 실패, workflow 실패, Judge 오류는 모두 결과에 포함됩니다. 성공 사례만 골라 평균을 낸 결과가 아닙니다.",
    ])
    return "\n".join(lines) + "\n"


def write_report(output_dir: pathlib.Path, report: dict[str, Any]) -> tuple[pathlib.Path, pathlib.Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "judge_first_economics_80.json"
    markdown_path = output_dir / "judge_first_economics_80.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def _read_existing_report(output_dir: pathlib.Path) -> dict[str, Any]:
    path = output_dir / "judge_first_economics_80.json"
    if not path.exists():
        raise RuntimeError("--resume에는 이전 실험 보고서가 필요합니다.")
    return json.loads(path.read_text(encoding="utf-8"))


def run_experiment(
    cases: list[ExperimentCase],
    output_dir: pathlib.Path,
    *,
    resume: bool,
    batch_offset: int,
) -> dict[str, Any]:
    if resume:
        previous_report = _read_existing_report(output_dir)
        rows = list(previous_report.get("runs") or [])
        available_models = list(previous_report.get("available_models") or [])
        prior_quality_cost = float(previous_report.get("quality_judge_total_cost_usd") or 0)
        prior_quality_calls = int(previous_report.get("quality_judge_call_count") or 0)
        prior_quality_errors = list(previous_report.get("quality_judge_errors") or [])
    else:
        with SessionLocal() as db:
            available_models = _ensure_runtime_models(db)
            _clear_prior_experiment_runs(db)
            _upsert_workflow_and_deployments(db, available_models)
            db.commit()
        rows = []
        prior_quality_cost = 0.0
        prior_quality_calls = 0
        prior_quality_errors: list[dict[str, Any]] = []

    quality_judge_metrics: list[dict[str, Any]] = []
    with synchronous_experiment_tasks():
        for index, case in enumerate(cases, start=1):
            results = {arm: _execute_case(arm, case) for arm in ARMS}
            _record_automatic_operational_result(case)
            quality, quality_meta = _quality_judge(case, results)
            quality_judge_metrics.append(quality_meta)
            rows.append(
                {
                    "case_id": case.case_id,
                    "category": case.category,
                    "expected_difficulty": case.expected_difficulty,
                    "customer_tier": case.customer_tier,
                    "message": case.message,
                    "arms": {arm: asdict(result) for arm, result in results.items()},
                    "quality": quality,
                }
            )
            if index == 1 or index % 5 == 0 or index == len(cases):
                print(
                    f"[progress] batch {batch_offset + index}/{batch_offset + len(cases)} "
                    f"(this batch {index}/{len(cases)}) completed",
                    flush=True,
                )

    report = {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "workflow_id": str(WORKFLOW_ID),
        "node_id": NODE_ID,
        "case_count": len(rows),
        "latest_batch": {
            "offset": batch_offset,
            "count": len(cases),
            "completed_case_count": len(rows),
        },
        "available_models": available_models,
        "runs": rows,
        "arm_summary": {arm: _arm_summary(rows, arm) for arm in ARMS},
        "learning_summary": {
            **_learning_summary(rows),
            "persisted": _persisted_learning_state(),
        },
        "quality_judge_total_cost_usd": prior_quality_cost + sum(
            float(metric.get("cost_usd") or 0) for metric in quality_judge_metrics
        ),
        "quality_judge_call_count": prior_quality_calls + sum(
            1 for metric in quality_judge_metrics if not metric.get("error")
        ),
        "quality_judge_errors": prior_quality_errors
        + [metric for metric in quality_judge_metrics if metric.get("error")],
    }
    json_path, markdown_path = write_report(output_dir, report)
    print(json.dumps({"json": str(json_path.resolve()), "markdown": str(markdown_path.resolve())}, ensure_ascii=False), flush=True)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Judge-first 자동 모델 라우팅 80회 경제성 실험")
    parser.add_argument("--execute", action="store_true", help="실제 provider 호출과 DB 로그 기록을 실행합니다.")
    parser.add_argument("--count", type=int, default=80, help="사전 검증용 실행 건수입니다. 기본값은 80입니다.")
    parser.add_argument("--offset", type=int, default=0, help="80개 고정 데이터셋에서 시작할 0-base 위치입니다.")
    parser.add_argument("--resume", action="store_true", help="이전 10건 batch의 DB 정책과 보고서를 이어서 누적합니다.")
    parser.add_argument("--output-dir", default="reports/model-routing/judge-first-economics-80")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cases = build_cases()
    if args.count < 1 or args.offset < 0 or args.offset + args.count > len(cases):
        raise SystemExit(f"--offset/--count 범위는 0~{len(cases)} 안이어야 합니다.")
    selected_cases = cases[args.offset : args.offset + args.count]
    if not args.execute:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "case_count": len(selected_cases),
                    "categories": dict(Counter(case.category for case in selected_cases)),
                    "difficulty": dict(Counter(case.expected_difficulty for case in selected_cases)),
                    "message": "실제 호출은 --execute를 붙여야 시작합니다.",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    run_experiment(
        selected_cases,
        pathlib.Path(args.output_dir),
        resume=args.resume,
        batch_offset=args.offset,
    )


if __name__ == "__main__":
    main()
