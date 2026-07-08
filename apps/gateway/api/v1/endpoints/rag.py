import json
import logging
from typing import AsyncIterator, List, Optional
from urllib.parse import quote
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from apps.gateway.api.deps import get_db
from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.utils.audit import audit
from apps.gateway.core.config import settings

# from services.ingestion_local_service import IngestionService
from apps.gateway.services.ingestion.service import (
    IngestionOrchestrator as IngestionService,
    finalize_stale_processing_start,
    recover_timed_out_document_with_artifacts,
)
from apps.gateway.services.rag_agent_answer_service import RAGAgentAnswerService
from apps.gateway.services.retrieval import RetrievalService
from apps.gateway.services.storage import get_storage_service
from apps.gateway.utils.api_errors import (
    error_detail,
    parse_organization_id,
    raise_api_error,
)
from apps.shared.audit.actions import AuditAction
from apps.shared.audit.logger import record_audit
from apps.shared.db.models.connection import Connection
from apps.shared.db.models.knowledge import Document, KnowledgeBase, SourceType
from apps.shared.db.models.user import User
from apps.shared.schemas.rag import (
    ApiPreviewRequest,
    ChunkPreview,
    DocumentAnalyzeResponse,
    IngestionResponse,
    RAGAgentAnswerRequest,
    RAGAgentAnswerResponse,
    RAGAgentSSEEvent,
    RAGResponse,
    SearchQuery,
)
from apps.shared.permissions import knowledge_base_auth_state_allows
from apps.shared.services.permission_audit import record_resource_permission_denied
from apps.shared.services.permissions import (
    get_effective_knowledge_base_auth_state,
    has_organization_scope_access,
)
from apps.shared.services.knowledge_permission_service import KnowledgePermissionHelper
from apps.shared.services.rag_filters import normalize_metadata_filter
from apps.shared.services.rag_hierarchy import (
    RAGHierarchyError,
    validate_chunking_request,
)
from apps.shared.services.egress_guard import (
    API_RESPONSE_CONTENT_TYPES,
    EgressGuardError,
    EgressGuardPolicy,
    safe_http_request,
)

logger = logging.getLogger(__name__)
router = APIRouter()

SAFE_DOCUMENT_EXTENSIONS = {
    ".csv",
    ".docx",
    ".md",
    ".pdf",
    ".txt",
    ".xls",
    ".xlsx",
}


def _chunking_http_exception(exc: RAGHierarchyError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"reason": exc.reason, "message": exc.message},
    )


def _require_search_knowledge_base_id(request: Request, query: SearchQuery) -> UUID:
    if query.knowledge_base_id is None:
        raise_api_error(
            request,
            400,
            "validation.failed",
            "knowledge_base_id is required for RAG search-test.",
            {"field": "knowledge_base_id"},
        )
    return query.knowledge_base_id


def _authorize_rag_use(
    request: Request,
    db: Session,
    current_user: User,
    organization_id: UUID,
    knowledge_base_id: UUID,
) -> KnowledgeBase:
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == knowledge_base_id).first()
    if (
        kb is None
        or kb.organization_id != organization_id
        or not has_organization_scope_access(db, current_user.id, organization_id)
    ):
        raise_api_error(
            request,
            404,
            "resource.not_found",
            "Knowledge Base not found.",
        )

    decision = KnowledgePermissionHelper(
        db,
        user_id=current_user.id,
        organization_id=organization_id,
    ).evaluate_kb_use(kb)
    if decision.allowed:
        return kb

    if decision.external_reason_code == "resource.hidden":
        raise_api_error(
            request,
            404,
            "resource.hidden",
            "Knowledge Base not found.",
        )

    record_resource_permission_denied(
        user_id=current_user.id,
        resource_type="knowledge_base",
        resource_id=knowledge_base_id,
        action="use",
        effective_auth_state=decision.effective_auth_state,
        organization_id=organization_id,
        metadata={
            "request_id": getattr(request.state, "request_id", None),
            "path": request.url.path,
            "reason_code": decision.reason_code or "kb_use_denied",
        },
    )
    exc = HTTPException(
        status_code=403,
        detail=error_detail(
            request,
            "permission.denied",
            "Knowledge Base use permission is required.",
        ),
    )
    setattr(exc, "audit_recorded", True)
    raise exc


def _record_rag_retrieve_audit(
    request: Request,
    current_user: User,
    knowledge_base_id: UUID,
    metadata_filter,
    result_count: int,
    mode: str,
) -> None:
    metadata = {
        "actor": {
            "id": str(current_user.id),
            "email": getattr(current_user, "email", None),
            "name": getattr(current_user, "name", None),
        },
        "request_id": getattr(request.state, "request_id", None),
        "knowledge_base_id": str(knowledge_base_id),
        "retrieval_mode": mode,
        "result_count": result_count,
        "metadata_filter": metadata_filter.audit_summary()
        if metadata_filter is not None
        else {},
        "policy_evaluated": False,
    }
    record_audit(
        action=AuditAction.RAG_RETRIEVE,
        category="action",
        actor_id=current_user.id,
        actor_type="user",
        target_type="knowledge_base",
        target_id=knowledge_base_id,
        status="success",
        metadata=metadata,
    )


def _rag_agent_sse_event(event: str, data: dict) -> str:
    payload = RAGAgentSSEEvent(event=event, data=data).model_dump(mode="json")
    return (
        f"event: {payload['event']}\n"
        f"data: {json.dumps(payload['data'], ensure_ascii=False, default=str)}\n\n"
    )


async def _rag_agent_sse_events(
    events: AsyncIterator[tuple[str, dict]],
) -> AsyncIterator[str]:
    async for event, data in events:
        yield _rag_agent_sse_event(event, data)


@router.post("/agent/answer", response_model=RAGAgentAnswerResponse)
async def rag_agent_answer(
    payload: RAGAgentAnswerRequest,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = parse_organization_id(request, x_organization_id)
    service = RAGAgentAnswerService(
        db=db,
        current_user=current_user,
        request=request,
        organization_id=organization_id,
    )
    return await service.answer(payload)


@router.post("/agent/answer/stream")
async def rag_agent_answer_stream(
    payload: RAGAgentAnswerRequest,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = parse_organization_id(request, x_organization_id)
    service = RAGAgentAnswerService(
        db=db,
        current_user=current_user,
        request=request,
        organization_id=organization_id,
    )
    execution = service.prepare_execution(payload)
    return StreamingResponse(
        _rag_agent_sse_events(service.stream_events(execution)),
        media_type="text/event-stream",
    )


@router.post("/upload/presigned-url")
async def generate_presigned_url(
    filename: str = Body(..., embed=True),
    content_type: str = Body(..., embed=True),
    current_user: User = Depends(get_current_user),
):
    """
    S3 Presigned URL 생성 (프론트엔드 직접 업로드용)

    브라우저가 S3에 직접 파일을 업로드할 수 있는 임시 URL을 생성합니다.
    이를 통해 백엔드 서버 부하를 줄이고 업로드 속도를 향상시킬 수 있습니다.

    Args:
        filename: 업로드할 파일명
        content_type: 파일의 MIME 타입 (예: application/pdf)
        current_user: 인증된 사용자

    Returns:
        dict: {
            "upload_url": 브라우저가 PUT 요청을 보낼 Presigned URL,
            "s3_key": S3 객체 키 (나중에 참조용),
            "method": HTTP 메서드 ("PUT")
        }

    Example:
        Request:
        POST /api/v1/rag/upload/presigned-url
        {
            "filename": "document.pdf",
            "content_type": "application/pdf"
        }

        Response:
        {
            "upload_url": "https://s3.amazonaws.com/...?signature=...",
            "s3_key": "uploads/user-123/abc-123_document.pdf",
            "method": "PUT"
        }
    """
    try:
        safe_filename = _validate_safe_document_filename(filename)
        storage = get_storage_service()

        # S3 Presigned URL 생성
        presigned_data = storage.generate_presigned_upload_url(
            filename=safe_filename,
            content_type=content_type,
            user_id=str(current_user.id),
        )

        return {
            "upload_url": presigned_data["url"],
            "s3_key": presigned_data["key"],
            "method": presigned_data["method"],
            "use_backend_proxy": presigned_data.get("use_backend_proxy"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Presigned URL generation failed: %s", type(e).__name__)
        raise HTTPException(
            status_code=500,
            detail={"reason_code": "storage.presigned_url_failed"},
        )


@router.post("/upload", response_model=IngestionResponse)
@audit(AuditAction.DOCUMENT_UPLOAD)
async def upload_document(
    background_tasks: BackgroundTasks,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    file: Optional[UploadFile] = File(None, alias="file"),
    knowledge_base_id: Optional[UUID] = Form(None, alias="knowledgeBaseId"),
    source_type: str = Form("FILE", alias="sourceType"),
    # [NEW] S3 Direct Upload Fields
    s3_file_url: Optional[str] = Form(None, alias="s3FileUrl"),
    s3_file_key: Optional[str] = Form(None, alias="s3FileKey"),
    # API Config Fields
    api_url: Optional[str] = Form(None, alias="apiUrl"),
    api_method: str = Form("GET", alias="apiMethod"),
    api_headers: Optional[str] = Form(None, alias="apiHeaders"),
    api_body: Optional[str] = Form(None, alias="apiBody"),
    connection_id: Optional[UUID] = Form(None, alias="connectionId"),
    # 지식 베이스 신규 생성일 때만 필요한 정보들
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    ai_model: Optional[str] = Form(None, alias="embeddingModel"),
    top_k: int = Form(5, alias="topK"),
    similarity_threshold: float = Form(0.7, alias="similarity"),
    # 문서별 청킹 설정
    chunk_size: int = Form(1000, alias="chunkSize"),
    chunk_overlap: int = Form(200, alias="chunkOverlap"),
    chunking_mode: str = Form("flat", alias="chunkingMode"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    파일 업로드 및 처리 파이프라인 시작점

    [NEW] S3 Direct Upload 지원:
    - s3_file_url과 s3_file_key가 제공되면 이미 S3에 업로드된 파일로 처리
    - file이 제공되면 기존 방식대로 백엔드를 통해 S3에 업로드 (기존 방식)
    """
    # 0. 환경 변수 확인 (Ingestion Mode)
    ingestion_mode = (settings.STORAGE_TYPE or "LOCAL").upper()
    logger.info(f"=== [upload_document] Request Received (Mode: {ingestion_mode}) ===")
    organization_id = parse_organization_id(request, x_organization_id)

    # 1. 자료 확인 또는 생성
    target_kb_id, target_ai_model = _get_or_create_knowledge_base(
        request,
        db,
        current_user,
        organization_id,
        knowledge_base_id,
        name,
        description,
        ai_model,
        top_k,
        similarity_threshold,
        file,
    )

    # 2. Ingestion Service 초기화
    local_service = IngestionService(
        db,
        user_id=current_user.id,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        ai_model=target_ai_model,
    )

    # 3. 소스 타입별 데이터 준비 (Strategy Pattern)
    try:
        source_enum = SourceType(source_type)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid source type")

    try:
        normalized_chunking_mode = validate_chunking_request(
            chunking_mode=chunking_mode,
            source_type=source_enum,
        )
    except RAGHierarchyError as exc:
        raise _chunking_http_exception(exc)

    if source_enum == SourceType.FILE:
        # [NEW] S3 Direct Upload 방식
        if s3_file_url and s3_file_key:
            file_path, filename, meta_info = _prepare_direct_upload_source(
                s3_file_key=s3_file_key,
                user_id=current_user.id,
            )

        # [기존] 백엔드 중계 업로드 방식
        elif file:
            file_path, filename, meta_info = _prepare_file_source(local_service, file)
            meta_info["upload_method"] = "backend"
        else:
            raise HTTPException(
                status_code=400,
                detail="File or S3 URL is required for FILE source type",
            )
    elif source_enum == SourceType.API:
        file_path, filename, meta_info = _prepare_api_source(
            api_url, api_method, api_headers, api_body
        )
    elif source_enum == SourceType.DB:  # [NEW] DB 타입 처리
        file_path, filename, meta_info = _prepare_db_source(
            db, current_user, connection_id
        )
    else:
        raise HTTPException(status_code=400, detail="Invalid source type")

    meta_info = dict(meta_info or {})
    meta_info["chunking_mode"] = normalized_chunking_mode

    # 4. DB 레코드 생성 (Pending 상태)
    doc_id = local_service.create_pending_document(
        knowledge_base_id=target_kb_id,
        filename=filename,
        file_path=file_path,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        source_type=source_enum,
        meta_info=meta_info,
    )

    return IngestionResponse(
        knowledge_base_id=target_kb_id,
        document_id=doc_id,
        status="pending",
        message="자료가 등록되었습니다. 설정을 확인하고 처리를 시작해주세요.",
    )


def _prepare_db_source(db: Session, user: User, connection_id: Optional[UUID]):
    """DB 소스처리를 위한 데이터 준비"""
    if not connection_id:
        raise HTTPException(
            status_code=400, detail="Connection ID is required for DB source."
        )

    # 연결 정보 조회 및 권한 확인
    conn = (
        db.query(Connection)
        .filter(Connection.id == connection_id, Connection.user_id == user.id)
        .first()
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found.")

    meta_info = {
        "connection_id": str(conn.id),
        "db_type": conn.type,
        "connection_name": conn.name,
    }

    return None, conn.name, meta_info


@router.post("/document/{document_id}/analyze", response_model=DocumentAnalyzeResponse)
async def analyze_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    문서 분석 API: 페이지 수 및 LlamaParse 비용 예측 반환
    """
    ingestion_service = IngestionService(db, user_id=current_user.id)
    try:
        result = await ingestion_service.analyze_document(document_id)
        return result
    except Exception as e:
        logger.error("Document analysis failed: %s", type(e).__name__)
        raise HTTPException(
            status_code=400,
            detail={"reason_code": "document.analyze_failed"},
        )


@router.post("/document/{document_id}/confirm")
async def confirm_document_parsing(
    document_id: UUID,
    background_tasks: BackgroundTasks,
    strategy: str = "llamaparse",  # "llamaparse" or "general"
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    비용 승인 대기 중인 문서의 파싱을 재개합니다.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.status != "waiting_for_approval":
        raise HTTPException(status_code=400, detail="Document remains in invalid state")

    # 서비스 초기화 및 재개 (백그라운드)
    # 기존 설정(청크 사이즈 등)은 DB doc에 저장되어 있으므로 불러와서 쓴다고 가정
    ingestion_service = IngestionService(db, user_id=current_user.id)

    background_tasks.add_task(ingestion_service.resume_processing, document_id, strategy)

    return {
        "message": f"Parsing resumed with strategy: {strategy}",
        "status": "processing",
    }


@router.delete("/document/{document_id}")
@audit(AuditAction.DOCUMENT_DELETE, target_param="document_id")
def delete_document(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    문서를 삭제합니다. (연관된 청크도 자동 삭제됨)
    """
    # 1. 문서 조회 (권한 확인)
    doc = (
        db.query(Document)
        .join(KnowledgeBase)
        .filter(Document.id == document_id, KnowledgeBase.user_id == current_user.id)
        .first()
    )

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # 2. 파일 삭제 (S3/Local 자동 분기)
    if doc.file_path:
        storage = get_storage_service()
        try:
            storage.delete(doc.file_path)
        except Exception as e:
            logger.warning("Failed to delete document file: %s", type(e).__name__)
            # 파일 삭제 실패해도 DB는 삭제 진행

    # 3. DB 삭제 (Cascade로 청크도 같이 삭제됨)
    db.delete(doc)
    db.commit()

    return {"status": "success", "message": "Document deleted successfully"}


@router.post("/search-test/chat", response_model=RAGResponse)
async def search_test_chat(
    query: SearchQuery,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    [Search Test] RAG Chat Mode
    벡터 검색 + LLM 답변 생성
    """
    organization_id = parse_organization_id(request, x_organization_id)
    knowledge_base_id = _require_search_knowledge_base_id(request, query)
    _authorize_rag_use(request, db, current_user, organization_id, knowledge_base_id)
    metadata_filter = normalize_metadata_filter(
        metadata_filter=query.metadata_filter,
        classification_filter=query.classification_filter,
        tags=query.tags,
        source_type=query.source_type,
        effective_at=query.effective_at,
    )
    retrieval_service = RetrievalService(
        db,
        user_id=current_user.id,
        organization_id=organization_id,
    )
    try:
        response = await retrieval_service.generate_answer_for_test(
            query.query,
            knowledge_base_id=str(knowledge_base_id),
            model_id=query.generation_model or "gpt-4o",
            top_k=query.top_k or 5,
            metadata_filter=metadata_filter,
            hierarchy_mode=query.hierarchy_mode,
        )
    except ValueError as exc:
        if str(exc) == "hierarchy_unavailable":
            raise_api_error(
                request,
                422,
                "hierarchy_unavailable",
                "Hierarchical retrieval data is not available for this Knowledge Base.",
            )
        raise
    _record_rag_retrieve_audit(
        request,
        current_user,
        knowledge_base_id,
        metadata_filter,
        len(response.references),
        query.hierarchy_mode,
    )
    return response


@router.post("/search-test/pure", response_model=List[ChunkPreview])
async def search_test_pure(
    query: SearchQuery,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    [Search Test] Pure Retrieval Mode
    순수 벡터 검색 (LLM 생성 없음)
    """
    organization_id = parse_organization_id(request, x_organization_id)
    knowledge_base_id = _require_search_knowledge_base_id(request, query)
    _authorize_rag_use(request, db, current_user, organization_id, knowledge_base_id)
    metadata_filter = normalize_metadata_filter(
        metadata_filter=query.metadata_filter,
        classification_filter=query.classification_filter,
        tags=query.tags,
        source_type=query.source_type,
        effective_at=query.effective_at,
    )
    retrieval_service = RetrievalService(
        db,
        user_id=current_user.id,
        organization_id=organization_id,
    )

    # RetrievalService.search_documents 직접 호출 (비동기)
    try:
        results = await retrieval_service.search_documents(
            query.query,
            knowledge_base_id=str(knowledge_base_id),
            top_k=query.top_k or 5,
            metadata_filter=metadata_filter,
            hierarchy_mode=query.hierarchy_mode,
        )
    except ValueError as exc:
        if str(exc) == "hierarchy_unavailable":
            raise_api_error(
                request,
                422,
                "hierarchy_unavailable",
                "Hierarchical retrieval data is not available for this Knowledge Base.",
            )
        raise
    _record_rag_retrieve_audit(
        request,
        current_user,
        knowledge_base_id,
        metadata_filter,
        len(results),
        query.hierarchy_mode,
    )
    return results


@router.get("/document/{document_id}/progress")
async def get_document_progress(
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    [SSE] 문서 처리 진행 상황을 실시간 스트리밍으로 반환합니다.
    """
    import asyncio
    import json

    from fastapi.responses import StreamingResponse

    from apps.shared.pubsub import get_redis_client

    async def event_generator():
        while True:
            # 1. DB에서 문서 상태 조회 (Polling)
            db.expire_all()
            doc = db.query(Document).get(document_id)

            if not doc:
                yield 'data: {"error": "Document not found"}\n\n'
                break

            if finalize_stale_processing_start(
                db,
                document_id,
            ) or recover_timed_out_document_with_artifacts(db, document_id):
                db.refresh(doc)

            status = doc.status

            # 2. Redis에서 실시간 진행률 조회 (에러 핸들링 포함)
            redis_progress = None
            try:
                redis_client = get_redis_client()
                redis_key = f"knowledge_progress:{document_id}"
                redis_progress = redis_client.get(redis_key)
            except Exception as e:
                logger.warning("Redis read failed for progress: %s", type(e).__name__)

            # 3. 진행률 결정 (상태 기반 우선)
            if status == "completed":
                progress = 100
            elif status == "failed":
                progress = 0
            elif redis_progress:
                try:
                    progress = int(redis_progress)
                except (ValueError, TypeError):
                    # Redis 값이 손상되었으면 이번 전송 건너뛰고 재시도
                    continue
            else:
                progress = 0

            # 메타 정보에서는 메시지만 가져옴
            meta = doc.meta_info or {}
            step_message = meta.get("processing_current_step", "처리 중...")

            # 4. 데이터 전송 포맷 (SSE 표준: "data: ...\n\n")
            data = json.dumps(
                {
                    "progress": progress,
                    "message": step_message,
                    "status": status,
                    "error": doc.error_message,
                },
                ensure_ascii=False,
            )

            yield f"data: {data}\n\n"

            # 5. 종료 조건
            if status == "completed" or progress >= 100:
                break
            if status == "failed":
                break

            # 1초 대기 (서버 부하 방지)
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/proxy/preview")
async def proxy_api_preview(
    request: ApiPreviewRequest,
    current_user: User = Depends(get_current_user),
):
    """
    프론트엔드 CORS 문제 해결을 위한 API 프록시 엔드포인트.
    Knowledge/RAG outbound guard를 거치지 않는 raw HTTP client는 사용하지 않는다.
    """
    import asyncio

    # 기본 헤더가 없으면 추가
    headers = request.headers or {}
    if "User-Agent" not in headers:
        headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
    method = str(request.method or "GET").upper()
    if method not in {"GET", "POST"}:
        raise HTTPException(
            status_code=400,
            detail={"reason_code": "egress.unsupported_method"},
        )

    try:
        response = await asyncio.to_thread(
            safe_http_request,
            method,
            request.url,
            headers=headers,
            json_body=request.body,
            policy=EgressGuardPolicy(
                timeout_seconds=30.0,
                max_response_bytes=10 * 1024 * 1024,
                allowed_content_types=API_RESPONSE_CONTENT_TYPES,
            ),
        )
        if response.status_code >= 400:
            raise HTTPException(
                status_code=response.status_code,
                detail={"reason_code": "egress.upstream_error"},
            )

        try:
            data = response.json()
        except Exception:
            data = response.text

        return {
            "status": response.status_code,
            "data": data,
            "headers": response.headers,
        }

    except EgressGuardError as e:
        logger.warning("[Proxy Log] Egress guard denied request: %s", e.reason_code)
        status_code = 504 if e.reason_code == "egress.timeout" else 400
        raise HTTPException(
            status_code=status_code,
            detail={"reason_code": e.reason_code},
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error("[Proxy Log] 기타 오류 발생: %s", type(e).__name__)
        raise HTTPException(
            status_code=500,
            detail={"reason_code": "egress.proxy_failed"},
        )


def _get_or_create_knowledge_base(
    request: Request,
    db: Session,
    user: User,
    organization_id: UUID,
    kb_id: Optional[UUID],
    name: Optional[str],
    description: Optional[str],
    ai_model: Optional[str],
    top_k: int,
    similarity_threshold: float,
    file: Optional[UploadFile],
) -> tuple[UUID, str]:
    """자료를 조회하거나 새로 생성합니다."""
    if not kb_id:
        if not has_organization_scope_access(db, user.id, organization_id):
            raise_api_error(
                request,
                404,
                "resource.not_found",
                "Knowledge Base not found.",
            )
        if not ai_model:
            raise HTTPException(
                status_code=400,
                detail="Embedding model must be selected for new Knowledge Base",
            )

        # 이름 결정: 입력된 이름 -> (파일 있으면 파일명) -> "API Source"
        kb_name = name if name else (file.filename if file else "API Source")

        new_kb = KnowledgeBase(
            user_id=user.id,
            organization_id=organization_id,
            name=kb_name,
            description=description,
            embedding_model=ai_model,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
        )
        db.add(new_kb)
        db.commit()
        db.refresh(new_kb)
        return new_kb.id, ai_model

    else:
        kb: KnowledgeBase = (
            db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
        )
        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge Base not found")
        if kb.organization_id != organization_id:
            raise HTTPException(status_code=404, detail="Knowledge Base not found")
        _authorize_upload_knowledge_base_write(request, db, user, kb)
        return kb.id, kb.embedding_model


def _authorize_upload_knowledge_base_write(
    request: Request,
    db: Session,
    user: User,
    kb: KnowledgeBase,
) -> None:
    if kb.organization_id and not has_organization_scope_access(
        db,
        user.id,
        kb.organization_id,
    ):
        raise HTTPException(status_code=404, detail="Knowledge Base not found")

    if kb.user_id == user.id:
        return

    effective_auth_state = get_effective_knowledge_base_auth_state(
        db,
        user.id,
        kb.id,
        organization_id=kb.organization_id,
    )
    if knowledge_base_auth_state_allows(effective_auth_state, "write"):
        return

    record_resource_permission_denied(
        user_id=user.id,
        resource_type="knowledge_base",
        resource_id=kb.id,
        action="write",
        effective_auth_state=effective_auth_state,
        organization_id=kb.organization_id,
        metadata={
            "request_id": getattr(request.state, "request_id", None),
            "path": request.url.path,
        },
    )
    exc = HTTPException(
        status_code=403,
        detail=error_detail(
            request,
            "permission.denied",
            "Knowledge Base write permission is required.",
        ),
    )
    setattr(exc, "audit_recorded", True)
    raise exc


def _validate_safe_document_filename(filename: str) -> str:
    safe_name = str(filename or "").replace("\\", "/").split("/")[-1]
    ext = "." + safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else ""
    if not safe_name or ext not in SAFE_DOCUMENT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail={"reason_code": "file_type.unsupported"},
        )
    return safe_name


def _prepare_file_source(local_service: IngestionService, file: Optional[UploadFile]):
    """파일 자료 처리를 위한 데이터 준비"""
    if not file:
        raise HTTPException(status_code=400, detail="File is required for FILE source")

    filename = _validate_safe_document_filename(file.filename)
    file.filename = filename
    file_path = local_service.save_temp_file(file)
    return file_path, filename, {}


def _prepare_direct_upload_source(
    *,
    s3_file_key: str,
    user_id: UUID,
) -> tuple[str, str, dict]:
    key = str(s3_file_key or "").strip().replace("\\", "/")
    expected_prefix = f"uploads/{user_id}/"
    if (
        not key
        or key.startswith("/")
        or ".." in key.split("/")
        or not key.startswith(expected_prefix)
    ):
        raise HTTPException(
            status_code=400,
            detail={"reason_code": "storage.invalid_object_key"},
        )

    filename = _validate_safe_document_filename(key.rsplit("/", 1)[-1])
    if not settings.S3_BUCKET_NAME or not settings.AWS_REGION:
        raise HTTPException(
            status_code=400,
            detail={"reason_code": "storage.s3_not_configured"},
        )

    encoded_key = quote(key, safe="/")
    file_path = (
        f"https://{settings.S3_BUCKET_NAME}.s3."
        f"{settings.AWS_REGION}.amazonaws.com/{encoded_key}"
    )
    return file_path, filename, {"s3_key": key, "upload_method": "direct"}


def _encrypt_source_config_value(value: str) -> str:
    from apps.shared.utils.encryption import encryption_manager as security_service

    try:
        return security_service.encrypt(value)
    except Exception as exc:
        logger.error("Failed to encrypt API source configuration: %s", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail={"reason_code": "source_config.encryption_required"},
        ) from exc


def _prepare_api_source(
    api_url: Optional[str],
    api_method: str,
    api_headers: Optional[str],
    api_body: Optional[str],
):
    """API 자료 처리를 위한 데이터 준비"""
    if not api_url:
        raise HTTPException(status_code=400, detail="API URL is required")

    import json

    # 헤더 처리 (JSON 파싱 및 암호화)
    encrypted_headers = None
    if api_headers:
        try:
            json.loads(api_headers)  # 유효성 검증
        except Exception as e:
            logger.warning("Failed to process API source headers: %s", type(e).__name__)
            raise HTTPException(
                status_code=400,
                detail={"reason_code": "validation.failed"},
            ) from e
        encrypted_headers = _encrypt_source_config_value(api_headers)

    # URL query와 body에는 token/secret이 들어갈 수 있으므로 원문을 durable metadata에 저장하지 않는다.
    encrypted_url = _encrypt_source_config_value(api_url)
    encrypted_body = None
    if api_body:
        try:
            json.loads(api_body)
        except Exception as e:
            logger.warning("Failed to process API source body: %s", type(e).__name__)
            raise HTTPException(
                status_code=400,
                detail={"reason_code": "validation.failed"},
            ) from e
        encrypted_body = _encrypt_source_config_value(api_body)

    method = str(api_method or "GET").upper()
    if method not in {"GET", "POST"}:
        raise HTTPException(
            status_code=400,
            detail={"reason_code": "egress.unsupported_method"},
        )

    meta_info = {
        "api_config": {
            "url_encrypted": encrypted_url,
            "method": method,
            "headers_encrypted": encrypted_headers,
            "body_encrypted": encrypted_body,
            "safe_label": "API source",
        }
    }

    return None, "API source", meta_info
