import json
import logging
import sys
from types import SimpleNamespace
from unittest.mock import sentinel
from uuid import uuid4

import pytest

from apps.gateway.services import llm_service as llm_service_module
from apps.gateway.services.ingestion.processors import file_processor as file_processor_module
from apps.gateway.services.ingestion.processors.file_processor import FileProcessor
from apps.gateway.services.ingestion.parsers.pdf_parser import PdfParser
from apps.gateway.services.ingestion.service import IngestionOrchestrator
from apps.gateway.services.llm_service import (
    LLMCredentialNotAvailableError,
    LLMService,
)


def _credential(*, provider_name="llamaparse", is_valid=True):
    return SimpleNamespace(
        id=uuid4(),
        is_valid=is_valid,
        provider=SimpleNamespace(name=provider_name),
        encrypted_config=json.dumps({"apiKey": "test-only-value"}),
    )


def _patch_candidates(monkeypatch, candidates):
    monkeypatch.setattr(
        LLMService,
        "_list_llamaparse_credentials",
        lambda _db, _organization_id: candidates,
    )


def test_resolver_does_not_select_foreign_credential(monkeypatch):
    subject_id = uuid4()
    organization_id = uuid4()
    foreign_credential = _credential()
    _patch_candidates(monkeypatch, [foreign_credential])
    monkeypatch.setattr(
        llm_service_module,
        "has_llm_credential_permission",
        lambda *_args, **_kwargs: False,
    )

    with pytest.raises(LLMCredentialNotAvailableError) as exc_info:
        LLMService.resolve_llamaparse_api_key(
            object(), user_id=subject_id, organization_id=organization_id
        )

    assert exc_info.value.reason == "credential_not_available"
    assert str(foreign_credential.id) not in str(exc_info.value)


def test_resolver_returns_single_authorized_organization_credential(monkeypatch):
    subject_id = uuid4()
    organization_id = uuid4()
    credential = _credential()
    _patch_candidates(monkeypatch, [credential])
    observed = []

    def has_use_permission(_db, user_id, credential_id, action, *, organization_id):
        observed.append((user_id, credential_id, action, organization_id))
        return True

    monkeypatch.setattr(
        llm_service_module,
        "has_llm_credential_permission",
        has_use_permission,
    )

    assert (
        LLMService.resolve_llamaparse_api_key(
            object(), user_id=subject_id, organization_id=organization_id
        )
        == "test-only-value"
    )
    assert observed == [(subject_id, credential.id, "use", organization_id)]


@pytest.mark.parametrize(
    "credential",
    [
        _credential(is_valid=False),
        _credential(provider_name="other-provider"),
    ],
)
def test_resolver_rejects_invalid_or_incompatible_credential(monkeypatch, credential):
    _patch_candidates(monkeypatch, [credential])
    monkeypatch.setattr(
        llm_service_module,
        "has_llm_credential_permission",
        lambda *_args, **_kwargs: True,
    )

    with pytest.raises(LLMCredentialNotAvailableError) as exc_info:
        LLMService.resolve_llamaparse_api_key(
            object(), user_id=uuid4(), organization_id=uuid4()
        )

    assert exc_info.value.reason == "credential_not_available"


def test_resolver_rejects_missing_execution_context_before_query(monkeypatch):
    monkeypatch.setattr(
        LLMService,
        "_list_llamaparse_credentials",
        lambda *_args, **_kwargs: pytest.fail("candidate query must not run"),
    )

    with pytest.raises(LLMCredentialNotAvailableError) as exc_info:
        LLMService.resolve_llamaparse_api_key(
            object(), user_id=None, organization_id=uuid4()
        )

    assert exc_info.value.reason == "credential_context_missing"


def test_resolver_rejects_permission_loss_and_ambiguous_candidates(monkeypatch):
    subject_id = uuid4()
    organization_id = uuid4()
    first = _credential()
    second = _credential()
    _patch_candidates(monkeypatch, [first, second])
    monkeypatch.setattr(
        llm_service_module,
        "has_llm_credential_permission",
        lambda *_args, **_kwargs: True,
    )

    with pytest.raises(LLMCredentialNotAvailableError) as exc_info:
        LLMService.resolve_llamaparse_api_key(
            object(), user_id=subject_id, organization_id=organization_id
        )

    assert exc_info.value.reason == "credential_selection_ambiguous"


def test_resolver_sanitizes_malformed_config(monkeypatch):
    subject_id = uuid4()
    organization_id = uuid4()
    credential = _credential()
    credential.encrypted_config = "not-json-with-opaque-material"
    _patch_candidates(monkeypatch, [credential])
    monkeypatch.setattr(
        llm_service_module,
        "has_llm_credential_permission",
        lambda *_args, **_kwargs: True,
    )

    with pytest.raises(LLMCredentialNotAvailableError) as exc_info:
        LLMService.resolve_llamaparse_api_key(
            object(), user_id=subject_id, organization_id=organization_id
        )

    assert "opaque-material" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.reason == "credential_not_available"


class _FakePdfParser:
    calls = []

    def parse(self, _path, **kwargs):
        self.calls.append(kwargs)
        return [{"text": "parsed", "page": 1}]


def test_file_processor_blocks_before_parser_call_when_credential_is_unavailable(
    monkeypatch, tmp_path
):
    file_path = tmp_path / "document.pdf"
    file_path.write_bytes(b"pdf")
    _FakePdfParser.calls = []
    monkeypatch.setattr(file_processor_module, "PdfParser", _FakePdfParser)
    monkeypatch.setattr(
        LLMService,
        "resolve_llamaparse_api_key",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            LLMCredentialNotAvailableError("credential_not_available")
        ),
    )

    result = FileProcessor(
        object(),
        user_id=uuid4(),
        organization_id=uuid4(),
    ).process({"file_path": str(file_path), "strategy": "llamaparse"})

    assert _FakePdfParser.calls == []
    assert result.metadata == {"error": "Parser credential is unavailable."}


def test_file_processor_delegates_secret_without_persisting_it(monkeypatch, tmp_path):
    file_path = tmp_path / "document.pdf"
    file_path.write_bytes(b"pdf")
    _FakePdfParser.calls = []
    monkeypatch.setattr(file_processor_module, "PdfParser", _FakePdfParser)
    monkeypatch.setattr(
        LLMService,
        "resolve_llamaparse_api_key",
        lambda *_args, **_kwargs: sentinel.resolved_credential_material,
    )

    result = FileProcessor(
        object(),
        user_id=uuid4(),
        organization_id=uuid4(),
    ).process({"file_path": str(file_path), "strategy": "llamaparse"})

    assert _FakePdfParser.calls == [
        {
            "strategy": "llamaparse",
            "api_key": sentinel.resolved_credential_material,
        }
    ]
    assert "credential" not in result.metadata
    assert "api_key" not in result.metadata


def test_pdf_parser_does_not_log_provider_exception_traceback(monkeypatch, caplog):
    class FailingLlamaParse:
        def __init__(self, **_kwargs):
            pass

        def load_data(self, _file_path):
            raise RuntimeError()

    parser = PdfParser()
    monkeypatch.setitem(
        sys.modules,
        "llama_parse",
        SimpleNamespace(LlamaParse=FailingLlamaParse),
    )
    monkeypatch.setattr(parser, "_parse_with_pymupdf", lambda _path: [])

    with caplog.at_level(logging.WARNING):
        assert parser._parse_with_llamaparse("document.pdf", sentinel.api_key) == []

    assert "LlamaParse parsing failed: RuntimeError" in caplog.text
    assert "Traceback" not in caplog.text


def test_ingestion_orchestrator_preserves_organization_context_for_processor(
    monkeypatch,
):
    subject_id = uuid4()
    organization_id = uuid4()
    observed = []

    class Processor:
        def process(self, source_config):
            assert source_config == {"file_path": "document.pdf"}
            return SimpleNamespace(metadata={}, chunks=[])

    monkeypatch.setattr(
        "apps.gateway.services.ingestion.service.IngestionFactory.get_processor",
        lambda *args: observed.append(args) or Processor(),
    )
    orchestrator = IngestionOrchestrator(
        object(),
        user_id=subject_id,
        organization_id=organization_id,
    )
    monkeypatch.setattr(
        orchestrator,
        "_build_config",
        lambda _document: {"file_path": "document.pdf"},
    )

    assert orchestrator._extract_raw_blocks(SimpleNamespace(source_type="FILE")) == []
    assert observed == [("FILE", orchestrator.db, subject_id, organization_id)]
