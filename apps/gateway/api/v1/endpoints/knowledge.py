import html
import json
import logging
import mimetypes
import os
import tempfile
from typing import List
from uuid import UUID

import pandas as pd
from docx import Document as DocxDocument
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    StreamingResponse,
)
from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.orm import Session

from apps.gateway.api.deps import get_db
from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.utils.api_errors import raise_api_error
from apps.gateway.utils.audit import audit
from apps.gateway.services.ingestion.service import (
    IngestionOrchestrator as IngestionService,
)
from apps.gateway.services.knowledge_candidate_resolver import KnowledgeCandidateResolver
from apps.gateway.services.knowledge_collection_service import (
    KnowledgeCollectionService,
    KnowledgeCollectionServiceError,
)
from apps.gateway.services.knowledge_rag_recommendation_service import (
    KnowledgeRAGRecommendationService,
)
from apps.gateway.services.organization_context import (
    get_user_primary_organization_id,
    resolve_active_organization_id,
)
from apps.shared.audit.actions import AuditAction
from apps.shared.db.models.knowledge import Document, KnowledgeBase
from apps.shared.db.models.user import User
from apps.shared.schemas.knowledge import (
    KnowledgeCandidateResolution,
    KnowledgeCandidateResolveRequest,
    KnowledgeCollectionCreateRequest,
    KnowledgeCollectionItemLinkRequest,
    KnowledgeCollectionItemReorderRequest,
    KnowledgeCollectionItemsResponse,
    KnowledgeCollectionLinkCandidatesResponse,
    KnowledgeCollectionListResponse,
    KnowledgeCollectionPermissionGrantRequest,
    KnowledgeCollectionPermissionsResponse,
    KnowledgeCollectionResponse,
    KnowledgeCollectionUpdateRequest,
    KnowledgeCollectionVisibilityRequest,
    KnowledgeCollectionVisibilityResponse,
    KnowledgeRAGRecommendationRequest,
    KnowledgeRAGRecommendationResponse,
)
from apps.shared.schemas.rag import (
    DocumentPreviewRequest,
    DocumentPreviewResponse,
    DocumentResponse,
    KnowledgeBaseCreate,
    KnowledgeBaseDetailResponse,
    KnowledgeBaseResponse,
    KnowledgeUpdate,
)
from apps.shared.services.rag_hierarchy import (
    RAGHierarchyError,
    validate_chunking_request,
)
from apps.shared.services.egress_guard import (
    DOCUMENT_RESPONSE_CONTENT_TYPES,
    EgressGuardError,
    EgressGuardPolicy,
    safe_http_request,
    safe_quote_filename,
)
from apps.shared.services.knowledge_permission_service import KnowledgePermissionHelper

logger = logging.getLogger(__name__)
router = APIRouter()

SAFE_INLINE_FILE_EXTENSIONS = {".md", ".pdf", ".txt"}
SAFE_INLINE_MEDIA_TYPES = {"application/pdf", "text/markdown", "text/plain"}


def _chunking_http_exception(exc: RAGHierarchyError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"reason": exc.reason, "message": exc.message},
    )


def _content_disposition_type_for_document(filename: str, media_type: str) -> str:
    ext = os.path.splitext(str(filename or ""))[1].lower()
    if ext in SAFE_INLINE_FILE_EXTENSIONS and media_type in SAFE_INLINE_MEDIA_TYPES:
        return "inline"
    return "attachment"


def _knowledge_collection_service(
    db: Session,
    request: Request,
    raw_organization_id: str | None,
    current_user: User,
) -> KnowledgeCollectionService:
    organization_id = resolve_active_organization_id(
        db,
        request,
        raw_organization_id,
        current_user.id,
    )
    return KnowledgeCollectionService(
        db,
        user_id=current_user.id,
        organization_id=organization_id,
    )


def _raise_collection_service_error(
    request: Request,
    exc: KnowledgeCollectionServiceError,
) -> None:
    raise_api_error(
        request,
        exc.status_code,
        exc.code,
        exc.message,
        exc.details,
    )


@router.post(
    "", response_model=KnowledgeBaseResponse, status_code=status.HTTP_201_CREATED
)
@audit(AuditAction.KNOWLEDGE_CREATE)
def create_knowledge_base(
    kb_in: KnowledgeBaseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    빈 지식 베이스를 생성합니다. (소스 없음)
    """
    # 임베딩 모델 유효성 검사 등은 생략하거나 추후 추가
    kb = KnowledgeBase(
        name=kb_in.name,
        description=kb_in.description,
        embedding_model=kb_in.embedding_model,
        organization_id=get_user_primary_organization_id(db, current_user.id),
        user_id=current_user.id,
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)

    return KnowledgeBaseResponse(
        id=kb.id,
        organization_id=kb.organization_id,
        name=kb.name,
        description=kb.description,
        document_count=0,
        created_at=kb.created_at,
        updated_at=kb.updated_at,
        source_types=[],
        embedding_model=kb.embedding_model,
    )


@router.get("", response_model=List[KnowledgeBaseResponse])
def list_knowledge_bases(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    사용자의 자료 목록을 조회합니다.
    각 지식 베이스 그룹에 포함된 문서 개수도 함께 반환합니다.
    """

    results = (
        db.query(
            KnowledgeBase,
            func.count(Document.id).label("document_count"),
            func.max(Document.updated_at).label("last_updated_at"),
            func.array_agg(Document.source_type).label("source_types"),
        )
        .outerjoin(Document, KnowledgeBase.id == Document.knowledge_base_id)
        .filter(KnowledgeBase.user_id == current_user.id)
        .group_by(KnowledgeBase.id)
        .order_by(KnowledgeBase.created_at.desc())
        .all()
    )

    response = []
    for kb, doc_count, last_updated_at, source_types in results:
        # source_types가 [None]인 경우 (문서가 없을 때) 빈 리스트로 처리
        clean_source_types = [st for st in source_types if st is not None]

        # KB 업데이트 시간과 문서 최신 업데이트 시간 중 더 최신을 선택
        # 문서가 없으면 KB 업데이트 시간 사용
        final_updated_at = (
            max(kb.updated_at, last_updated_at) if last_updated_at else kb.updated_at
        )

        response.append(
            KnowledgeBaseResponse(
                id=kb.id,
                organization_id=kb.organization_id,
                name=kb.name,
                description=kb.description,
                document_count=doc_count,
                created_at=kb.created_at,
                updated_at=final_updated_at,
                source_types=clean_source_types,
                embedding_model=kb.embedding_model,
            )
        )
    return response


@router.post("/candidates/resolve", response_model=KnowledgeCandidateResolution)
def resolve_knowledge_candidates(
    candidate_request: KnowledgeCandidateResolveRequest,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Workflow Builder와 deployment preflight가 사용할 안전한 Knowledge 후보를 조회합니다.
    """
    organization_id = resolve_active_organization_id(
        db,
        request,
        x_organization_id,
        current_user.id,
    )
    runtime_permission_helper = None
    if candidate_request.intended_execution_subject_id:
        runtime_permission_helper = KnowledgePermissionHelper(
            db,
            user_id=candidate_request.intended_execution_subject_id,
            organization_id=organization_id,
        )

    resolver = KnowledgeCandidateResolver(
        db,
        user_id=current_user.id,
        organization_id=organization_id,
        runtime_permission_helper=runtime_permission_helper,
    )

    # 예상 실행 대상이 명시되어도 Phase 7에서는 후보 노출 scope만 좁힌다.
    # 실제 runtime 권한 판정은 Workflow execution_subject 기준으로 다시 수행한다.
    if candidate_request.mode == "explicit_kb":
        return resolver.resolve_explicit_kbs(candidate_request.knowledge_base_ids)

    return resolver.resolve_auto_collection_candidates(
        collection_ids=candidate_request.collection_ids,
        max_collections=candidate_request.max_collections,
        max_candidate_kbs=candidate_request.max_candidate_kbs,
    )


def _safe_validation_errors(exc: ValidationError) -> list[dict]:
    # workflow_intent/node_purpose는 prompt-like 입력이므로 validation 응답에서도 raw input을 제거한다.
    # Pydantic errors()의 input 필드는 의도치 않게 사용자 원문을 echo할 수 있다.
    errors = []
    for error in exc.errors():
        errors.append(
            {
                "loc": list(error.get("loc", ())),
                "msg": error.get("msg", "Invalid input."),
                "type": error.get("type", "value_error"),
            }
        )
    return errors


async def _parse_rag_recommendation_request(
    request: Request,
) -> KnowledgeRAGRecommendationRequest:
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise_api_error(
            request,
            422,
            "validation.failed",
            "Request validation failed.",
            {
                "errors": [
                    {
                        "loc": ["body"],
                        "msg": "Invalid JSON body.",
                        "type": "json_invalid",
                    }
                ]
            },
        )

    try:
        return KnowledgeRAGRecommendationRequest.model_validate(payload)
    except ValidationError as exc:
        raise_api_error(
            request,
            422,
            "validation.failed",
            "Request validation failed.",
            {"errors": _safe_validation_errors(exc)},
        )


@router.post("/rag-recommendations", response_model=KnowledgeRAGRecommendationResponse)
async def recommend_rag_options(
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Workflow Builder가 LLM node RAG 옵션을 구성할 때 사용할 안전한 KB 추천을 반환합니다.
    """
    recommendation_request = await _parse_rag_recommendation_request(request)
    organization_id = resolve_active_organization_id(
        db,
        request,
        x_organization_id,
        current_user.id,
    )
    service = KnowledgeRAGRecommendationService(
        db,
        user_id=current_user.id,
        organization_id=organization_id,
    )
    return service.recommend_for_builder(recommendation_request)


@router.get("/collections", response_model=KnowledgeCollectionListResponse)
def list_knowledge_collections(
    request: Request,
    lifecycle_state: str = Query(default="active"),
    visibility: str | None = Query(default=None),
    system_managed: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = _knowledge_collection_service(db, request, x_organization_id, current_user)
    try:
        collections = service.list_collections(
            lifecycle_state=lifecycle_state,
            visibility=visibility,
            system_managed=system_managed,
            limit=limit,
        )
    except KnowledgeCollectionServiceError as exc:
        _raise_collection_service_error(request, exc)
    return KnowledgeCollectionListResponse(collections=collections)


@router.post(
    "/collections",
    response_model=KnowledgeCollectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_knowledge_collection(
    collection_request: KnowledgeCollectionCreateRequest,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = _knowledge_collection_service(db, request, x_organization_id, current_user)
    try:
        return service.create_collection(collection_request)
    except KnowledgeCollectionServiceError as exc:
        _raise_collection_service_error(request, exc)


@router.get("/collections/{collection_id}", response_model=KnowledgeCollectionResponse)
def get_knowledge_collection(
    collection_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = _knowledge_collection_service(db, request, x_organization_id, current_user)
    try:
        return service.get_collection(collection_id)
    except KnowledgeCollectionServiceError as exc:
        _raise_collection_service_error(request, exc)


@router.patch("/collections/{collection_id}", response_model=KnowledgeCollectionResponse)
def update_knowledge_collection(
    collection_id: UUID,
    collection_request: KnowledgeCollectionUpdateRequest,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = _knowledge_collection_service(db, request, x_organization_id, current_user)
    try:
        return service.update_collection(collection_id, collection_request)
    except KnowledgeCollectionServiceError as exc:
        _raise_collection_service_error(request, exc)


@router.delete("/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_knowledge_collection(
    collection_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = _knowledge_collection_service(db, request, x_organization_id, current_user)
    try:
        service.archive_collection(collection_id)
    except KnowledgeCollectionServiceError as exc:
        _raise_collection_service_error(request, exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/collections/{collection_id}/items",
    response_model=KnowledgeCollectionItemsResponse,
)
def list_knowledge_collection_items(
    collection_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = _knowledge_collection_service(db, request, x_organization_id, current_user)
    try:
        return KnowledgeCollectionItemsResponse(items=service.list_items(collection_id))
    except KnowledgeCollectionServiceError as exc:
        _raise_collection_service_error(request, exc)


@router.post(
    "/collections/{collection_id}/items",
    response_model=KnowledgeCollectionItemsResponse,
)
def link_knowledge_collection_item(
    collection_id: UUID,
    item_request: KnowledgeCollectionItemLinkRequest,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = _knowledge_collection_service(db, request, x_organization_id, current_user)
    try:
        item = service.link_item(collection_id, item_request)
        return KnowledgeCollectionItemsResponse(items=[item])
    except KnowledgeCollectionServiceError as exc:
        _raise_collection_service_error(request, exc)


@router.patch(
    "/collections/{collection_id}/items/reorder",
    response_model=KnowledgeCollectionItemsResponse,
)
def reorder_knowledge_collection_items(
    collection_id: UUID,
    reorder_request: KnowledgeCollectionItemReorderRequest,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = _knowledge_collection_service(db, request, x_organization_id, current_user)
    try:
        return KnowledgeCollectionItemsResponse(
            items=service.reorder_items(collection_id, reorder_request)
        )
    except KnowledgeCollectionServiceError as exc:
        _raise_collection_service_error(request, exc)


@router.delete(
    "/collections/{collection_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def unlink_knowledge_collection_item(
    collection_id: UUID,
    item_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = _knowledge_collection_service(db, request, x_organization_id, current_user)
    try:
        service.unlink_item(collection_id, item_id)
    except KnowledgeCollectionServiceError as exc:
        _raise_collection_service_error(request, exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/collections/{collection_id}/link-candidates",
    response_model=KnowledgeCollectionLinkCandidatesResponse,
)
def list_knowledge_collection_link_candidates(
    collection_id: UUID,
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = _knowledge_collection_service(db, request, x_organization_id, current_user)
    try:
        return KnowledgeCollectionLinkCandidatesResponse(
            candidates=service.list_link_candidates(collection_id, limit=limit)
        )
    except KnowledgeCollectionServiceError as exc:
        _raise_collection_service_error(request, exc)


@router.get(
    "/collections/{collection_id}/permissions",
    response_model=KnowledgeCollectionPermissionsResponse,
)
def list_knowledge_collection_permissions(
    collection_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = _knowledge_collection_service(db, request, x_organization_id, current_user)
    try:
        return KnowledgeCollectionPermissionsResponse(
            permissions=service.list_permissions(collection_id)
        )
    except KnowledgeCollectionServiceError as exc:
        _raise_collection_service_error(request, exc)


@router.post(
    "/collections/{collection_id}/permissions",
    response_model=KnowledgeCollectionPermissionsResponse,
)
def grant_knowledge_collection_permission(
    collection_id: UUID,
    permission_request: KnowledgeCollectionPermissionGrantRequest,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = _knowledge_collection_service(db, request, x_organization_id, current_user)
    try:
        permission = service.grant_permission(collection_id, permission_request)
        return KnowledgeCollectionPermissionsResponse(permissions=[permission])
    except KnowledgeCollectionServiceError as exc:
        _raise_collection_service_error(request, exc)


@router.delete(
    "/collections/{collection_id}/permissions/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_knowledge_collection_permission(
    collection_id: UUID,
    permission_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = _knowledge_collection_service(db, request, x_organization_id, current_user)
    try:
        service.revoke_permission(collection_id, permission_id)
    except KnowledgeCollectionServiceError as exc:
        _raise_collection_service_error(request, exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/collections/{collection_id}/visibility",
    response_model=KnowledgeCollectionVisibilityResponse,
)
def update_knowledge_collection_visibility(
    collection_id: UUID,
    visibility_request: KnowledgeCollectionVisibilityRequest,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = _knowledge_collection_service(db, request, x_organization_id, current_user)
    try:
        return service.update_visibility(collection_id, visibility_request)
    except KnowledgeCollectionServiceError as exc:
        _raise_collection_service_error(request, exc)


@router.get("/{kb_id}", response_model=KnowledgeBaseDetailResponse)
def get_knowledge_base(
    kb_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    지식 베이스의 상세 정보를 조회합니다.
    포함된 자료 목록과 각 자료의 상태를 함께 반환합니다.
    """
    kb = (
        db.query(KnowledgeBase)
        .filter(KnowledgeBase.id == kb_id, KnowledgeBase.user_id == current_user.id)
        .first()
    )

    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")

    # 문서 목록 변환
    doc_responses = []
    for doc in kb.documents:
        # TODO: 청크 개수나 토큰 수는 별도 쿼리로 최적화 필요 (현재는 Lazy Loading)
        doc_responses.append(
            DocumentResponse(
                id=doc.id,
                filename=doc.filename,
                status=doc.status,
                created_at=doc.created_at,
                updated_at=doc.updated_at,
                error_message=doc.error_message,
                chunk_count=len(doc.chunks),  # N+1 발생 가능, 추후 최적화
                token_count=0,  # 우선 0으로 반환
                source_type=doc.source_type,
                meta_info=doc.meta_info,
            )
        )

    return KnowledgeBaseDetailResponse(
        id=kb.id,
        organization_id=kb.organization_id,
        name=kb.name,
        description=kb.description,
        document_count=len(doc_responses),
        created_at=kb.created_at,
        embedding_model=kb.embedding_model,
        documents=doc_responses,
    )


@router.patch("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
@audit(AuditAction.KNOWLEDGE_UPDATE, target_param="kb_id")
def update_knowledge_base(
    kb_id: UUID,
    update_data: KnowledgeUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    지식 베이스의 설정을 수정합니다. (이름, 설명, 즐겨찾기 임베딩 모델)
    """
    kb = (
        db.query(KnowledgeBase)
        .filter(KnowledgeBase.id == kb_id, KnowledgeBase.user_id == current_user.id)
        .first()
    )

    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")

    if update_data.name is not None:
        kb.name = update_data.name
    if update_data.description is not None:
        kb.description = update_data.description

    # 임베딩 모델 변경 및 재인덱싱 트리거
    if (
        update_data.embedding_model is not None
        and update_data.embedding_model != kb.embedding_model
    ):
        kb.embedding_model = update_data.embedding_model

        # 재인덱싱 트리거
        orchestrator = IngestionService(db, current_user.id)
        background_tasks.add_task(
            orchestrator.reindex_knowledge_base, kb.id, update_data.embedding_model
        )

    db.commit()
    db.refresh(kb)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
@audit(AuditAction.KNOWLEDGE_DELETE, target_param="kb_id")
def delete_knowledge_base(
    kb_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    지식 베이스를 삭제합니다.
    연결된 문서 및 임베딩 데이터는 DB Cascade 설정에 따라 함께 삭제됩니다.
    물리적 파일(S3/Local)도 함께 삭제합니다.
    """
    kb = (
        db.query(KnowledgeBase)
        .filter(KnowledgeBase.id == kb_id, KnowledgeBase.user_id == current_user.id)
        .first()
    )

    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge Base not found")

    # 물리적 파일 삭제 (Storage)
    from services.storage import get_storage_service

    storage = get_storage_service()

    for doc in kb.documents:
        if doc.file_path:
            try:
                # S3/Local 파일 삭제
                storage.delete(doc.file_path)
            except Exception as e:
                # 파일 삭제 실패하더라도 DB 삭제는 계속 진행 (로그만 남김)
                logger.warning(
                    "Failed to delete document file for doc %s: %s",
                    doc.id,
                    type(e).__name__,
                )

    # DB 삭제 (Cascade로 청크도 같이 삭제됨)
    db.delete(kb)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{kb_id}/documents/{document_id}", response_model=DocumentResponse)
def get_document(
    kb_id: UUID,
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    특정 문서를 조회합니다.
    """
    doc = (
        db.query(Document)
        .join(KnowledgeBase)
        .filter(Document.id == document_id, KnowledgeBase.user_id == current_user.id)
        .first()
    )

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.knowledge_base_id != kb_id:
        raise HTTPException(
            status_code=400, detail="Document does not belong to this Knowledge Base"
        )

    return DocumentResponse(
        id=doc.id,
        filename=doc.filename,
        status=doc.status,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        error_message=doc.error_message,
        chunk_count=len(doc.chunks),
        # token_count=doc.token_count,
        source_type=doc.source_type,
        meta_info=doc.meta_info,
    )


@router.get("/{kb_id}/documents/{document_id}/content")
def get_document_content(
    kb_id: UUID,
    document_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    문서의 원본 파일을 반환합니다. (브라우저 표시용)
    """
    doc = (
        db.query(Document)
        .join(KnowledgeBase)
        .filter(Document.id == document_id, KnowledgeBase.user_id == current_user.id)
        .first()
    )

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found in DB")

    if doc.knowledge_base_id != kb_id:
        raise HTTPException(
            status_code=400, detail="Document does not belong to this Knowledge Base"
        )

    # API 소스는 파일이 없으므로 미리보기 불가 처리
    if doc.source_type == "API" or not doc.file_path:
        raise HTTPException(
            status_code=400,
            detail="API로 받은 응답은 원문 보기를 제공하지 않습니다.",
        )

    # file path가 S3 URL인지 확인합니다.
    is_s3_file = str(doc.file_path).startswith("http") or str(doc.file_path).startswith(
        "s3://"
    )

    # 파일 존재 확인 (Local only)
    if not is_s3_file and not os.path.exists(doc.file_path):
        raise HTTPException(status_code=404, detail="File not found on server")

    # 미디어 타입 추론
    media_type, _ = mimetypes.guess_type(doc.file_path)
    if not media_type:
        media_type = "application/octet-stream"
    content_disposition_type = _content_disposition_type_for_document(
        doc.filename,
        media_type,
    )

    # Excel/CSV/Word 파일은 HTML로 변환하여 미리보기 제공
    ext = os.path.splitext(doc.filename)[1].lower()
    if ext in [".xlsx", ".xls", ".csv", ".docx"]:
        temp_file_path = None
        try:
            target_path = doc.file_path

            # S3 파일인 경우 임시 다운로드
            if is_s3_file:
                if doc.file_path.startswith("s3://"):
                    # s3:// 프로토콜은 presigned url 변환이 필요하나, 현재는 http url을 가정
                    pass
                else:
                    response = safe_http_request(
                        "GET",
                        doc.file_path,
                        policy=EgressGuardPolicy(
                            timeout_seconds=30.0,
                            max_response_bytes=50 * 1024 * 1024,
                            allowed_content_types=DOCUMENT_RESPONSE_CONTENT_TYPES,
                        ),
                    )
                    if response.status_code >= 400:
                        raise RuntimeError("Remote file returned an error.")

                    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                        tmp.write(response.content)
                        temp_file_path = tmp.name
                        target_path = temp_file_path

            body_content = ""

            if ext == ".docx":
                # WORD 처리
                doc_word = DocxDocument(target_path)
                paragraphs = [
                    f"<p>{html.escape(p.text)}</p>"
                    for p in doc_word.paragraphs
                    if p.text.strip()
                ]

                # 표 내용도 간단히 추가
                for table in doc_word.tables:
                    rows_html = []
                    for row in table.rows:
                        cells = [
                            f"<td>{html.escape(cell.text)}</td>"
                            for cell in row.cells
                        ]
                        rows_html.append(f"<tr>{''.join(cells)}</tr>")
                    if rows_html:
                        paragraphs.append(
                            f"<table class='docx-table'>{''.join(rows_html)}</table>"
                        )

                body_content = "\n".join(paragraphs)

            else:
                # EXCEL/CSV 처리
                if ext == ".csv":
                    df = pd.read_csv(target_path, nrows=100)
                else:
                    df = pd.read_excel(target_path, nrows=100)

                body_content = f"""
                <div class="info-banner">
                    <span>⚠️</span>
                    성능을 위해 상위 100행만 미리보기로 제공됩니다.
                </div>
                {df.to_html(index=False, border=0)}
                """

            # 공통 HTML 스타일링
            html_content = f"""
            <html>
            <head>
                <style>
                    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 20px; background-color: #ffffff; line-height: 1.6; }}
                    /* Table Styles */
                    table {{ border-collapse: collapse; width: 100%; font-size: 14px; border: 1px solid #e5e7eb; margin-bottom: 20px; }}
                    th {{ background-color: #f9fafb; color: #374151; font-weight: 600; text-align: left; padding: 12px 16px; border-bottom: 1px solid #e5e7eb; }}
                    td {{ padding: 12px 16px; border-bottom: 1px solid #e5e7eb; color: #4b5563; }}
                    tr:last-child td {{ border-bottom: none; }}
                    tr:hover td {{ background-color: #f9fafb; }}
                    
                    /* Docx Specific */
                    p {{ margin-bottom: 0.8em; color: #1f2937; }}
                    .docx-table td {{ border: 1px solid #e5e7eb; }}

                    .info-banner {{
                        margin-bottom: 16px; padding: 10px 14px; background: #fffbeb; border: 1px solid #fcd34d;
                        color: #92400e; border-radius: 6px; font-size: 13px; font-weight: 500; display: flex; align-items: center; gap: 6px;
                    }}
                </style>
            </head>
            <body>
                {body_content}
            </body>
            </html>
            """
            return HTMLResponse(content=html_content)
        except EgressGuardError as e:
            logger.warning("External preview denied by egress guard: %s", e.reason_code)
            raise HTTPException(
                status_code=400,
                detail={"reason_code": e.reason_code},
            )
        except Exception as e:
            logger.error("Document preview conversion failed: %s", type(e).__name__)
            # 변환 실패 시 다운로드로 fallback
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception:
                    pass

    # 브라우저가 s3에서 파일을 직접 받아온다.
    if is_s3_file:
        try:
            # 1. 서버가 외부 파일을 guard를 통해 가져옴
            external_res = safe_http_request(
                "GET",
                doc.file_path,
                policy=EgressGuardPolicy(
                    timeout_seconds=30.0,
                    max_response_bytes=50 * 1024 * 1024,
                    allowed_content_types=DOCUMENT_RESPONSE_CONTENT_TYPES,
                ),
            )
            if external_res.status_code >= 400:
                raise RuntimeError("Remote file returned an error.")

            # 2. 클라이언트에게 스트리밍 전송 함수 정의
            def iterfile():
                yield external_res.content

            # 3. StreamingResponse 반환
            return StreamingResponse(
                iterfile(),
                media_type=media_type,
                headers={
                    "Content-Disposition": (
                        f"{content_disposition_type}; "
                        f"filename={safe_quote_filename(doc.filename)}"
                    )
                },
            )
        except EgressGuardError as e:
            logger.warning(
                "External file proxy denied by egress guard: %s",
                e.reason_code,
            )
            raise HTTPException(
                status_code=400,
                detail={"reason_code": e.reason_code},
            )
        except Exception as e:
            logger.error("Failed to proxy external file: %s", type(e).__name__)
            raise HTTPException(
                status_code=502,
                detail={"reason_code": "egress.proxy_failed"},
            )

    return FileResponse(
        doc.file_path,
        filename=doc.filename,
        media_type=media_type,
        content_disposition_type=content_disposition_type,
    )


@router.post(
    "/{kb_id}/documents/{document_id}/process", status_code=status.HTTP_202_ACCEPTED
)
@audit(AuditAction.DOCUMENT_PROCESS, target_param="document_id")
async def process_document(
    kb_id: UUID,
    document_id: UUID,
    request: DocumentPreviewRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    문서 설정(청킹 등)을 저장하고 백그라운드 처리를 시작합니다.
    """

    # 1. 문서 조회 (권한 확인)
    doc = (
        db.query(Document)
        .join(KnowledgeBase)
        .filter(
            Document.id == document_id,
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == current_user.id,
        )
        .first()
    )

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        normalized_chunking_mode = validate_chunking_request(
            chunking_mode=request.chunking_mode,
            source_type=doc.source_type,
            selection_mode=request.selection_mode,
        )
    except RAGHierarchyError as exc:
        raise _chunking_http_exception(exc)

    # 2. 설정 업데이트
    doc.chunk_size = request.chunk_size
    doc.chunk_overlap = request.chunk_overlap

    # 메타데이터에 추가 설정 저장
    new_meta = dict(doc.meta_info or {})
    new_meta.update(
        {
            "segment_identifier": request.segment_identifier,
            "remove_urls_emails": request.remove_urls_emails,
            "remove_whitespace": request.remove_whitespace,
            "strategy": request.strategy,  # LlamaParse 등 파싱 전략 저장
            "chunking_mode": normalized_chunking_mode,
            "db_config": request.db_config,
            # 필터링 설정 저장
            "selection_mode": request.selection_mode,
            "chunk_range": request.chunk_range,
            "keyword_filter": request.keyword_filter,
        }
    )
    doc.meta_info = new_meta

    # DB 소스인 경우 FK 관계 검증 (백그라운드 실행 전)
    if doc.source_type == "DB" and request.db_config:
        selections = request.db_config.get("selections", [])
        join_config = request.db_config.get("join_config", {})

        # 2개 테이블 선택 시 FK 관계 필수
        if len(selections) == 2 and not join_config.get("enabled", False):
            raise HTTPException(
                status_code=400, detail="선택한 테이블 간 FK 관계가 없습니다."
            )

    # 상태 업데이트 (처리 시작 전)
    doc.status = (
        "indexing"  # IngestionService가 실행되기 전부터 UI에서 처리중으로 표시하기 위함
    )
    db.commit()

    # 3. 백그라운드 작업 시작
    ingestion_service = IngestionService(
        db,
        user_id=current_user.id,
        chunk_size=request.chunk_size,
        chunk_overlap=request.chunk_overlap,
        ai_model=doc.knowledge_base.embedding_model,
    )

    background_tasks.add_task(
        ingestion_service.process_document,
        document_id,
    )

    return {"status": "processing", "message": "Document processing started"}


@router.post(
    "/{kb_id}/documents/{document_id}/preview", response_model=DocumentPreviewResponse
)
def preview_document_chunking(
    kb_id: UUID,
    document_id: UUID,
    request: DocumentPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    문서 청킹 설정을 미리보기 합니다. DB를 업데이트하지 않고 결과만 반환합니다.
    """
    # 1. 문서 존재 및 권한 확인
    doc = (
        db.query(Document)
        .join(KnowledgeBase)
        .filter(Document.id == document_id, KnowledgeBase.user_id == current_user.id)
        .first()
    )

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.knowledge_base_id != kb_id:
        raise HTTPException(
            status_code=400, detail="Document does not belong to this Knowledge Base"
        )

    try:
        normalized_chunking_mode = validate_chunking_request(
            chunking_mode=request.chunking_mode,
            source_type=doc.source_type,
            selection_mode=request.selection_mode,
        )
    except RAGHierarchyError as exc:
        raise _chunking_http_exception(exc)

    # 2. 서비스 호출
    service = IngestionService(db, user_id=current_user.id)
    try:
        segments = service.preview_chunking(
            file_path=doc.file_path,
            chunk_size=request.chunk_size,
            chunk_overlap=request.chunk_overlap,
            segment_identifier=request.segment_identifier,
            remove_urls_emails=request.remove_urls_emails,
            remove_whitespace=request.remove_whitespace,
            strategy=request.strategy,
            source_type=doc.source_type,
            chunking_mode=normalized_chunking_mode,
            meta_info=doc.meta_info,
            db_config=request.db_config,
            # 필터링 파라미터 전달
            selection_mode=request.selection_mode,
            chunk_range=request.chunk_range,
            keyword_filter=request.keyword_filter,
        )
    except ValueError as e:
        logger.warning("Preview validation failed: %s", type(e).__name__)
        raise HTTPException(
            status_code=400,
            detail={"reason_code": "validation.failed"},
        )
    except Exception as e:
        logger.error("Preview failed: %s", type(e).__name__)
        raise HTTPException(
            status_code=500,
            detail={"reason_code": "preview.failed"},
        )

    # 3. 응답 반환
    return DocumentPreviewResponse(
        segments=segments,
        total_count=len(segments),
        preview_text_sample="",  # 필요시 원본 텍스트 일부 반환 가능
    )


@router.post(
    "/{kb_id}/documents/{document_id}/sync", status_code=status.HTTP_202_ACCEPTED
)
async def sync_document(
    kb_id: UUID,
    document_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    문서를 동기화합니다. (API 소스 등 재위)
    기존 설정을 유지하면서 처리를 다시 시작합니다.
    """
    # 1. 문서 조회
    doc = (
        db.query(Document)
        .join(KnowledgeBase)
        .filter(
            Document.id == document_id,
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == current_user.id,
        )
        .first()
    )

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # 상태 업데이트
    doc.status = "indexing"
    db.commit()

    # 2. 백그라운드 작업 시작
    ingestion_service = IngestionService(
        db,
        user_id=current_user.id,
        chunk_size=doc.chunk_size,
        chunk_overlap=doc.chunk_overlap,
        ai_model=doc.knowledge_base.embedding_model,
    )

    background_tasks.add_task(
        ingestion_service.process_document,
        document_id,
    )

    return {"status": "processing", "message": "Document sync started"}
