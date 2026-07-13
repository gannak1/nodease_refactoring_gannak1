import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.gateway.services.audit_records import add_action_audit, add_data_change_audit
from apps.shared.db.models.knowledge import (
    KnowledgeBase,
    KnowledgeCollection,
    KnowledgeCollectionItem,
)
from apps.shared.db.models.team import (
    Team,
    TeamKnowledgeCollectionPermission,
    TeamMembership,
    UserKnowledgeCollectionPermission,
)
from apps.shared.db.models.organization_membership import OrganizationMembership
from apps.shared.db.models.user import User
from apps.shared.permissions import knowledge_base_auth_state_allows
from apps.shared.schemas.knowledge import (
    KnowledgeCollectionCreateRequest,
    KnowledgeCollectionItemLinkRequest,
    KnowledgeCollectionItemReorderRequest,
    KnowledgeCollectionItemResponse,
    KnowledgeCollectionLinkCandidate,
    KnowledgeCollectionPermissionGrantRequest,
    KnowledgeCollectionPermissionBundleGrantRequest,
    KnowledgeCollectionPermissionResponse,
    KnowledgeCollectionResponse,
    KnowledgeCollectionUpdateRequest,
    KnowledgeCollectionVisibilityRequest,
    KnowledgeCollectionVisibilityResponse,
    KnowledgeDelegationSubject,
    KnowledgeDelegationSubjectsResponse,
)
from apps.shared.services.knowledge_permission_service import KnowledgePermissionHelper
from apps.shared.services.permissions import (
    get_effective_knowledge_domain_actions,
    get_effective_knowledge_base_auth_state,
    has_active_organization_membership,
    has_knowledge_base_permission,
    has_organization_manager_permission,
)
from apps.gateway.services.knowledge_collection_policy import (
    bucket_count,
    collection_visibility,
    normalize_optional_text,
    normalize_required_text,
    safe_metadata_key_is_forbidden,
    sanitize_safe_metadata_value,
)

GENERIC_KB_LABEL = "Knowledge Base"
LINK_CANDIDATE_SCAN_LIMIT = 5000
COLLECTION_ROLE_BUNDLE_ACTIONS = {
    "viewer": ("read",),
    "workflow_router": ("read", "route"),
    "maintainer": ("read", "manage"),
    "sync_operator": ("read", "sync"),
}


@dataclass
class KnowledgeCollectionServiceError(Exception):
    status_code: int
    code: str
    message: str
    details: dict[str, Any] | None = None


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
        self._domain_actions_cache: set[str] | None = None

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
            if (
                (not decision or not decision.allowed)
                and not self._has_safe_collection_admin_visibility()
            ):
                continue
            if visibility is not None and self._visibility(collection) != visibility:
                continue
            responses.append(self._collection_response(collection))
            if len(responses) >= min(max(limit, 1), 500):
                break
        return responses

    def management_capabilities(self) -> dict[str, bool]:
        can_manage_public_scope = self._is_org_manager()
        return {
            "can_create_collection": (
                can_manage_public_scope or self._has_domain_action("catalog_manage")
            ),
            "can_change_public_visibility": can_manage_public_scope,
        }

    def get_collection(self, collection_id: uuid.UUID) -> KnowledgeCollectionResponse:
        collection = self._collection_or_hidden(collection_id)
        if not self._has_safe_collection_admin_visibility():
            self._require_collection_action(collection, "read")
        return self._collection_response(collection)

    def create_collection(
        self,
        request: KnowledgeCollectionCreateRequest,
    ) -> KnowledgeCollectionResponse:
        self._require_org_manager_or_domain("catalog_manage")
        safe_metadata = self._sanitize_safe_metadata(request.safe_metadata)
        name = self._normalize_required_text(request.name, "name")
        collection = KnowledgeCollection(
            id=uuid.uuid4(),
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
            self._record_collection_audit("knowledge.collection.created", collection)
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise KnowledgeCollectionServiceError(
                409,
                "conflict",
                "Knowledge Collection name already exists.",
            ) from exc
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(collection)
        return self._collection_response(collection)

    def update_collection(
        self,
        collection_id: uuid.UUID,
        request: KnowledgeCollectionUpdateRequest,
    ) -> KnowledgeCollectionResponse:
        collection = self._collection_or_hidden(collection_id)
        self._require_collection_manage_or_catalog(collection)
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
            self._record_collection_audit("knowledge.collection.updated", collection)
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise KnowledgeCollectionServiceError(
                409,
                "conflict",
                "Knowledge Collection name already exists.",
            ) from exc
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(collection)
        return self._collection_response(collection)

    def archive_collection(self, collection_id: uuid.UUID) -> None:
        collection = self._collection_or_hidden(collection_id)
        if not self._has_domain_action("lifecycle_manage"):
            self._require_collection_action(collection, "manage")
        if collection.is_system_managed:
            raise KnowledgeCollectionServiceError(
                403,
                "policy.denied",
                "System-managed collections cannot be manually archived.",
            )
        collection.lifecycle_state = "archived"
        collection.updated_at = self._now()
        self._record_collection_audit_and_commit(
            "knowledge.collection.archived",
            collection,
        )

    def list_items(self, collection_id: uuid.UUID) -> list[KnowledgeCollectionItemResponse]:
        collection = self._collection_or_hidden(collection_id)
        if not (
            self._visibility(collection) == "private"
            and self._has_domain_action("catalog_manage")
        ):
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
        kb = self._knowledge_base_or_hidden(request.knowledge_base_id)
        self._require_collection_membership_mutation(
            collection,
            kb=kb,
            acknowledged_public_runtime_exposure=(
                request.acknowledged_public_runtime_exposure
            ),
            adds_public_exposure=True,
        )
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
            id=uuid.uuid4(),
            organization_id=self.organization_id,
            collection_id=collection.id,
            knowledge_base_id=kb.id,
            rank=request.rank,
            safe_metadata={},
        )
        self.db.add(item)
        try:
            self._record_collection_audit(
                "knowledge.collection.item.linked",
                collection,
                metadata={"knowledge_base_id": str(kb.id)},
            )
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
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(item)
        return self._item_response(item)

    def unlink_item(
        self,
        collection_id: uuid.UUID,
        item_id: uuid.UUID,
        *,
        acknowledged_public_runtime_exposure: bool = False,
    ) -> None:
        collection = self._collection_or_hidden(collection_id)
        item = self._item_or_hidden(collection.id, item_id)
        kb = self._knowledge_base_or_hidden(item.knowledge_base_id)
        self._require_collection_membership_mutation(
            collection,
            kb=kb,
            acknowledged_public_runtime_exposure=(
                acknowledged_public_runtime_exposure
            ),
        )
        self.db.delete(item)
        self._record_collection_audit_and_commit(
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
        self._require_collection_membership_mutation(
            collection,
            acknowledged_public_runtime_exposure=(
                request.acknowledged_public_runtime_exposure
            ),
        )
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
        self._record_collection_audit_and_commit(
            "knowledge.collection.items.reordered",
            collection,
        )
        for item in items:
            self.db.refresh(item)
        return self.list_items(collection.id)

    def list_link_candidates(
        self,
        collection_id: uuid.UUID,
        *,
        limit: int = 100,
    ) -> list[KnowledgeCollectionLinkCandidate]:
        collection = self._collection_or_hidden(collection_id)
        self._require_collection_membership_candidate_access(collection)
        linked_ids = self._linked_kb_ids(collection.id)
        requested_limit = min(max(limit, 1), 500)
        batch_size = min(max(requested_limit * 2, 100), 500)
        candidates: list[KnowledgeCollectionLinkCandidate] = []
        scanned = 0
        while len(candidates) < requested_limit and scanned < LINK_CANDIDATE_SCAN_LIMIT:
            page = self._link_candidate_kb_page(
                limit=min(batch_size, LINK_CANDIDATE_SCAN_LIMIT - scanned),
                offset=scanned,
            )
            if not page:
                break
            scanned += len(page)
            for kb in page:
                if kb.id in linked_ids or not self._kb_link_candidate_allowed(
                    collection,
                    kb,
                ):
                    continue
                candidates.append(
                    KnowledgeCollectionLinkCandidate(
                        knowledge_base_id=kb.id,
                        safe_label=self._kb_safe_label(kb),
                        disabled=False,
                        safe_reason_code=None,
                    )
                )
                if len(candidates) >= requested_limit:
                    break
            if len(page) < batch_size:
                break
        return candidates

    def _link_candidate_kb_page(self, *, limit: int, offset: int) -> list[KnowledgeBase]:
        return (
            self.db.query(KnowledgeBase)
            .filter(
                KnowledgeBase.organization_id == self.organization_id,
                KnowledgeBase.lifecycle_state == "active",
            )
            .order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def _linked_kb_ids(self, collection_id: uuid.UUID) -> set[uuid.UUID]:
        return {
            row[0]
            for row in self.db.query(KnowledgeCollectionItem.knowledge_base_id)
            .filter(
                KnowledgeCollectionItem.organization_id == self.organization_id,
                KnowledgeCollectionItem.collection_id == collection_id,
            )
            .all()
        }

    def list_permissions(
        self,
        collection_id: uuid.UUID,
    ) -> list[KnowledgeCollectionPermissionResponse]:
        collection = self._collection_or_hidden(collection_id)
        self._require_collection_permission_authority(collection)
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

    def list_delegation_subjects(
        self,
        collection_id: uuid.UUID,
    ) -> KnowledgeDelegationSubjectsResponse:
        collection = self._collection_or_hidden(collection_id)
        self._require_collection_permission_authority(collection)
        return self._delegation_subjects_response()

    def list_domain_delegation_subjects(self) -> KnowledgeDelegationSubjectsResponse:
        self._require_org_manager()
        return self._delegation_subjects_response()

    def _delegation_subjects_response(self) -> KnowledgeDelegationSubjectsResponse:
        teams = (
            self.db.query(Team)
            .filter(
                Team.organization_id == self.organization_id,
                Team.is_active.is_(True),
            )
            .order_by(Team.name.asc(), Team.id.asc())
            .all()
        )
        users = (
            self.db.query(User)
            .join(
                OrganizationMembership,
                OrganizationMembership.user_id == User.id,
            )
            .filter(
                OrganizationMembership.organization_id == self.organization_id,
                OrganizationMembership.membership_state == "active",
                User.deactivated_at.is_(None),
            )
            .order_by(User.name.asc(), User.id.asc())
            .all()
        )
        return KnowledgeDelegationSubjectsResponse(
            teams=[
                KnowledgeDelegationSubject(
                    subject_type="team",
                    subject_id=team.id,
                    subject_safe_label=str(team.name or "Team"),
                )
                for team in teams
            ],
            users=[
                KnowledgeDelegationSubject(
                    subject_type="user",
                    subject_id=user.id,
                    subject_safe_label=str(user.name or "User"),
                )
                for user in users
            ],
        )

    def grant_permission(
        self,
        collection_id: uuid.UUID,
        request: KnowledgeCollectionPermissionGrantRequest,
    ) -> KnowledgeCollectionPermissionResponse:
        collection = self._collection_or_hidden(collection_id)
        authority = self._require_collection_permission_authority(collection)
        self._block_collection_delegate_self_escalation(
            collection,
            request,
            authority=authority,
        )
        if request.subject_type == "team":
            row, created = self._grant_team_permission(collection, request)
            if not created:
                return self._team_permission_response(row)
            self._record_collection_audit_and_commit(
                "knowledge.collection.permission.granted",
                collection,
                metadata={
                    "subject_type": "team",
                    "permission_action": request.permission_action,
                },
            )
            self.db.refresh(row)
            return self._team_permission_response(row)
        row, created = self._grant_user_permission(collection, request)
        if not created:
            return self._user_permission_response(row)
        self._record_collection_audit_and_commit(
            "knowledge.collection.permission.granted",
            collection,
            metadata={
                "subject_type": "user",
                "permission_action": request.permission_action,
            },
        )
        self.db.refresh(row)
        return self._user_permission_response(row)

    def grant_permission_bundle(
        self,
        collection_id: uuid.UUID,
        request: KnowledgeCollectionPermissionBundleGrantRequest,
    ) -> list[KnowledgeCollectionPermissionResponse]:
        collection = self._collection_or_hidden(collection_id)
        authority = self._require_collection_permission_authority(collection)
        actions = COLLECTION_ROLE_BUNDLE_ACTIONS[request.role_bundle]
        escalation_probe = KnowledgeCollectionPermissionGrantRequest(
            subject_type=request.subject_type,
            subject_id=request.subject_id,
            permission_action=actions[0],
        )
        self._block_collection_delegate_self_escalation(
            collection,
            escalation_probe,
            authority=authority,
        )

        rows: list[
            TeamKnowledgeCollectionPermission | UserKnowledgeCollectionPermission
        ] = []
        created_rows: list[
            TeamKnowledgeCollectionPermission | UserKnowledgeCollectionPermission
        ] = []
        for action in actions:
            grant = KnowledgeCollectionPermissionGrantRequest(
                subject_type=request.subject_type,
                subject_id=request.subject_id,
                permission_action=action,
            )
            if request.subject_type == "team":
                row, created = self._grant_team_permission(collection, grant)
            else:
                row, created = self._grant_user_permission(collection, grant)
            rows.append(row)
            if created:
                created_rows.append(row)

        if created_rows:
            try:
                self._record_collection_audit(
                    "knowledge.collection.permission_bundle.granted",
                    collection,
                    metadata={
                        "subject_type": request.subject_type,
                        "role_bundle": request.role_bundle,
                        "permission_actions": list(actions),
                    },
                )
                self.db.commit()
            except IntegrityError as exc:
                self.db.rollback()
                raise KnowledgeCollectionServiceError(
                    409,
                    "conflict",
                    "Knowledge Collection permission bundle changed concurrently.",
                ) from exc
            except Exception:
                self.db.rollback()
                raise
            for row in created_rows:
                self.db.refresh(row)

        if request.subject_type == "team":
            return [self._team_permission_response(row) for row in rows]
        return [self._user_permission_response(row) for row in rows]

    def revoke_permission(self, collection_id: uuid.UUID, permission_id: uuid.UUID) -> None:
        collection = self._collection_or_hidden(collection_id)
        self._require_collection_permission_authority(collection)
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
        if self._would_revoke_current_user_last_manage_path(
            collection.id,
            subject_type,
            row,
        ):
            raise KnowledgeCollectionServiceError(
                403,
                "permission.denied",
                "Cannot revoke your own last management path.",
            )
        permission_action = row.permission_action
        self.db.delete(row)
        self._record_collection_audit_and_commit(
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
        if (
            request.visibility == "public"
            and self._collection_has_source_managed_items(collection.id)
        ):
            raise KnowledgeCollectionServiceError(
                409,
                "policy.blocked",
                "Source-managed Knowledge requires public exposure approval.",
                {"policy_reason": "source_public_exposure_required"},
            )

        metadata = dict(collection.safe_metadata or {})
        metadata["visibility"] = request.visibility
        collection.safe_metadata = metadata
        collection.updated_at = self._now()
        self._record_collection_audit_and_commit(
            "knowledge.collection.visibility.changed",
            collection,
            metadata={"visibility": request.visibility},
        )
        self.db.refresh(collection)
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
    ) -> tuple[TeamKnowledgeCollectionPermission, bool]:
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
            return row, False
        row = TeamKnowledgeCollectionPermission(
            id=uuid.uuid4(),
            grantee_organization_id=self.organization_id,
            team_id=team.id,
            assigned_by=self.user_id,
            knowledge_collection_id=collection.id,
            permission_action=request.permission_action,
        )
        self.db.add(row)
        return row, True

    def _grant_user_permission(
        self,
        collection: KnowledgeCollection,
        request: KnowledgeCollectionPermissionGrantRequest,
    ) -> tuple[UserKnowledgeCollectionPermission, bool]:
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
            return row, False
        row = UserKnowledgeCollectionPermission(
            id=uuid.uuid4(),
            grantee_organization_id=self.organization_id,
            user_id=user.id,
            assigned_by=self.user_id,
            knowledge_collection_id=collection.id,
            permission_action=request.permission_action,
        )
        self.db.add(row)
        return row, True

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
            linked_kb_count_bucket=bucket_count(linked_count),
            active_kb_count_bucket=bucket_count(active_count),
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
            safe_label=self._kb_safe_label(kb),
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

    def _require_org_manager_or_domain(self, action: str) -> None:
        if self._is_org_manager() or self._has_domain_action(action):
            return
        raise KnowledgeCollectionServiceError(
            403,
            "permission.denied",
            "Knowledge administration permission is required.",
        )

    def _is_org_manager(self) -> bool:
        return has_organization_manager_permission(
            self.db,
            self.user_id,
            self.organization_id,
        )

    def _has_domain_action(self, action: str) -> bool:
        if self._domain_actions_cache is None:
            self._domain_actions_cache = get_effective_knowledge_domain_actions(
                self.db,
                self.user_id,
                self.organization_id,
            )
        return action in self._domain_actions_cache

    def _has_safe_collection_admin_visibility(self) -> bool:
        return any(
            self._has_domain_action(action)
            for action in (
                "catalog_manage",
                "permission_delegate",
                "lifecycle_manage",
                "sync_manage",
            )
        )

    def _require_collection_manage_or_catalog(
        self,
        collection: KnowledgeCollection,
    ) -> None:
        if (
            not collection.is_system_managed
            and self._visibility(collection) == "private"
            and self._has_domain_action("catalog_manage")
        ):
            return
        self._require_collection_action(collection, "manage")

    def _require_collection_membership_candidate_access(
        self,
        collection: KnowledgeCollection,
    ) -> None:
        if self._visibility(collection) == "public":
            self._require_org_manager()
            return
        self._require_collection_manage_or_catalog(collection)

    def _require_collection_membership_mutation(
        self,
        collection: KnowledgeCollection,
        *,
        kb: KnowledgeBase | None = None,
        acknowledged_public_runtime_exposure: bool = False,
        adds_public_exposure: bool = False,
    ) -> None:
        if collection.is_system_managed:
            raise KnowledgeCollectionServiceError(
                403,
                "policy.denied",
                "System-managed collections cannot be manually changed.",
            )
        if self._visibility(collection) == "public":
            self._require_org_manager()
            if not acknowledged_public_runtime_exposure:
                raise KnowledgeCollectionServiceError(
                    400,
                    "validation.failed",
                    "Public membership acknowledgement is required.",
                    {"field": "acknowledged_public_runtime_exposure"},
                )
            if adds_public_exposure and kb is not None and self._is_source_managed_kb(kb):
                raise KnowledgeCollectionServiceError(
                    409,
                    "policy.blocked",
                    "Source-managed Knowledge requires public exposure approval.",
                    {"policy_reason": "source_public_exposure_required"},
                )
            return
        if self._has_domain_action("catalog_manage"):
            return
        self._require_collection_action(collection, "manage")
        if kb is not None:
            self._require_kb_manage(kb)

    def _kb_link_candidate_allowed(
        self,
        collection: KnowledgeCollection,
        kb: KnowledgeBase,
    ) -> bool:
        if self._visibility(collection) == "public":
            return self._is_org_manager() and not self._is_source_managed_kb(kb)
        if self._has_domain_action("catalog_manage"):
            return True
        return self._kb_manage_allowed(kb)

    def _require_collection_permission_authority(
        self,
        collection: KnowledgeCollection,
    ) -> str:
        if self._is_org_manager():
            return "organization_manager"
        decision = self.permission_helper.evaluate_collection_action(
            collection,
            "manage",
        )
        if decision.allowed:
            return "resource_manager"
        if self._has_domain_action("permission_delegate"):
            return "domain_delegate"
        status_code = 404 if decision.external_reason_code == "resource.hidden" else 403
        raise KnowledgeCollectionServiceError(
            status_code,
            decision.external_reason_code,
            "Resource not found." if status_code == 404 else "Permission denied.",
        )

    def _block_collection_delegate_self_escalation(
        self,
        collection: KnowledgeCollection,
        request: KnowledgeCollectionPermissionGrantRequest,
        *,
        authority: str,
    ) -> None:
        if authority != "domain_delegate":
            return
        targets_actor = request.subject_type == "user" and request.subject_id == self.user_id
        if request.subject_type == "team":
            targets_actor = request.subject_id in self._active_team_ids()
        if not targets_actor:
            return
        try:
            add_action_audit(
                self.db,
                "knowledge.collection.permission_grant.blocked",
                self.user_id,
                "knowledge_collection",
                collection.id,
                organization_id=self.organization_id,
                status="blocked",
                metadata={"policy_reason": "knowledge.self_escalation"},
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        raise KnowledgeCollectionServiceError(
            409,
            "policy.blocked",
            "Knowledge permission grant is blocked by policy.",
            {"policy_reason": "knowledge.self_escalation"},
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

    def _kb_safe_label(self, kb: KnowledgeBase) -> str:
        source_identity = getattr(kb, "source_identity", None)
        if source_identity is not None:
            if getattr(source_identity, "display_policy_state", None) == "approved":
                safe_display_name = getattr(source_identity, "safe_display_name", None)
                if safe_display_name:
                    return str(safe_display_name)
            return GENERIC_KB_LABEL
        return str(getattr(kb, "name", None) or GENERIC_KB_LABEL)

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

    def _collection_has_source_managed_items(
        self,
        collection_id: uuid.UUID,
    ) -> bool:
        return (
            self.db.query(func.count(KnowledgeCollectionItem.id))
            .join(
                KnowledgeBase,
                KnowledgeBase.id == KnowledgeCollectionItem.knowledge_base_id,
            )
            .filter(
                KnowledgeCollectionItem.organization_id == self.organization_id,
                KnowledgeCollectionItem.collection_id == collection_id,
                KnowledgeBase.source_identity_id.is_not(None),
            )
            .scalar()
            or 0
        ) > 0

    def _is_source_managed_kb(self, kb: KnowledgeBase) -> bool:
        return getattr(kb, "source_identity_id", None) is not None

    def _visibility(self, collection: KnowledgeCollection) -> str:
        return collection_visibility(collection)

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
                if key_text == "visibility":
                    continue
                if safe_metadata_key_is_forbidden(key_text):
                    raise KnowledgeCollectionServiceError(
                        400,
                        "validation.failed",
                        "safe_metadata contains a forbidden key.",
                        {"field": "safe_metadata"},
                    )
                try:
                    sanitized[key_text[:64]] = sanitize_safe_metadata_value(value)
                except TypeError as exc:
                    raise KnowledgeCollectionServiceError(
                        400,
                        "validation.failed",
                        "safe_metadata supports only primitive values and primitive lists.",
                        {"field": "safe_metadata"},
                    ) from exc
        if preserve_visibility in {"public", "private"}:
            sanitized["visibility"] = preserve_visibility
        return sanitized

    def _normalize_optional_text(self, value: str | None) -> str | None:
        return normalize_optional_text(value)

    def _normalize_required_text(self, value: str, field: str) -> str:
        normalized = normalize_required_text(value)
        if not normalized:
            raise KnowledgeCollectionServiceError(
                400,
                "validation.failed",
                "Required text field cannot be blank.",
                {"field": field},
            )
        return normalized

    def _would_revoke_current_user_last_manage_path(
        self,
        collection_id: uuid.UUID,
        subject_type: str,
        row: TeamKnowledgeCollectionPermission | UserKnowledgeCollectionPermission,
    ) -> bool:
        if self._is_org_manager() or row.permission_action != "manage":
            return False

        if subject_type == "user":
            if getattr(row, "user_id", None) != self.user_id:
                return False
        elif subject_type == "team":
            if getattr(row, "team_id", None) not in self._active_team_ids():
                return False
        else:
            return False

        # 본인의 마지막 manage 경로를 끊으면 이후 복구가 관리자 개입에 의존한다.
        return not self._has_alternate_collection_manage_path(
            collection_id,
            exclude_permission_id=row.id,
        )

    def _has_alternate_collection_manage_path(
        self,
        collection_id: uuid.UUID,
        *,
        exclude_permission_id: uuid.UUID,
    ) -> bool:
        direct_user_grant = (
            self.db.query(UserKnowledgeCollectionPermission.id)
            .filter(
                UserKnowledgeCollectionPermission.user_id == self.user_id,
                UserKnowledgeCollectionPermission.grantee_organization_id
                == self.organization_id,
                UserKnowledgeCollectionPermission.knowledge_collection_id
                == collection_id,
                UserKnowledgeCollectionPermission.permission_action == "manage",
                UserKnowledgeCollectionPermission.id != exclude_permission_id,
            )
            .first()
        )
        if direct_user_grant is not None:
            return True

        team_ids = self._active_team_ids()
        if not team_ids:
            return False
        return (
            self.db.query(TeamKnowledgeCollectionPermission.id)
            .filter(
                TeamKnowledgeCollectionPermission.grantee_organization_id
                == self.organization_id,
                TeamKnowledgeCollectionPermission.knowledge_collection_id
                == collection_id,
                TeamKnowledgeCollectionPermission.permission_action == "manage",
                TeamKnowledgeCollectionPermission.team_id.in_(team_ids),
                TeamKnowledgeCollectionPermission.id != exclude_permission_id,
            )
            .first()
            is not None
        )

    def _active_team_ids(self) -> set[uuid.UUID]:
        rows = (
            self.db.query(TeamMembership.team_id)
            .join(Team, Team.id == TeamMembership.team_id)
            .filter(
                TeamMembership.user_id == self.user_id,
                TeamMembership.grantee_organization_id == self.organization_id,
                Team.organization_id == self.organization_id,
                Team.is_active.is_(True),
            )
            .all()
        )
        return {row[0] for row in rows}

    def _record_collection_audit_and_commit(
        self,
        action: str,
        collection: KnowledgeCollection,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        try:
            self._record_collection_audit(
                action,
                collection,
                metadata=metadata,
            )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _record_collection_audit(
        self,
        action: str,
        collection: KnowledgeCollection,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        # Audit에는 raw source title/path/url이나 hidden count를 넣지 않는다.
        add_data_change_audit(
            self.db,
            action,
            self.user_id,
            "knowledge_collection",
            collection.id,
            organization_id=self.organization_id,
            metadata={
                "organization_id": str(self.organization_id),
                "visibility": self._visibility(collection),
                **(metadata or {}),
            },
        )

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)
