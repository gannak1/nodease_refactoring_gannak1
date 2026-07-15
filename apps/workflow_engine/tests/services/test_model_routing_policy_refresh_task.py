from datetime import datetime, timezone
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
        refresh_requested_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
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
        patch.object(
            PersistedModelRoutingPolicyRefreshService,
            "_adaptive_semantic_router_snapshot",
            return_value=None,
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
        refresh_requested_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        last_refreshed_at=None,
        last_refresh_result=None,
        status="refreshing",
    )
    node_data = {
        "model_id": "gpt-4.1",
        "model_routing_context": {
            "semantic_router": {
                "route_catalog_version": "ticket-routing-v1",
                "encoder_model_id": "text-embedding-test",
                "routes": [
                    {
                        "cohort_id": "routine_support",
                        "label": "단순 사용·안내 문의",
                        "threshold": 0.7,
                        "utterances": ["다운로드 위치를 알려 주세요."],
                    }
                ],
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
            "_adaptive_semantic_router_snapshot",
            return_value=None,
        ),
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


def test_adaptive_refresh_defers_rule_changes_until_replay_validation_completes():
    """자동 라우팅 refresh는 DB 상태만 짧게 갱신하고 legacy judge를 호출하지 않는다."""
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
        refresh_requested_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        last_refreshed_at=None,
        last_refresh_result=None,
        status="refreshing",
    )
    node_data = {
        "model_id": "gpt-4.1",
        "auto_model_routing": True,
    }
    deployment = SimpleNamespace(
        graph_snapshot={"nodes": [{"id": "llm-1", "data": node_data}]}
    )
    profile = SimpleNamespace(
        operational_usable_runs=20,
        as_snapshot=lambda: {
            "operational_usable_runs": 20,
            "model_performance": {},
            "segment_performance": [],
        },
    )
    db = MagicMock()
    db.query.side_effect = [_FirstQuery(policy), _FirstQuery(deployment), _CountQuery()]

    with (
        patch.object(
            PersistedModelRoutingPolicyRefreshService,
            "_resolve_semantic_router_snapshot",
            return_value=None,
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
        ) as refresh_policy,
    ):
        update = PersistedModelRoutingPolicyRefreshService.refresh(
            db,
            policy_id=policy.id,
            trigger="manual_refresh",
        )

    assert update.status == "pending_review"
    assert policy.active_policy["default_model_id"] == "gpt-4.1"
    assert policy.status == "refreshing"
    assert policy.refresh_requested_at == datetime(2026, 7, 14, tzinfo=timezone.utc)
    assert update.output_summary["adaptive_validation"]["judge_called"] is False
    refresh_policy.assert_not_called()


def test_adaptive_semantic_config_without_static_routes_does_not_activate_a_catalog():
    """FR-011: 입력 경로 설정만 있는 adaptive router를 불완전한 정적 catalog로 만들지 않는다."""
    from apps.workflow_engine.services.model_routing_policy_refresh_task import (
        PersistedModelRoutingPolicyRefreshService,
    )

    policy = SimpleNamespace(
        active_policy={},
        judge_user_id=uuid4(),
        organization_id=uuid4(),
    )
    node_data = {
        "model_routing_context": {
            "semantic_router": {
                "encoder_model_id": "text-embedding-3-large",
                "input_paths": ["start-question.question"],
                "aggregation": "centroid",
            }
        }
    }

    with (
        patch.object(
            PersistedModelRoutingPolicyRefreshService,
            "_adaptive_semantic_router_snapshot",
            return_value=None,
        ),
        patch.object(
            PersistedModelRoutingPolicyRefreshService,
            "_semantic_router_snapshot",
        ) as build_static_snapshot,
    ):
        snapshot = PersistedModelRoutingPolicyRefreshService._resolve_semantic_router_snapshot(
            MagicMock(),
            policy=policy,
            node_data=node_data,
        )

    assert snapshot is None
    build_static_snapshot.assert_not_called()


def test_adaptive_refresh_projects_catalog_safety_route_to_baseline_rule():
    """FR-011-A51: catalog의 safety 표시는 baseline 고정 rule로만 투영한다."""
    from apps.workflow_engine.services.model_routing_policy_refresh_task import (
        PersistedModelRoutingPolicyRefreshService,
    )

    rules = PersistedModelRoutingPolicyRefreshService._static_safety_rules(
        [
            {
                "id": "old-adaptive",
                "when": {"semantic_cohort_id": "invoice"},
                "selected_model_id": "gpt-4o-mini",
                "reason_code": "validated_adaptive_cohort",
            }
        ],
        semantic_router={
            "routes": [
                {"cohort_id": "high_risk", "safety_override": True},
                {"cohort_id": "billing", "safety_override": False},
            ]
        },
        default_model_id="gpt-4.1",
        fallback_model_id="gpt-4.1-mini",
    )

    assert rules[0] == {
        "id": "safety-baseline-high_risk",
        "when": {"semantic_cohort_id": "high_risk"},
        "selected_model_id": "gpt-4.1",
        "fallback_model_id": "gpt-4.1-mini",
        "priority": 10,
        "reason_code": "safety_override_baseline",
    }
    assert rules[1]["id"] == "old-adaptive"


def test_static_safety_rule_is_not_treated_as_a_validated_adaptive_rule():
    """고위험 baseline 고정 rule만으로 adaptive policy가 활성화됐다고 판단하면 안 된다."""
    from apps.workflow_engine.services.model_routing_policy_refresh_task import (
        PersistedModelRoutingPolicyRefreshService,
    )

    assert not PersistedModelRoutingPolicyRefreshService._has_active_adaptive_rule(
        {
            "rules": [
                {
                    "when": {"semantic_cohort_id": "high-risk"},
                    "reason_code": "safety_override_baseline",
                }
            ]
        }
    )
    assert PersistedModelRoutingPolicyRefreshService._has_active_adaptive_rule(
        {
            "rules": [
                {
                    "when": {"semantic_cohort_id": "invoice"},
                    "reason_code": "validated_adaptive_cohort",
                }
            ]
        }
    )
