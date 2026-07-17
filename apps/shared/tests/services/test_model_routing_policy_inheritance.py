from uuid import uuid4

from sqlalchemy.sql.operators import eq, in_op

from apps.shared.db.models.model_routing_cohort import (
    LLMNodeModelRoutingCohort,
    LLMNodeModelRoutingCohortExample,
    LLMNodeModelRoutingModelEvidence,
)
from apps.shared.db.models.model_routing_policy import LLMNodeModelRoutingPolicy
from apps.shared.services.model_routing_policy_inheritance import (
    ModelRoutingPolicyInheritanceService,
)
from apps.shared.services.node_config_fingerprint import llm_node_config_fingerprint


def test_inherits_policy_cohorts_and_evidence_for_same_llm_node():
    workflow_id = uuid4()
    source_deployment_id = uuid4()
    target_deployment_id = uuid4()
    source_policy = LLMNodeModelRoutingPolicy(
        id=uuid4(),
        workflow_id=workflow_id,
        deployment_id=source_deployment_id,
        node_id="llm-triage",
        organization_id=uuid4(),
        enabled=True,
        status="active",
        policy_version="routing-policy-v4",
        active_policy={
            "default_model_id": "gpt-4.1-mini",
            "fallback_model_id": "gpt-4.1",
            "rules": [
                {
                    "id": "support",
                    "selected_model_id": "gpt-4o-mini",
                    "when": {"semantic_cohort_id": "SOURCE_COHORT_ID"},
                }
            ],
            "semantic_router": {
                "routes": [{"cohort_id": "SOURCE_COHORT_ID", "label": "단순 안내 문의"}]
            },
        },
        pending_policy=None,
        refresh_every_runs=20,
        eligible_runs_since_last_refresh=11,
        validation_budget_usd=3,
        max_cohorts=6,
    )
    node_data = {
        "auto_model_routing": True,
        "model_id": "gpt-4.1",
        "system_prompt": "고객 문의를 처리합니다.",
        "user_prompt": "{{message}}",
        "knowledgeBases": [],
    }
    node_fingerprint = llm_node_config_fingerprint(node_data)
    source_cohort = LLMNodeModelRoutingCohort(
        id=uuid4(),
        policy_id=source_policy.id,
        cohort_key="routine_support",
        label="단순 안내 문의",
        label_en="routine_support",
        source="manual",
        status="active",
        required=True,
        safety_protected=False,
        encoder_model_id="text-embedding-3-large",
        centroid_embedding=[0.1, 0.2],
        observation_count=12,
        review_window_count=2,
        low_share_streak=0,
        last_traffic_share=0.5,
        node_config_fingerprint=node_fingerprint,
    )
    source_evidence = LLMNodeModelRoutingModelEvidence(
        id=uuid4(),
        cohort_id=source_cohort.id,
        model_id="gpt-4o-mini",
        node_config_fingerprint=node_fingerprint,
        evidence_version="evidence-v1",
        status="validated",
        sample_count=4,
        quality_summary={"schema_pass_rate": 1.0},
        efficiency_summary={"average_cost": 0.001},
        source_candidate_ids=["candidate-1"],
    )
    source_example = LLMNodeModelRoutingCohortExample(
        id=uuid4(),
        cohort_id=source_cohort.id,
        synthetic_text="비밀번호를 다시 설정하는 방법을 알려주세요.",
        embedding=[0.1, 0.2],
        ordinal=0,
    )
    source_policy.active_policy["rules"][0]["when"]["semantic_cohort_id"] = str(
        source_cohort.id
    )
    source_policy.active_policy["semantic_router"]["routes"][0]["cohort_id"] = str(
        source_cohort.id
    )
    db = _Db(
        {
            LLMNodeModelRoutingPolicy: [source_policy],
            LLMNodeModelRoutingCohort: [source_cohort],
            LLMNodeModelRoutingCohortExample: [source_example],
            LLMNodeModelRoutingModelEvidence: [source_evidence],
        }
    )

    inherited = ModelRoutingPolicyInheritanceService.inherit_for_deployment(
        db,
        workflow_id=workflow_id,
        source_deployment_id=source_deployment_id,
        target_deployment_id=target_deployment_id,
        target_graph={
            "nodes": [
                {
                    "id": "llm-triage",
                    "type": "llmNode",
                    "data": node_data,
                }
            ]
        },
    )

    assert inherited == 1
    target_policy = next(
        policy
        for policy in db.rows_for(LLMNodeModelRoutingPolicy)
        if policy.deployment_id == target_deployment_id
    )
    assert target_policy.policy_version == "routing-policy-v4"
    assert target_policy.active_policy is not source_policy.active_policy
    assert target_policy.eligible_runs_since_last_refresh == 0
    assert target_policy.refresh_requested_at is None

    target_cohort = next(
        cohort
        for cohort in db.rows_for(LLMNodeModelRoutingCohort)
        if cohort.policy_id == target_policy.id
    )
    assert target_cohort.cohort_key == "routine_support"
    assert target_cohort.status == "active"
    assert target_cohort.required is True
    assert (
        target_policy.active_policy["rules"][0]["when"]["semantic_cohort_id"]
        == str(target_cohort.id)
    )
    assert (
        target_policy.active_policy["semantic_router"]["routes"][0]["cohort_id"]
        == str(target_cohort.id)
    )

    target_example = next(
        example
        for example in db.rows_for(LLMNodeModelRoutingCohortExample)
        if example.cohort_id == target_cohort.id
    )
    assert target_example.synthetic_text == source_example.synthetic_text
    assert target_example.embedding == source_example.embedding
    assert target_example.embedding is not source_example.embedding

    target_evidence = next(
        evidence
        for evidence in db.rows_for(LLMNodeModelRoutingModelEvidence)
        if evidence.cohort_id == target_cohort.id
    )
    assert target_evidence.model_id == "gpt-4o-mini"
    assert target_evidence.status == "validated"
    assert target_evidence.quality_summary == source_evidence.quality_summary
    assert target_evidence.quality_summary is not source_evidence.quality_summary


def test_skips_inheritance_when_target_llm_configuration_changed():
    """FR-011: 같은 node id여도 설정이 바뀌면 이전 정책을 물려받지 않는다."""
    workflow_id = uuid4()
    source_deployment_id = uuid4()
    target_deployment_id = uuid4()
    source_data = {
        "auto_model_routing": True,
        "model_id": "gpt-4.1",
        "system_prompt": "고객 문의를 처리합니다.",
        "user_prompt": "{{message}}",
        "knowledgeBases": [],
    }
    source_policy = LLMNodeModelRoutingPolicy(
        id=uuid4(),
        workflow_id=workflow_id,
        deployment_id=source_deployment_id,
        node_id="llm-triage",
        organization_id=uuid4(),
        enabled=True,
        active_policy={"default_model_id": "gpt-4.1-mini"},
    )
    source_cohort = LLMNodeModelRoutingCohort(
        id=uuid4(),
        policy_id=source_policy.id,
        cohort_key="routine_support",
        label="단순 안내 문의",
        label_en="routine_support",
        source="manual",
        status="active",
        required=False,
        safety_protected=False,
        encoder_model_id="text-embedding-3-large",
        centroid_embedding=[0.1, 0.2],
        node_config_fingerprint=llm_node_config_fingerprint(source_data),
    )
    db = _Db(
        {
            LLMNodeModelRoutingPolicy: [source_policy],
            LLMNodeModelRoutingCohort: [source_cohort],
        }
    )

    inherited = ModelRoutingPolicyInheritanceService.inherit_for_deployment(
        db,
        workflow_id=workflow_id,
        source_deployment_id=source_deployment_id,
        target_deployment_id=target_deployment_id,
        target_graph={
            "nodes": [
                {
                    "id": "llm-triage",
                    "type": "llmNode",
                    "data": {**source_data, "model_id": "gpt-5.4-mini"},
                }
            ]
        },
    )

    assert inherited == 0
    assert db.rows_for(LLMNodeModelRoutingPolicy) == [source_policy]


def test_skips_inheritance_when_target_node_disables_automatic_routing():
    workflow_id = uuid4()
    source_deployment_id = uuid4()
    target_deployment_id = uuid4()
    source_policy = LLMNodeModelRoutingPolicy(
        id=uuid4(),
        workflow_id=workflow_id,
        deployment_id=source_deployment_id,
        node_id="llm-triage",
        organization_id=uuid4(),
        enabled=True,
        active_policy={"default_model_id": "gpt-4.1-mini"},
    )
    db = _Db({LLMNodeModelRoutingPolicy: [source_policy]})

    inherited = ModelRoutingPolicyInheritanceService.inherit_for_deployment(
        db,
        workflow_id=workflow_id,
        source_deployment_id=source_deployment_id,
        target_deployment_id=target_deployment_id,
        target_graph={
            "nodes": [
                {
                    "id": "llm-triage",
                    "type": "llmNode",
                    "data": {"auto_model_routing": False},
                }
            ]
        },
    )

    assert inherited == 0
    assert db.rows_for(LLMNodeModelRoutingPolicy) == [source_policy]


def test_skips_legacy_policy_inheritance_for_bootstrap_strategy():
    """새 bootstrap artifact는 이전 deployment runtime policy를 복제하지 않는다."""
    workflow_id = uuid4()
    source_policy = LLMNodeModelRoutingPolicy(
        id=uuid4(),
        workflow_id=workflow_id,
        deployment_id=uuid4(),
        node_id="llm-triage",
        organization_id=uuid4(),
        enabled=True,
        active_policy={"default_model_id": "gpt-4.1-mini"},
    )
    db = _Db({LLMNodeModelRoutingPolicy: [source_policy]})

    inherited = ModelRoutingPolicyInheritanceService.inherit_for_deployment(
        db,
        workflow_id=workflow_id,
        source_deployment_id=source_policy.deployment_id,
        target_deployment_id=uuid4(),
        target_graph={
            "nodes": [
                {
                    "id": "llm-triage",
                    "type": "llmNode",
                    "data": {
                        "auto_model_routing": True,
                        "model_routing_strategy": "bootstrap_mdeberta_difficulty_v1",
                        "model_routing_bootstrap_id": str(uuid4()),
                    },
                }
            ]
        },
    )

    assert inherited == 0
    assert db.rows_for(LLMNodeModelRoutingPolicy) == [source_policy]


class _Db:
    def __init__(self, rows_by_model):
        self.rows_by_model = {model: list(rows) for model, rows in rows_by_model.items()}

    def query(self, model):
        return _Query(self.rows_by_model.setdefault(model, []))

    def add(self, row):
        if getattr(row, "id", None) is None:
            row.id = uuid4()
        self.rows_by_model.setdefault(type(row), []).append(row)

    def flush(self):
        pass

    def rows_for(self, model):
        return self.rows_by_model.setdefault(model, [])


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.expressions = []

    def filter(self, *expressions):
        self.expressions.extend(expressions)
        return self

    def all(self):
        return [row for row in self.rows if _matches(row, self.expressions)]

    def first(self):
        return next(iter(self.all()), None)


def _matches(row, expressions):
    for expression in expressions:
        column = str(expression.left).split(".")[-1]
        if not hasattr(row, column):
            continue
        expected = _right_value(expression.right)
        actual = getattr(row, column)
        if expression.operator is eq and actual != expected:
            return False
        if expression.operator is in_op and actual not in set(expected):
            return False
    return True


def _right_value(value):
    if hasattr(value, "value"):
        return value.value
    return value
