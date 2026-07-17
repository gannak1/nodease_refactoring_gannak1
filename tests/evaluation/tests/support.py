from __future__ import annotations

from tests.evaluation.paired_runner import RunnerConfig
from tests.evaluation.protocol import canonical_hash
from tests.evaluation.schemas import ArtifactLineage, FrozenProtocol


SHA = "sha256:" + "a" * 64


def make_protocol(
    config: RunnerConfig,
    *,
    planned_answerable_n: int,
    planned_unanswerable_n: int,
    pool_depth: int = 5,
) -> FrozenProtocol:
    return FrozenProtocol.model_validate(
        {
            "schema_version": "1",
            "estimand": "controlled_child_boundary_retrieval_effect",
            "study_phase": config.study_phase,
            "code_commit": "a" * 40,
            "migration_head": "head-v1",
            "retrieval_config_hash": canonical_hash(config),
            "model_contract": {
                "safe_model_id": "embedding-safe",
                "immutable_version": "v1",
                "dimension": 2,
                "score_normalization_version": "cosine-v1",
            },
            "retrieval_controls": {
                "hybrid_search": config.hybrid_search,
                "use_rerank": False,
                "use_rewrite": False,
                "top_k": config.top_k,
                "threshold": config.threshold,
                "source_tier_policy": config.source_tier_policy,
            },
            "primary_metric": "answerable_cluster_macro_recall_at_5",
            "decision_gates": {
                "confidence_level": 0.95,
                "bootstrap_iterations": (
                    10_000 if config.study_phase == "confirmatory_holdout" else 1_000
                ),
                "recall_superiority_margin": 0.03,
                "safety_noninferiority_margin": 0.05,
                "latency_ratio_noninferiority_margin": 1.30,
                "mrr_consistency_margin": 0.01,
                "win_tie_loss_epsilon": 0.01,
                "fixed_order": [
                    "recall_superiority",
                    "safety_noninferiority",
                    "latency_noninferiority",
                    "mrr_consistency",
                ],
            },
            "sample_size_plan": {
                "method": "paired-normal-v1",
                "alpha": 0.05,
                "power": 0.8,
                "target_recall_delta": 0.03,
                "paired_sd_delta": 0.15,
                "cluster_design_effect": 1.0,
                "planned_n": planned_answerable_n + planned_unanswerable_n,
                "planned_answerable_n": planned_answerable_n,
                "planned_unanswerable_n": planned_unanswerable_n,
            },
            "cluster_plan": {
                "minimum_independent_clusters": 30,
                "maximum_questions_per_cluster": 5,
                "equal_weight": True,
            },
            "split_hash": SHA,
            "pooling_plan": {
                "depth": pool_depth,
                "blind_projection_version": "blind-v1",
                "adjudication_version": "adjudication-v1",
            },
            "tie_policy": {
                "score_precision": 8,
                "complete_tie_group_cap": 100,
                "expected_metric_version": "expected_tie_permutation_v1",
            },
            "retry_attrition_policy": {
                "max_attempts_per_condition": config.max_attempts,
                "symmetric": True,
                "complete_pair_required": True,
            },
            "latency_plan": {
                "method": "question_session_median_ratio_v1",
                "repeats_per_session": 5,
                "session_count": 3,
                "randomized_ab_ba": True,
                "monotonic_clock": True,
                "target_ratio_ci_half_width": 0.1,
                "environment_profile_id": "dedicated-v1",
                "cache_profile_id": "warm-cache-v1",
                "connection_pool_profile_id": "pool-v1",
            },
            "permission_batch_limit": 10,
            "exclusion_policy": ["policy.revoked", "readiness.failed"],
            "seeds": {
                "split": 1,
                "order": config.seed,
                "pool": 3,
                "bootstrap": 279,
            },
        }
    )


def make_lineage(
    protocol: FrozenProtocol,
    config: RunnerConfig,
    *,
    ready: bool = True,
) -> ArtifactLineage:
    return ArtifactLineage(
        protocol_hash=canonical_hash(protocol),
        dataset_hash=SHA,
        split_hash=protocol.split_hash,
        config_hash=canonical_hash(config),
        code_commit=protocol.code_commit,
        source_equality_verified=ready,
        child_boundary_equality_verified=ready,
        child_vector_equality=ready,
        segmentation_contract_version="canonical-child-v1",
        vector_equality_check_version="exact-float-v1",
        parent_builder_fingerprint=SHA,
    )
