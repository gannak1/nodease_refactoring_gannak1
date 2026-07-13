import uuid
from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from apps.gateway.services.organization_context import ensure_user_default_organization
from apps.gateway.services.app_service import AppService
from apps.shared.db.models.app import App
from apps.shared.audit.context import get_current_metadata
from apps.shared.db.models.mail_credential import (
    MAIL_CREDENTIAL_ACTIVE,
    MailCredential,
)
from apps.shared.db.models.workflow import Workflow
from apps.shared.domain.mail_credential import (
    MailNodeCredentialBoundaryError,
    validate_mail_node_credential_boundary,
    validate_mail_processing_node_boundary,
)
from apps.shared.domain.workflow_knowledge_references import (
    WorkflowKnowledgeReferenceError,
    aggregate_workflow_knowledge_reference_ids,
    parse_workflow_knowledge_references,
)
from apps.shared.domain.slack_delivery import (
    SlackGraphBoundaryError,
    validate_slack_graph_boundary,
)
from apps.shared.schemas.workflow import WorkflowCreateRequest, WorkflowDraftRequest
from apps.shared.services.permission_audit import record_resource_permission_denied
from apps.shared.services.permissions import (
    get_effective_mail_credential_auth_state,
    has_mail_credential_permission,
)
from apps.gateway.services.workflow_knowledge_reference_service import (
    WorkflowKnowledgeReferenceAuthorizationUnavailable,
    WorkflowKnowledgeReferenceService,
    WorkflowKnowledgeReferenceUnavailable,
)


class WorkflowService:
    @staticmethod
    def _iter_workflow_nodes(nodes: Iterable[Any]) -> Iterable[Any]:
        pending = list(nodes)
        while pending:
            node = pending.pop()
            yield node
            data = (
                node.get("data")
                if isinstance(node, Mapping)
                else getattr(node, "data", None)
            )
            if not isinstance(data, Mapping):
                continue
            subgraph = data.get("subGraph")
            if not isinstance(subgraph, Mapping):
                continue
            nested_nodes = subgraph.get("nodes")
            if isinstance(nested_nodes, list):
                pending.extend(nested_nodes)

    @staticmethod
    def create_workflow(
        db: Session,
        request: WorkflowCreateRequest,
        user_id: UUID,
        organization_id: UUID | None = None,
    ) -> Workflow:
        """
        새 워크플로우 생성

        Args:
            db: 데이터베이스 세션
            request: 워크플로우 생성 요청 (app_id, name, description)
            user_id: 생성자 ID (UUID)
        Returns:
            생성된 Workflow 객체
        """
        # 앱 존재 확인 및 권한 체크
        app = db.query(App).filter(App.id == request.app_id).first()
        if not app:
            raise HTTPException(status_code=404, detail="App not found")

        if (
            app.organization_id
            and organization_id
            and app.organization_id != organization_id
        ):
            raise HTTPException(status_code=404, detail="App not found")

        denial_status = AppService.access_denial_status(db, app, user_id, "manage")
        if denial_status is not None:
            detail = "Forbidden" if denial_status == 403 else "App not found"
            raise HTTPException(status_code=denial_status, detail=detail)

        # organization_id fallback은 organization scope가 없는 legacy app 보정용이다.
        organization_id = (
            app.organization_id
            or organization_id
            or ensure_user_default_organization(db, user_id)
        )

        # 새 워크플로우 생성
        workflow = Workflow(
            organization_id=organization_id,
            app_id=request.app_id,
            created_by=user_id,
            graph={
                "nodes": [],
                "edges": [],
                "viewport": {"x": 0, "y": 0, "zoom": 1},
            },
        )

        db.add(workflow)
        db.flush()
        AppService._grant_workflow_manager_permission(
            db, workflow, user_id, organization_id
        )
        db.commit()
        db.refresh(workflow)

        return workflow

    @staticmethod
    def save_draft(
        db: Session,
        workflow_id: str,
        request: WorkflowDraftRequest | dict[str, Any],
        user_id: str,
    ):
        """
        워크플로우 초안을 PostgreSQL에 저장합니다.

        Args:
            db: 데이터베이스 세션
            workflow_id: 워크플로우 ID
            request: 워크플로우 데이터 (노드, 엣지, 뷰포트)
            user_id: 사용자 ID

        Returns:
            저장된 Workflow 객체
        """
        # 기존 워크플로우 찾기
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()

        # workflow 없으면 error 반환
        if not workflow:
            raise HTTPException(
                status_code=404,  # "찾을 수 없음" (에러 종류)
                detail="Workflow not found",  # 상세 메시지
            )

        WorkflowService.validate_knowledge_references(
            db,
            request,
            user_id=user_id,
            organization_id=workflow.organization_id,
        )

        WorkflowService.validate_mail_credential_references(
            db,
            request,
            user_id=user_id,
            organization_id=workflow.organization_id,
        )

        # Graph 데이터 저장 (JSONB 형식)
        workflow.graph = {
            "nodes": [node.model_dump() for node in request.nodes],
            "edges": [edge.model_dump() for edge in request.edges],
            "viewport": request.viewport.model_dump() if request.viewport else None,
        }

        workflow.features = request.features if request.features else {}

        # 환경 변수 처리: 요청에 환경 변수가 있으면 딕셔너리 형태로 변환하여 저장, 없으면 빈 리스트 저장
        workflow.env_variables = (
            [v.model_dump() for v in request.env_variables]
            if request.env_variables
            else []
        )
        # 런타임 변수 처리: 요청에 런타임 변수가 있으면 딕셔너리 형태로 변환하여 저장, 없으면 빈 리스트 저장
        workflow.runtime_variables = (
            [v.model_dump() for v in request.runtime_variables]
            if request.runtime_variables
            else []
        )
        workflow.updated_by = user_id

        # DB에 커밋
        db.commit()
        db.refresh(workflow)

        return {
            "status": "success",
            "message": "Draft saved to PostgreSQL",
            "workflow_id": workflow_id,
        }

    @staticmethod
    def validate_knowledge_references(
        db: Session,
        request: WorkflowDraftRequest | Mapping[str, Any],
        *,
        user_id: str | UUID,
        organization_id: UUID | None,
    ) -> None:
        graph = (
            request.model_dump(mode="python")
            if isinstance(request, WorkflowDraftRequest)
            else dict(request)
        )
        try:
            parsed_nodes = parse_workflow_knowledge_references(graph)
            direct_ids, collection_ids = aggregate_workflow_knowledge_reference_ids(
                parsed_nodes
            )
        except WorkflowKnowledgeReferenceError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": exc.reason_code, "field": exc.field_path},
            ) from exc

        # Legacy workflows may not have organization scope. A graph with no
        # Knowledge intent needs neither authorization context nor a DB query.
        if not direct_ids and not collection_ids:
            return

        try:
            user_uuid = uuid.UUID(str(user_id))
            organization_uuid = uuid.UUID(str(organization_id))
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "knowledge_reference_context_invalid",
                    "field": "graph",
                },
            ) from exc

        service = WorkflowKnowledgeReferenceService(
            db,
            user_id=user_uuid,
            organization_id=organization_uuid,
        )
        try:
            service.validate_parsed_references(parsed_nodes)
        except WorkflowKnowledgeReferenceError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": exc.reason_code, "field": exc.field_path},
            ) from exc
        except WorkflowKnowledgeReferenceUnavailable as exc:
            raise HTTPException(
                status_code=403,
                detail={"code": exc.reason_code, "field": exc.field_path},
            ) from exc
        except WorkflowKnowledgeReferenceAuthorizationUnavailable as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "knowledge_reference_authorization_unavailable",
                    "field": "graph.knowledgeReferences",
                },
            ) from exc

    @staticmethod
    def validate_mail_credential_references(
        db: Session,
        request: WorkflowDraftRequest | Mapping[str, Any],
        *,
        user_id: str,
        organization_id: UUID,
        require_resolved: bool = False,
    ) -> None:
        nodes = (
            request.nodes
            if isinstance(request, WorkflowDraftRequest)
            else request.get("nodes", [])
        )
        try:
            validate_slack_graph_boundary(
                nodes,
                require_resolved=require_resolved,
                allow_legacy_selectors=not require_resolved,
            )
        except SlackGraphBoundaryError as exc:
            raise HTTPException(
                status_code=422, detail="slack.graph_configuration_invalid"
            ) from exc
        mail_nodes = [
            node
            for node in WorkflowService._iter_workflow_nodes(nodes)
            if (
                getattr(node, "type", None)
                if not isinstance(node, dict)
                else node.get("type")
            )
            in {"mailNode", "gmailDraftNode", "mailAcknowledgeNode"}
        ]
        if not mail_nodes:
            return
        WorkflowService._validate_mail_processing_graph_contract(
            request,
            require_resolved=require_resolved,
        )
        try:
            user_uuid = uuid.UUID(str(user_id))
            organization_uuid = uuid.UUID(str(organization_id))
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail="mail.credential_context_invalid"
            ) from exc

        for node in mail_nodes:
            raw_data = node.get("data") if isinstance(node, dict) else node.data
            node_type = node.get("type") if isinstance(node, dict) else node.type
            try:
                if node_type == "mailNode":
                    validate_mail_node_credential_boundary(raw_data)
                else:
                    validate_mail_processing_node_boundary(
                        node_type,
                        raw_data,
                        allow_unresolved=not require_resolved,
                    )
            except MailNodeCredentialBoundaryError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "mail.credential_reference_required"
                        if node_type == "mailNode"
                        else "mail.processing_configuration_invalid"
                    ),
                ) from exc
            data = raw_data
            if node_type == "mailAcknowledgeNode":
                continue
            credential_value = data.get("credential_id")
            if credential_value in (None, ""):
                if require_resolved:
                    raise HTTPException(
                        status_code=422,
                        detail="mail.credential_reference_required",
                    )
                continue
            try:
                credential_id = uuid.UUID(str(credential_value))
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail="mail.credential_reference_invalid",
                ) from exc

            credential = (
                db.query(MailCredential)
                .filter(
                    MailCredential.id == credential_id,
                    MailCredential.organization_id == organization_uuid,
                    MailCredential.status == MAIL_CREDENTIAL_ACTIVE,
                )
                .first()
            )
            if credential is None:
                raise HTTPException(status_code=404, detail="resource.not_found")
            if has_mail_credential_permission(
                db,
                user_uuid,
                credential.id,
                "use",
                organization_id=organization_uuid,
            ):
                if node_type == "gmailDraftNode" and (
                    credential.provider != "gmail"
                    or credential.auth_type != "oauth2"
                ):
                    raise HTTPException(
                        status_code=422,
                        detail="mail.gmail_oauth_credential_required",
                    )
                continue
            record_resource_permission_denied(
                user_id=user_uuid,
                resource_type="mail_credential",
                resource_id=credential.id,
                action="use",
                effective_auth_state=get_effective_mail_credential_auth_state(
                    db,
                    user_uuid,
                    credential.id,
                    organization_id=organization_uuid,
                ),
                organization_id=organization_uuid,
                metadata=get_current_metadata(),
            )
            raise HTTPException(
                status_code=403,
                detail="mail.credential_permission_denied",
            )

    @staticmethod
    def _validate_mail_processing_graph_contract(
        request: WorkflowDraftRequest | Mapping[str, Any],
        *,
        require_resolved: bool,
    ) -> None:
        graph = (
            request.model_dump(mode="python")
            if isinstance(request, WorkflowDraftRequest)
            else dict(request)
        )
        for current_graph in WorkflowService._iter_graphs(graph):
            nodes = current_graph.get("nodes")
            edges = current_graph.get("edges")
            if not isinstance(nodes, list):
                continue
            node_by_id = {
                str(node.get("id")): node
                for node in nodes
                if isinstance(node, Mapping) and node.get("id")
            }
            edge_pairs = {
                (str(edge.get("source")), str(edge.get("target")))
                for edge in (edges if isinstance(edges, list) else [])
                if isinstance(edge, Mapping)
                and edge.get("source")
                and edge.get("target")
            }

            for node in node_by_id.values():
                node_type = str(node.get("type") or "")
                if node_type not in {"gmailDraftNode", "mailAcknowledgeNode"}:
                    continue
                data = node.get("data")
                if not isinstance(data, Mapping):
                    continue
                processing_selector = data.get("processing_ref_selector")
                if processing_selector in (None, []) and not require_resolved:
                    continue
                source = WorkflowService._mail_processing_source(
                    node_by_id,
                    processing_selector,
                )
                if source is None or not WorkflowService._has_graph_path(
                    edge_pairs,
                    str(source.get("id")),
                    str(node.get("id")),
                ):
                    raise HTTPException(
                        status_code=422,
                        detail="mail.processing_configuration_invalid",
                    )

                if node_type == "gmailDraftNode":
                    reply_selector = data.get("reply_body_selector")
                    reply_source_id = (
                        str(reply_selector[0])
                        if isinstance(reply_selector, list) and len(reply_selector) >= 2
                        else ""
                    )
                    reply_source = node_by_id.get(reply_source_id)
                    if (
                        reply_source is None
                        or not WorkflowService._has_graph_path(
                            edge_pairs,
                            reply_source_id,
                            str(node.get("id")),
                        )
                        or source.get("data", {}).get("credential_id")
                        != data.get("credential_id")
                    ):
                        raise HTTPException(
                            status_code=422,
                            detail="mail.processing_configuration_invalid",
                        )
                    continue

                effect_selectors = data.get("required_effect_ref_selectors")
                if effect_selectors in (None, []) and not require_resolved:
                    continue
                for selector in effect_selectors or []:
                    effect_id = (
                        str(selector[0])
                        if isinstance(selector, list) and len(selector) >= 2
                        else ""
                    )
                    effect_node = node_by_id.get(effect_id)
                    effect_data = (
                        effect_node.get("data")
                        if isinstance(effect_node, Mapping)
                        else None
                    )
                    if (
                        not isinstance(effect_node, Mapping)
                        or effect_node.get("type") != "gmailDraftNode"
                        or selector[1] != "draft_ref"
                        or not isinstance(effect_data, Mapping)
                        or effect_data.get("processing_ref_selector")
                        != processing_selector
                        or not WorkflowService._has_graph_path(
                            edge_pairs,
                            effect_id,
                            str(node.get("id")),
                        )
                    ):
                        raise HTTPException(
                            status_code=422,
                            detail="mail.processing_configuration_invalid",
                        )

    @staticmethod
    def _iter_graphs(graph: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
        pending = [graph]
        while pending:
            current = pending.pop()
            yield current
            nodes = current.get("nodes")
            if not isinstance(nodes, list):
                continue
            for node in nodes:
                data = node.get("data") if isinstance(node, Mapping) else None
                subgraph = data.get("subGraph") if isinstance(data, Mapping) else None
                if isinstance(subgraph, Mapping):
                    pending.append(subgraph)

    @staticmethod
    def _mail_processing_source(
        node_by_id: Mapping[str, Mapping[str, Any]],
        selector: Any,
    ) -> Mapping[str, Any] | None:
        if (
            not isinstance(selector, list)
            or len(selector) != 2
            or selector[1] != "processing_ref"
        ):
            return None
        source = node_by_id.get(str(selector[0]))
        data = source.get("data") if isinstance(source, Mapping) else None
        if (
            not isinstance(source, Mapping)
            or source.get("type") != "mailNode"
            or not isinstance(data, Mapping)
            or data.get("processing_mode") != "durable"
            or data.get("mark_as_read") is True
            or data.get("max_results") != 1
        ):
            return None
        return source

    @staticmethod
    def _has_graph_path(
        edge_pairs: set[tuple[str, str]],
        source_id: str,
        target_id: str,
    ) -> bool:
        if not source_id or not target_id or source_id == target_id:
            return False
        pending = [source_id]
        visited: set[str] = set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            for edge_source, edge_target in edge_pairs:
                if edge_source != current:
                    continue
                if edge_target == target_id:
                    return True
                pending.append(edge_target)
        return False

    @staticmethod
    def get_draft(db: Session, workflow_id: str):
        """
        워크플로우 초안을 PostgreSQL에서 조회합니다.
        """
        # db.query(...).first()는 조건에 맞는 첫 번째 행을 'Workflow' 모델 인스턴스(객체)로 반환합니다.
        # 데이터가 없으면 None을 반환합니다.
        workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()

        if not workflow:
            return None

        # workflow.graph는 DB의 JSONB 타입 컬럼이며, 파이썬에서는 딕셔너리(dict)로 변환되어 반환됩니다.
        # 구조 예시: {"nodes": [...], "edges": [...], "viewport": {...}}
        # 이 데이터는 WorkflowEngine의 초기화 인자로 전달되어 실행에 사용됩니다.
        from apps.shared.domain.workflow_node_binding import (
            strip_workflow_node_bindings,
        )

        data = strip_workflow_node_bindings(workflow.graph)

        if workflow.features:
            data["features"] = workflow.features

        return data
