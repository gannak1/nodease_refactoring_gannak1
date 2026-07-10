from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy.orm import Session

from apps.gateway.application.deployment.models import (
    KnowledgeBaseSnapshot,
    WorkflowNodeTargetSnapshot,
)
from apps.shared.db.models.app import App
from apps.shared.db.models.knowledge import (
    KnowledgeBase,
    KnowledgeCollection,
    KnowledgeCollectionItem,
)
from apps.shared.db.models.workflow_deployment import DeploymentType, WorkflowDeployment


class SqlAlchemyDeploymentPreflightRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_active_knowledge_bases(
        self,
        knowledge_base_ids: Iterable[uuid.UUID],
        organization_id: uuid.UUID | None,
    ) -> dict[uuid.UUID, KnowledgeBaseSnapshot]:
        ids = _dedupe_ids(knowledge_base_ids)
        if not ids or organization_id is None:
            return {}
        rows = (
            self.db.query(KnowledgeBase)
            .filter(
                KnowledgeBase.id.in_(ids),
                KnowledgeBase.organization_id == organization_id,
                KnowledgeBase.lifecycle_state == "active",
            )
            .all()
        )
        return {
            row.id: KnowledgeBaseSnapshot(
                id=row.id,
                source_managed=getattr(row, "source_identity_id", None) is not None,
            )
            for row in rows
        }

    def get_public_runtime_eligible_knowledge_base_ids(
        self,
        knowledge_base_ids: Iterable[uuid.UUID],
        organization_id: uuid.UUID | None,
    ) -> set[uuid.UUID]:
        ids = _dedupe_ids(knowledge_base_ids)
        if not ids or organization_id is None:
            return set()

        items = (
            self.db.query(KnowledgeCollectionItem)
            .filter(
                KnowledgeCollectionItem.organization_id == organization_id,
                KnowledgeCollectionItem.knowledge_base_id.in_(ids),
            )
            .all()
        )
        collection_ids = _dedupe_ids(item.collection_id for item in items)
        if not collection_ids:
            return set()

        collections = (
            self.db.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.id.in_(collection_ids),
                KnowledgeCollection.organization_id == organization_id,
                KnowledgeCollection.lifecycle_state == "active",
            )
            .all()
        )
        public_collection_ids = {
            collection.id
            for collection in collections
            if (getattr(collection, "safe_metadata", None) or {}).get("visibility")
            == "public"
        }
        return {
            item.knowledge_base_id
            for item in items
            if item.collection_id in public_collection_ids
        }

    def get_workflow_node_target(
        self,
        app_id: uuid.UUID,
        organization_id: uuid.UUID | None,
    ) -> WorkflowNodeTargetSnapshot | None:
        query = self.db.query(App).filter(App.id == app_id)
        if organization_id is not None:
            query = query.filter(App.organization_id == organization_id)
        app = query.first()
        if app is None:
            return None

        deployment_id = _uuid_or_none(getattr(app, "active_deployment_id", None))
        if deployment_id is None:
            return WorkflowNodeTargetSnapshot(
                app_id=app.id,
                active_graph_snapshot=None,
            )

        deployment = (
            self.db.query(WorkflowDeployment)
            .filter(
                WorkflowDeployment.id == deployment_id,
                WorkflowDeployment.app_id == app.id,
                WorkflowDeployment.is_active.is_(True),
                WorkflowDeployment.type == DeploymentType.WORKFLOW_NODE,
            )
            .first()
        )
        return WorkflowNodeTargetSnapshot(
            app_id=app.id,
            active_graph_snapshot=(
                deployment.graph_snapshot if deployment is not None else None
            ),
        )


def _dedupe_ids(values: Iterable[uuid.UUID]) -> list[uuid.UUID]:
    result: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _uuid_or_none(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None
