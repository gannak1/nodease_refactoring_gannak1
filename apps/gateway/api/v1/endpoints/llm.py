from datetime import datetime
from typing import Annotated, List
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.auth.permissions import ensure_llm_credential_permission
from apps.gateway.utils.audit import audit
from apps.gateway.services.organization_context import ensure_user_default_organization
from apps.gateway.services.llm_service import LLMService
from apps.shared.audit.actions import AuditAction
from apps.shared.db.models.llm import LLMModel, LLMProvider, LLMUsageLog
from apps.shared.db.models.user import User
from apps.shared.db.session import get_db
from apps.shared.schemas.llm import (
    LLMCredentialCreate,
    LLMCredentialResponse,
    LLMModelPricingUpdate,
    LLMModelResponse,
    LLMProviderResponse,
)
from apps.shared.services.tracing.access import TraceAccessService

router = APIRouter()


def _require_system_admin(db: Session, current_user: User):
    # TracAccessService에서 admin으로 판별하면 오류 발생 안함
    if not TraceAccessService.is_system_admin(db, current_user):
        raise HTTPException(status_code=403, detail="system_admin_required")


def _resolve_llm_organization_id(
    db: Session,
    current_user: User,
    x_organization_id: UUID | None,
    body_organization_id: UUID | None = None,
) -> UUID:
    # HTTP 요청이 제대로 되었는지 확인하는 함수, x_organization, body_organization이 없고 body와 header의 organization이 다르면 에러 아니면 header 우선으로 리턴, body 후순위로 리턴
    if (
        x_organization_id is not None
        and body_organization_id is not None
        and x_organization_id != body_organization_id
    ):
        raise HTTPException(status_code=400, detail="organization_id_mismatch")
    if x_organization_id is not None:
        return x_organization_id
    if body_organization_id is not None:
        return body_organization_id
    return ensure_user_default_organization(db, current_user.id)

# --- Providers (System) ---


@router.get("/providers", response_model=List[LLMProviderResponse])
def get_system_providers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List all system-defined LLM providers and their models.
    """
    try:
        return LLMService.get_system_providers(db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# --- Credentials (User) ---


@router.get("/my-models", response_model=List[LLMModelResponse])
def get_my_models(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    x_organization_id: Annotated[
        UUID | None, Header(alias="X-Organization-Id")
    ] = None,
):
    """
    List all models available to the current user.
    """
    try:
        # Handles organization-scoped model listing for the current user MBA-43
        organization_id = _resolve_llm_organization_id(
            db, current_user, x_organization_id
        )
        return LLMService.get_my_available_models(
            db, current_user.id, organization_id=organization_id
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/my-embedding-models", response_model=List[LLMModelResponse])
def get_my_embedding_models(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    x_organization_id: Annotated[
        UUID | None, Header(alias="X-Organization-Id")
    ] = None,
):
    """
    현재 사용자가 사용 가능한 임베딩 모델 목록 조회.
    """
    try:
        # Handles organization-scoped embedding model listing for the current user MBA-43
        organization_id = _resolve_llm_organization_id(
            db, current_user, x_organization_id
        )
        return LLMService.get_my_embedding_models(
            db, current_user.id, organization_id=organization_id
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/credentials", response_model=List[LLMCredentialResponse])
def get_my_credentials(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    x_organization_id: Annotated[
        UUID | None, Header(alias="X-Organization-Id")
    ] = None,
):
    """
    List all credentials for the current user.
    """
    try:
        # Handles organization-scoped credential listing for the current user MBA-43
        organization_id = _resolve_llm_organization_id(
            db, current_user, x_organization_id
        )
        return LLMService.get_user_credentials(
            db, current_user.id, organization_id=organization_id
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/credentials", response_model=LLMCredentialResponse)
@audit(AuditAction.CREDENTIAL_CREATE)
def register_credential(
    request: LLMCredentialCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    x_organization_id: Annotated[
        UUID | None, Header(alias="X-Organization-Id")
    ] = None,
):
    """
    Register a new API Key for a specific provider.
    """
    try:
        # Handles organization-scoped credential creation with header/body validation MBA-43
        organization_id = _resolve_llm_organization_id(
            db, current_user, x_organization_id, request.organization_id
        )
        return LLMService.register_credential(
            db, current_user.id, request, organization_id=organization_id
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/credentials/{credential_id}")
@audit(AuditAction.CREDENTIAL_DELETE, target_param="credential_id")
def delete_credential(
    credential_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    x_organization_id: Annotated[
        UUID | None, Header(alias="X-Organization-Id")
    ] = None,
):
    """
    Delete a user credential.
    """
    try:
        # Handles organization-scoped credential deletion for the current user MBA-43
        organization_id = _resolve_llm_organization_id(
            db, current_user, x_organization_id
        )
        ensure_llm_credential_permission(
            db,
            current_user,
            credential_id,
            "write",
            organization_id=organization_id,
        )
        deleted = LLMService.delete_credential(
            db, credential_id, current_user.id, organization_id=organization_id
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="Credential not found")
        return {"message": "Credential deleted", "id": str(credential_id)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/credentials/{credential_id}/sync-models")
def sync_credential_models(
    credential_id: UUID,
    purge_unverified: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    x_organization_id: Annotated[
        UUID | None, Header(alias="X-Organization-Id")
    ] = None,
):
    """
    해당 크리덴셜 기준으로 모델 매핑을 재동기화합니다.
    """
    try:
        # Handles organization-scoped credential model synchronization MBA-43
        organization_id = _resolve_llm_organization_id(
            db, current_user, x_organization_id
        )
        ensure_llm_credential_permission(
            db,
            current_user,
            credential_id,
            "write",
            organization_id=organization_id,
        )
        return LLMService.sync_credential_models(
            db,
            current_user.id,
            credential_id,
            purge_unverified=purge_unverified,
            organization_id=organization_id,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# --- Stats ---


@router.get("/stats/top-models")
def get_top_expensive_models(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get Top 3 expensive models for the current month (user-scoped).
    각 사용자의 본인 사용량 기준으로 Top 3 모델을 반환합니다.
    """
    try:
        # 1. Determine date range (This Month in UTC mostly, or naive)
        now = datetime.now()
        start_of_month = datetime(now.year, now.month, 1)

        # 2. Query (User-scoped)
        # Join Log -> Model -> Provider
        # Group by Model, filtered by current user
        results = (
            db.query(
                LLMModel.name.label("model_name"),
                LLMProvider.name.label("provider_name"),
                func.sum(LLMUsageLog.total_cost).label("total_cost"),
                func.sum(
                    LLMUsageLog.prompt_tokens + LLMUsageLog.completion_tokens
                ).label("total_tokens"),
            )
            .join(LLMModel, LLMUsageLog.model_id == LLMModel.id)
            .join(LLMProvider, LLMModel.provider_id == LLMProvider.id)
            .filter(LLMUsageLog.created_at >= start_of_month)
            .filter(LLMUsageLog.user_id == current_user.id)  # 사용자별 필터링
            .group_by(LLMModel.id, LLMModel.name, LLMProvider.id, LLMProvider.name)
            .order_by(desc("total_cost"))
            .limit(3)
            .all()
        )

        # 3. Format Response
        response = []
        for r in results:
            response.append(
                {
                    "model_name": r.model_name,
                    "provider_name": r.provider_name,
                    "total_cost": float(r.total_cost) if r.total_cost else 0.0,
                    "total_tokens": int(r.total_tokens) if r.total_tokens else 0,
                }
            )

        return response

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# --- Pricing Management ---


@router.post("/models/sync-pricing")
def sync_system_pricing(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    [Admin] Sync all DB models with hardcoded system prices.
    Useful when system price list is updated.
    """
    _require_system_admin(db, current_user)
    try:
        result = LLMService.sync_system_prices(db)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/models/{model_id}/pricing")
@audit(AuditAction.MODEL_PRICING_UPDATE, target_param="model_id")
def update_model_pricing(
    model_id: UUID,
    pricing: LLMModelPricingUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    [Admin] Manually update pricing for a specific model.
    """
    _require_system_admin(db, current_user)
    try:
        model = LLMService.update_model_pricing(
            db, model_id, pricing.input_price_1k, pricing.output_price_1k
        )
        return {"message": "Pricing updated", "model": model.name}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
