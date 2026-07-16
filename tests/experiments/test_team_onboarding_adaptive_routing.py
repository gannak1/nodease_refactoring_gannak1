from collections import Counter

from scripts.experiment_team_onboarding_adaptive_routing import (
    DEFAULT_MAX_PROVIDER_CALLS,
    FINANCE_EMERGENCE_QUESTIONS,
    SALES_RETURN_QUESTIONS,
    _cohort_lookup,
    _failed_observation,
    _wait_for_policy_settle,
    _wait_for_run_detail,
    build_experiment_cases,
    estimate_provider_call_ceiling,
)


def test_team_onboarding_seed_has_three_valid_routing_cohort_drafts():
    from apps.shared.db.demo_seed import _team_onboarding_adaptive_routing_graph

    graph = _team_onboarding_adaptive_routing_graph()
    llm_node = next(node for node in graph["nodes"] if node["id"] == "llm-answer")
    drafts = llm_node["data"]["model_routing_policy"]["cohort_drafts"]

    assert len(drafts) == 3
    assert all(len(draft.get("representative_examples") or []) >= 3 for draft in drafts)


def test_failed_deployment_call_is_recorded_without_stopping_the_experiment():
    case = build_experiment_cases(shuffle_seed=270)[0]

    observation = _failed_observation(
        sequence=1,
        case=case,
        policy={
            "status": "active",
            "adaptive": {
                "cohorts": [{"key": "sales_enablement", "status": "proposed"}],
                "latest_batch": None,
            },
        },
    )

    assert observation.run_id == ""
    assert observation.run_status == "failed"
    assert observation.node_status == "unknown"
    assert observation.error_code == "deployment_run_failed"
    assert [
        (cohort["key"], cohort["status"])
        for cohort in observation.cohort_states
    ] == [("sales_enablement", "proposed")]


def test_source_filename_detection_reads_cited_pdf_names_from_answer_text():
    from scripts.experiment_team_onboarding_adaptive_routing import (
        _find_source_filenames,
    )

    found = _find_source_filenames(
        {
            "answer_text": (
                "보안 교육을 먼저 완료합니다. "
                "출처: `company_common_onboarding.pdf`, platform_team_onboarding_v4.pdf"
            )
        }
    )

    assert found == {
        "company_common_onboarding.pdf",
        "platform_team_onboarding_v4.pdf",
    }


def test_dataset_drives_discovery_dormancy_and_reactivation_in_80_runs():
    cases = build_experiment_cases(shuffle_seed=270)

    assert len(cases) == 80
    assert len({case.case_id for case in cases}) == 80
    assert len({case.question for case in cases}) == 80
    assert [case.phase for case in cases[:6]] == ["sales_seed"] * 6
    assert [case.phase for case in cases[6:16]] == ["finance_emergence"] * 10
    assert [case.phase for case in cases[16:18]] == ["finance_validation"] * 2
    assert [case.phase for case in cases[-5:]] == ["post_validation"] * 5

    decline_cases = [case for case in cases if case.phase == "sales_decline"]
    assert len(decline_cases) == 38
    assert all(case.expected_cohort_key != "sales_enablement" for case in decline_cases)

    counts = Counter(case.expected_cohort_key for case in cases)
    assert counts == {
        "sales_enablement": 11,
        "finance_operations": 12,
        "common_security": 29,
        "platform_access": 28,
    }


def test_finance_trend_cases_share_a_discoverable_business_context():
    assert len(FINANCE_EMERGENCE_QUESTIONS) == 10
    assert all("재무팀" in question for question in FINANCE_EMERGENCE_QUESTIONS)
    assert all("결산" in question for question in FINANCE_EMERGENCE_QUESTIONS)


def test_sales_return_cases_are_close_enough_to_reactivate_the_seed_cohort():
    assert len(SALES_RETURN_QUESTIONS) == 5
    assert all("영업팀" in question for question in SALES_RETURN_QUESTIONS)
    assert all("CRM" in question for question in SALES_RETURN_QUESTIONS)


def test_cohort_lookup_accepts_database_id_and_runtime_cohort_key():
    lookup = _cohort_lookup(
        {
            "adaptive": {
                "cohorts": [
                    {"id": "database-uuid", "key": "finance_operations", "label": "재무 결산"}
                ]
            }
        }
    )

    assert lookup["database-uuid"]["label"] == "재무 결산"
    assert lookup["finance_operations"]["label"] == "재무 결산"


def test_every_case_declares_rag_source_and_human_reason():
    cases = build_experiment_cases(shuffle_seed=270)

    assert all(case.expected_source_filename.endswith(".pdf") for case in cases)
    assert all(case.rationale.strip() for case in cases)
    assert all(case.question.strip() for case in cases)


def test_live_experiment_provider_call_ceiling_stays_below_guardrail():
    cases = build_experiment_cases(shuffle_seed=270)

    estimate = estimate_provider_call_ceiling(
        cases,
        max_cohorts=6,
        candidate_models_per_cohort=4,
        replays_per_candidate=2,
    )

    assert estimate <= DEFAULT_MAX_PROVIDER_CALLS


def test_run_detail_waits_until_target_node_log_is_terminal():
    class FakeClient:
        def __init__(self):
            self.responses = [
                {
                    "id": "run-1",
                    "status": "running",
                    "node_runs": [
                        {"node_id": "llm-answer", "status": "running"}
                    ],
                },
                {
                    "id": "run-1",
                    "status": "success",
                    "node_runs": [
                        {"node_id": "llm-answer", "status": "success"}
                    ],
                },
            ]
            self.calls = 0

        def get_json(self, path, *, timeout=None):
            response = self.responses[min(self.calls, len(self.responses) - 1)]
            self.calls += 1
            return response

    client = FakeClient()

    result = _wait_for_run_detail(
        client,
        workflow_id="workflow-1",
        run_id="run-1",
        node_id="llm-answer",
        timeout_seconds=1,
        poll_interval_seconds=0,
    )

    assert result["status"] == "success"
    assert client.calls == 2


def test_policy_settle_waits_for_async_validation_to_finish():
    class FakeClient:
        def __init__(self):
            self.responses = [
                {"status": "collecting", "adaptive": {"latest_batch": None}},
                {
                    "status": "refreshing",
                    "adaptive": {"latest_batch": {"status": "running"}},
                },
                {
                    "status": "active",
                    "adaptive": {"latest_batch": {"status": "completed"}},
                },
            ]
            self.calls = 0

        def get_json(self, path, *, timeout=None):
            response = self.responses[min(self.calls, len(self.responses) - 1)]
            self.calls += 1
            return response

    client = FakeClient()

    result = _wait_for_policy_settle(
        client,
        workflow_id="workflow-1",
        node_id="llm-answer",
        timeout_seconds=1,
        poll_interval_seconds=0,
        minimum_wait_seconds=0,
    )

    assert result["status"] == "active"
    assert client.calls == 3


def test_policy_settle_accepts_completed_collecting_policy_without_routes():
    """검증이 끝났지만 활성 규칙이 없으면 다음 실험 입력으로 진행한다."""

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def get_json(self, path, *, timeout=None):
            self.calls += 1
            return {
                "status": "collecting",
                "adaptive": {"latest_batch": {"status": "completed"}},
            }

    client = FakeClient()

    result = _wait_for_policy_settle(
        client,
        workflow_id="workflow-1",
        node_id="llm-answer",
        timeout_seconds=1,
        poll_interval_seconds=0,
        minimum_wait_seconds=0,
    )

    assert result["status"] == "collecting"
    assert client.calls == 1
