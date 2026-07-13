from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from typing import Protocol

from .models import (
    KnowledgeBaseSnapshot,
    KnowledgeCollectionPreflightSnapshot,
    WorkflowNodeTargetSnapshot,
)


class DeploymentPreflightRepository(Protocol):
    def get_active_knowledge_bases(
        self,
        knowledge_base_ids: Iterable[uuid.UUID],
        organization_id: uuid.UUID | None,
    ) -> Mapping[uuid.UUID, KnowledgeBaseSnapshot]: ...

    def get_public_runtime_eligible_knowledge_base_ids(
        self,
        knowledge_base_ids: Iterable[uuid.UUID],
        organization_id: uuid.UUID | None,
    ) -> set[uuid.UUID]: ...

    def get_active_knowledge_collections(
        self,
        collection_ids: Iterable[uuid.UUID],
        organization_id: uuid.UUID | None,
    ) -> Mapping[uuid.UUID, KnowledgeCollectionPreflightSnapshot]: ...

    def get_workflow_node_target(
        self,
        app_id: uuid.UUID,
        organization_id: uuid.UUID | None,
    ) -> WorkflowNodeTargetSnapshot | None: ...

    def get_workflow_node_deployment(
        self,
        app_id: uuid.UUID,
        deployment_id: uuid.UUID,
        organization_id: uuid.UUID | None,
    ) -> WorkflowNodeTargetSnapshot | None: ...
