from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4


class _FirstQuery:
    def __init__(self, value):
        self.value = value

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.value


class _CountQuery:
    def filter(self, *args, **kwargs):
        return self

    def count(self):
        return 0


def test_persisted_refresh_records_judge_usage_log_reference():
    """정책 갱신 judge 호출 비용은 usage log와 policy update에 연결되어야 한다."""
    from apps.workflow_engine.services.model_routing_policy_refresh_task import (
        PersistedModelRoutingPolicyRefreshService,
    )

    policy = SimpleNamespace(
        id=uuid4(),
        deployment_id=uuid4(),
        workflow_id=uuid4(),
        node_id="llm-1",
        organization_id=uuid4(),
        judge_user_id=uuid4(),
        active_policy={"default_model_id": "gpt-4.1", "rules": []},
        pending_policy=None,
        policy_version="router-policy-v1",
        refresh_every_runs=20,
        eligible_runs_since_last_refresh=20,
        refresh_requested_at=None,
        last_refreshed_at=None,
        last_refresh_result=None,
        status="refreshing",
    )
    deployment = SimpleNamespace(graph_snapshot={"nodes": []})
    usage_log = SimpleNamespace(id=uuid4(), total_cost=0.0012)
    db = MagicMock()
    db.query.side_effect = [_FirstQuery(policy), _FirstQuery(deployment), _CountQuery()]
    refresh_result = SimpleNamespace(
        status="applied",
        policy={
            "policy_version": "router-policy-v2",
            "active_policy": {"default_model_id": "gpt-4.1-mini", "rules": []},
        },
        reason="quality gate passed",
        judge_model_id="gpt-4.1-mini",
        judge_usage={
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        },
        metadata={"confidence": 0.95},
        judge_credential_id=uuid4(),
        judge_provider="openai",
    )

    with (
        patch.object(
            PersistedModelRoutingPolicyRefreshService,
            "_node_data",
            return_value={},
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.ModelRouter.collect_candidates",
            return_value=[
                SimpleNamespace(model_id="gpt-4.1", price_score=0.1),
                SimpleNamespace(model_id="gpt-4.1-mini", price_score=0.01)
            ],
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.LLMService.get_runtime_available_model_ids_for_user",
            return_value=["gpt-4.1-mini"],
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.ModelRouter.collect_profile",
            return_value=SimpleNamespace(
                operational_usable_runs=20,
                as_snapshot=lambda: {
                    "operational_usable_runs": 20,
                    "model_performance": {},
                },
            ),
        ),
        patch.object(
            PersistedModelRoutingPolicyRefreshService,
            "_excluded_run_count",
            return_value=0,
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.ModelRoutingPolicyRefreshService.refresh_policy",
            return_value=refresh_result,
        ) as refresh_policy,
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.LLMService.calculate_cost",
            return_value=0.0012,
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.LLMService.log_usage",
            return_value=usage_log,
        ) as log_usage,
    ):
        update = PersistedModelRoutingPolicyRefreshService.refresh(
            db,
            policy_id=policy.id,
            trigger="manual_refresh",
        )

    assert update.error_code is None, update.output_summary
    assert update.judge_provider == "openai"
    assert update.judge_usage_log_id == usage_log.id
    assert update.output_summary["judge_cost"] == 0.0012
    log_usage.assert_called_once()
    refresh_request = refresh_policy.call_args.args[1]
    assert [candidate.model_id for candidate in refresh_request.candidate_models] == [
        "gpt-4.1-mini"
    ]


def test_persisted_refresh_prefers_current_model_for_judge_when_available():
    """judge 비용·품질 기준은 현재 운영 모델을 우선해 비교 기준을 잃지 않는다."""
    from apps.workflow_engine.services.model_routing_policy_refresh_task import (
        PersistedModelRoutingPolicyRefreshService,
    )

    candidates = [
        SimpleNamespace(model_id="gpt-4.1", price_score=0.1),
        SimpleNamespace(model_id="gpt-4.1-mini", price_score=0.01),
    ]

    assert (
        PersistedModelRoutingPolicyRefreshService._select_judge_model(
            candidates,
            current_model_id="gpt-4.1",
        )
        == "gpt-4.1"
    )


def test_safe_node_summary_treats_collection_only_node_as_knowledge_enabled():
    from apps.workflow_engine.services.model_routing_policy_refresh_task import (
        PersistedModelRoutingPolicyRefreshService,
    )

    summary = PersistedModelRoutingPolicyRefreshService._safe_node_summary(
        {
            "knowledgeBases": [],
            "knowledgeCollections": [{"id": str(uuid4())}],
            "output_format": {"type": "text"},
        }
    )

    assert summary["knowledge_enabled"] is True


def test_semantic_route_catalog_is_built_with_embedding_credential_and_safe_summary():
    """대표 문장은 activation 때만 임베딩하고 judge summary에는 원문을 넣지 않는다."""
    from apps.workflow_engine.services.model_routing_policy_refresh_task import (
        PersistedModelRoutingPolicyRefreshService,
    )

    node_data = {
        "model_id": "gpt-4.1",
        "model_routing_context": {
            "customer_facing": True,
            "semantic_router": {
                "route_catalog_version": "ticket-routing-v1",
                "encoder_model_id": "text-embedding-test",
                "routes": [
                    {
                        "cohort_id": "routine_support",
                        "label": "단순 사용·안내 문의",
                        "threshold": 0.7,
                        "utterances": ["다운로드 위치를 알려 주세요."],
                    },
                        {
                            "cohort_id": "high_risk",
                            "label": "보안·보상 위험 문의",
                            "threshold": 0.8,
                            "utterances": ["계정 탈취가 의심됩니다."],
                            "safety_override": True,
                            "lexical_override_threshold": 1.0,
                            "lexical_signals": [
                                {"term": "credential leak", "weight": 1.0}
                            ],
                        },
                ],
            },
        },
    }
    client = SimpleNamespace(
        embed_sync=lambda text: [1.0, 0.0]
        if "다운로드" in text
        else [0.0, 1.0]
    )
    selection = SimpleNamespace(client=client)
    db = MagicMock()
    user_id = uuid4()
    organization_id = uuid4()

    with patch(
        "apps.workflow_engine.services.model_routing_policy_refresh_task.LLMService.get_runtime_client_for_user",
        return_value=selection,
    ) as get_client:
        snapshot = (
            PersistedModelRoutingPolicyRefreshService._semantic_router_snapshot(
                db,
                node_data=node_data,
                user_id=user_id,
                organization_id=organization_id,
            )
        )

    get_client.assert_called_once_with(
        db,
        user_id=user_id,
        model_id="text-embedding-test",
        organization_id=organization_id,
    )
    assert snapshot["routes"][0]["representatives"][0]["embedding"] == [
        1.0,
        0.0,
    ]
    assert "다운로드 위치" not in str(snapshot)

    safe_summary = PersistedModelRoutingPolicyRefreshService._safe_node_summary(
        node_data
    )
    assert "다운로드 위치" not in str(safe_summary)
    assert "credential leak" not in str(safe_summary)
    assert safe_summary["semantic_router"] == {
        "route_catalog_version": "ticket-routing-v1",
        "encoder_model_id": "text-embedding-test",
        "route_count": 2,
        "cohort_ids": ["routine_support", "high_risk"],
        "safety_override_route_count": 1,
        "lexical_signal_count": 1,
    }


def test_persisted_refresh_activates_new_route_catalog_without_changing_model():
    """새 catalog는 모델 변경 증거가 없어도 default 모델을 유지한 채 활성화한다."""
    from apps.workflow_engine.services.model_routing_policy_refresh_task import (
        PersistedModelRoutingPolicyRefreshService,
    )

    policy = SimpleNamespace(
        id=uuid4(),
        deployment_id=uuid4(),
        workflow_id=uuid4(),
        node_id="llm-1",
        organization_id=uuid4(),
        judge_user_id=uuid4(),
        active_policy={"default_model_id": "gpt-4.1", "rules": []},
        pending_policy=None,
        policy_version="router-policy-v1",
        refresh_every_runs=20,
        eligible_runs_since_last_refresh=20,
        refresh_requested_at=None,
        last_refreshed_at=None,
        last_refresh_result=None,
        status="refreshing",
    )
    node_data = {
        "model_id": "gpt-4.1",
        "model_routing_context": {"semantic_router": {"routes": []}},
    }
    deployment = SimpleNamespace(
        graph_snapshot={"nodes": [{"id": "llm-1", "data": node_data}]}
    )
    snapshot = {
        "route_catalog_version": "ticket-routing-v1",
        "encoder_model_id": "text-embedding-test",
        "top_k": 3,
        "aggregation": "mean",
        "min_margin": 0.05,
        "routes": [
            {
                "cohort_id": "routine_support",
                "label": "단순 사용·안내 문의",
                "threshold": 0.7,
                "representatives": [
                    {"utterance_hash": "safe-hash", "embedding": [1.0, 0.0]}
                ],
            }
        ],
    }
    db = MagicMock()
    db.query.side_effect = [_FirstQuery(policy), _FirstQuery(deployment), _CountQuery()]
    candidate = SimpleNamespace(model_id="gpt-4.1", price_score=0.1)
    profile = SimpleNamespace(
        operational_usable_runs=20,
        as_snapshot=lambda: {
            "operational_usable_runs": 20,
            "model_performance": {},
            "segment_performance": [],
        },
    )

    def keep_current(_db, request):
        return SimpleNamespace(
            status="kept_current",
            policy=request.current_policy,
            reason="validated model change unavailable",
            judge_model_id="gpt-4.1",
            judge_usage={},
            metadata={},
            judge_credential_id=None,
            judge_provider="openai",
        )

    with (
        patch.object(
            PersistedModelRoutingPolicyRefreshService,
            "_semantic_router_snapshot",
            return_value=snapshot,
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.ModelRouter.collect_candidates",
            return_value=[candidate],
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.LLMService.get_runtime_available_model_ids_for_user",
            return_value=["gpt-4.1"],
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.ModelRouter.collect_profile",
            return_value=profile,
        ),
        patch.object(
            PersistedModelRoutingPolicyRefreshService,
            "_excluded_run_count",
            return_value=0,
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.ModelRoutingPolicyRefreshService.refresh_policy",
            side_effect=keep_current,
        ) as refresh_policy,
    ):
        update = PersistedModelRoutingPolicyRefreshService.refresh(
            db,
            policy_id=policy.id,
            trigger="manual_refresh",
        )

    assert update.status == "kept_current"
    assert policy.active_policy["default_model_id"] == "gpt-4.1"
    assert policy.active_policy["semantic_router"] == snapshot
    assert policy.policy_version == "router-policy-v2"
    refresh_request = refresh_policy.call_args.args[1]
    assert refresh_request.current_policy["active_policy"]["semantic_router"] == snapshot


def test_persisted_refresh_uses_validated_replay_optimizer_over_judge_model_choice():
    """Judge 설명과 무관하게 검증된 Replay 계산 결과만 active rule을 결정한다."""
    from apps.workflow_engine.services.model_router import ModelCandidate
    from apps.workflow_engine.services.model_routing_evidence import (
        RoutingEvidenceBatch,
        RoutingEvidenceSample,
    )
    from apps.workflow_engine.services.model_routing_policy_refresh_task import (
        PersistedModelRoutingPolicyRefreshService,
    )

    policy = SimpleNamespace(
        id=uuid4(),
        deployment_id=uuid4(),
        workflow_id=uuid4(),
        node_id="llm-1",
        organization_id=uuid4(),
        judge_user_id=uuid4(),
        active_policy={"default_model_id": "gpt-4.1", "rules": []},
        pending_policy=None,
        policy_version="router-policy-v1",
        refresh_every_runs=20,
        eligible_runs_since_last_refresh=20,
        refresh_requested_at=None,
        last_refreshed_at=None,
        last_refresh_result=None,
        status="refreshing",
    )
    node_data = {
        "model_id": "gpt-4.1",
        "auto_model_routing": True,
        "model_routing_context": {
            "semantic_router": {
                "route_catalog_version": "ticket-routing-v1",
                "encoder_model_id": "text-embedding-test",
                "routes": [{"cohort_id": "routine_support"}],
            }
        },
    }
    deployment = SimpleNamespace(
        graph_snapshot={"nodes": [{"id": "llm-1", "data": node_data}]}
    )
    snapshot = {
        "route_catalog_version": "ticket-routing-v1",
        "encoder_model_id": "text-embedding-test",
        "top_k": 3,
        "aggregation": "mean",
        "min_margin": 0.05,
        "routes": [
            {
                "cohort_id": "routine_support",
                "label": "단순 사용 문의",
                "threshold": 0.7,
                "representatives": [
                    {"utterance_hash": "safe-hash", "embedding": [1.0, 0.0]}
                ],
            }
        ],
    }
    samples = tuple(
        RoutingEvidenceSample(
            source="replay",
            model_id="gpt-4o-mini",
            semantic_cohort_id="routine_support",
            baseline_model_id="gpt-4.1",
            execution_succeeded=True,
            schema_passed=True,
            downstream_passed=True,
            quality_score=89,
            baseline_quality_score=90,
            quality_confidence=0.9,
            execution_cost=0.001,
            baseline_execution_cost=0.01,
            evaluation_cost=0.00002,
            latency_ms=400,
            baseline_latency_ms=1200,
            candidate_id=f"candidate-{index}",
            route_catalog_version="ticket-routing-v1",
        )
        for index in range(10)
    )
    evidence_batch = RoutingEvidenceBatch(samples=samples, excluded_reason_counts={})
    candidates = [
        ModelCandidate("gpt-4.1", "GPT-4.1", 0.01, 0.03),
        ModelCandidate("gpt-4o-mini", "GPT-4o mini", 0.001, 0.002),
    ]
    profile = SimpleNamespace(
        operational_usable_runs=20,
        as_snapshot=lambda: {
            "operational_usable_runs": 20,
            "model_performance": {},
            "segment_performance": [],
        },
    )
    judge_result = SimpleNamespace(
        status="applied",
        policy={
            "policy_version": "judge-policy-v99",
            "active_policy": {
                "default_model_id": "gpt-4.1",
                "rules": [],
            },
        },
        reason="judge explanation only",
        judge_model_id="gpt-4.1",
        judge_usage={},
        metadata={"confidence": 0.9},
        judge_credential_id=None,
        judge_provider="openai",
    )
    db = MagicMock()
    db.query.side_effect = [_FirstQuery(policy), _FirstQuery(deployment), _CountQuery()]

    with (
        patch.object(
            PersistedModelRoutingPolicyRefreshService,
            "_semantic_router_snapshot",
            return_value=snapshot,
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.ModelRouter.collect_candidates",
            return_value=candidates,
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.LLMService.get_runtime_available_model_ids_for_user",
            return_value=["gpt-4.1", "gpt-4o-mini"],
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.ReplayEvidenceAdapter.collect",
            return_value=evidence_batch,
        ) as collect_replay,
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.ModelRouter.collect_profile",
            return_value=profile,
        ),
        patch.object(
            PersistedModelRoutingPolicyRefreshService,
            "_excluded_run_count",
            return_value=0,
        ),
        patch(
            "apps.workflow_engine.services.model_routing_policy_refresh_task.ModelRoutingPolicyRefreshService.refresh_policy",
            return_value=judge_result,
        ),
    ):
        update = PersistedModelRoutingPolicyRefreshService.refresh(
            db,
            policy_id=policy.id,
            trigger="manual_refresh",
        )

    assert update.status == "applied"
    assert policy.active_policy["default_model_id"] == "gpt-4.1"
    assert policy.active_policy["semantic_router"] == snapshot
    assert policy.active_policy["rules"][0]["selected_model_id"] == "gpt-4o-mini"
    assert policy.active_policy["rules"][0]["when"] == {
        "semantic_cohort_id": "routine_support"
    }
    assert policy.active_policy["rules"][0]["reason_code"] == (
        "validated_quality_floor_cost_reduction"
    )
    assert update.output_summary["optimizer"]["status"] == "applied"
    cohort_summary = update.output_summary["optimizer"]["cohort_decisions"][0]
    assert cohort_summary["candidate_quality_lower_bound"] is not None
    assert cohort_summary["baseline_quality_lower_bound"] is not None
    collect_replay.assert_called_once()
