import pathlib
import sys
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

ROOT = pathlib.Path(__file__).resolve().parents[2]
PARENT_OF_ROOT = ROOT.parent
for p in [ROOT, PARENT_OF_ROOT]:
    if str(p) not in sys.path:
        sys.path.append(str(p))

from apps.workflow_engine.services.model_router import (  # noqa: E402
    ModelCandidate,
    ModelPerformance,
    ModelRouter,
    ModelRouterContext,
    NodeRunProfile,
)


class _ProfileQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self.limit_value = None

    def join(self, *args, **kwargs):
        return self

    def outerjoin(self, *args, **kwargs):
        return self

    def filter(self, *criteria):
        self.filters.extend(criteria)
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def all(self):
        return self.rows


class _ProfileSession:
    def __init__(self, rows):
        self.query_obj = _ProfileQuery(rows)

    def query(self, *models):
        self.models = models
        return self.query_obj


class _CandidateQuery:
    def __init__(self, models):
        self.models = models

    def join(self, *args, **kwargs):
        return self

    def filter(self, *criteria):
        return self

    def all(self):
        return self.models


class _CandidateSession:
    def __init__(self, models):
        self.models = models

    def query(self, *models):
        return _CandidateQuery(self.models)


def _candidate(model_id: str, price: float) -> ModelCandidate:
    return ModelCandidate(
        model_id=model_id,
        display_name=model_id,
        input_price_1k=price / 2,
        output_price_1k=price / 2,
    )


def test_cold_start_high_risk_uses_conservative_model():
    """운영 로그가 부족하고 고객-facing/RAG 위험이 있으면 cheap 모델을 고르지 않는다."""
    decision = ModelRouter.resolve(
        ModelRouterContext(
            workflow_id="workflow-1",
            node_id="llm-triage",
            current_model_id="gpt-4.1",
            candidate_models=[
                _candidate("gpt-4.1-mini", 0.01),
                _candidate("gpt-4.1", 0.1),
                _candidate("gpt-5.5-pro", 1.0),
            ],
            node_profile=NodeRunProfile(operational_usable_runs=0),
            customer_facing=True,
            knowledge_enabled=True,
        )
    )

    assert decision.routing_stage == "cold_start"
    assert decision.selected_model_id == "gpt-4.1"
    assert decision.fallback_model_id is None
    assert "보수" in decision.reason


def test_cold_start_low_risk_keeps_current_model_until_operational_logs_exist():
    """낮은 위험 작업도 운영 로그가 쌓이기 전에는 현재 모델을 유지한다."""
    decision = ModelRouter.resolve(
        ModelRouterContext(
            workflow_id="workflow-1",
            node_id="llm-triage",
            current_model_id="gpt-4.1",
            candidate_models=[
                _candidate("gpt-4o-mini", 0.001),
                _candidate("gpt-4.1-mini", 0.01),
                _candidate("gpt-4.1", 0.1),
            ],
            node_profile=NodeRunProfile(operational_usable_runs=0),
            customer_facing=False,
            knowledge_enabled=False,
        )
    )

    assert decision.routing_stage == "cold_start"
    assert decision.selected_model_id == "gpt-4.1"
    assert decision.fallback_model_id is None


def test_model_router_stage_boundaries_are_20_and_90_runs():
    """자동 라우터는 20회부터 warming, 90회부터 optimized로 전환한다."""
    candidates = [
        _candidate("gpt-4o-mini", 0.001),
        _candidate("gpt-4.1-mini", 0.01),
        _candidate("gpt-4.1", 0.1),
    ]

    cold = ModelRouter.resolve(
        ModelRouterContext(
            workflow_id="workflow-1",
            node_id="llm-triage",
            current_model_id="gpt-4.1",
            candidate_models=candidates,
            node_profile=NodeRunProfile(operational_usable_runs=19),
        )
    )
    warming = ModelRouter.resolve(
        ModelRouterContext(
            workflow_id="workflow-1",
            node_id="llm-triage",
            current_model_id="gpt-4.1",
            candidate_models=candidates,
            node_profile=NodeRunProfile(operational_usable_runs=20),
        )
    )
    optimized = ModelRouter.resolve(
        ModelRouterContext(
            workflow_id="workflow-1",
            node_id="llm-triage",
            current_model_id="gpt-4.1",
            candidate_models=candidates,
            node_profile=NodeRunProfile(operational_usable_runs=90),
        )
    )

    assert cold.routing_stage == "cold_start"
    assert warming.routing_stage == "warming_up"
    assert optimized.routing_stage == "optimized"


def test_warming_up_uses_passing_lower_cost_candidate():
    """운영 로그가 쌓이고 품질 gate를 통과한 저가 후보가 있으면 선택한다."""
    decision = ModelRouter.resolve(
        ModelRouterContext(
            workflow_id="workflow-1",
            node_id="llm-triage",
            current_model_id="gpt-4.1",
            candidate_models=[
                _candidate("gpt-4.1-mini", 0.01),
                _candidate("gpt-4.1", 0.1),
            ],
            node_profile=NodeRunProfile(
                operational_usable_runs=42,
                model_performance={
                    "gpt-4.1-mini": ModelPerformance(
                        model_id="gpt-4.1-mini",
                        run_count=12,
                        success_count=12,
                        schema_pass_count=12,
                        schema_eval_count=12,
                        downstream_success_count=12,
                        downstream_eval_count=12,
                        fallback_count=0,
                        retry_count=0,
                        total_cost=0.012,
                        total_latency_ms=12000,
                    )
                },
            ),
        )
    )

    assert decision.routing_stage == "warming_up"
    assert decision.selected_model_id == "gpt-4.1-mini"
    assert decision.fallback_model_id == "gpt-4.1"
    assert decision.metrics_snapshot["operational_usable_runs"] == 42


def test_warming_up_keeps_current_model_when_lower_cost_candidate_is_unverified():
    """정책 갱신은 검증 샘플 생성을 위해 자동 하향하지 않고 현재 모델을 유지한다."""
    decision = ModelRouter.resolve(
        ModelRouterContext(
            workflow_id="workflow-1",
            node_id="llm-triage",
            current_model_id="gpt-4.1",
            candidate_models=[
                _candidate("gpt-4.1-mini", 0.01),
                _candidate("gpt-4o", 0.08),
                _candidate("gpt-4.1", 0.1),
            ],
            node_profile=NodeRunProfile(
                operational_usable_runs=30,
                model_performance={
                    "gpt-4.1": ModelPerformance(
                        model_id="gpt-4.1",
                        run_count=30,
                        success_count=30,
                        schema_pass_count=30,
                        schema_eval_count=30,
                        downstream_success_count=30,
                        downstream_eval_count=30,
                        fallback_count=0,
                        retry_count=0,
                        total_cost=3.0,
                        total_latency_ms=30000,
                    )
                },
            ),
            customer_facing=False,
            knowledge_enabled=False,
        )
    )

    assert decision.routing_stage == "warming_up"
    assert decision.selected_model_id == "gpt-4.1"
    assert decision.fallback_model_id is None
    assert "안정 모델" in decision.reason


def test_high_risk_warming_up_keeps_current_model_instead_of_exploring():
    """고객-facing/schema 계약이 있는 high-risk 노드는 검증 샘플 생성을 위해 자동 하향하지 않는다."""
    decision = ModelRouter.resolve(
        ModelRouterContext(
            workflow_id="workflow-1",
            node_id="llm-risk-review",
            current_model_id="gpt-4.1",
            candidate_models=[
                _candidate("gpt-5.4-mini", 0.03),
                _candidate("gpt-4.1-mini", 0.01),
                _candidate("gpt-4.1", 0.1),
            ],
            node_profile=NodeRunProfile(
                operational_usable_runs=120,
                model_performance={
                    "gpt-4.1": ModelPerformance(
                        model_id="gpt-4.1",
                        run_count=120,
                        success_count=120,
                        schema_pass_count=120,
                        schema_eval_count=120,
                        downstream_success_count=120,
                        downstream_eval_count=120,
                        fallback_count=0,
                        retry_count=0,
                        total_cost=12.0,
                        total_latency_ms=120000,
                    )
                },
            ),
            customer_facing=True,
            output_format="json",
        )
    )

    assert decision.routing_stage == "optimized"
    assert decision.selected_model_id == "gpt-4.1"
    assert decision.fallback_model_id is None
    assert "안정 모델" in decision.reason


def test_optimized_promotes_when_recent_lower_cost_candidate_regresses():
    """optimized 상태라도 품질 지표가 나쁜 cheap 후보는 제외하고 상위 모델로 되돌린다."""
    decision = ModelRouter.resolve(
        ModelRouterContext(
            workflow_id="workflow-1",
            node_id="llm-triage",
            current_model_id="gpt-4.1",
            candidate_models=[
                _candidate("gpt-4.1-mini", 0.01),
                _candidate("gpt-4.1", 0.1),
            ],
            node_profile=NodeRunProfile(
                operational_usable_runs=140,
                model_performance={
                    "gpt-4.1-mini": ModelPerformance(
                        model_id="gpt-4.1-mini",
                        run_count=40,
                        success_count=40,
                        schema_pass_count=30,
                        schema_eval_count=40,
                        downstream_success_count=40,
                        downstream_eval_count=40,
                        fallback_count=0,
                        retry_count=0,
                        total_cost=0.04,
                        total_latency_ms=40000,
                    ),
                    "gpt-4.1": ModelPerformance(
                        model_id="gpt-4.1",
                        run_count=100,
                        success_count=100,
                        schema_pass_count=100,
                        schema_eval_count=100,
                        downstream_success_count=100,
                        downstream_eval_count=100,
                        fallback_count=0,
                        retry_count=0,
                        total_cost=1.0,
                        total_latency_ms=100000,
                    ),
                },
            ),
        )
    )

    assert decision.routing_stage == "optimized"
    assert decision.selected_model_id == "gpt-4.1"
    assert "품질 gate" in decision.reason


def test_collect_profile_counts_only_deployed_operational_llm_usage_rows():
    """라우터 프로필은 배포 후 운영 실행의 LLM usage와 node run만 usable run으로 본다."""
    workflow_id = uuid4()
    now = datetime.now(timezone.utc)
    successful_node_run = SimpleNamespace(
        node_id="llm-triage",
        node_type="llmNode",
        status="success",
        outputs={"text": "ok"},
        started_at=now,
        retry_count=0,
        trace_metadata={
            "schema_status": "passed",
            "downstream_status": "compatible",
            "llm": {"fallback_used": False},
        },
    )
    missing_usage_node_run = SimpleNamespace(
        node_id="llm-triage",
        node_type="llmNode",
        status="success",
        outputs={"text": "not counted"},
        started_at=now,
        retry_count=0,
        trace_metadata={},
    )
    workflow_run = SimpleNamespace(id=uuid4())
    usage = SimpleNamespace(
        model_id=uuid4(),
        status="success",
        total_cost=Decimal("0.004"),
        latency_ms=1300,
    )
    model = SimpleNamespace(model_id_for_api_call="gpt-4.1-mini")
    db = _ProfileSession(
        [
            (successful_node_run, workflow_run, usage, model),
            (missing_usage_node_run, workflow_run, None, None),
        ]
    )

    profile = ModelRouter.collect_profile(
        db,
        ModelRouterContext(
            workflow_id=str(workflow_id),
            node_id="llm-triage",
            current_model_id="gpt-4.1",
        ),
    )

    filter_sql = "\n".join(str(criteria) for criteria in db.query_obj.filters)
    assert "workflow_runs.deployment_id IS NOT NULL" in filter_sql
    assert "workflow_runs.trigger_mode IN" in filter_sql
    assert "workflow_node_runs.node_id = :node_id_1" in filter_sql
    assert db.query_obj.limit_value == 200
    assert profile.operational_usable_runs == 1
    assert profile.model_performance["gpt-4.1-mini"].run_count == 1
    assert profile.model_performance["gpt-4.1-mini"].schema_pass_count == 1
    assert profile.model_performance["gpt-4.1-mini"].downstream_success_count == 1


def test_collect_profile_uses_workflow_success_as_downstream_fallback():
    """명시 downstream metadata가 없으면 배포 후 workflow 성공을 후속 통과 근거로 쓴다."""
    now = datetime.now(timezone.utc)
    node_run = SimpleNamespace(
        node_id="llm-triage",
        node_type="llmNode",
        status="success",
        outputs={"text": "ok"},
        started_at=now,
        retry_count=0,
        trace_metadata={},
    )
    workflow_run = SimpleNamespace(id=uuid4(), status="success")
    usage = SimpleNamespace(
        model_id=uuid4(),
        status="success",
        total_cost=Decimal("0.004"),
        latency_ms=1300,
    )
    model = SimpleNamespace(model_id_for_api_call="gpt-4.1-mini")

    profile = ModelRouter.collect_profile(
        _ProfileSession([(node_run, workflow_run, usage, model)]),
        ModelRouterContext(
            workflow_id=str(uuid4()),
            node_id="llm-triage",
            current_model_id="gpt-4.1",
        ),
    )

    performance = profile.model_performance["gpt-4.1-mini"]
    assert performance.downstream_eval_count == 1
    assert performance.downstream_success_count == 1
    assert performance.downstream_success_rate == 1.0


def test_collect_profile_without_workflow_id_falls_back_to_empty_profile():
    """workflow_id가 없는 특수 실행 경로는 라우터 실패 대신 cold start profile로 닫는다."""
    profile = ModelRouter.collect_profile(
        _ProfileSession([]),
        ModelRouterContext(
            workflow_id="",
            node_id="llm-triage",
            current_model_id="gpt-4.1",
        ),
    )

    assert profile.operational_usable_runs == 0
    assert profile.model_performance == {}


def test_collect_candidates_uses_workflow_chat_model_filter():
    """자동 라우터 후보는 LLM 노드에서 실행 가능한 채팅 모델로만 제한한다."""
    models = [
        SimpleNamespace(
            model_id_for_api_call="gpt-4.1-mini",
            name="GPT-4.1 Mini",
            type="chat",
            is_active=True,
            input_price_1k=Decimal("0.0004"),
            output_price_1k=Decimal("0.0016"),
        ),
        SimpleNamespace(
            model_id_for_api_call="gpt-realtime-mini",
            name="GPT Realtime Mini",
            type="chat",
            is_active=True,
            input_price_1k=Decimal("0.0006"),
            output_price_1k=Decimal("0.0024"),
        ),
        SimpleNamespace(
            model_id_for_api_call="gpt-4.1-mini-2025-04-14",
            name="GPT-4.1 Mini Versioned",
            type="chat",
            is_active=True,
            input_price_1k=Decimal("0.0004"),
            output_price_1k=Decimal("0.0016"),
        ),
        SimpleNamespace(
            model_id_for_api_call="text-embedding-3-small",
            name="Text Embedding 3 Small",
            type="embedding",
            is_active=True,
            input_price_1k=Decimal("0.00002"),
            output_price_1k=Decimal("0"),
        ),
    ]

    candidates = ModelRouter.collect_candidates(
        _CandidateSession(models), organization_id=uuid4()
    )

    assert [candidate.model_id for candidate in candidates] == ["gpt-4.1-mini"]


def test_recommendation_service_does_not_require_auto_toggle():
    """모델 추천 분석은 자동 라우팅 토글 없이 현재 모델과 운영 로그 기준으로 계산된다."""
    decision = ModelRouter.resolve(
        ModelRouterContext(
            workflow_id="workflow-1",
            node_id="llm-triage",
            current_model_id="gpt-4.1",
            candidate_models=[
                _candidate("gpt-4.1-mini", 0.01),
                _candidate("gpt-4.1", 0.1),
            ],
            node_profile=NodeRunProfile(operational_usable_runs=200),
        )
    )

    assert decision.routing_stage == "optimized"
    assert decision.selected_model_id == "gpt-4.1"


def test_runtime_policy_evaluator_matches_high_risk_rule():
    """실행 시점 라우터는 저장된 policy의 도메인 keyword rule만 평가한다."""
    policy = {
        "active_policy": {
            "default_model_id": "gpt-4.1-mini",
            "fallback_model_id": "gpt-4.1",
            "rules": [
                {
                    "id": "low-risk-simple",
                    "priority": 20,
                    "when": {"keyword_any": ["다운로드", "위치"]},
                    "selected_model_id": "gpt-4o-mini",
                    "fallback_model_id": "gpt-4.1-mini",
                    "reason_code": "simple_low_risk",
                },
                {
                    "id": "high-risk-customer",
                    "priority": 10,
                    "when": {"keyword_any": ["SLA", "보상", "결제 API"]},
                    "selected_model_id": "gpt-4.1",
                    "reason_code": "high_risk_requires_strong_model",
                },
            ],
        }
    }

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={
            "message": "SLA 위반 가능성이 있는 결제 API 장애입니다. 보상 여부도 검토해 주세요.",
            "customerTier": "enterprise",
        },
        node_data=SimpleNamespace(
            model_id="gpt-4.1-mini",
            fallback_model_id="gpt-4.1",
            knowledgeBases=[],
            output_format={"type": "json"},
            system_prompt="",
            user_prompt="",
            assistant_prompt="",
        ),
    )

    assert decision.selected_model_id == "gpt-4.1"
    assert decision.fallback_model_id is None
    assert decision.matched_rule_id == "high-risk-customer"
    assert decision.reason_code == "high_risk_requires_strong_model"
    assert decision.runtime_context.risk_level == "medium"
    assert decision.runtime_context.input_length_bucket == "short"


def test_runtime_policy_evaluator_matches_low_risk_rule_and_uses_fallback():
    """keyword 조건은 코드 상수가 아니라 active policy rule에 있을 때만 동작한다."""
    policy = {
        "active_policy": {
            "default_model_id": "gpt-4.1-mini",
            "fallback_model_id": "gpt-4.1",
            "rules": [
                {
                    "id": "low-risk-simple",
                    "priority": 10,
                    "when": {"keyword_any": ["다운로드", "위치"]},
                    "selected_model_id": "gpt-4o-mini",
                    "fallback_model_id": "gpt-4.1-mini",
                    "reason_code": "simple_low_risk",
                },
            ],
        }
    }

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "정산 파일 다운로드 위치를 안내해 주세요."},
        node_data=SimpleNamespace(
            model_id="gpt-4.1",
            fallback_model_id="gpt-4.1",
            knowledgeBases=[],
            output_format={"type": "text"},
            system_prompt="",
            user_prompt="",
            assistant_prompt="",
        ),
    )

    assert decision.selected_model_id == "gpt-4o-mini"
    assert decision.fallback_model_id == "gpt-4.1-mini"
    assert decision.matched_rule_id == "low-risk-simple"
    assert decision.runtime_context.intent == "generate"


def test_runtime_policy_evaluator_prioritizes_specific_keyword_rule_over_generic_rule():
    """judge가 낮은 우선순위 숫자를 잘못 줘도 keyword rule은 generic rule에 가려지지 않는다."""
    policy = {
        "active_policy": {
            "default_model_id": "gpt-4.1-mini",
            "fallback_model_id": "gpt-4.1",
            "rules": [
                {
                    "id": "generic-short-json",
                    "priority": 10,
                    "when": {
                        "output_format": "json",
                        "knowledge_enabled": False,
                        "input_length_bucket": "short",
                    },
                    "selected_model_id": "gpt-4o-mini",
                    "fallback_model_id": "gpt-4.1-mini",
                    "reason_code": "generic_short_json",
                },
                {
                    "id": "domain-risk-keyword",
                    "priority": 50,
                    "when": {
                        "customer_facing": True,
                        "keyword_any": ["치명", "SLA", "보상"],
                    },
                    "selected_model_id": "gpt-4.1",
                    "fallback_model_id": None,
                    "reason_code": "domain_keyword_quality",
                },
            ],
        }
    }

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={
            "message": "SLA 위반 가능성이 있는 치명 장애입니다. 보상 안내도 검토해 주세요."
        },
        node_data=SimpleNamespace(
            model_id="gpt-4.1-mini",
            fallback_model_id="gpt-4.1",
            knowledgeBases=[],
            output_format={"type": "json", "schema": {"type": "object"}},
            system_prompt="",
            user_prompt="",
            assistant_prompt="",
            model_routing_context={"customer_facing": True},
        ),
    )

    assert decision.selected_model_id == "gpt-4.1"
    assert decision.matched_rule_id == "domain-risk-keyword"
    assert decision.reason_code == "domain_keyword_quality"


def test_runtime_policy_evaluator_rejects_unknown_condition_keys():
    """judge가 허용되지 않은 condition key를 만들면 rule을 넓게 매칭하지 않는다."""
    policy = {
        "active_policy": {
            "default_model_id": "gpt-4.1-mini",
            "fallback_model_id": "gpt-4.1",
            "rules": [
                {
                    "id": "bad-unknown-key",
                    "priority": 10,
                    "when": {
                        "customer_facing": True,
                        "customer_support_ticket_triage": True,
                    },
                    "selected_model_id": "gpt-4.1",
                    "fallback_model_id": None,
                    "reason_code": "bad_unknown_condition",
                },
            ],
        }
    }

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "고객 문의입니다."},
        node_data=SimpleNamespace(
            model_id="gpt-4.1-mini",
            fallback_model_id="gpt-4.1",
            knowledgeBases=[],
            output_format={"type": "text"},
            system_prompt="",
            user_prompt="",
            assistant_prompt="",
            model_routing_context={"customer_facing": True},
        ),
    )

    assert decision.selected_model_id == "gpt-4.1-mini"
    assert decision.matched_rule_id is None
    assert decision.reason_code == "policy_default"


def test_runtime_policy_evaluator_falls_back_to_default_when_rule_model_unavailable():
    """사용 가능한 모델 목록에서 제외된 rule 모델은 건너뛰고 default 모델로 닫는다."""
    policy = {
        "active_policy": {
            "default_model_id": "gpt-4.1-mini",
            "fallback_model_id": "gpt-4.1",
            "rules": [
                {
                    "id": "low-risk-simple",
                    "priority": 10,
                    "when": {"keyword_any": ["다운로드", "위치"]},
                    "selected_model_id": "missing-model",
                    "fallback_model_id": "also-missing",
                    "reason_code": "simple_low_risk",
                },
            ],
        }
    }

    decision = ModelRouter.resolve_policy(
        policy,
        inputs={"message": "다운로드 위치를 알려 주세요."},
        node_data=SimpleNamespace(
            model_id="gpt-4.1-mini",
            fallback_model_id="gpt-4.1",
            knowledgeBases=[],
            output_format={"type": "text"},
            system_prompt="",
            user_prompt="",
            assistant_prompt="",
        ),
        available_model_ids=["gpt-4.1-mini", "gpt-4.1"],
    )

    assert decision.selected_model_id == "gpt-4.1-mini"
    assert decision.fallback_model_id == "gpt-4.1"
    assert decision.matched_rule_id is None
    assert decision.reason_code == "policy_default"


def test_runtime_context_does_not_classify_domain_keywords_by_itself():
    """도메인 키워드는 런타임 코드가 아니라 저장된 policy rule에서만 의미를 가진다."""
    context = ModelRouter.infer_runtime_context(
        {
            "message": "SLA 위반 가능성이 있는 결제 API 장애입니다. 보상 여부도 검토해 주세요."
        },
        SimpleNamespace(
            model_id="gpt-4.1-mini",
            fallback_model_id="gpt-4.1",
            knowledgeBases=[],
            output_format={"type": "json", "schema": {"type": "object"}},
            system_prompt="",
            user_prompt="",
            assistant_prompt="",
            task_type="generate",
        ),
    )

    assert context.risk_level == "medium"
    assert context.intent == "generate"
    assert context.schema_required is True
    assert context.output_format == "json"
    assert "keywords" not in context.as_metadata()
