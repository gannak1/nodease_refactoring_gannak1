from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from apps.workflow_engine.adapters.provider_usage import (
    PostgresProviderUsageRecorder,
)
from apps.workflow_engine.application.provider_execution import (
    ProviderExecutionAttribution,
    ProviderExecutionPricingSnapshot,
)
from apps.workflow_engine.application.provider_usage import ProviderUsageRecord
from apps.workflow_engine.services import llm_service as workflow_llm_service
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


def test_capability_usage_uses_admission_pricing_snapshot(monkeypatch):
    session = _Session()
    organization_id = uuid.uuid4()
    model_db_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    principal_id = uuid.uuid4()
    captured: dict = {}

    monkeypatch.setattr(
        LLMService,
        "calculate_cost",
        lambda *_args, **_kwargs: pytest.fail(
            "capability usage must not re-read mutable model pricing"
        ),
    )
    monkeypatch.setattr(
        LLMService,
        "log_usage",
        lambda **kwargs: captured.update(usage=kwargs),
    )
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
                pricing_snapshot=ProviderExecutionPricingSnapshot(
                    revision="d" * 64,
                    input_price_per_1k=Decimal("1"),
                    output_price_per_1k=Decimal("2"),
                ),
            )
        )
    )

    assert cost == pytest.approx(0.007)
    assert captured["usage"]["cost"] == pytest.approx(0.007)
    assert captured["usage"]["model_db_id"] == model_db_id
    assert captured["usage"]["organization_id"] == organization_id
    assert captured["usage"]["credential_id"] == credential_id
    assert session.closes == 1


def test_legacy_usage_recorder_preserves_catalog_fallback(monkeypatch):
    session = _Session()
    captured: dict = {}

    def calculate_cost(_db, _model_id, _prompt_tokens, _completion_tokens, **kwargs):
        captured.update(kwargs)
        return 0.25

    monkeypatch.setattr(LLMService, "calculate_cost", calculate_cost)
    monkeypatch.setattr(LLMService, "log_usage", lambda **_kwargs: None)
    recorder = PostgresProviderUsageRecorder(session_factory=lambda: session)

    cost = recorder.record(
        _record(
            attribution=ProviderExecutionAttribution(
                credential_id=uuid.uuid4(),
                credential_principal_user_id=uuid.uuid4(),
                organization_id=uuid.uuid4(),
                model_id="gpt-4o",
                model_db_id=uuid.uuid4(),
            )
        )
    )

    assert cost == 0.25
    assert captured["allow_catalog_fallback"] is True
    assert session.closes == 1


def test_legacy_cost_uses_catalog_when_canonical_row_has_no_prices(monkeypatch):
    model_db_id = uuid.uuid4()
    model = type(
        "Model",
        (),
        {
            "id": model_db_id,
            "input_price_1k": None,
            "output_price_1k": None,
        },
    )()

    class _Query:
        def filter(self, *_values):
            return self

        def first(self):
            return model

    class _Db:
        def query(self, *_entities):
            return _Query()

    calls: list[str] = []
    monkeypatch.setattr(
        workflow_llm_service,
        "calculate_text_token_cost",
        lambda model_id, **_kwargs: calls.append(model_id) or 0.75,
    )

    cost = LLMService.calculate_cost(
        _Db(),
        "gpt-4o",
        1_000,
        1_000,
        model_db_id=model_db_id,
        allow_catalog_fallback=True,
    )

    assert cost == 0.75
    assert calls == ["gpt-4o"]


def test_capability_cost_does_not_fallback_without_exact_prices(monkeypatch):
    model = type(
        "Model",
        (),
        {"input_price_1k": None, "output_price_1k": None},
    )()

    class _Query:
        def filter(self, *_values):
            return self

        def first(self):
            return model

    class _Db:
        def query(self, *_entities):
            return _Query()

    monkeypatch.setattr(
        workflow_llm_service,
        "calculate_text_token_cost",
        lambda *_args, **_kwargs: pytest.fail(
            "capability must not use catalog fallback"
        ),
    )

    assert (
        LLMService.calculate_cost(
            _Db(),
            "gpt-4o",
            1_000,
            1_000,
            model_db_id=uuid.uuid4(),
            allow_catalog_fallback=False,
        )
        == 0.0
    )


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
