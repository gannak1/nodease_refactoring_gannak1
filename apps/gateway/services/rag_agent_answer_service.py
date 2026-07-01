import asyncio
import json
import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session, aliased, joinedload

from apps.gateway.services.llm_service import LLMService
from apps.gateway.services.retrieval import RetrievalService
from apps.gateway.utils.api_errors import error_detail, raise_api_error
from apps.shared.audit.actions import AuditAction
from apps.shared.audit.logger import record_audit
from apps.shared.db.models.knowledge import DocumentChunk, KnowledgeBase, RAGAnswerRun
from apps.shared.db.models.llm import (
    LLMCredential,
    LLMModel,
    LLMRelCredentialModel,
    LLMUsageLog,
)
from apps.shared.db.models.user import User
from apps.shared.permissions import (
    knowledge_base_auth_state_allows,
    llm_credential_auth_state_allows,
)
from apps.shared.schemas.rag import (
    CORRELATION_ID_PATTERN,
    CORRELATION_ID_SECRET_PATTERNS,
    RAGAgentAnswerRequest,
    RAGAgentAnswerResponse,
    RAGAnswerSummary,
    RAGCitation,
    RAGRetrievalSummary,
    RAGUsageSummary,
)
from apps.shared.services.llm_client import get_llm_client
from apps.shared.services.permission_audit import record_resource_permission_denied
from apps.shared.services.permissions import (
    get_effective_knowledge_base_auth_state,
    get_effective_llm_credential_auth_state,
    has_organization_scope_access,
)
from apps.shared.services.rag_filters import normalize_metadata_filter
from apps.shared.services.tracing.policy import TracePolicyService
from apps.shared.services.tracing.redaction import TraceRedactionService

logger = logging.getLogger(__name__)

RETENTION_DAYS = 90
CONTENT_PREVIEW_LIMIT = 300
CONTEXT_TOKEN_BUDGET = 8000
MAX_OUTPUT_TOKENS = 1000
PROVIDER_TIMEOUT_SECONDS = 60
SSE_IDLE_TIMEOUT_SECONDS = 30
MIN_TOP_K = 1
MAX_TOP_K = 8

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_API_KEY_RE = re.compile(r"\b(?:sk|pk|rk|api)[-_][A-Za-z0-9_-]{8,}\b")
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}\b", re.IGNORECASE)


@dataclass
class RAGAnswerExecution:
    payload: RAGAgentAnswerRequest
    correlation_id: str
    metadata_filter: Any
    kb: KnowledgeBase
    model: LLMModel
    credential: LLMCredential
    run: RAGAnswerRun


class RAGAgentAnswerService:
    """RAG Agent answer의 권한, 상태 전이, audit, LLM 호출을 담당한다."""

    def __init__(
        self,
        db: Session,
        current_user: User,
        request: Request,
        organization_id: uuid.UUID,
    ) -> None:
        self.db = db
        self.current_user = current_user
        self.request = request
        self.organization_id = organization_id

    async def answer(self, payload: RAGAgentAnswerRequest) -> RAGAgentAnswerResponse:
        execution = self.prepare_execution(payload)
        payload = execution.payload
        kb = execution.kb
        model = execution.model
        credential = execution.credential
        run = execution.run
        metadata_filter = execution.metadata_filter
        timeout_stage: str | None = None

        try:
            retrieval_start = time.perf_counter()
            retrieval_service = RetrievalService(
                self.db,
                user_id=self.current_user.id,
                organization_id=self.organization_id,
            )
            timeout_stage = "retrieval"
            chunks = await retrieval_service.search_documents(
                payload.query,
                knowledge_base_id=str(kb.id),
                top_k=payload.top_k,
                metadata_filter=metadata_filter,
                hierarchy_mode=payload.hierarchy_mode,
            )
            timeout_stage = None
            retrieval_latency_ms = int((time.perf_counter() - retrieval_start) * 1000)
            citations = self._build_citations(chunks)
            retrieval_summary = self._build_retrieval_summary(
                kb.id,
                payload.hierarchy_mode,
                citations,
                retrieval_latency_ms,
            )
            self._record_retrieval(
                run,
                metadata_filter,
                len(citations),
                payload.hierarchy_mode,
            )

            if self._contains_pii_evidence(citations):
                self._block_policy(run, retrieval_summary, citations)

            if not chunks:
                answer = "해당 질문에 답변할 수 있는 문서를 찾지 못했습니다."
                usage_summary = RAGUsageSummary(
                    model_name=model.name,
                    provider=model.provider_name,
                )
            else:
                timeout_stage = "generation"
                answer, usage_summary = await self._generate_answer(
                    payload,
                    chunks,
                    model,
                    credential,
                    run,
                )
                timeout_stage = None

            policy_result = self._allowed_policy_result(citations)
            answer_summary = RAGAnswerSummary(
                answer_length=len(answer),
                cited_document_count=len({str(c.document_id) for c in citations}),
                citation_ids=[c.citation_id for c in citations],
                policy_result=policy_result,
                completion_status="completed",
            )
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            run.retrieval_summary = retrieval_summary.model_dump(mode="json")
            run.citation_summary = [
                c.model_dump(mode="json", exclude={"content_preview"}) for c in citations
            ]
            run.answer_summary = answer_summary.model_dump(mode="json")
            run.policy_result = policy_result
            run.usage_summary = self._durable_usage_summary(
                usage_summary, model, credential
            )
            self.db.add(run)
            self.db.commit()
            self.db.refresh(run)
            self._record_lifecycle(AuditAction.RAG_ANSWER_COMPLETED, run)

            return RAGAgentAnswerResponse(
                answer_run_id=run.id,
                correlation_id=run.correlation_id,
                status=run.status,
                answer=answer,
                citations=citations,
                retrieval_summary=retrieval_summary,
                usage_summary=usage_summary,
                policy_result=policy_result,
            )
        except asyncio.CancelledError:
            self._mark_cancelled(run)
            raise
        except asyncio.TimeoutError:
            if timeout_stage == "generation":
                logger.warning("RAG Agent answer provider timeout")
                self._mark_failed(run, "provider.timeout")
                raise_api_error(
                    self.request,
                    504,
                    "provider.timeout",
                    "RAG answer provider timeout.",
                    {
                        "answer_run_id": str(run.id),
                        "correlation_id": run.correlation_id,
                    },
                )
            logger.warning("RAG Agent answer retrieval timeout")
            self._mark_failed(run, "generation.failed")
            raise_api_error(
                self.request,
                500,
                "generation.failed",
                "RAG answer generation failed.",
                {"answer_run_id": str(run.id), "correlation_id": run.correlation_id},
            )
        except ValueError as exc:
            if str(exc) == "hierarchy_unavailable":
                self._mark_failed(run, "hierarchy_unavailable")
                raise_api_error(
                    self.request,
                    422,
                    "hierarchy_unavailable",
                    "Hierarchical retrieval data is not available for this Knowledge Base.",
                    {
                        "answer_run_id": str(run.id),
                        "correlation_id": run.correlation_id,
                    },
                )
            self._mark_failed(run, "generation.failed")
            raise_api_error(
                self.request,
                500,
                "generation.failed",
                "RAG answer generation failed.",
                {"answer_run_id": str(run.id), "correlation_id": run.correlation_id},
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - service boundary에서 상태와 audit을 닫는다
            logger.exception("RAG Agent answer failed")
            self._mark_failed(run, "generation.failed")
            raise_api_error(
                self.request,
                500,
                "generation.failed",
                "RAG answer generation failed.",
                {"answer_run_id": str(run.id), "correlation_id": run.correlation_id},
            )

    def prepare_execution(self, payload: RAGAgentAnswerRequest) -> RAGAnswerExecution:
        self._validate_top_k(payload.top_k)
        correlation_id = self._validated_correlation_id(payload.correlation_id)
        metadata_filter = normalize_metadata_filter(
            metadata_filter=payload.metadata_filter,
            classification_filter=payload.classification_filter,
            tags=payload.tags,
            source_type=payload.source_type,
            effective_at=payload.effective_at,
        )

        kb = self._visible_knowledge_base(payload.knowledge_base_id)
        model = self._visible_generation_model(payload.generation_model_id)
        credential = self._visible_credential(payload.credential_id)
        self._ensure_generation_model(model)
        self._ensure_hierarchy_available(payload, kb)

        run = self._create_run(
            payload=payload,
            correlation_id=correlation_id,
            kb=kb,
            model=model,
            credential=credential,
        )
        try:
            self._record_lifecycle(AuditAction.RAG_ANSWER_REQUESTED, run)
            self._ensure_kb_use(run, kb)
            self._ensure_credential_use_and_relation(run, credential, model)
            self._mark_running(run)
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001 - run 생성 후 preflight는 상태를 닫는다
            logger.exception("RAG Agent answer preflight failed")
            self._mark_preflight_failed(run)
            raise_api_error(
                self.request,
                500,
                "generation.failed",
                "RAG answer preflight failed.",
                {"answer_run_id": str(run.id), "correlation_id": run.correlation_id},
            )
        return RAGAnswerExecution(
            payload=payload,
            correlation_id=correlation_id,
            metadata_filter=metadata_filter,
            kb=kb,
            model=model,
            credential=credential,
            run=run,
        )

    async def stream_events(
        self, execution: RAGAnswerExecution
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        payload = execution.payload
        kb = execution.kb
        model = execution.model
        credential = execution.credential
        run = execution.run
        metadata_filter = execution.metadata_filter
        timeout_stage: str | None = None
        try:
            yield (
                "retrieval.started",
                {
                    "answer_run_id": str(run.id),
                    "correlation_id": run.correlation_id,
                    "status": "running",
                    "knowledge_base_id": str(kb.id),
                    "hierarchy_mode": payload.hierarchy_mode,
                },
            )

            retrieval_start = time.perf_counter()
            retrieval_service = RetrievalService(
                self.db,
                user_id=self.current_user.id,
                organization_id=self.organization_id,
            )
            timeout_stage = "retrieval"
            chunks = await asyncio.wait_for(
                retrieval_service.search_documents(
                    payload.query,
                    knowledge_base_id=str(kb.id),
                    top_k=payload.top_k,
                    metadata_filter=metadata_filter,
                    hierarchy_mode=payload.hierarchy_mode,
                ),
                timeout=SSE_IDLE_TIMEOUT_SECONDS,
            )
            timeout_stage = None
            retrieval_latency_ms = int((time.perf_counter() - retrieval_start) * 1000)
            citations = self._build_citations(chunks)
            retrieval_summary = self._build_retrieval_summary(
                kb.id,
                payload.hierarchy_mode,
                citations,
                retrieval_latency_ms,
            )
            self._record_retrieval(
                run,
                metadata_filter,
                len(citations),
                payload.hierarchy_mode,
            )

            if self._contains_pii_evidence(citations):
                try:
                    self._block_policy(run, retrieval_summary, citations)
                except HTTPException:
                    yield self._error_event(run, "pii_policy_blocked", retryable=False)
                    return

            yield (
                "retrieval.completed",
                {
                    "answer_run_id": str(run.id),
                    "correlation_id": run.correlation_id,
                    "retrieval_summary": retrieval_summary.model_dump(mode="json"),
                    "citations": [c.model_dump(mode="json") for c in citations],
                },
            )

            if not chunks:
                answer = "해당 질문에 답변할 수 있는 문서를 찾지 못했습니다."
                usage_summary = RAGUsageSummary(
                    model_name=model.name,
                    provider=model.provider_name,
                )
            else:
                timeout_stage = "generation"
                answer, usage_summary = await self._generate_answer(
                    payload,
                    chunks,
                    model,
                    credential,
                    run,
                )
                timeout_stage = None

            policy_result = self._allowed_policy_result(citations)
            answer_summary = RAGAnswerSummary(
                answer_length=len(answer),
                cited_document_count=len({str(c.document_id) for c in citations}),
                citation_ids=[c.citation_id for c in citations],
                policy_result=policy_result,
                completion_status="completed",
            )
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            run.retrieval_summary = retrieval_summary.model_dump(mode="json")
            run.citation_summary = [
                c.model_dump(mode="json", exclude={"content_preview"}) for c in citations
            ]
            run.answer_summary = answer_summary.model_dump(mode="json")
            run.policy_result = policy_result
            run.usage_summary = self._durable_usage_summary(
                usage_summary, model, credential
            )
            self.db.add(run)
            self.db.commit()
            self.db.refresh(run)
            self._record_lifecycle(AuditAction.RAG_ANSWER_COMPLETED, run)

            if answer:
                yield (
                    "answer.delta",
                    {
                        "answer_run_id": str(run.id),
                        "correlation_id": run.correlation_id,
                        "delta": answer,
                        "index": 0,
                    },
                )
            yield (
                "usage",
                {
                    "answer_run_id": str(run.id),
                    "correlation_id": run.correlation_id,
                    "usage_summary": usage_summary.model_dump(mode="json"),
                },
            )
            yield (
                "summary",
                {
                    "answer_run_id": str(run.id),
                    "correlation_id": run.correlation_id,
                    "status": run.status,
                    "retrieval_summary": retrieval_summary.model_dump(mode="json"),
                    "citation_summary": [
                        c.model_dump(mode="json", exclude={"content_preview"})
                        for c in citations
                    ],
                    "answer_summary": answer_summary.model_dump(mode="json"),
                    "policy_result": policy_result,
                },
            )
            yield (
                "answer.completed",
                {
                    "answer_run_id": str(run.id),
                    "correlation_id": run.correlation_id,
                    "status": run.status,
                },
            )
        except asyncio.CancelledError:
            self._mark_cancelled(run)
            raise
        except asyncio.TimeoutError:
            error_code = (
                "provider.timeout"
                if timeout_stage == "generation"
                else "stream.timeout"
            )
            self._mark_failed(run, error_code)
            yield self._error_event(run, error_code, retryable=True)
        except ValueError as exc:
            error_code = (
                "hierarchy_unavailable"
                if str(exc) == "hierarchy_unavailable"
                else "generation.failed"
            )
            self._mark_failed(run, error_code)
            yield self._error_event(run, error_code, retryable=error_code != "hierarchy_unavailable")
        except HTTPException as exc:
            reason_code = self._reason_code_from_http_exception(exc)
            yield self._error_event(run, reason_code, retryable=False)
        except Exception:
            logger.exception("RAG Agent answer stream failed")
            self._mark_failed(run, "generation.failed")
            yield self._error_event(run, "generation.failed", retryable=True)
        finally:
            if getattr(run, "status", None) in {"requested", "running"}:
                self._mark_cancelled(run)

    def _visible_knowledge_base(self, knowledge_base_id: uuid.UUID) -> KnowledgeBase:
        kb = (
            self.db.query(KnowledgeBase)
            .filter(KnowledgeBase.id == knowledge_base_id)
            .first()
        )
        if (
            kb is None
            or kb.organization_id != self.organization_id
            or not has_organization_scope_access(
                self.db, self.current_user.id, self.organization_id
            )
        ):
            self._raise_not_found("Knowledge Base not found.")
        return kb

    def _visible_generation_model(self, model_id: uuid.UUID) -> LLMModel:
        model = (
            self.db.query(LLMModel)
            .options(joinedload(LLMModel.provider))
            .filter(LLMModel.id == model_id)
            .first()
        )
        if model is None or not model.is_active:
            self._raise_not_found("Generation model not found.")
        return model

    def _visible_credential(self, credential_id: uuid.UUID) -> LLMCredential:
        credential = (
            self.db.query(LLMCredential)
            .options(joinedload(LLMCredential.provider))
            .filter(LLMCredential.id == credential_id)
            .first()
        )
        if (
            credential is None
            or not credential.is_valid
            or credential.organization_id != self.organization_id
            or not has_organization_scope_access(
                self.db, self.current_user.id, self.organization_id
            )
        ):
            self._raise_not_found("Credential not found.")
        return credential

    def _ensure_generation_model(self, model: LLMModel) -> None:
        if model.type != "chat":
            raise_api_error(
                self.request,
                400,
                "validation.failed",
                "generation_model_id must reference an active chat model.",
                {"field": "generation_model_id"},
            )

    def _ensure_hierarchy_available(
        self, payload: RAGAgentAnswerRequest, kb: KnowledgeBase
    ) -> None:
        if payload.hierarchy_mode != "parent_child":
            return
        parent = aliased(DocumentChunk)
        exists = (
            self.db.query(DocumentChunk.id)
            .join(parent, DocumentChunk.parent_chunk_id == parent.id)
            .filter(
                DocumentChunk.knowledge_base_id == kb.id,
                DocumentChunk.chunk_level == "child",
                parent.chunk_level == "parent",
                DocumentChunk.document_id == parent.document_id,
                DocumentChunk.knowledge_base_id == parent.knowledge_base_id,
            )
            .first()
        )
        if exists is None:
            raise_api_error(
                self.request,
                422,
                "hierarchy_unavailable",
                "Hierarchical retrieval data is not available for this Knowledge Base.",
            )

    def _create_run(
        self,
        *,
        payload: RAGAgentAnswerRequest,
        correlation_id: str,
        kb: KnowledgeBase,
        model: LLMModel,
        credential: LLMCredential,
    ) -> RAGAnswerRun:
        now = datetime.now(timezone.utc)
        run = RAGAnswerRun(
            organization_id=self.organization_id,
            user_id=self.current_user.id,
            actor_user_ref={"id": str(self.current_user.id)},
            knowledge_base_id=kb.id,
            knowledge_base_ref={"id": str(kb.id), "name": kb.name},
            correlation_id=correlation_id,
            status="requested",
            retrieval_summary={},
            citation_summary=[],
            answer_summary={},
            policy_result={},
            generation_model_id=model.id,
            generation_model_snapshot={
                "id": str(model.id),
                "model_id_for_api_call": model.model_id_for_api_call,
                "name": model.name,
                "provider": model.provider_name,
                "type": model.type,
            },
            generation_credential_id=credential.id,
            generation_credential_ref={
                "id": str(credential.id),
                "provider": credential.provider.name if credential.provider else None,
            },
            usage_summary={},
            retention_expires_at=now + timedelta(days=RETENTION_DAYS),
            created_at=now,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def _ensure_kb_use(self, run: RAGAnswerRun, kb: KnowledgeBase) -> None:
        effective_auth_state = get_effective_knowledge_base_auth_state(
            self.db,
            self.current_user.id,
            kb.id,
            organization_id=self.organization_id,
        )
        if knowledge_base_auth_state_allows(effective_auth_state, "use"):
            return

        record_resource_permission_denied(
            user_id=self.current_user.id,
            resource_type="knowledge_base",
            resource_id=kb.id,
            action="use",
            effective_auth_state=effective_auth_state,
            organization_id=self.organization_id,
            metadata=self._permission_metadata(
                run,
                reason_code="kb_use_denied",
            ),
        )
        self._block_permission(run, "kb_use_denied")

    def _ensure_credential_use_and_relation(
        self, run: RAGAnswerRun, credential: LLMCredential, model: LLMModel
    ) -> None:
        effective_auth_state = get_effective_llm_credential_auth_state(
            self.db,
            self.current_user.id,
            credential.id,
            organization_id=self.organization_id,
        )
        if not llm_credential_auth_state_allows(effective_auth_state, "use"):
            record_resource_permission_denied(
                user_id=self.current_user.id,
                resource_type="llm_credential",
                resource_id=credential.id,
                action="use",
                effective_auth_state=effective_auth_state,
                organization_id=self.organization_id,
                metadata=self._permission_metadata(
                    run,
                    reason_code="credential_use_denied",
                ),
            )
            self._block_permission(run, "credential_use_denied")

        relation = (
            self.db.query(LLMRelCredentialModel)
            .filter(
                LLMRelCredentialModel.credential_id == credential.id,
                LLMRelCredentialModel.model_id == model.id,
                LLMRelCredentialModel.is_verified.is_(True),
            )
            .first()
        )
        if relation is not None:
            return

        record_resource_permission_denied(
            user_id=self.current_user.id,
            resource_type="llm_model",
            resource_id=model.id,
            action="use",
            effective_auth_state=effective_auth_state,
            organization_id=self.organization_id,
            metadata=self._permission_metadata(
                run,
                reason_code="credential_model_relation_denied",
                extra={"credential_id": str(credential.id)},
            ),
        )
        self._block_permission(run, "credential_model_relation_denied")

    def _validate_top_k(self, top_k: int) -> None:
        if MIN_TOP_K <= top_k <= MAX_TOP_K:
            return
        raise_api_error(
            self.request,
            400,
            "validation.failed",
            f"top_k must be between {MIN_TOP_K} and {MAX_TOP_K}.",
            {"field": "top_k", "min": MIN_TOP_K, "max": MAX_TOP_K},
        )

    def _validated_correlation_id(self, value: str | None) -> str:
        if value is None:
            return str(uuid.uuid4())
        normalized = value.strip()
        if not CORRELATION_ID_PATTERN.fullmatch(normalized) or any(
            pattern.search(normalized)
            for pattern in CORRELATION_ID_SECRET_PATTERNS
        ):
            raise_api_error(
                self.request,
                400,
                "invalid_correlation_id",
                "correlation_id is invalid.",
                {"field": "correlation_id"},
            )
        return normalized

    def _mark_running(self, run: RAGAnswerRun) -> None:
        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)

    async def _generate_answer(
        self,
        payload: RAGAgentAnswerRequest,
        chunks,
        model: LLMModel,
        credential: LLMCredential,
        run: RAGAnswerRun,
    ) -> tuple[str, RAGUsageSummary]:
        client = self._client_for(model, credential)
        context_text = self._context_for_chunks(chunks)
        system_prompt = (
            "You are a helpful assistant. Use the following context to answer the user's question.\n"
            "If the answer is not in the context, say you don't know.\n\n"
            f"Context:\n{context_text}"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": payload.query},
        ]
        llm_start = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                client.invoke(messages, max_tokens=MAX_OUTPUT_TOKENS),
                timeout=PROVIDER_TIMEOUT_SECONDS,
            )
        except Exception:
            self._record_llm_call(run, model, credential, status="failure")
            raise

        latency_ms = int((time.perf_counter() - llm_start) * 1000)
        usage = dict(result.get("usage") or {})
        usage["latency_ms"] = latency_ms
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = int(
            usage.get("total_tokens") or prompt_tokens + completion_tokens
        )
        total_cost = LLMService.calculate_cost(
            self.db,
            model.model_id_for_api_call,
            prompt_tokens,
            completion_tokens,
        )
        answer = (
            result.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        self._record_llm_call(
            run,
            model,
            credential,
            status="success",
            metadata={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "latency_ms": latency_ms,
            },
        )
        self._record_usage_log(
            model,
            credential,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_cost=total_cost,
            latency_ms=latency_ms,
        )
        return answer, RAGUsageSummary(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            total_cost=total_cost,
            latency_ms=latency_ms,
            model_name=model.name,
            provider=model.provider_name,
        )

    def _context_for_chunks(self, chunks) -> str:
        parts: list[str] = []
        total_tokens = 0
        for chunk in chunks:
            content = chunk.content or ""
            token_count = chunk.token_count or max(1, len(content) // 4)
            if total_tokens and total_tokens + token_count > CONTEXT_TOKEN_BUDGET:
                break
            if token_count > CONTEXT_TOKEN_BUDGET:
                parts.append(content[: CONTEXT_TOKEN_BUDGET * 4])
                break
            parts.append(content)
            total_tokens += token_count
        return "\n\n".join(parts)

    def _client_for(self, model: LLMModel, credential: LLMCredential):
        try:
            config = json.loads(credential.encrypted_config)
        except Exception as exc:  # noqa: BLE001 - secret 원문을 응답에 포함하지 않는다
            raise ValueError("Invalid credential config") from exc
        return get_llm_client(
            provider=credential.provider.name,
            model_id=model.model_id_for_api_call,
            credentials={
                "apiKey": config.get("apiKey"),
                "baseUrl": config.get("baseUrl"),
            },
        )

    def _build_citations(self, chunks) -> list[RAGCitation]:
        citations: list[RAGCitation] = []
        for index, chunk in enumerate(chunks, start=1):
            citation_id = f"c{index}"
            metadata_summary = dict(chunk.metadata_summary or {})
            citations.append(
                RAGCitation(
                    citation_id=citation_id,
                    document_id=chunk.document_id,
                    chunk_id=chunk.chunk_id,
                    rank=chunk.rank or index,
                    score=(
                        chunk.score
                        if chunk.score is not None
                        else chunk.similarity_score
                    ),
                    filename=chunk.filename,
                    heading=metadata_summary.get("heading"),
                    hierarchy_path=chunk.hierarchy_path,
                    metadata_summary=metadata_summary,
                    content_preview=self._content_preview(chunk.content),
                )
            )
        return citations

    def _build_retrieval_summary(
        self,
        knowledge_base_id: uuid.UUID,
        hierarchy_mode: str,
        citations: list[RAGCitation],
        latency_ms: int,
    ) -> RAGRetrievalSummary:
        scores = [c.score for c in citations if c.score is not None]
        score_summary = {}
        if scores:
            score_summary = {
                "min": min(scores),
                "max": max(scores),
                "avg": sum(scores) / len(scores),
            }
        document_ids = list({c.document_id for c in citations})
        return RAGRetrievalSummary(
            knowledge_base_id=knowledge_base_id,
            hierarchy_mode=hierarchy_mode,
            retrieved_chunk_count=len(citations),
            document_ids=document_ids,
            citation_ids=[c.citation_id for c in citations],
            score_summary=score_summary,
            latency_ms=latency_ms,
            raw_content_returned=False,
        )

    def _contains_pii_evidence(self, citations: list[RAGCitation]) -> bool:
        for citation in citations:
            classification = citation.metadata_summary.get("classification")
            if str(classification).lower() == "pii":
                return True
        return False

    def _allowed_policy_result(self, citations: list[RAGCitation]) -> dict[str, Any]:
        classifications = sorted(
            {
                str(citation.metadata_summary.get("classification")).lower()
                for citation in citations
                if citation.metadata_summary.get("classification")
            }
        )
        result: dict[str, Any] = {"result": "allow"}
        if classifications:
            result["evidence_classifications"] = classifications
        return result

    def _block_policy(
        self,
        run: RAGAnswerRun,
        retrieval_summary: RAGRetrievalSummary,
        citations: list[RAGCitation],
    ) -> None:
        reason_code = "pii_policy_blocked"
        policy_result = {"result": "block", "reason_code": reason_code}
        run.status = "blocked"
        run.completed_at = datetime.now(timezone.utc)
        run.error_code = reason_code
        run.retrieval_summary = retrieval_summary.model_dump(mode="json")
        run.citation_summary = [
            c.model_dump(mode="json", exclude={"content_preview"}) for c in citations
        ]
        run.answer_summary = {
            "answer_length": 0,
            "cited_document_count": len({str(c.document_id) for c in citations}),
            "citation_ids": [c.citation_id for c in citations],
            "policy_result": policy_result,
            "completion_status": "blocked",
        }
        run.policy_result = policy_result
        run.usage_summary = {}
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        record_audit(
            action=AuditAction.POLICY_BLOCK,
            category="action",
            actor_id=self.current_user.id,
            actor_type="user",
            target_type="rag_answer_run",
            target_id=run.id,
            status="failure",
            metadata={
                "organization_id": str(self.organization_id),
                "answer_run_id": str(run.id),
                "correlation_id": run.correlation_id,
                "policy_result": policy_result,
            },
        )
        exc = HTTPException(
            status_code=403,
            detail=error_detail(
                self.request,
                "policy.blocked",
                "RAG answer blocked by policy.",
                self._blocked_details(run, reason_code),
            ),
        )
        setattr(exc, "audit_recorded", True)
        raise exc

    def _block_permission(self, run: RAGAnswerRun, reason_code: str) -> None:
        run.status = "blocked"
        run.completed_at = datetime.now(timezone.utc)
        run.error_code = reason_code
        run.policy_result = {"result": "deny", "reason_code": reason_code}
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        exc = HTTPException(
            status_code=403,
            detail=error_detail(
                self.request,
                "permission.denied",
                "RAG answer permission denied.",
                self._blocked_details(run, reason_code),
            ),
        )
        setattr(exc, "audit_recorded", True)
        raise exc

    def _mark_failed(self, run: RAGAnswerRun, error_code: str) -> None:
        run.status = "failed"
        run.error_code = error_code
        run.completed_at = datetime.now(timezone.utc)
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        self._record_lifecycle(AuditAction.RAG_ANSWER_FAILED, run, status="failure")

    def _mark_preflight_failed(self, run: RAGAnswerRun) -> None:
        try:
            self.db.rollback()
        except Exception:  # noqa: BLE001 - rollback 실패는 원래 예외를 대체하지 않는다
            logger.exception("RAG Agent answer preflight rollback failed")
        try:
            self._mark_failed(run, "generation.failed")
        except Exception:  # noqa: BLE001 - 상태 마감 실패도 sanitized 응답은 유지한다
            logger.exception("RAG Agent answer preflight failure close failed")

    def _mark_cancelled(self, run: RAGAnswerRun) -> None:
        run.status = "cancelled"
        run.error_code = "client.cancelled"
        run.completed_at = datetime.now(timezone.utc)
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        self._record_lifecycle(AuditAction.RAG_ANSWER_CANCELLED, run, status="failure")

    def _record_lifecycle(
        self, action: str, run: RAGAnswerRun, status: str = "success"
    ) -> None:
        record_audit(
            action=action,
            category="action",
            actor_id=self.current_user.id,
            actor_type="user",
            target_type="rag_answer_run",
            target_id=run.id,
            status=status,
            metadata={
                "organization_id": str(self.organization_id),
                "answer_run_id": str(run.id),
                "correlation_id": run.correlation_id,
                "run_status": run.status,
            },
        )

    def _record_retrieval(
        self, run: RAGAnswerRun, metadata_filter, result_count: int, mode: str
    ) -> None:
        record_audit(
            action=AuditAction.RAG_RETRIEVE,
            category="action",
            actor_id=self.current_user.id,
            actor_type="user",
            target_type="knowledge_base",
            target_id=run.knowledge_base_id,
            status="success",
            metadata={
                "organization_id": str(self.organization_id),
                "answer_run_id": str(run.id),
                "correlation_id": run.correlation_id,
                "retrieval_mode": mode,
                "result_count": result_count,
                "metadata_filter": metadata_filter.audit_summary()
                if metadata_filter is not None
                else {},
            },
        )

    def _record_llm_call(
        self,
        run: RAGAnswerRun,
        model: LLMModel,
        credential: LLMCredential,
        *,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        record_audit(
            action=AuditAction.LLM_CALL,
            category="action",
            actor_id=self.current_user.id,
            actor_type="user",
            target_type="llm_model",
            target_id=model.id,
            status=status,
            metadata={
                "organization_id": str(self.organization_id),
                "answer_run_id": str(run.id),
                "correlation_id": run.correlation_id,
                "model_id": str(model.id),
                "credential_id": str(credential.id),
                **(metadata or {}),
            },
        )

    def _record_usage_log(
        self,
        model: LLMModel,
        credential: LLMCredential,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        total_cost: float | None,
        latency_ms: int,
    ) -> None:
        usage_log = LLMUsageLog(
            user_id=self.current_user.id,
            organization_id=self.organization_id,
            credential_id=credential.id,
            model_id=model.id,
            workflow_id=None,
            workflow_run_id=None,
            node_id=None,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_cost=total_cost,
            latency_ms=latency_ms,
            status="success",
        )
        self.db.add(usage_log)

    def _permission_metadata(
        self,
        run: RAGAnswerRun,
        *,
        reason_code: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "request_id": getattr(self.request.state, "request_id", None),
            "path": self.request.url.path,
            "answer_run_id": str(run.id),
            "correlation_id": run.correlation_id,
            "reason_code": reason_code,
            **(extra or {}),
        }

    def _blocked_details(self, run: RAGAnswerRun, reason_code: str) -> dict[str, str]:
        return {
            "answer_run_id": str(run.id),
            "correlation_id": run.correlation_id,
            "status": "blocked",
            "reason_code": reason_code,
        }

    def _error_event(
        self, run: RAGAnswerRun, reason_code: str, *, retryable: bool
    ) -> tuple[str, dict[str, Any]]:
        return (
            "error",
            {
                "answer_run_id": str(run.id),
                "correlation_id": run.correlation_id,
                "status": run.status,
                "reason_code": reason_code,
                "retryable": retryable,
            },
        )

    @staticmethod
    def _reason_code_from_http_exception(exc: HTTPException) -> str:
        detail = exc.detail
        if isinstance(detail, dict):
            error = detail.get("error")
            if isinstance(error, dict):
                details = error.get("details")
                if isinstance(details, dict) and details.get("reason_code"):
                    return str(details["reason_code"])
                if error.get("code"):
                    return str(error["code"])
        return "generation.failed"

    def _durable_usage_summary(
        self,
        usage_summary: RAGUsageSummary,
        model: LLMModel,
        credential: LLMCredential,
    ) -> dict[str, Any]:
        durable = usage_summary.model_dump(mode="json")
        durable["model_id"] = str(model.id)
        durable["credential_id"] = str(credential.id)
        return durable

    def _content_preview(self, content: str) -> str:
        normalized = " ".join((content or "").split())
        redaction = TraceRedactionService.redact_payload(
            normalized,
            TracePolicyService.bootstrap_redaction_policy(),
            payload_kind="rag.citation_preview",
        )
        redacted = (
            redaction.redacted_payload
            if isinstance(redaction.redacted_payload, str)
            else normalized
        )
        redacted = _EMAIL_RE.sub("[redacted-email]", redacted)
        redacted = _API_KEY_RE.sub("[redacted-secret]", redacted)
        redacted = _BEARER_RE.sub("Bearer [redacted-secret]", redacted)
        return redacted[:CONTENT_PREVIEW_LIMIT]

    def _raise_not_found(self, message: str) -> None:
        raise_api_error(self.request, 404, "resource.not_found", message)
