from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.gateway.services.cost_optimizer_parameter_recommendation_service import (
    CostOptimizerParameterRecommendationService,
)
from apps.shared.db.models.workflow_run import NodeRunStatus, RunStatus, RunTriggerMode


def test_fr12_recommends_max_tokens_from_deployed_successful_usage_only():
    workflow_id = uuid4()
    deployed_run_ids = [uuid4() for _ in range(24)]
    manual_run_id = uuid4()
    candidate_run_id = uuid4()
    db = _RecommendationDb(
        workflow_runs=[
            *[
                _workflow_run(workflow_id, run_id, deployment_id=uuid4())
                for run_id in deployed_run_ids
            ],
            _workflow_run(workflow_id, manual_run_id, deployment_id=None),
            _workflow_run(workflow_id, candidate_run_id, deployment_id=uuid4()),
        ],
        node_runs=[
            *[
                _node_run(run_id, completion_tokens=420, finish_reason="stop")
                for run_id in deployed_run_ids
            ],
            _node_run(manual_run_id, completion_tokens=2200, finish_reason="length"),
            _node_run(candidate_run_id, completion_tokens=2100, finish_reason="length"),
        ],
        usage_logs=[
            *[
                _usage_log(workflow_id, run_id, completion_tokens=420)
                for run_id in deployed_run_ids
            ],
            _usage_log(workflow_id, manual_run_id, completion_tokens=2200),
            _usage_log(
                workflow_id,
                candidate_run_id,
                completion_tokens=2100,
                cost_optimizer_candidate_id=uuid4(),
            ),
        ],
    )

    response = CostOptimizerParameterRecommendationService.recommend(
        db,
        workflow=_workflow(workflow_id, max_tokens=4096),
        node_id="llm-triage",
    )

    max_tokens = _recommendation(response, "max_tokens")
    assert response["analysis_stage"] == "recommendations_available"
    assert max_tokens["confidence"] == "high"
    assert max_tokens["risk"] == "low"
    assert max_tokens["apply_mode"] == "experiment_required"
    assert max_tokens["suggested_value"] < 4096
    assert max_tokens["candidate_patch"] == {
        "parameters": {"max_tokens": max_tokens["suggested_value"]}
    }
    assert max_tokens["evidence"]["sample_count"] == 24
    assert max_tokens["evidence"]["completion_tokens_p95"] == 420


def test_fr12_returns_insufficient_logs_until_deployed_samples_reach_threshold():
    workflow_id = uuid4()
    run_ids = [uuid4() for _ in range(19)]
    db = _RecommendationDb(
        workflow_runs=[
            _workflow_run(workflow_id, run_id, deployment_id=uuid4())
            for run_id in run_ids
        ],
        node_runs=[
            _node_run(run_id, completion_tokens=420, finish_reason="stop")
            for run_id in run_ids
        ],
        usage_logs=[
            _usage_log(workflow_id, run_id, completion_tokens=420)
            for run_id in run_ids
        ],
    )

    response = CostOptimizerParameterRecommendationService.recommend(
        db,
        workflow=_workflow(workflow_id, max_tokens=4096),
        node_id="llm-triage",
    )

    assert response["analysis_stage"] == "insufficient_logs"
    assert [
        recommendation["parameter_key"]
        for recommendation in response["recommendations"]
    ] == ["model_routing.enable"]
    assert response["profile"]["sample_count"] == 19
    assert response["warnings"][0]["code"] == "operation_logs_insufficient"


def test_fr12_recommends_enabling_model_routing_even_with_insufficient_logs():
    workflow_id = uuid4()
    db = _RecommendationDb(workflow_runs=[], node_runs=[], usage_logs=[])

    response = CostOptimizerParameterRecommendationService.recommend(
        db,
        workflow=_workflow(
            workflow_id,
            auto_model_routing=False,
            refresh_every_runs=100,
        ),
        node_id="llm-triage",
    )

    routing = _recommendation(response, "model_routing.enable")
    shorten = _recommendation(response, "model_routing.refresh_interval_shorten")
    assert response["analysis_stage"] == "insufficient_logs"
    assert routing["recommendation_type"] == "model_routing_policy"
    assert routing["current_value"] is False
    assert routing["suggested_value"] is True
    assert routing["apply_mode"] == "direct_policy_update"
    assert routing["candidate_patch"] == {"auto_model_routing": True}
    assert shorten["suggested_value"] == 20


def test_fr12_recommends_model_routing_refresh_interval_changes():
    workflow_id = uuid4()
    run_ids = [uuid4() for _ in range(20)]
    db = _RecommendationDb(
        workflow_runs=[
            _workflow_run(workflow_id, run_id, deployment_id=uuid4())
            for run_id in run_ids
        ],
        node_runs=[
            _node_run(run_id, completion_tokens=500, finish_reason="stop")
            for run_id in run_ids
        ],
        usage_logs=[
            _usage_log(workflow_id, run_id, completion_tokens=500)
            for run_id in run_ids
        ],
    )

    shorten_response = CostOptimizerParameterRecommendationService.recommend(
        db,
        workflow=_workflow(
            workflow_id,
            auto_model_routing=True,
            refresh_every_runs=100,
        ),
        node_id="llm-triage",
    )
    relax_response = CostOptimizerParameterRecommendationService.recommend(
        db,
        workflow=_workflow(
            workflow_id,
            auto_model_routing=True,
            refresh_every_runs=5,
        ),
        node_id="llm-triage",
    )

    shorten = _recommendation(
        shorten_response,
        "model_routing.refresh_interval_shorten",
    )
    relax = _recommendation(
        relax_response,
        "model_routing.refresh_interval_relax",
    )

    assert shorten["current_value"] == 100
    assert shorten["suggested_value"] == 20
    assert shorten["candidate_patch"] == {
        "model_routing_policy": {"refresh": {"refresh_every_runs": 20}}
    }
    assert relax["current_value"] == 5
    assert relax["suggested_value"] == 20
    assert relax["candidate_patch"] == {
        "model_routing_policy": {"refresh": {"refresh_every_runs": 20}}
    }


def test_fr12_lowers_confidence_when_finish_reason_is_unknown():
    workflow_id = uuid4()
    run_ids = [uuid4() for _ in range(20)]
    db = _RecommendationDb(
        workflow_runs=[
            _workflow_run(workflow_id, run_id, deployment_id=uuid4())
            for run_id in run_ids
        ],
        node_runs=[_node_run(run_id, completion_tokens=500) for run_id in run_ids],
        usage_logs=[
            _usage_log(workflow_id, run_id, completion_tokens=500)
            for run_id in run_ids
        ],
    )

    response = CostOptimizerParameterRecommendationService.recommend(
        db,
        workflow=_workflow(workflow_id, max_tokens=4096),
        node_id="llm-triage",
    )

    max_tokens = _recommendation(response, "max_tokens")
    assert max_tokens["confidence"] == "medium"
    assert "길이 잘림 근거 부족" in max_tokens["reason"]


def test_fr12_blocks_token_and_rag_reduction_when_quality_signals_are_bad():
    workflow_id = uuid4()
    run_ids = [uuid4() for _ in range(20)]
    db = _RecommendationDb(
        workflow_runs=[
            _workflow_run(workflow_id, run_id, deployment_id=uuid4())
            for run_id in run_ids
        ],
        node_runs=[
            _node_run(
                run_id,
                completion_tokens=500,
                finish_reason="length" if index < 4 else "stop",
                downstream_status="failed" if index < 3 else "pass",
                evidence_sufficient=False,
                context_token_estimate=1800,
                retrieved_chunk_count=10,
            )
            for index, run_id in enumerate(run_ids)
        ],
        usage_logs=[
            _usage_log(workflow_id, run_id, completion_tokens=500, prompt_tokens=2400)
            for run_id in run_ids
        ],
    )

    response = CostOptimizerParameterRecommendationService.recommend(
        db,
        workflow=_workflow(
            workflow_id,
            max_tokens=4096,
            knowledge={"topK": 10, "retrievedContextMaxChars": 6000},
        ),
        node_id="llm-triage",
    )

    assert _recommendation(response, "max_tokens") is None
    assert _recommendation(response, "rag.top_k") is None
    assert any(warning["code"] == "quality_signal_unstable" for warning in response["warnings"])
    assert any(warning["code"] == "rag_evidence_insufficient" for warning in response["warnings"])


def test_fr12_recommends_temperature_for_schema_node_but_not_plain_generation():
    workflow_id = uuid4()
    run_ids = [uuid4() for _ in range(20)]
    db = _RecommendationDb(
        workflow_runs=[
            _workflow_run(workflow_id, run_id, deployment_id=uuid4())
            for run_id in run_ids
        ],
        node_runs=[
            _node_run(
                run_id,
                completion_tokens=500,
                finish_reason="stop",
                schema_status="failed" if index < 3 else "pass",
            )
            for index, run_id in enumerate(run_ids)
        ],
        usage_logs=[
            _usage_log(workflow_id, run_id, completion_tokens=500)
            for run_id in run_ids
        ],
    )

    json_response = CostOptimizerParameterRecommendationService.recommend(
        db,
        workflow=_workflow(
            workflow_id,
            temperature=0.9,
            output_format={"type": "json", "schema": {"type": "object"}},
        ),
        node_id="llm-triage",
    )
    plain_response = CostOptimizerParameterRecommendationService.recommend(
        db,
        workflow=_workflow(workflow_id, temperature=0.9, output_format={"type": "text"}),
        node_id="llm-triage",
    )

    temperature = _recommendation(json_response, "temperature")
    assert temperature["suggested_value"] == pytest.approx(0.2)
    assert "schema" in temperature["reason"]
    assert _recommendation(plain_response, "temperature") is None


def test_fr12_recommends_claude_top_p_removal_for_runtime_compatibility():
    workflow_id = uuid4()
    run_ids = [uuid4() for _ in range(20)]
    db = _RecommendationDb(
        workflow_runs=[
            _workflow_run(workflow_id, run_id, deployment_id=uuid4())
            for run_id in run_ids
        ],
        node_runs=[
            _node_run(run_id, completion_tokens=500, finish_reason="stop")
            for run_id in run_ids
        ],
        usage_logs=[
            _usage_log(workflow_id, run_id, completion_tokens=500)
            for run_id in run_ids
        ],
    )

    response = CostOptimizerParameterRecommendationService.recommend(
        db,
        workflow=_workflow(
            workflow_id,
            max_tokens=2048,
            model_id="claude-sonnet-4",
            parameters={"max_tokens": 2048, "temperature": 0.2, "top_p": 0.8},
        ),
        node_id="llm-triage",
    )

    top_p = _recommendation(response, "top_p")
    assert top_p["suggested_value"] is None
    assert top_p["candidate_patch"] == {"parameters": {"top_p": None}}


def test_fr12_recommends_frequency_penalty_only_for_plain_repetitive_output():
    workflow_id = uuid4()
    run_ids = [uuid4() for _ in range(20)]
    db = _RecommendationDb(
        workflow_runs=[
            _workflow_run(workflow_id, run_id, deployment_id=uuid4())
            for run_id in run_ids
        ],
        node_runs=[
            _node_run(
                run_id,
                completion_tokens=700,
                finish_reason="stop",
                repetition_rate=0.21,
            )
            for run_id in run_ids
        ],
        usage_logs=[
            _usage_log(workflow_id, run_id, completion_tokens=700)
            for run_id in run_ids
        ],
    )

    plain_response = CostOptimizerParameterRecommendationService.recommend(
        db,
        workflow=_workflow(
            workflow_id,
            output_format={"type": "text"},
            parameters={"max_tokens": 2048, "temperature": 0.4, "frequency_penalty": 0},
        ),
        node_id="llm-triage",
    )
    json_response = CostOptimizerParameterRecommendationService.recommend(
        db,
        workflow=_workflow(
            workflow_id,
            output_format={"type": "json", "schema": {"type": "object"}},
            parameters={"max_tokens": 2048, "temperature": 0.4, "frequency_penalty": 0},
        ),
        node_id="llm-triage",
    )

    frequency_penalty = _recommendation(plain_response, "frequency_penalty")
    assert frequency_penalty["suggested_value"] == pytest.approx(0.2)
    assert _recommendation(json_response, "frequency_penalty") is None


def test_fr12_recommends_rag_context_controls_without_trimming_author_prompt():
    workflow_id = uuid4()
    run_ids = [uuid4() for _ in range(20)]
    db = _RecommendationDb(
        workflow_runs=[
            _workflow_run(workflow_id, run_id, deployment_id=uuid4())
            for run_id in run_ids
        ],
        node_runs=[
            _node_run(
                run_id,
                completion_tokens=500,
                finish_reason="stop",
                context_token_estimate=1800,
                retrieved_chunk_count=12,
                evidence_sufficient=True,
            )
            for run_id in run_ids
        ],
        usage_logs=[
            _usage_log(workflow_id, run_id, prompt_tokens=2400, completion_tokens=500)
            for run_id in run_ids
        ],
    )

    response = CostOptimizerParameterRecommendationService.recommend(
        db,
        workflow=_workflow(
            workflow_id,
            user_prompt="긴 업무 프롬프트 원문은 추천 응답에 노출되면 안 됩니다.",
            knowledge={"topK": 12, "retrievedContextMaxChars": 8000},
        ),
        node_id="llm-triage",
    )

    top_k = _recommendation(response, "rag.top_k")
    compression = _recommendation(response, "rag.retrieved_context_compression")

    assert top_k["suggested_value"] == 6
    assert top_k["candidate_patch"]["knowledge"]["top_k"] == 6
    assert compression["suggested_value"] == "light"
    assert "system_prompt" not in str(response)
    assert "user_prompt" not in str(response)
    assert "긴 업무 프롬프트" not in str(response)


def _recommendation(response, parameter_key):
    return next(
        (
            recommendation
            for recommendation in response["recommendations"]
            if recommendation["parameter_key"] == parameter_key
        ),
        None,
    )


def _workflow(
    workflow_id,
    *,
    max_tokens=2048,
    temperature=0.2,
    model_id="gpt-4.1-mini",
    auto_model_routing=None,
    refresh_every_runs=None,
    output_format=None,
    user_prompt="",
    knowledge=None,
    parameters=None,
):
    node_parameters = parameters or {"max_tokens": max_tokens, "temperature": temperature}
    data = {
        "title": "티켓 처리 판단",
        "model_id": model_id,
        "parameters": node_parameters,
        "output_format": output_format or {"type": "json", "schema": {"type": "object"}},
        "system_prompt": "정책을 기준으로 답변하세요.",
        "user_prompt": user_prompt,
        "assistant_prompt": "",
    }
    if auto_model_routing is not None:
        data["auto_model_routing"] = auto_model_routing
    if refresh_every_runs is not None:
        data["model_routing_policy"] = {
            "refresh": {"refresh_every_runs": refresh_every_runs}
        }
    if knowledge:
        data.update(knowledge)
    return SimpleNamespace(
        id=workflow_id,
        graph={
            "nodes": [
                {
                    "id": "llm-triage",
                    "type": "llmNode",
                    "data": data,
                }
            ],
            "edges": [],
        },
    )


def _workflow_run(workflow_id, run_id, *, deployment_id):
    return SimpleNamespace(
        id=run_id,
        workflow_id=workflow_id,
        deployment_id=deployment_id,
        trigger_mode=RunTriggerMode.API,
        status=RunStatus.SUCCESS,
    )


def _node_run(
    workflow_run_id,
    *,
    completion_tokens,
    finish_reason=None,
    schema_status="pass",
    downstream_status="pass",
    evidence_sufficient=True,
    context_token_estimate=0,
    retrieved_chunk_count=0,
    repetition_rate=None,
):
    return SimpleNamespace(
        id=uuid4(),
        workflow_run_id=workflow_run_id,
        node_id="llm-triage",
        node_type="llmNode",
        status=NodeRunStatus.SUCCESS,
        retry_count=0,
        trace_metadata={
            "finish_reason": finish_reason,
            "schema_status": schema_status,
            "downstream_status": downstream_status,
            "rag_summary": {
                "context_token_estimate": context_token_estimate,
                "retrieved_chunk_count": retrieved_chunk_count,
                "evidence_sufficient": evidence_sufficient,
            },
            "completion_tokens": completion_tokens,
            "repetition_rate": repetition_rate,
        },
    )


def _usage_log(
    workflow_id,
    workflow_run_id,
    *,
    prompt_tokens=1000,
    completion_tokens,
    cost_optimizer_candidate_id=None,
):
    return SimpleNamespace(
        workflow_id=workflow_id,
        workflow_run_id=workflow_run_id,
        cost_optimizer_candidate_id=cost_optimizer_candidate_id,
        node_id="llm-triage",
        status="success",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_cost=0.001,
        latency_ms=1200,
    )


class _RecommendationDb:
    def __init__(self, *, workflow_runs, node_runs, usage_logs):
        self.workflow_runs = workflow_runs
        self.node_runs = node_runs
        self.usage_logs = usage_logs
