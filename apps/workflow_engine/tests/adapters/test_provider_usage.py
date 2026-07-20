from __future__ import annotations

import uuid

import pytest

from apps.workflow_engine.adapters.provider_usage import (
    PostgresProviderUsageRecorder,
)
from apps.workflow_engine.application.provider_execution import (
    ProviderExecutionAttribution,
)
from apps.workflow_engine.application.provider_usage import ProviderUsageRecord
from apps.workflow_engine.services.llm_service import LLMService


class _Session:
    def __init__(self) -> None:
        self.closes = 0

    def close(self) -> None:
        self.closes += 1


def _record(*, attribution: ProviderExecutionAttribution) -> ProviderUsageRecord:
    return ProviderUsageRecord(
        attribution=attribution,
        usage={"prompt_tokens": 3, "completion_tokens": 2},
        workflow_id=uuid.uuid4(),
        workflow_run_id=uuid.uuid4(),
        node_id="llm-1",
    )


def test_usage_recorder_preserves_admitted_model_and_organization(monkeypatch):
    session = _Session()
    organization_id = uuid.uuid4()
    model_db_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    principal_id = uuid.uuid4()
    captured: dict = {}

    def calculate_cost(db, model_id, prompt_tokens, completion_tokens, **kwargs):
        captured["cost"] = {
            "db": db,
            "model_id": model_id,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            **kwargs,
        }
        return 0.125

    def log_usage(**kwargs):
        captured["usage"] = kwargs

    monkeypatch.setattr(LLMService, "calculate_cost", calculate_cost)
    monkeypatch.setattr(LLMService, "log_usage", log_usage)
    recorder = PostgresProviderUsageRecorder(session_factory=lambda: session)

    cost = recorder.record(
        _record(
            attribution=ProviderExecutionAttribution(
                credential_id=credential_id,
                credential_principal_user_id=principal_id,
                organization_id=organization_id,
                model_id="shared-provider-id",
                model_db_id=model_db_id,
                capability_id=uuid.uuid4(),
                capability_revision=2,
            )
        )
    )

    assert cost == 0.125
    assert captured["cost"]["model_db_id"] == model_db_id
    assert captured["usage"]["model_db_id"] == model_db_id
    assert captured["usage"]["organization_id"] == organization_id
    assert captured["usage"]["credential_id"] == credential_id
    assert session.closes == 1


def test_usage_recorder_closes_session_when_projection_fails(monkeypatch):
    session = _Session()
    monkeypatch.setattr(
        LLMService,
        "calculate_cost",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("failed")),
    )
    recorder = PostgresProviderUsageRecorder(session_factory=lambda: session)

    with pytest.raises(RuntimeError, match="failed"):
        recorder.record(
            _record(
                attribution=ProviderExecutionAttribution(
                    credential_id=uuid.uuid4(),
                    credential_principal_user_id=uuid.uuid4(),
                    organization_id=uuid.uuid4(),
                    model_id="gpt-safe",
                    model_db_id=uuid.uuid4(),
                )
            )
        )

    assert session.closes == 1
