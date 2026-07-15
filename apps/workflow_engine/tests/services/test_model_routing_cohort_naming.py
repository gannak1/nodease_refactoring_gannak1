from types import SimpleNamespace
from uuid import uuid4

from apps.shared.db.models.model_routing_cohort import (
    LLMNodeModelRoutingCohort,
    LLMNodeModelRoutingObservation,
)
from apps.shared.db.models.workflow_run import WorkflowNodeRun
from apps.workflow_engine.services.model_routing_cohort_naming import (
    AdaptiveModelRoutingCohortNamingService,
)


class _Query:
    def __init__(self, rows):
        self.rows = list(rows)

    def filter(self, *_args):
        return self

    def order_by(self, *_args):
        return self

    def limit(self, value):
        self.rows = self.rows[:value]
        return self

    def all(self):
        return self.rows


class _Db:
    def __init__(self, *, cohort, observations, node_runs):
        self.cohort = cohort
        self.observations = observations
        self.node_runs = node_runs
        self.flush_count = 0

    def query(self, model):
        if model is LLMNodeModelRoutingCohort:
            return _Query([self.cohort])
        if model is LLMNodeModelRoutingObservation:
            return _Query(self.observations)
        if model is WorkflowNodeRun:
            return _Query(self.node_runs)
        raise AssertionError(f"unexpected query model: {model}")

    def flush(self):
        self.flush_count += 1


def _generic_auto_cohort(policy_id):
    return SimpleNamespace(
        id=uuid4(),
        policy_id=policy_id,
        cohort_key="auto-2f875d8e563f10284722",
        label="자동 발견 입력군 4",
        label_en="auto_cohort_4",
        source="auto",
    )


def test_pending_auto_cohort_gets_business_label_and_key_from_redacted_samples():
    """FR-011-A54: 자동 입력군은 순번 대신 사람이 이해할 수 있는 이름을 사용한다."""
    policy_id = uuid4()
    cohort = _generic_auto_cohort(policy_id)
    node_run_ids = [uuid4(), uuid4(), uuid4()]
    observations = [
        SimpleNamespace(workflow_node_run_id=node_run_id)
        for node_run_id in node_run_ids
    ]
    node_runs = [
        SimpleNamespace(
            id=node_run_ids[0],
            inputs={"question": "월말 결산 마감 절차와 제출 기한을 알려 주세요."},
        ),
        SimpleNamespace(
            id=node_run_ids[1],
            inputs={"question": "지급 승인에 필요한 증빙과 결재 순서를 확인하고 싶습니다."},
        ),
        SimpleNamespace(
            id=node_run_ids[2],
            inputs={"question": "재무팀 비용 정산과 지급 승인 기준을 알려 주세요."},
        ),
    ]
    policy = SimpleNamespace(
        id=policy_id,
        active_policy={
            "rules": [
                {"when": {"semantic_cohort_id": cohort.cohort_key}}
            ],
            "semantic_router": {
                "routes": [
                    {"cohort_id": cohort.cohort_key, "label": cohort.label}
                ]
            },
        },
        pending_policy={
            "rules": [
                {"when": {"semantic_cohort_id": cohort.cohort_key}}
            ]
        },
    )
    db = _Db(cohort=cohort, observations=observations, node_runs=node_runs)
    received_samples = []

    renamed = AdaptiveModelRoutingCohortNamingService.name_pending_auto_cohorts(
        db,
        policy=policy,
        node_data={"model_routing_context": {"input_paths": ["question"]}},
        invoke=lambda samples: received_samples.extend(samples)
        or {
            "label": "재무 결산·지급 승인",
            "key": "finance_closing_approval",
        },
    )

    assert renamed == [cohort]
    assert cohort.label == "재무 결산·지급 승인"
    assert cohort.cohort_key == "finance_closing_approval"
    assert cohort.label_en == "finance_closing_approval"
    assert len(received_samples) == 3
    assert policy.active_policy["rules"][0]["when"]["semantic_cohort_id"] == (
        "finance_closing_approval"
    )
    assert policy.active_policy["semantic_router"]["routes"][0] == {
        "cohort_id": "finance_closing_approval",
        "label": "재무 결산·지급 승인",
    }
    assert policy.pending_policy["rules"][0]["when"]["semantic_cohort_id"] == (
        "finance_closing_approval"
    )
    assert db.flush_count == 1


def test_invalid_naming_response_keeps_existing_auto_identity():
    """FR-011-A54: 이름 생성 실패가 입력군 발견과 라우팅을 실패시키지 않는다."""
    policy_id = uuid4()
    cohort = _generic_auto_cohort(policy_id)
    node_run_id = uuid4()
    policy = SimpleNamespace(id=policy_id, active_policy={})
    db = _Db(
        cohort=cohort,
        observations=[SimpleNamespace(workflow_node_run_id=node_run_id)],
        node_runs=[
            SimpleNamespace(
                id=node_run_id,
                inputs={"question": "법인카드 결산 방법을 알려 주세요."},
            )
        ],
    )

    renamed = AdaptiveModelRoutingCohortNamingService.name_pending_auto_cohorts(
        db,
        policy=policy,
        node_data={"model_routing_context": {"input_paths": ["question"]}},
        invoke=lambda _samples: {"label": "", "key": "!!!"},
    )

    assert renamed == []
    assert cohort.label == "자동 발견 입력군 4"
    assert cohort.cohort_key == "auto-2f875d8e563f10284722"
    assert db.flush_count == 0


def test_duplicate_generated_key_gets_stable_suffix():
    """FR-011-A54: 같은 주제명이 생겨도 policy 내 key 충돌을 만들지 않는다."""
    resolved = AdaptiveModelRoutingCohortNamingService.unique_key(
        "finance_closing_approval",
        existing_keys={"finance_closing_approval"},
        stable_source="auto-2f875d8e563f10284722",
    )

    assert resolved.startswith("finance_closing_approval_")
    assert resolved == AdaptiveModelRoutingCohortNamingService.unique_key(
        "finance_closing_approval",
        existing_keys={"finance_closing_approval"},
        stable_source="auto-2f875d8e563f10284722",
    )


def test_retired_auto_cohort_is_not_renamed_but_its_key_still_reserves_uniqueness():
    """FR-011-A54: 종료된 이력에는 비용을 쓰지 않고 key 충돌만 방지한다."""
    cohort = _generic_auto_cohort(uuid4())
    cohort.status = "retired"

    assert AdaptiveModelRoutingCohortNamingService._needs_naming(cohort) is False
    assert (
        AdaptiveModelRoutingCohortNamingService.unique_key(
            "finance_closing_approval",
            existing_keys={"finance_closing_approval"},
            stable_source=cohort.cohort_key,
        )
        != "finance_closing_approval"
    )
