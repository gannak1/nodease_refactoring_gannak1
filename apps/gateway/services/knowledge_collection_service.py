import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.shared.audit.logger import record_audit
from apps.shared.db.models.knowledge import (
    KnowledgeBase,
    KnowledgeCollection,
    KnowledgeCollectionItem,
)
from apps.shared.db.models.team import (
    Team,
    TeamKnowledgeCollectionPermission,
    UserKnowledgeCollectionPermission,
)
from apps.shared.db.models.user import User
from apps.shared.permissions import knowledge_base_auth_state_allows
from apps.shared.schemas.knowledge import (
    KnowledgeCollectionCreateRequest,
    KnowledgeCollectionItemLinkRequest,
    KnowledgeCollectionItemReorderRequest,
    KnowledgeCollectionItemResponse,
    KnowledgeCollectionLinkCandidate,
    KnowledgeCollectionPermissionGrantRequest,
    KnowledgeCollectionPermissionResponse,
    KnowledgeCollectionResponse,
    KnowledgeCollectionUpdateRequest,
    KnowledgeCollectionVisibilityRequest,
    KnowledgeCollectionVisibilityResponse,
)
from apps.shared.services.knowledge_permission_service import KnowledgePermissionHelper
from apps.shared.services.permissions import (
    get_effective_knowledge_base_auth_state,
    has_active_organization_membership,
    has_knowledge_base_permission,
    has_organization_manager_permission,
)


COLLECTION_SAFE_METADATA_FORBIDDEN_KEYS = {
    "raw",
    "raw_source_url",
    "raw_source_path",
    "raw_source_title",
    "raw_source_id",
    "raw_principal",
    "source_principal",
    "credential",
    "secret",
    "token",
}


@dataclass
class KnowledgeCollectionServiceError(Exception):
    status_code: int
    code: str
    message: str
    details: dict[str, Any] | None = None


def _bucket_count(count: int) -> str:
    if count <= 0:
        return "0"
    if count == 1:
        return "1"
    if count <= 10:
        return "2-10"
    if count <= 100:
        return "11-100"
    if count <= 1000:
        return "101-1000"
    return "1000+"


class KnowledgeCollectionService:
    """Manual Knowledge Collection 관리 경계.

    Collection은 grouping/routing/ops 단위이고, 하위 KB content 권한을
    상속하지 않는다. 이 service는 Collection action과 KB manage/use 판정을
    분리해 UI/API가 권한 의미를 섞지 않도록 한다.
    """

    def __init__(
        self,
        db: Session,
        *,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> None:
        self.db = db
        self.user_id = user_id
        self.organization_id = organization_id
        self.permission_helper = KnowledgePermissionHelper(
            db,
            user_id=user_id,
            organization_id=organization_id,
        )

    def list_collections(
        self,
        *,
        lifecycle_state: str = "active",
        visibility: str | None = None,
        system_managed: bool | None = None,
        limit: int = 100,
    ) -> list[KnowledgeCollectionResponse]:
        if lifecycle_state not in {"active", "archived", "deleted"}:
            raise KnowledgeCollectionServiceError(
                400,
                "validation.failed",
                "Invalid lifecycle_state.",
                {"field": "lifecycle_state"},
            )
        if visibility not in {None, "public", "private"}:
            raise KnowledgeCollectionServiceError(
                400,
                "validation.failed",
                "Invalid visibility.",
                {"field": "visibility"},
            )
        query = self.db.query(KnowledgeCollection).filter(
            KnowledgeCollection.organization_id == self.organization_id,
            KnowledgeCollection.lifecycle_state == lifecycle_state,
        )
        if system_managed is not None:
            query = query.filter(KnowledgeCollection.is_system_managed.is_(system_managed))

        collections = (
            query.order_by(KnowledgeCollection.created_at.desc())
            .all()
        )
        decisions = self.permission_helper.bulk_evaluate_collection_action(
            collections,
            "read",
        )
        responses: list[KnowledgeCollectionResponse] = []
        for collection in collections:
            decision = decisions.get(collection.id)
            if not decision or not decision.allowed:
                continue
            if visibility is not None and self._visibility(collection) != visibility:
                continue
            responses.append(self._collection_response(collection))
            if len(responses) >= min(max(limit, 1), 500):
                break
        return responses

    def get_collection(self, collection_id: uuid.UUID) -> KnowledgeCollectionResponse:
        collection = self._collection_or_hidden(collection_id)
        self._require_collection_action(collection, "read")
        return self._collection_response(collection)

    def create_collection(
        self,
        request: KnowledgeCollectionCreateRequest,
    ) -> KnowledgeCollectionResponse:
        self._require_org_manager()
        safe_metadata = self._sanitize_safe_metadata(request.safe_metadata)
        name = self._normalize_required_text(request.name, "name")
        collection = KnowledgeCollection(
            organization_id=self.organization_id,
            name=name,
            description=self._normalize_optional_text(request.description),
            safe_metadata=safe_metadata,
            created_by=self.user_id,
            is_system_managed=False,
            sync_state="manual",
            lifecycle_state="active",
        )
        self.db.add(collection)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise KnowledgeCollectionServiceError(
                409,
                "conflict",
                "Knowledge Collection name already exists.",
            ) from exc
        self.db.refresh(collection)
        self._record_collection_audit("knowledge.collection.created", collection)
        return self._collection_response(collection)

    def update_collection(
        self,
        collection_id: uuid.UUID,
        request: KnowledgeCollectionUpdateRequest,
    ) -> KnowledgeCollectionResponse:
        collection = self._collection_or_hidden(collection_id)
        self._require_collection_action(collection, "manage")
        if collection.is_system_managed:
            raise KnowledgeCollectionServiceError(
                403,
                "policy.denied",
                "System-managed collections cannot be manually edited.",
            )
        if request.name is not None:
            collection.name = self._normalize_required_text(request.name, "name")
        if request.description is not None:
            collection.description = self._normalize_optional_text(request.description)
        if request.safe_metadata is not None:
            collection.safe_metadata = self._sanitize_safe_metadata(
                request.safe_metadata,
                preserve_visibility=collection.safe_metadata.get("visibility"),
            )
        collection.updated_at = self._now()
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise KnowledgeCollectionServiceError(
                409,
                "conflict",
                "Knowledge Collection name already exists.",
            ) from exc
        self.db.refresh(collection)
        self._record_collection_audit("knowledge.collection.updated", collection)
        return self._collection_response(collection)

    def archive_collection(self, collection_id: uuid.UUID) -> None:
        collection = self._collection_or_hidden(collection_id)
        self._require_collection_action(collection, "manage")
        if collection.is_system_managed:
            raise KnowledgeCollectionServiceError(
                403,
                "policy.denied",
                "System-managed collections cannot be manually archived.",
            )
        collection.lifecycle_state = "archived"
        collection.updated_at = self._now()
        self.db.commit()
        self._record_collection_audit("knowledge.collection.archived", collection)

    def list_items(self, collection_id: uuid.UUID) -> list[KnowledgeCollectionItemResponse]:
        collection = self._collection_or_hidden(collection_id)
        self._require_collection_action(collection, "read")
        items = (
            self.db.query(KnowledgeCollectionItem)
            .filter(
                KnowledgeCollectionItem.organization_id == self.organization_id,
                KnowledgeCollectionItem.collection_id == collection.id,
            )
            .order_by(KnowledgeCollectionItem.rank.asc(), KnowledgeCollectionItem.created_at.asc())
            .all()
        )
        return [self._item_response(item) for item in items]

    def link_item(
        self,
        collection_id: uuid.UUID,
        request: KnowledgeCollectionItemLinkRequest,
    ) -> KnowledgeCollectionItemResponse:
        collection = self._collection_or_hidden(collection_id)
        self._require_collection_action(collection, "manage")
        kb = self._knowledge_base_or_hidden(request.knowledge_base_id)
        self._require_kb_manage(kb)
        if kb.lifecycle_state != "active":
            raise KnowledgeCollectionServiceError(
                404,
                "resource.hidden",
                "Resource not found.",
            )

        existing = (
            self.db.query(KnowledgeCollectionItem)
            .filter(
                KnowledgeCollectionItem.collection_id == collection.id,
                KnowledgeCollectionItem.knowledge_base_id == kb.id,
            )
            .first()
        )
        if existing is not None:
            return self._item_response(existing)

        item = KnowledgeCollectionItem(
            organization_id=self.organization_id,
            collection_id=collection.id,
            knowledge_base_id=kb.id,
            rank=request.rank,
            safe_metadata={},
        )
        self.db.add(item)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = (
                self.db.query(KnowledgeCollectionItem)
                .filter(
                    KnowledgeCollectionItem.collection_id == collection.id,
                    KnowledgeCollectionItem.knowledge_base_id == kb.id,
                )
                .first()
            )
            if existing is not None:
                return self._item_response(existing)
            raise
        self.db.refresh(item)
        self._record_collection_audit(
            "knowledge.collection.item.linked",
            collection,
            metadata={"knowledge_base_id": str(kb.id)},
        )
        return self._item_response(item)

    def unlink_item(self, collection_id: uuid.UUID, item_id: uuid.UUID) -> None:
        collection = self._collection_or_hidden(collection_id)
        self._require_collection_action(collection, "manage")
        item = self._item_or_hidden(collection.id, item_id)
        kb = self._knowledge_base_or_hidden(item.knowledge_base_id)
        self._require_kb_manage(kb)
        self.db.delete(item)
        self.db.commit()
        self._record_collection_audit(
            "knowledge.collection.item.unlinked",
            collection,
            metadata={"knowledge_base_id": str(kb.id)},
        )

    def reorder_items(
        self,
        collection_id: uuid.UUID,
        request: KnowledgeCollectionItemReorderRequest,
    ) -> list[KnowledgeCollectionItemResponse]:
        collection = self._collection_or_hidden(collection_id)
        self._require_collection_action(collection, "manage")
        ranks = {entry.item_id: entry.rank for entry in request.items}
        items = (
            self.db.query(KnowledgeCollectionItem)
            .filter(
                KnowledgeCollectionItem.organization_id == self.organization_id,
                KnowledgeCollectionItem.collection_id == collection.id,
                KnowledgeCollectionItem.id.in_(ranks.keys()),
            )
            .all()
        )
        if len(items) != len(ranks):
            raise KnowledgeCollectionServiceError(404, "resource.hidden", "Resource not found.")
        for item in items:
            item.rank = ranks[item.id]
        self.db.commit()
        for item in items:
            self.db.refresh(item)
        self._record_collection_audit("knowledge.collection.items.reordered", collection)
        return self.list_items(collection.id)

    def list_link_candidates(
        self,
        collection_id: uuid.UUID,
        *,
        limit: int = 100,
    ) -> list[KnowledgeCollectionLinkCandidate]:
        collection = self._collection_or_hidden(collection_id)
        self._require_collection_action(collection, "manage")
        linked_ids = {
            row[0]
            for row in self.db.query(KnowledgeCollectionItem.knowledge_base_id)
            .filter(KnowledgeCollectionItem.collection_id == collection.id)
            .all()
        }
        kbs = (
            self.db.query(KnowledgeBase)
            .filter(
                KnowledgeBase.organization_id == self.organization_id,
                KnowledgeBase.lifecycle_state == "active",
            )
            .order_by(KnowledgeBase.created_at.desc())
            .limit(min(max(limit, 1), 500))
            .all()
        )
        candidates: list[KnowledgeCollectionLinkCandidate] = []
        for kb in kbs:
            if kb.id in linked_ids or not self._kb_manage_allowed(kb):
                continue
            candidates.append(
                KnowledgeCollectionLinkCandidate(
                    knowledge_base_id=kb.id,
                    safe_label=kb.name,
                    disabled=False,
                    safe_reason_code=None,
                )
            )
        return candidates

    def list_permissions(
        self,
        collection_id: uuid.UUID,
    ) -> list[KnowledgeCollectionPermissionResponse]:
        collection = self._collection_or_hidden(collection_id)
        self._require_collection_action(collection, "manage")
        team_rows = (
            self.db.query(TeamKnowledgeCollectionPermission)
            .filter(
                TeamKnowledgeCollectionPermission.grantee_organization_id
                == self.organization_id,
                TeamKnowledgeCollectionPermission.knowledge_collection_id
                == collection.id,
            )
            .all()
        )
        user_rows = (
            self.db.query(UserKnowledgeCollectionPermission)
            .filter(
                UserKnowledgeCollectionPermission.grantee_organization_id
                == self.organization_id,
                UserKnowledgeCollectionPermission.knowledge_collection_id
                == collection.id,
            )
            .all()
        )
        return [self._team_permission_response(row) for row in team_rows] + [
            self._user_permission_response(row) for row in user_rows
        ]

    def grant_permission(
        self,
        collection_id: uuid.UUID,
        request: KnowledgeCollectionPermissionGrantRequest,
    ) -> KnowledgeCollectionPermissionResponse:
        collection = self._collection_or_hidden(collection_id)
        self._require_collection_action(collection, "manage")
        if request.subject_type == "team":
            row = self._grant_team_permission(collection, request)
            self._record_collection_audit(
                "knowledge.collection.permission.granted",
                collection,
                metadata={
                    "subject_type": "team",
                    "permission_action": request.permission_action,
                },
            )
            return self._team_permission_response(row)
        row = self._grant_user_permission(collection, request)
        self._record_collection_audit(
            "knowledge.collection.permission.granted",
            collection,
            metadata={
                "subject_type": "user",
                "permission_action": request.permission_action,
            },
        )
        return self._user_permission_response(row)

    def revoke_permission(self, collection_id: uuid.UUID, permission_id: uuid.UUID) -> None:
        collection = self._collection_or_hidden(collection_id)
        self._require_collection_action(collection, "manage")
        row = (
            self.db.query(TeamKnowledgeCollectionPermission)
            .filter(
                TeamKnowledgeCollectionPermission.id == permission_id,
                TeamKnowledgeCollectionPermission.grantee_organization_id
                == self.organization_id,
                TeamKnowledgeCollectionPermission.knowledge_collection_id
                == collection.id,
            )
            .first()
        )
        subject_type = "team"
        if row is None:
            row = (
                self.db.query(UserKnowledgeCollectionPermission)
                .filter(
                    UserKnowledgeCollectionPermission.id == permission_id,
                    UserKnowledgeCollectionPermission.grantee_organization_id
                    == self.organization_id,
                    UserKnowledgeCollectionPermission.knowledge_collection_id
                    == collection.id,
                )
                .first()
            )
            subject_type = "user"
        if row is None:
            raise KnowledgeCollectionServiceError(404, "resource.hidden", "Resource not found.")
        if (
            subject_type == "user"
            and row.user_id == self.user_id
            and row.permission_action == "manage"
            and not self._is_org_manager()
        ):
            raise KnowledgeCollectionServiceError(
                403,
                "permission.denied",
                "Cannot revoke your own last management path.",
            )
        permission_action = row.permission_action
        self.db.delete(row)
        self.db.commit()
        self._record_collection_audit(
            "knowledge.collection.permission.revoked",
            collection,
            metadata={
                "subject_type": subject_type,
                "permission_action": permission_action,
            },
        )

    def update_visibility(
        self,
        collection_id: uuid.UUID,
        request: KnowledgeCollectionVisibilityRequest,
    ) -> KnowledgeCollectionVisibilityResponse:
        collection = self._collection_or_hidden(collection_id)
        self._require_org_manager()
        if request.visibility == "public" and not request.acknowledged_public_runtime_exposure:
            raise KnowledgeCollectionServiceError(
                400,
                "validation.failed",
                "Public visibility acknowledgement is required.",
                {"field": "acknowledged_public_runtime_exposure"},
            )

        metadata = dict(collection.safe_metadata or {})
        metadata["visibility"] = request.visibility
        collection.safe_metadata = metadata
        collection.updated_at = self._now()
        self.db.commit()
        self.db.refresh(collection)
        self._record_collection_audit(
            "knowledge.collection.visibility.changed",
            collection,
            metadata={"visibility": request.visibility},
        )
        response = self._collection_response(collection)
        return KnowledgeCollectionVisibilityResponse(
            collection=response,
            linked_kb_count_bucket=response.linked_kb_count_bucket,
            active_kb_count_bucket=response.active_kb_count_bucket,
        )

    def _grant_team_permission(
        self,
        collection: KnowledgeCollection,
        request: KnowledgeCollectionPermissionGrantRequest,
    ) -> TeamKnowledgeCollectionPermission:
        team = (
            self.db.query(Team)
            .filter(
                Team.id == request.subject_id,
                Team.organization_id == self.organization_id,
                Team.is_active.is_(True),
            )
            .first()
        )
        if team is None:
            raise KnowledgeCollectionServiceError(404, "resource.hidden", "Resource not found.")
        row = (
            self.db.query(TeamKnowledgeCollectionPermission)
            .filter(
                TeamKnowledgeCollectionPermission.grantee_organization_id
                == self.organization_id,
                TeamKnowledgeCollectionPermission.team_id == team.id,
                TeamKnowledgeCollectionPermission.knowledge_collection_id
                == collection.id,
                TeamKnowledgeCollectionPermission.permission_action
                == request.permission_action,
            )
            .first()
        )
        if row is not None:
            return row
        row = TeamKnowledgeCollectionPermission(
            grantee_organization_id=self.organization_id,
            team_id=team.id,
            assigned_by=self.user_id,
            knowledge_collection_id=collection.id,
            permission_action=request.permission_action,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def _grant_user_permission(
        self,
        collection: KnowledgeCollection,
        request: KnowledgeCollectionPermissionGrantRequest,
    ) -> UserKnowledgeCollectionPermission:
        user = (
            self.db.query(User)
            .filter(User.id == request.subject_id, User.deactivated_at.is_(None))
            .first()
        )
        if user is None or not has_active_organization_membership(
            self.db,
            user.id,
            self.organization_id,
        ):
            raise KnowledgeCollectionServiceError(404, "resource.hidden", "Resource not found.")
        row = (
            self.db.query(UserKnowledgeCollectionPermission)
            .filter(
                UserKnowledgeCollectionPermission.grantee_organization_id
                == self.organization_id,
                UserKnowledgeCollectionPermission.user_id == user.id,
                UserKnowledgeCollectionPermission.knowledge_collection_id
                == collection.id,
                UserKnowledgeCollectionPermission.permission_action
                == request.permission_action,
            )
            .first()
        )
        if row is not None:
            return row
        row = UserKnowledgeCollectionPermission(
            grantee_organization_id=self.organization_id,
            user_id=user.id,
            assigned_by=self.user_id,
            knowledge_collection_id=collection.id,
            permission_action=request.permission_action,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def _collection_response(
        self,
        collection: KnowledgeCollection,
    ) -> KnowledgeCollectionResponse:
        permissions = {
            action: self.permission_helper.evaluate_collection_action(
                collection,
                action,
            ).allowed
            for action in ("read", "route", "manage", "sync")
        }
        linked_count = self._linked_kb_count(collection.id)
        active_count = self._active_kb_count(collection.id)
        safe_metadata = dict(collection.safe_metadata or {})
        return KnowledgeCollectionResponse(
            id=collection.id,
            organization_id=collection.organization_id,
            name=collection.name,
            description=collection.description,
            is_system_managed=collection.is_system_managed,
            sync_state=collection.sync_state,
            lifecycle_state=collection.lifecycle_state,
            visibility=self._visibility(collection),
            linked_kb_count_bucket=_bucket_count(linked_count),
            active_kb_count_bucket=_bucket_count(active_count),
            can_read=permissions["read"],
            can_route=permissions["route"],
            can_manage=permissions["manage"],
            can_sync=permissions["sync"],
            safe_metadata=safe_metadata,
            created_at=collection.created_at,
            updated_at=collection.updated_at,
        )

    def _item_response(
        self,
        item: KnowledgeCollectionItem,
    ) -> KnowledgeCollectionItemResponse:
        kb = item.knowledge_base or self._knowledge_base_or_hidden(item.knowledge_base_id)
        auth_state = get_effective_knowledge_base_auth_state(
            self.db,
            self.user_id,
            kb.id,
            organization_id=self.organization_id,
        )
        use_decision = self.permission_helper.evaluate_kb_use(kb)
        return KnowledgeCollectionItemResponse(
            item_id=item.id,
            knowledge_base_id=kb.id,
            safe_label=kb.name,
            lifecycle_state=kb.lifecycle_state,
            sync_state=kb.sync_state,
            rank=item.rank,
            can_manage_kb=knowledge_base_auth_state_allows(auth_state, "manage"),
            can_use_kb=use_decision.allowed,
        )

    def _team_permission_response(
        self,
        row: TeamKnowledgeCollectionPermission,
    ) -> KnowledgeCollectionPermissionResponse:
        team = row.team or self.db.query(Team).filter(Team.id == row.team_id).first()
        return KnowledgeCollectionPermissionResponse(
            permission_id=row.id,
            subject_type="team",
            subject_id=row.team_id,
            subject_safe_label=getattr(team, "name", None),
            permission_action=row.permission_action,
        )

    def _user_permission_response(
        self,
        row: UserKnowledgeCollectionPermission,
    ) -> KnowledgeCollectionPermissionResponse:
        user = row.user or self.db.query(User).filter(User.id == row.user_id).first()
        return KnowledgeCollectionPermissionResponse(
            permission_id=row.id,
            subject_type="user",
            subject_id=row.user_id,
            subject_safe_label=getattr(user, "name", None),
            permission_action=row.permission_action,
        )

    def _require_org_manager(self) -> None:
        if not self._is_org_manager():
            raise KnowledgeCollectionServiceError(
                403,
                "permission.denied",
                "Organization manager permission is required.",
            )

    def _is_org_manager(self) -> bool:
        return has_organization_manager_permission(
            self.db,
            self.user_id,
            self.organization_id,
        )

    def _require_collection_action(
        self,
        collection: KnowledgeCollection,
        action: str,
    ) -> None:
        decision = self.permission_helper.evaluate_collection_action(collection, action)
        if not decision.allowed:
            status_code = 404 if decision.external_reason_code == "resource.hidden" else 403
            raise KnowledgeCollectionServiceError(
                status_code,
                decision.external_reason_code,
                "Resource not found." if status_code == 404 else "Permission denied.",
            )

    def _require_kb_manage(self, kb: KnowledgeBase) -> None:
        if not self._kb_manage_allowed(kb):
            raise KnowledgeCollectionServiceError(
                403,
                "permission.denied",
                "Knowledge Base manage permission is required.",
            )

    def _kb_manage_allowed(self, kb: KnowledgeBase) -> bool:
        return has_knowledge_base_permission(
            self.db,
            self.user_id,
            kb.id,
            "manage",
            organization_id=self.organization_id,
        )

    def _collection_or_hidden(self, collection_id: uuid.UUID) -> KnowledgeCollection:
        collection = (
            self.db.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.id == collection_id,
                KnowledgeCollection.organization_id == self.organization_id,
                KnowledgeCollection.lifecycle_state != "deleted",
            )
            .first()
        )
        if collection is None:
            raise KnowledgeCollectionServiceError(404, "resource.hidden", "Resource not found.")
        return collection

    def _item_or_hidden(
        self,
        collection_id: uuid.UUID,
        item_id: uuid.UUID,
    ) -> KnowledgeCollectionItem:
        item = (
            self.db.query(KnowledgeCollectionItem)
            .filter(
                KnowledgeCollectionItem.id == item_id,
                KnowledgeCollectionItem.organization_id == self.organization_id,
                KnowledgeCollectionItem.collection_id == collection_id,
            )
            .first()
        )
        if item is None:
            raise KnowledgeCollectionServiceError(404, "resource.hidden", "Resource not found.")
        return item

    def _knowledge_base_or_hidden(self, kb_id: uuid.UUID) -> KnowledgeBase:
        kb = (
            self.db.query(KnowledgeBase)
            .filter(
                KnowledgeBase.id == kb_id,
                KnowledgeBase.organization_id == self.organization_id,
                KnowledgeBase.lifecycle_state != "deleted",
            )
            .first()
        )
        if kb is None:
            raise KnowledgeCollectionServiceError(404, "resource.hidden", "Resource not found.")
        return kb

    def _linked_kb_count(self, collection_id: uuid.UUID) -> int:
        return (
            self.db.query(func.count(KnowledgeCollectionItem.id))
            .filter(KnowledgeCollectionItem.collection_id == collection_id)
            .scalar()
            or 0
        )

    def _active_kb_count(self, collection_id: uuid.UUID) -> int:
        return (
            self.db.query(func.count(KnowledgeCollectionItem.id))
            .join(KnowledgeBase, KnowledgeBase.id == KnowledgeCollectionItem.knowledge_base_id)
            .filter(
                KnowledgeCollectionItem.collection_id == collection_id,
                KnowledgeBase.lifecycle_state == "active",
            )
            .scalar()
            or 0
        )

    def _visibility(self, collection: KnowledgeCollection) -> str:
        if (collection.safe_metadata or {}).get("visibility") == "public":
            return "public"
        return "private"

    def _sanitize_safe_metadata(
        self,
        metadata: dict | None,
        *,
        preserve_visibility: str | None = None,
    ) -> dict:
        if not metadata:
            sanitized: dict[str, Any] = {}
        else:
            sanitized = {}
            for key, value in metadata.items():
                key_text = str(key)
                lowered = key_text.lower()
                if key_text == "visibility":
                    continue
                if any(forbidden in lowered for forbidden in COLLECTION_SAFE_METADATA_FORBIDDEN_KEYS):
                    raise KnowledgeCollectionServiceError(
                        400,
                        "validation.failed",
                        "safe_metadata contains a forbidden key.",
                        {"field": "safe_metadata"},
                    )
                sanitized[key_text[:64]] = self._sanitize_metadata_value(value)
        if preserve_visibility in {"public", "private"}:
            sanitized["visibility"] = preserve_visibility
        return sanitized

    def _sanitize_metadata_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return value[:512]
        if isinstance(value, list):
            return [self._sanitize_metadata_value(item) for item in value[:50]]
        raise KnowledgeCollectionServiceError(
            400,
            "validation.failed",
            "safe_metadata supports only primitive values and primitive lists.",
            {"field": "safe_metadata"},
        )

    def _normalize_optional_text(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None

    def _normalize_required_text(self, value: str, field: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise KnowledgeCollectionServiceError(
                400,
                "validation.failed",
                "Required text field cannot be blank.",
                {"field": field},
            )
        return normalized

    def _record_collection_audit(
        self,
        action: str,
        collection: KnowledgeCollection,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        # Audit에는 raw source title/path/url이나 hidden count를 넣지 않는다.
        record_audit(
            action=action,
            category="knowledge",
            actor_id=self.user_id,
            actor_type="user",
            target_type="knowledge_collection",
            target_id=collection.id,
            status="success",
            metadata={
                "organization_id": str(self.organization_id),
                "visibility": self._visibility(collection),
                **(metadata or {}),
            },
        )

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)
