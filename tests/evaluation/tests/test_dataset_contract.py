from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from tests.evaluation.evidence_refs import OpaqueEvidenceRegistry
from tests.evaluation.protocol import (
    canonical_hash,
    dataset_content_hashes,
    read_sealed_artifact,
    validate_dataset,
    validate_protocol,
    write_sealed_artifact,
)
from tests.evaluation.schemas import (
    BenchmarkQuestion,
    DatasetManifest,
    DatasetPackage,
    FrozenProtocol,
)


SHA = "sha256:" + "a" * 64


def manifest(**updates) -> DatasetManifest:
    question_hash, evidence_hash, split_hash = dataset_content_hashes(questions())
    values = {
        "schema_version": "1",
        "dataset_id": "paired-safe-v1",
        "dataset_version": "1.0.0",
        "language": "ko-KR",
        "question_count": 2,
        "development_count": 1,
        "holdout_count": 1,
        "sampling_cluster_count": 2,
        "protocol_hash": SHA,
        "split_hash": split_hash,
        "source_manifest_hash": SHA,
        "canonical_children_hash": SHA,
        "question_set_hash": question_hash,
        "expected_evidence_hash": evidence_hash,
        "content_class": "synthetic",
        "license_ref": None,
        "created_from": "curated",
    }
    values.update(updates)
    return DatasetManifest.model_validate(values)


def questions() -> tuple[BenchmarkQuestion, ...]:
    return (
        BenchmarkQuestion(
            question_id="q-dev",
            sampling_cluster_ref="cluster-dev",
            split="development",
            category="single_fact",
            difficulty="easy",
            answerable=True,
            query="승인된 합성 질문",
            required_evidence_refs=("ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",),
        ),
        BenchmarkQuestion(
            question_id="q-holdout",
            sampling_cluster_ref="cluster-holdout",
            split="holdout",
            category="unanswerable",
            difficulty="hard",
            answerable=False,
            query="답이 없는 합성 질문",
            required_evidence_refs=(),
        ),
    )


def protocol(**updates) -> FrozenProtocol:
    _, _, split_hash = dataset_content_hashes(questions())
    values = {
        "schema_version": "1",
        "estimand": "controlled_child_boundary_retrieval_effect",
        "study_phase": "development",
        "code_commit": "a" * 40,
        "migration_head": "head-v1",
        "retrieval_config_hash": SHA,
        "model_contract": {
            "safe_model_id": "embedding-safe",
            "immutable_version": "v1",
            "dimension": 2,
            "score_normalization_version": "cosine-v1",
        },
        "retrieval_controls": {
            "hybrid_search": True,
            "use_rerank": False,
            "use_rewrite": False,
            "top_k": 5,
            "threshold": 0.15,
            "source_tier_policy": "ignore",
        },
        "primary_metric": "answerable_cluster_macro_recall_at_5",
        "decision_gates": {
            "confidence_level": 0.95,
            "bootstrap_iterations": 1000,
            "recall_superiority_margin": 0.03,
            "safety_noninferiority_margin": 0.05,
            "latency_ratio_noninferiority_margin": 1.3,
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
            "planned_n": 1,
            "planned_answerable_n": 1,
            "planned_unanswerable_n": 0,
        },
        "cluster_plan": {
            "minimum_independent_clusters": 30,
            "maximum_questions_per_cluster": 5,
            "equal_weight": True,
        },
        "split_hash": split_hash,
        "pooling_plan": {
            "depth": 8,
            "blind_projection_version": "blind-v1",
            "adjudication_version": "adjudication-v1",
        },
        "tie_policy": {
            "score_precision": 8,
            "complete_tie_group_cap": 100,
            "expected_metric_version": "expected_tie_permutation_v1",
        },
        "retry_attrition_policy": {
            "max_attempts_per_condition": 2,
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
        "seeds": {"split": 1, "order": 2, "pool": 3, "bootstrap": 279},
    }
    values.update(updates)
    return FrozenProtocol.model_validate(values)


def test_dataset_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        manifest(unknown=True)


def test_frozen_protocol_rejects_unknown_or_primary_confounding_fields() -> None:
    assert protocol().retrieval_controls.use_rerank is False
    with pytest.raises(ValidationError):
        protocol(unknown=True)
    raw = protocol().model_dump(mode="json")
    raw["retrieval_controls"]["use_rerank"] = True
    with pytest.raises(ValidationError, match="use_rerank"):
        FrozenProtocol.model_validate(raw)
    raw = protocol().model_dump(mode="json")
    raw["retrieval_controls"]["source_tier_policy"] = "tie_break"
    with pytest.raises(ValidationError, match="source_tier_policy"):
        FrozenProtocol.model_validate(raw)


def test_confirmatory_protocol_enforces_unanswerable_precision_floor() -> None:
    raw = protocol().model_dump(mode="json")
    raw["study_phase"] = "confirmatory_holdout"
    raw["sample_size_plan"].update(
        {"planned_n": 100, "planned_answerable_n": 42, "planned_unanswerable_n": 58}
    )
    with pytest.raises(ValidationError, match="confirmatory_unanswerable_below_precision_floor"):
        FrozenProtocol.model_validate(raw)


def test_protocol_tie_scan_cap_covers_pool_and_retrieval_bounds() -> None:
    raw = protocol().model_dump(mode="json")
    raw["tie_policy"]["complete_tie_group_cap"] = 49

    with pytest.raises(ValueError, match="tie_group_cap_below_retrieval_bound"):
        FrozenProtocol.model_validate(raw)

    raw["tie_policy"]["complete_tie_group_cap"] = 50
    assert FrozenProtocol.model_validate(raw).tie_policy.complete_tie_group_cap == 50


def test_dataset_rejects_invalid_hash_and_public_dataset_without_license() -> None:
    with pytest.raises(ValidationError):
        manifest(protocol_hash="not-a-hash")
    with pytest.raises(ValidationError):
        manifest(content_class="public", license_ref=None)


def test_dataset_counts_and_clusters_are_validated() -> None:
    package = DatasetPackage(manifest=manifest(), questions=questions())
    validate_dataset(package)

    with pytest.raises(ValueError, match="question_count_mismatch"):
        validate_dataset(
            DatasetPackage(
                manifest=manifest(question_count=3, development_count=2),
                questions=questions(),
            )
        )


def test_declared_question_evidence_and_split_hashes_are_recomputed() -> None:
    changed = list(questions())
    changed[0] = BenchmarkQuestion.model_validate(
        {**changed[0].model_dump(), "query": "변경된 승인 질문"}
    )
    with pytest.raises(ValueError, match="question_set_hash_mismatch"):
        validate_dataset(
            DatasetPackage(manifest=manifest(), questions=tuple(changed))
        )

    package = DatasetPackage(
        manifest=manifest(protocol_hash=canonical_hash(protocol())),
        questions=questions(),
    )
    validate_protocol(package, protocol())


def test_question_text_boundaries_and_secret_markers_fail_without_echo() -> None:
    base = questions()[0].model_dump()
    BenchmarkQuestion.model_validate({**base, "query": "가" * 1000})
    BenchmarkQuestion.model_validate({**base, "safe_display_label": "가" * 120})
    for field, value in (
        ("query", ""),
        ("query", "가" * 1001),
        ("query", "approved\nquestion"),
        ("query", "api_key=RAW_SECRET_SENTINEL"),
        ("safe_display_label", "가" * 121),
    ):
        with pytest.raises(ValidationError) as captured:
            BenchmarkQuestion.model_validate({**base, field: value})
        assert "RAW_SECRET_SENTINEL" not in str(captured.value)


def test_cluster_cannot_cross_development_and_holdout() -> None:
    leaked = list(questions())
    leaked[1] = leaked[1].model_copy(
        update={"sampling_cluster_ref": "cluster-dev"}
    )
    with pytest.raises(ValueError, match="split_cluster_leakage"):
        validate_dataset(
            DatasetPackage(manifest=manifest(sampling_cluster_count=1), questions=tuple(leaked))
        )


def test_duplicate_question_and_required_evidence_are_rejected() -> None:
    duplicate = (questions()[0], questions()[0])
    with pytest.raises(ValueError, match="duplicate_question_id"):
        validate_dataset(
            DatasetPackage(manifest=manifest(development_count=2, holdout_count=0), questions=duplicate)
        )
    with pytest.raises(ValidationError):
        questions()[0].model_copy(
            update={
                "required_evidence_refs":
                    ("ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",) * 2
            }
        ).__class__.model_validate(
            questions()[0]
            .model_copy(
                update={
                    "required_evidence_refs":
                        ("ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",) * 2
                }
            )
            .model_dump()
        )


def test_opaque_registry_is_one_to_one_and_import_is_immutable() -> None:
    registry = OpaqueEvidenceRegistry()
    first = registry.issue("flat-child-1")
    assert first == registry.issue("flat-child-1")
    assert first.startswith("ev:")
    second = registry.issue("flat-child-2")
    assert first != second

    imported = OpaqueEvidenceRegistry({"child-a": first})
    assert imported.reference_for("child-a") == first
    with pytest.raises(ValueError, match="duplicate_evidence_ref"):
        OpaqueEvidenceRegistry({"child-a": first, "child-b": first})


def test_opaque_registry_collision_retry_is_bounded(monkeypatch) -> None:
    monkeypatch.setattr(
        "tests.evaluation.evidence_refs.secrets.token_hex",
        lambda _size: "a" * 32,
    )
    registry = OpaqueEvidenceRegistry()
    assert registry.issue("child-a") == "ev:" + "a" * 32
    with pytest.raises(RuntimeError, match="evidence_ref_generation_exhausted"):
        registry.issue("child-b")


def test_sealed_artifact_detects_tampering_and_is_canonical(tmp_path) -> None:
    path = tmp_path / "sealed.json"
    payload = {"schema_version": "1", "items": [2, 1], "safe": True}
    artifact_hash = write_sealed_artifact(path, "test", payload)
    assert artifact_hash == canonical_hash(json.loads(path.read_text(encoding="utf-8")))
    assert read_sealed_artifact(path, expected_type="test") == payload

    with pytest.raises(ValueError, match="artifact_output_exists"):
        write_sealed_artifact(path, "test", {"replacement": True})
    assert read_sealed_artifact(path, expected_type="test") == payload

    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["payload"]["safe"] = False
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="artifact_hash_mismatch"):
        read_sealed_artifact(path, expected_type="test")
