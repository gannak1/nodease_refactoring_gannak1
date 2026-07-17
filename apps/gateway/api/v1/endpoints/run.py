from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Response, status
from sqlalchemy.orm import Session

from apps.gateway.api.deps import get_deployment_runtime_policy
from apps.shared.db.session import get_db
from apps.gateway.services.deployment_service import DeploymentService
from apps.shared.domain.deployment_runtime_policy import DeploymentRuntimePolicy

router = APIRouter()


@router.post("/run/{url_slug}")
async def run_workflow(
    url_slug: str,
    runtime_policy: Annotated[
        DeploymentRuntimePolicy,
        Depends(get_deployment_runtime_policy),
    ],
    request_body: dict = Body(...),
    authorization: list[str] | None = Header(None),
    db: Session = Depends(get_db),
):
    """
    배포된 워크플로우를 URL Slug로 실행합니다 (REST API: 인증 필요).
    - url_slug: workflow_deployments 생성시 만들어진 고유 주소
    """
    # 인증 토큰 추출

    auth_token = None
    if authorization and len(authorization) == 1 and "," not in authorization[0]:
        scheme, separator, candidate = authorization[0].partition(" ")
        if separator and scheme.lower() == "bearer" and candidate:
            auth_token = candidate

    # REST API: 인증 필요
    return await DeploymentService.run_deployment(
        db=db,
        url_slug=url_slug,
        user_inputs=request_body.get("inputs", {}),
        auth_token=auth_token,
        require_auth=True,  # 인증 필수
        trigger_mode="api",  # REST API 호출
        runtime_policy=runtime_policy,
    )


@router.post("/run-public/{url_slug}")
async def run_workflow_public(
    url_slug: str,
    runtime_policy: Annotated[
        DeploymentRuntimePolicy,
        Depends(get_deployment_runtime_policy),
    ],
    request_body: dict = Body(...),
    response: Response = None,
    db: Session = Depends(get_db),
):
    """
    배포된 워크플로우를 URL Slug로 실행합니다 (웹 앱/임베딩: 공개 접근).
    - url_slug: workflow_deployments 생성시 만들어진 고유 주소

    """
    # Target Conversation Memory uses its own lifecycle/grant endpoints.  Do
    # not let a root-level conversation envelope reach the legacy runtime until
    # MBA-318 installs the verified vertical execution contract.
    if "conversation" in request_body:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "memory.feature_unavailable",
                "message": "Conversation workflow execution is not available.",
            },
        )
    # 웹 앱/임베딩: 공개 접근 (인증 불필요)
    return await DeploymentService.run_deployment(
        db=db,
        url_slug=url_slug,
        user_inputs=request_body.get("inputs", {}),
        auth_token=None,
        require_auth=False,  # 인증 불필요
        trigger_mode="app",  # 웹 앱/임베딩 호출
        runtime_policy=runtime_policy,
    )
