from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from apps.shared.db.models import LLMNodeVersion
from apps.shared.db.models.workflow import Workflow


def test_llm_node_version_model_contract():
    table = LLMNodeVersion.__table__

    assert LLMNodeVersion.__tablename__ == "llm_node_versions"

    assert table.c.workflow_id.nullable is False
    assert table.c.node_id.nullable is False
    assert table.c.version_number.nullable is False
    assert table.c.parent_version_id.nullable is True
    assert table.c.created_by.nullable is False

    assert next(iter(table.c.workflow_id.foreign_keys)).ondelete == "CASCADE"
    assert next(iter(table.c.parent_version_id.foreign_keys)).ondelete == "SET NULL"
    assert next(iter(table.c.created_by.foreign_keys)).ondelete is None


def test_llm_node_version_jsonb_defaults():
    table = LLMNodeVersion.__table__
    expected_defaults = {
        "referenced_variables": "'[]'::jsonb",
        "parameters": "'{}'::jsonb",
        "knowledge_bases": "'[]'::jsonb",
        "output_config": "'{}'::jsonb",
        "retrieval_config": "'{}'::jsonb",
        "tool_config": "'[]'::jsonb",
    }

    for column_name, server_default in expected_defaults.items():
        column = table.c[column_name]
        assert isinstance(column.type, JSONB)
        assert column.nullable is False
        assert str(column.server_default.arg) == server_default


def test_llm_node_version_constraints_and_indexes():
    table = LLMNodeVersion.__table__

    assert any(
        isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_llm_node_versions_node_version"
        and [column.name for column in constraint.columns]
        == ["workflow_id", "node_id", "version_number"]
        for constraint in table.constraints
    )

    check_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert check_names >= {
        "ck_llm_node_versions_version_number_positive",
        "ck_llm_node_versions_top_k_positive",
        "ck_llm_node_versions_score_threshold_range",
    }

    indexes = {
        index.name: [column.name for column in index.columns]
        for index in table.indexes
    }
    assert indexes["ix_llm_node_versions_workflow_id"] == ["workflow_id"]
    assert indexes["ix_llm_node_versions_parent_version_id"] == ["parent_version_id"]
    assert indexes["ix_llm_node_versions_created_by"] == ["created_by"]


def test_workflow_llm_node_versions_relationship():
    relationship = Workflow.__mapper__.relationships["llm_node_versions"]

    assert relationship.mapper.class_ is LLMNodeVersion
    assert relationship.back_populates == "workflow"
    assert "delete-orphan" in relationship.cascade
