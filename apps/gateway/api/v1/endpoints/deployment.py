import uuid
from typing import Any, List

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session

from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.auth.permissions import ensure_workflow_permission
from apps.gateway.services.organization_context import resolve_active_organization_id
from apps.gateway.utils.audit import audit
from apps.gateway.services.deployment_service import DeploymentService
from apps.shared.audit.actions import AuditAction
from apps.shared.audit.context import AuditActor, clear_current_actor, set_current_actor
from apps.shared.audit.logger import record_audit
from apps.shared.db.models.app import App
from apps.shared.db.models.user import User
from apps.shared.db.models.workflow_deployment import WorkflowDeployment
from apps.shared.domain.deployment_runtime_policy import (
    SURFACE_PUBLIC_INFO,
    is_deployment_type_allowed_for_surface,
)
from apps.shared.db.session import get_db
from apps.shared.schemas.deployment import (
    DeploymentCreate,
    DeploymentPreflightRequest,
    DeploymentPreflightResponse,
    DeploymentResponse,
    DeploymentRunInfoResponse,
)

router = APIRouter()


def _request_id_from_request(request: Request) -> str | None:
    return getattr(
        getattr(request, "state", None), "request_id", None
    ) or request.headers.get("x-request-id")


def _deployment_app_and_workflow_id(db: Session, deployment_id: str):
    deployment = (
        db.query(WorkflowDeployment)
        .filter(WorkflowDeployment.id == deployment_id)
        .first()
    )
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    app = db.query(App).filter(App.id == deployment.app_id).first()
    if not app or not app.workflow_id:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return deployment, app, app.workflow_id


def _deployment_workflow_id(db: Session, deployment_id: str):
    _, _, workflow_id = _deployment_app_and_workflow_id(db, deployment_id)
    return workflow_id


def _ensure_app_matches_active_organization(
    db: Session,
    request: Request,
    current_user: User,
    app: App,
    raw_organization_id: str | None,
) -> None:
    if not isinstance(raw_organization_id, str):
        return

    organization_id = resolve_active_organization_id(
        db,
        request,
        raw_organization_id,
        current_user.id,
    )
    app_organization_id = getattr(app, "organization_id", None)
    if app_organization_id is not None and str(app_organization_id) != str(
        organization_id
    ):
        raise HTTPException(status_code=404, detail="Deployment not found")


def _deployment_toggle_audit_action(
    deployment: WorkflowDeployment, app: App
) -> str:
    if (
        not deployment.is_active
        and app.active_deployment_id is not None
        and app.active_deployment_id != deployment.id
    ):
        return AuditAction.DEPLOYMENT_ACTIVATE_PREVIOUS
    return AuditAction.DEPLOYMENT_TOGGLE


def _deployment_audit_actor(user: User) -> AuditActor:
    return AuditActor(
        actor_id=str(user.id),
        actor_type="user",
        snapshot={
            "id": str(user.id),
            "email": getattr(user, "email", None),
            "name": getattr(user, "name", None),
        },
    )


def _record_deployment_toggle_audit(
    action: str,
    current_user: User,
    deployment_id: str,
    status: str,
    metadata: dict | None = None,
) -> None:
    actor = _deployment_audit_actor(current_user)
    audit_metadata = {"actor": actor.snapshot}
    if metadata:
        audit_metadata.update(metadata)
    record_audit(
        action=action,
        category="action",
        actor_id=current_user.id,
        actor_type="user",
        target_type="deployment",
        target_id=deployment_id,
        status=status,
        metadata=audit_metadata,
    )


@router.post("", response_model=DeploymentResponse)
@audit(AuditAction.WORKFLOW_DEPLOY)
def create_deployment(
    deployment_in: DeploymentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    워크플로우를 배포합니다.
    [TEST] bugfix/KAN-000, gateway 배포를 위해 주석 추가
    """
    app = db.query(App).filter(App.id == deployment_in.app_id).first()
    if not app or not app.workflow_id:
        raise HTTPException(status_code=404, detail="App not found")
    ensure_workflow_permission(db, current_user, app.workflow_id, "deploy")
    return DeploymentService.create_deployment(db, deployment_in, current_user.id)


@router.post("/preflight", response_model=DeploymentPreflightResponse)
def preview_deployment_preflight(
    preflight_in: DeploymentPreflightRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    배포 graph snapshot과 deployment type 기준으로 runtime availability를 검사합니다.
    """
    app = db.query(App).filter(App.id == preflight_in.app_id).first()
    if not app or not app.workflow_id:
        raise HTTPException(status_code=404, detail="App not found")
    ensure_workflow_permission(db, current_user, app.workflow_id, "deploy")
    graph_snapshot = DeploymentService._resolve_graph_snapshot(
        db,
        app.workflow_id,
        preflight_in.graph_snapshot,
    )
    return DeploymentService.preview_knowledge_preflight(
        db,
        app=app,
        deployment_type=preflight_in.type,
        graph_snapshot=graph_snapshot,
        audience_hint=preflight_in.audience,
        is_active=preflight_in.is_active,
    )


@router.get("", response_model=List[DeploymentResponse])
def get_deployments(
    app_id: str = None,
    workflow_id: str = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    특정 앱의 배포 이력을 조회합니다.
    app_id 또는 workflow_id 중 하나는 필수입니다.
    """
    target_workflow_id = workflow_id
    if app_id:
        app = db.query(App).filter(App.id == app_id).first()
        if not app:
            return []
        if not app.workflow_id:
            return []
        target_workflow_id = app.workflow_id
        ensure_workflow_permission(db, current_user, target_workflow_id, "read")
        if workflow_id:
            try:
                supplied_workflow_id = uuid.UUID(str(workflow_id))
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=400, detail="app_id does not match workflow_id"
                )
            if uuid.UUID(str(target_workflow_id)) != supplied_workflow_id:
                raise HTTPException(
                    status_code=400, detail="app_id does not match workflow_id"
                )
    elif target_workflow_id:
        ensure_workflow_permission(db, current_user, target_workflow_id, "read")
    else:
        return []
    return DeploymentService.list_deployments(
        db,
        app_id=app_id,
        workflow_id=workflow_id,
        skip=skip,
        limit=limit,
    )


@router.get("/nodes", response_model=List[dict])
def list_workflow_nodes(
    excluded_app_id: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    배포된 워크플로우 노드 목록을 조회합니다. (재사용 가능한 모듈)
    """
    return DeploymentService.list_workflow_node_deployments(
        db, current_user.id, excluded_app_id=excluded_app_id
    )


@router.get("/{deployment_id}/run-info", response_model=DeploymentRunInfoResponse)
def get_authenticated_deployment_run_info(
    deployment_id: str,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    로그인 사용자 실행 화면에 필요한 safe 배포 정보를 조회합니다.
    """
    _, app, workflow_id = _deployment_app_and_workflow_id(db, deployment_id)
    _ensure_app_matches_active_organization(
        db,
        request,
        current_user,
        app,
        x_organization_id,
    )
    ensure_workflow_permission(db, current_user, workflow_id, "execute")
    return DeploymentService.get_deployment_run_info(db, deployment_id)


@router.post("/{deployment_id}/run")
async def run_authenticated_deployment(
    deployment_id: str,
    request: Request,
    request_body: dict[str, Any] | None = Body(default=None),
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    로그인 사용자의 권한 주체로 활성 배포 snapshot을 실행합니다.
    """
    _, app, workflow_id = _deployment_app_and_workflow_id(db, deployment_id)
    _ensure_app_matches_active_organization(
        db,
        request,
        current_user,
        app,
        x_organization_id,
    )
    ensure_workflow_permission(db, current_user, workflow_id, "execute")

    request_body = request_body or {}
    inputs = request_body.get("inputs", {})
    if not isinstance(inputs, dict):
        raise HTTPException(status_code=400, detail="inputs must be an object")

    return await DeploymentService.run_authenticated_deployment(
        db=db,
        deployment_id=deployment_id,
        user_inputs=inputs,
        current_user_id=current_user.id,
        request_id=_request_id_from_request(request),
        correlation_id=request.headers.get("x-correlation-id"),
    )


@router.get("/{deployment_id}", response_model=DeploymentResponse)
def get_deployment(
    deployment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    특정 배포 ID의 상세 정보를 조회합니다.
    """
    workflow_id = _deployment_workflow_id(db, deployment_id)
    ensure_workflow_permission(db, current_user, workflow_id, "read")
    return DeploymentService.get_deployment(db, deployment_id)


@router.get("/public/{url_slug}/info")
def get_deployment_info_public(
    url_slug: str, response: Response, db: Session = Depends(get_db)
):
    """
    배포 정보 공개 조회 (웹 앱/임베딩용, 인증 불필요)

    공유 페이지에서 입력 폼을 동적으로 생성하기 위해
    input_schema와 output_schema를 조회합니다.

    CORS: 모든 출처 허용 (임베딩 위젯 지원)
    """
    from fastapi import HTTPException

    from apps.shared.db.models.app import App
    from apps.shared.db.models.workflow_deployment import WorkflowDeployment
    from apps.shared.schemas.deployment import DeploymentInfoResponse

    # CORS 헤더 추가 (임베딩 위젯 지원)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"

    # 1. url_slug로 App 조회
    app = db.query(App).filter(App.url_slug == url_slug).first()
    if not app:
        raise HTTPException(status_code=404, detail="App not found")

    # 2. 활성 배포 조회
    if not app.active_deployment_id:
        raise HTTPException(
            status_code=404, detail="No active deployment found for this app"
        )

    deployment = (
        db.query(WorkflowDeployment)
        .filter(
            WorkflowDeployment.id == app.active_deployment_id,
            WorkflowDeployment.app_id == app.id,
        )
        .first()
    )

    if not deployment:
        raise HTTPException(status_code=404, detail="Active deployment not found")

    if not deployment.is_active:
        raise HTTPException(status_code=404, detail="Deployment is inactive")
    if not is_deployment_type_allowed_for_surface(
        deployment.type,
        SURFACE_PUBLIC_INFO,
    ):
        raise HTTPException(status_code=404, detail="Active deployment not found")

    return DeploymentInfoResponse(
        url_slug=app.url_slug,
        name=app.name,
        version=deployment.version,
        description=deployment.description,
        type=deployment.type.value,
        input_schema=deployment.input_schema,
        output_schema=deployment.output_schema,
    )


@router.patch("/{deployment_id}/toggle", response_model=DeploymentResponse)
def toggle_deployment(
    deployment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    배포의 is_active 상태를 토글합니다.
    """
    from apps.gateway.services.scheduler_service import get_scheduler_service

    deployment, app, workflow_id = _deployment_app_and_workflow_id(db, deployment_id)
    ensure_workflow_permission(db, current_user, workflow_id, "deploy")
    audit_action = _deployment_toggle_audit_action(deployment, app)
    actor = _deployment_audit_actor(current_user)
    token = set_current_actor(actor)
    try:
        scheduler = get_scheduler_service()
        result = DeploymentService.toggle_deployment(db, deployment_id, scheduler)
    except Exception as e:
        _record_deployment_toggle_audit(
            audit_action,
            current_user,
            deployment_id,
            "failure",
            {"error": str(e)},
        )
        raise
    else:
        _record_deployment_toggle_audit(
            audit_action,
            current_user,
            deployment_id,
            "success",
        )
        return result
    finally:
        clear_current_actor(token)


@router.delete("/{deployment_id}")
@audit(AuditAction.DEPLOYMENT_DELETE, target_param="deployment_id")
def delete_deployment(
    deployment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    배포를 삭제합니다.
    """
    from apps.gateway.services.scheduler_service import get_scheduler_service

    workflow_id = _deployment_workflow_id(db, deployment_id)
    ensure_workflow_permission(db, current_user, workflow_id, "manage")
    scheduler = get_scheduler_service()
    return DeploymentService.delete_deployment(db, deployment_id, scheduler)
