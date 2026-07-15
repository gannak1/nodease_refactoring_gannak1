import pytest

from apps.shared.db.models.cost_optimizer import (
    CostOptimizerExperiment,
    CostOptimizerRecommendationVerification,
)
from apps.shared.db.models.llm import LLMUsageLog
from apps.shared.db.models.mail_processing import MailMessageProcessing
from apps.shared.db.models.model_routing_policy import LLMNodeModelRoutingPolicy
from apps.shared.db.models.workflow_run import WorkflowRun


def _foreign_key(model, column_name, target_fullname):
    return next(
        (
            foreign_key
            for foreign_key in model.__table__.c[column_name].foreign_keys
            if foreign_key.target_fullname == target_fullname
        ),
        None,
    )


def test_retained_workflow_run_has_durable_organization_provenance():
    assert "organization_id" in WorkflowRun.__table__.c


@pytest.mark.parametrize(
    "model",
    [
        CostOptimizerExperiment,
        CostOptimizerRecommendationVerification,
        LLMNodeModelRoutingPolicy,
    ],
    ids=[
        "cost-optimizer-experiment",
        "cost-optimizer-verification",
        "model-routing-evidence",
    ],
)
def test_retained_records_have_non_nullable_organization_provenance(model):
    assert "organization_id" in model.__table__.c
    assert model.__table__.c.organization_id.nullable is False


def test_usage_log_detaches_deleted_workflow_instead_of_blocking_deletion():
    workflow_fk = _foreign_key(LLMUsageLog, "workflow_id", "workflows.id")

    assert workflow_fk is not None
    assert LLMUsageLog.__table__.c.workflow_id.nullable is True
    assert workflow_fk.ondelete == "SET NULL"


@pytest.mark.parametrize(
    ("model", "column_name"),
    [
        (WorkflowRun, "workflow_id"),
        (CostOptimizerExperiment, "workflow_id"),
        (CostOptimizerRecommendationVerification, "workflow_id"),
        (LLMNodeModelRoutingPolicy, "workflow_id"),
        (MailMessageProcessing, "workflow_id"),
    ],
    ids=[
        "workflow-run-trace",
        "cost-optimizer-experiment",
        "cost-optimizer-verification",
        "model-routing-evidence",
        "mail-idempotency-ledger",
    ],
)
def test_retained_records_do_not_cascade_when_workflow_is_deleted(
    model,
    column_name,
):
    workflow_fk = _foreign_key(model, column_name, "workflows.id")

    assert workflow_fk is None or workflow_fk.ondelete != "CASCADE"
