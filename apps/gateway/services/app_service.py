import copy
import secrets

from sqlalchemy.orm import Session, joinedload

from apps.gateway.services.organization_context import ensure_user_default_organization
from apps.shared.db.models.app import App
from apps.shared.db.models.team import UserWorkflowPermission
from apps.shared.db.models.workflow import Workflow
from apps.shared.db.models.user import User
from apps.shared.permissions import AUTH_STATE_MANAGER
from apps.shared.schemas.app import AppCreateRequest, AppUpdateRequest
from apps.shared.services.permissions import (
    has_organization_scope_access,
    has_organization_manager_permission,
    has_workflow_permission,
)


class AppService:
    @staticmethod
    def create_app(
        db: Session,
        request: AppCreateRequest,
        user_id: str,
        organization_id: str = None,
    ):
        """
        새로운 앱을 생성합니다.

        Args:
            db: 데이터베이스 세션
            request: 앱 생성 요청 데이터
            user_id: 생성자 ID (필수)
            organization_id: active organization ID. 없으면 legacy fallback 사용

        Returns:
            생성된 App 객체
        """
        if not organization_id:
            organization_id = ensure_user_default_organization(db, user_id)

        # url_slug, auth_secret 생성
        url_slug = AppService._generate_url_slug(db, request.name)
        auth_secret = f"sk-{secrets.token_hex(24)}"

        # 이름 중복 체크
        if (
            db.query(App)
            .filter(App.organization_id == organization_id, App.name == request.name)
            .first()
        ):
            raise ValueError("App with this name already exists.")

        # App 생성
        app = App(
            organization_id=organization_id,
            name=request.name,
            description=request.description,
            icon=request.icon.model_dump(),
            is_market=request.is_market,
            created_by=user_id,
            url_slug=url_slug,
            auth_secret=auth_secret,
        )
        db.add(app)
        db.flush()  # App ID 생성

        # 기본 워크플로우 생성
        workflow = Workflow(
            organization_id=organization_id,
            app_id=app.id,
            created_by=user_id,
        )
        db.add(workflow)
        db.flush()

        # App에 워크플로우 연결
        app.workflow_id = workflow.id
        AppService._grant_workflow_manager_permission(
            db, workflow, user_id, organization_id
        )

        db.commit()
        db.refresh(app)

        AppService._populate_owner_name(db, app)
        return app

    @staticmethod
    def _populate_owner_name(db: Session, app: App):
        """App 객체에 owner_name 속성을 채웁니다."""
        if app.created_by:
            user = db.query(User).filter(User.id == app.created_by).first()
            if user:
                # Pydantic 모델 변환 시 사용될 속성 할당
                setattr(app, "owner_name", user.name)

    @staticmethod
    def _grant_workflow_manager_permission(
        db: Session,
        workflow: Workflow,
        user_id,
        organization_id,
    ) -> None:
        if not organization_id:
            return
        db.add(
            UserWorkflowPermission(
                grantee_organization_id=organization_id,
                workflow_id=workflow.id,
                user_id=user_id,
                auth_state=AUTH_STATE_MANAGER,
                assigned_by=user_id,
            )
        )

    @staticmethod
    def _populate_deployment_status(db: Session, app: App):
        """App 객체에 active_deployment_is_active 속성을 채웁니다."""
        from apps.shared.db.models.workflow_deployment import WorkflowDeployment

        if app.active_deployment_id:
            deployment = (
                db.query(WorkflowDeployment)
                .filter(WorkflowDeployment.id == app.active_deployment_id)
                .first()
            )
            if deployment:
                setattr(app, "active_deployment_is_active", deployment.is_active)
            else:
                setattr(app, "active_deployment_is_active", None)
        else:
            setattr(app, "active_deployment_is_active", None)

    @staticmethod
    def can_read_app(db: Session, app: App, user_id) -> bool:
        if app.is_market:
            return True
        if app.organization_id and has_organization_manager_permission(
            db, user_id, app.organization_id
        ):
            return True
        if app.workflow_id and has_workflow_permission(
            db,
            user_id,
            app.workflow_id,
            "read",
            organization_id=app.organization_id,
        ):
            return True
        return app.organization_id is None and app.created_by == user_id

    @staticmethod
    def can_manage_app(db: Session, app: App, user_id) -> bool:
        if app.organization_id and has_organization_manager_permission(
            db, user_id, app.organization_id
        ):
            return True
        if app.workflow_id and has_workflow_permission(
            db,
            user_id,
            app.workflow_id,
            "manage",
            organization_id=app.organization_id,
        ):
            return True
        return app.organization_id is None and app.created_by == user_id

    @staticmethod
    def can_access_app_scope(db: Session, app: App, user_id) -> bool:
        if app.organization_id:
            return has_organization_scope_access(db, user_id, app.organization_id)
        return app.created_by == user_id

    @staticmethod
    def access_denial_status(db: Session, app: App, user_id, action: str) -> int | None:
        if action == "read":
            if AppService.can_read_app(db, app, user_id):
                return None
        elif action == "manage":
            if AppService.can_manage_app(db, app, user_id):
                return None
            if AppService.can_read_app(db, app, user_id):
                return 403
        else:
            raise ValueError(f"Unsupported app permission action: {action}")

        if AppService.can_access_app_scope(db, app, user_id):
            return 403
        return 404

    @staticmethod
    def get_app(db: Session, app_id: str, user_id=None):
        """
        특정 앱을 조회합니다.

        Args:
            db: 데이터베이스 세션
            app_id: 앱 ID
            user_id: 요청 유저 ID (선택, 비공개 앱의 경우 소유자만 접근 가능)

        Returns:
            App 객체 또는 None
        """
        app = db.query(App).filter(App.id == app_id).first()

        if not app:
            return None

        if user_id and not AppService.can_read_app(db, app, user_id):
            return None

        AppService._populate_owner_name(db, app)
        AppService._populate_deployment_status(db, app)
        return app

    @staticmethod
    def get_user_apps(db: Session, user_id, organization_id: str = None):
        """
        특정 유저의 모든 앱을 조회합니다.

        Args:
            db: 데이터베이스 세션
            user_id: 유저 ID

        Returns:
            App 객체 리스트
        """
        query = db.query(App).options(joinedload(App.active_deployment))
        if organization_id:
            query = query.filter(App.organization_id == organization_id)

        apps = query.all()
        apps = [app for app in apps if AppService.can_read_app(db, app, user_id)]

        for app in apps:
            AppService._populate_owner_name(db, app)

        # 각 앱에 배포 상태 정보 추가
        for app in apps:
            AppService._populate_deployment_status(db, app)

        return apps

    @staticmethod
    def list_explore_apps(db: Session, user_id):
        """
        마켓플레이스에 공개된 앱 목록을 조회합니다.

        Args:
            db: 데이터베이스 세션
            user_id: 현재 유저 ID

        Returns:
            공개된 App 객체 리스트
        """
        apps = (
            db.query(App)
            .options(joinedload(App.active_deployment))
            .filter(App.is_market == True)
            .all()
        )

        # owner_name 및 배포 상태 정보 추가
        for app in apps:
            AppService._populate_owner_name(db, app)
            AppService._populate_deployment_status(db, app)

        return apps

    @staticmethod
    def update_app(db: Session, app_id: str, request: AppUpdateRequest, user_id):
        """
        앱 정보를 수정합니다.

        Args:
            db: 데이터베이스 세션
            app_id: 앱 ID
            request: 앱 수정 요청 데이터
            user_id: 요청 유저 ID

        Returns:
            수정된 App 객체 또는 None
        """
        app = db.query(App).filter(App.id == app_id).first()
        if not app:
            return None

        if not AppService.can_manage_app(db, app, user_id):
            return None

        # 필드 업데이트
        if request.name is not None:
            # 이름 중복 체크
            if (
                db.query(App)
                .filter(
                    App.organization_id == app.organization_id,
                    App.name == request.name,
                    App.id != app_id,
                )
                .first()
            ):
                raise ValueError("App with this name already exists.")
            app.name = request.name
        if request.description is not None:
            app.description = request.description
        if request.icon is not None:
            app.icon = request.icon.model_dump()
        if request.is_market is not None:
            # 복제된 앱은 마켓에 공개 불가
            if request.is_market and app.forked_from:
                raise ValueError("Cannot publish cloned app to market")
            app.is_market = request.is_market

        db.commit()
        db.refresh(app)

        AppService._populate_owner_name(db, app)
        return app

    @staticmethod
    def clone_app(
        db: Session,
        source_app_id: str,
        user_id: str,
        organization_id: str = None,
    ):
        """
        기존 앱을 복제합니다.
        """
        from apps.shared.db.models.workflow_deployment import WorkflowDeployment

        # 1. 원본 앱 조회
        source_app = db.query(App).filter(App.id == source_app_id).first()
        if not source_app:
            return None
        if not AppService.can_read_app(db, source_app, user_id):
            return None

        # 2. 활성 배포 확인 (Active Deployment)
        if not source_app.active_deployment_id:
            # 배포된 버전이 없으면 복제 불가 (에러 발생)
            raise ValueError("Cannot clone app without active deployment.")

        # 3. 배포 데이터 조회
        deployment = (
            db.query(WorkflowDeployment)
            .filter(WorkflowDeployment.id == source_app.active_deployment_id)
            .first()
        )

        if not deployment:
            raise ValueError("Active deployment data not found.")

        # 4. 앱 복제 (새로운 객체 생성)
        new_icon = copy.deepcopy(source_app.icon)

        # 마켓플레이스에서 복제할 때 url_slug와 auth_secret 생성
        new_slug = AppService._generate_url_slug(db, f"{source_app.name} (복사본)")
        new_secret = secrets.token_urlsafe(32)

        if not organization_id:
            organization_id = ensure_user_default_organization(db, user_id)

        new_app = App(
            organization_id=organization_id,
            name=f"{source_app.name} (복사본)",
            description=source_app.description,
            icon=new_icon,
            url_slug=new_slug,
            auth_secret=new_secret,
            forked_from=source_app_id,  # 원본 추적
            created_by=user_id,
            is_market=False,  # 복제된 앱은 기본적으로 비공개
        )
        db.add(new_app)
        db.flush()

        # 5. 워크플로우 복제 (배포된 스냅샷 기반)
        graph_snapshot = deployment.graph_snapshot

        # 민감 정보 필터링
        cleaned_snapshot = AppService._clean_graph_data(graph_snapshot)

        # graph_snapshot에서 features 분리 (있다면)
        features = cleaned_snapshot.get("features", {})

        # graph 데이터 (features 제외)
        graph_data = {k: v for k, v in cleaned_snapshot.items() if k != "features"}

        new_workflow = Workflow(
            organization_id=organization_id,
            app_id=new_app.id,
            created_by=user_id,
            # 스냅샷 기반 데이터 설정
            graph=graph_data,
            features=features,
            # 배포된 버전은 환경변수/런타임변수가 스냅샷에 포함되지 않을 수 있음 (현재 스키마 기준)
            # 따라서 초기화 또는 스냅샷에 있다면 사용
            env_variables=graph_snapshot.get("env_variables", []),
            runtime_variables=graph_snapshot.get("runtime_variables", []),
        )
        db.add(new_workflow)
        db.flush()

        # App에 워크플로우 연결
        new_app.workflow_id = new_workflow.id
        AppService._grant_workflow_manager_permission(
            db, new_workflow, user_id, organization_id
        )

        db.commit()
        db.refresh(new_app)

        return new_app

    @staticmethod
    def delete_app(db: Session, app_id: str, user_id: str):
        """
        앱을 삭제합니다.
        """
        app = db.query(App).filter(App.id == app_id).first()
        if not app:
            return None

        if not AppService.can_manage_app(db, app, user_id):
            return None

        # 1. Circular dependency 해결을 위해 workflow_id 관계 끊기
        app.workflow_id = None
        db.flush()

        # 2. 연결된 워크플로우 삭제
        # Workflow.app_id가 ON DELETE CASCADE가 아닐 수 있으므로 수동 삭제
        db.query(Workflow).filter(Workflow.app_id == app_id).delete()
        db.flush()

        # 3. 앱 삭제
        # WorkflowDeployment는 ON DELETE CASCADE로 설정되어 있어 자동 삭제됨
        db.delete(app)
        db.commit()

        return True

    @staticmethod
    def _clean_graph_data(graph_snapshot: dict) -> dict:
        """
        그래프 스냅샷에서 민감 정보를 제거합니다.
        (knowledgeBases, api_token, authConfig, password, email 등)
        """
        cleaned_data = copy.deepcopy(graph_snapshot)
        nodes = cleaned_data.get("nodes", [])

        for node in nodes:
            data = node.get("data", {})
            node_type = node.get("type")

            if node_type == "llmNode":
                data.pop("knowledgeBases", None)
            elif node_type == "githubNode":
                data.pop("api_token", None)
            elif node_type == "httpRequestNode":
                data.pop("authConfig", None)
            elif node_type == "mailNode":
                data.pop("password", None)
                data.pop("email", None)

        return cleaned_data

    @staticmethod
    def _generate_url_slug(db: Session, name: str) -> str:
        """
        앱 이름으로부터 고유한 URL slug를 생성합니다.
        고유한 App URL Slug를 생성합니다.
        형식: app-{random_hex_4} (예: app-a1b2c3d4)
        """
        while True:
            # 8글자 Hex (4 bytes) -> 총 12글자 (app-XXXXXXXX)
            slug = f"app-{secrets.token_hex(4)}"
            # 중복 체크
            if not db.query(App).filter(App.url_slug == slug).first():
                return slug
