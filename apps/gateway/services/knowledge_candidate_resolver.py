import uuid
from collections.abc import Iterable

from sqlalchemy.orm import Session, joinedload

from apps.shared.db.models.knowledge import (
    KnowledgeBase,
    KnowledgeCollection,
    KnowledgeCollectionItem,
)
from apps.shared.schemas.knowledge import (
    KnowledgeCandidate,
    KnowledgeCandidateResolution,
    KnowledgePermissionDecision,
)
from apps.shared.services.knowledge_permission_service import KnowledgePermissionHelper


DEFAULT_MAX_COLLECTIONS = 20
DEFAULT_MAX_CANDIDATE_KBS = 5000


def bucket_count(value: int) -> str:
    if value <= 0:
        return "0"
    if value == 1:
        return "1"
    if value <= 10:
        return "2-10"
    if value <= 100:
        return "11-100"
    return "100+"


class KnowledgeCandidateResolver:
    """Builds safe Knowledge candidates for Builder/deployment preflight.

    The resolver never exposes denied resource identifiers. It consumes
    KnowledgePermissionHelper decisions and returns only allowed candidates plus
    bucketed summary counts.
    """

    def __init__(
        self,
        db: Session,
        *,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
        permission_helper: KnowledgePermissionHelper | None = None,
    ) -> None:
        self.db = db
        self.user_id = user_id
        self.organization_id = organization_id
        self.permission_helper = permission_helper or KnowledgePermissionHelper(
            db,
            user_id=user_id,
            organization_id=organization_id,
        )

    def resolve_explicit_kbs(
        self,
        knowledge_base_ids: Iterable[uuid.UUID],
    ) -> KnowledgeCandidateResolution:
        # Explicit KB mode는 collection route 권한을 요구하지 않는다.
        # 다만 KB use/source ACL/final evidence gate는 helper를 통해 그대로 적용한다.
        requested_ids = list(dict.fromkeys(knowledge_base_ids))
        kbs_by_id = self._knowledge_bases_by_id(requested_ids)

        hidden_count = len(requested_ids) - len(kbs_by_id)
        unavailable_count = 0
        candidates: list[KnowledgeCandidate] = []

        for kb_id in requested_ids:
            kb = kbs_by_id.get(kb_id)
            if kb is None:
                continue
            decision = self.permission_helper.evaluate_kb_use(kb)
            if decision.allowed:
                candidates.append(self._kb_candidate(kb, decision))
            elif decision.external_reason_code == "resource.hidden":
                hidden_count += 1
            else:
                unavailable_count += 1

        return KnowledgeCandidateResolution(
            candidates=candidates,
            hidden_candidate_count_bucket=bucket_count(hidden_count),
            unavailable_candidate_count_bucket=bucket_count(unavailable_count),
            reason_code=None if candidates else "resource.hidden",
        )

    def resolve_auto_collection_candidates(
        self,
        *,
        collection_ids: Iterable[uuid.UUID] | None = None,
        max_collections: int = DEFAULT_MAX_COLLECTIONS,
        max_candidate_kbs: int = DEFAULT_MAX_CANDIDATE_KBS,
    ) -> KnowledgeCandidateResolution:
        # Auto collection mode는 route-allowed collection scope 안에서만 KB 후보를 만든다.
        # 권한 없는 collection/KB는 식별자를 노출하지 않고 bucketed count로만 요약한다.
        requested_collection_ids = (
            self._dedupe_ids(collection_ids) if collection_ids is not None else None
        )
        collections = self._collections(requested_collection_ids, max_collections)
        route_decisions = self.permission_helper.bulk_evaluate_collection_action(
            collections,
            "route",
        )
        route_allowed_collection_ids = [
            collection.id
            for collection in collections
            if route_decisions[collection.id].allowed
        ]
        hidden_count = (
            len(requested_collection_ids or []) - len(collections)
            if requested_collection_ids is not None
            else 0
        )
        hidden_count += sum(
            1
            for collection in collections
            if route_decisions[collection.id].external_reason_code == "resource.hidden"
        )
        unavailable_count = sum(
            1
            for collection in collections
            if (
                not route_decisions[collection.id].allowed
                and route_decisions[collection.id].external_reason_code
                != "resource.hidden"
            )
        )

        items = self._collection_items(
            route_allowed_collection_ids,
            max_candidate_kbs,
        )
        kb_ids = self._dedupe_ids([item.knowledge_base_id for item in items])
        kbs_by_id = self._knowledge_bases_by_id(kb_ids)
        hidden_count += len(kb_ids) - len(kbs_by_id)

        candidates: list[KnowledgeCandidate] = []
        for kb_id in kb_ids:
            kb = kbs_by_id.get(kb_id)
            if kb is None:
                continue
            decision = self.permission_helper.evaluate_kb_use(kb)
            if decision.allowed:
                candidates.append(self._kb_candidate(kb, decision))
            elif decision.external_reason_code == "resource.hidden":
                hidden_count += 1
            else:
                unavailable_count += 1

        return KnowledgeCandidateResolution(
            candidates=candidates,
            hidden_candidate_count_bucket=bucket_count(hidden_count),
            unavailable_candidate_count_bucket=bucket_count(unavailable_count),
            reason_code=None if candidates else "resource.hidden",
        )

    def _collections(
        self,
        collection_ids: Iterable[uuid.UUID] | None,
        max_collections: int,
    ) -> list[KnowledgeCollection]:
        query = self.db.query(KnowledgeCollection).filter(
            KnowledgeCollection.organization_id == self.organization_id,
            KnowledgeCollection.lifecycle_state == "active",
        )
        if collection_ids is not None:
            requested_ids = self._dedupe_ids(collection_ids)
            if not requested_ids:
                return []
            query = query.filter(KnowledgeCollection.id.in_(requested_ids))
        return (
            query.order_by(KnowledgeCollection.name.asc(), KnowledgeCollection.id.asc())
            .limit(max_collections)
            .all()
        )

    def _collection_items(
        self,
        collection_ids: Iterable[uuid.UUID],
        max_candidate_kbs: int,
    ) -> list[KnowledgeCollectionItem]:
        collection_id_list = self._dedupe_ids(collection_ids)
        if not collection_id_list:
            return []
        return (
            self.db.query(KnowledgeCollectionItem)
            .filter(
                KnowledgeCollectionItem.organization_id == self.organization_id,
                KnowledgeCollectionItem.collection_id.in_(collection_id_list),
            )
            .order_by(
                KnowledgeCollectionItem.collection_id.asc(),
                KnowledgeCollectionItem.rank.asc(),
                KnowledgeCollectionItem.knowledge_base_id.asc(),
            )
            .limit(max_candidate_kbs)
            .all()
        )

    def _knowledge_bases_by_id(
        self,
        knowledge_base_ids: Iterable[uuid.UUID],
    ) -> dict[uuid.UUID, KnowledgeBase]:
        ids = self._dedupe_ids(knowledge_base_ids)
        if not ids:
            return {}
        rows = (
            self.db.query(KnowledgeBase)
            .options(joinedload(KnowledgeBase.source_identity))
            .filter(
                KnowledgeBase.id.in_(ids),
                KnowledgeBase.organization_id == self.organization_id,
                KnowledgeBase.lifecycle_state == "active",
            )
            .all()
        )
        return {row.id: row for row in rows}

    def _kb_candidate(
        self,
        kb: KnowledgeBase,
        permission: KnowledgePermissionDecision,
    ) -> KnowledgeCandidate:
        return KnowledgeCandidate(
            candidate_id=kb.id,
            candidate_type="knowledge_base",
            permission=permission,
            runtime_availability="available",
            safe_label=self._kb_safe_label(kb),
            safe_metadata=permission.safe_metadata,
        )

    def _kb_safe_label(self, kb: KnowledgeBase) -> str | None:
        source_identity = getattr(kb, "source_identity", None)
        if source_identity is None:
            return kb.name
        if getattr(source_identity, "display_policy_state", None) == "approved":
            return getattr(source_identity, "safe_display_name", None)
        return None

    def _dedupe_ids(self, values: Iterable[uuid.UUID]) -> list[uuid.UUID]:
        result: list[uuid.UUID] = []
        seen: set[uuid.UUID] = set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result
