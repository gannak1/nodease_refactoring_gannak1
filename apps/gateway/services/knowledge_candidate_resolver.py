import uuid
from collections import Counter
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
        runtime_permission_helper: KnowledgePermissionHelper | None = None,
    ) -> None:
        self.db = db
        self.user_id = user_id
        self.organization_id = organization_id
        self.permission_helper = permission_helper or KnowledgePermissionHelper(
            db,
            user_id=user_id,
            organization_id=organization_id,
        )
        self.runtime_permission_helper = runtime_permission_helper

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
        allowed_pairs: list[tuple[KnowledgeBase, KnowledgePermissionDecision]] = []

        kb_decisions = self.permission_helper.bulk_evaluate_kb_use(kbs_by_id.values())
        for kb_id in requested_ids:
            kb = kbs_by_id.get(kb_id)
            if kb is None:
                continue
            decision = kb_decisions[kb.id]
            if decision.allowed:
                allowed_pairs.append((kb, decision))
            elif decision.external_reason_code == "resource.hidden":
                hidden_count += 1
            else:
                unavailable_count += 1
        runtime_decisions = self._bulk_runtime_kb_decisions(
            [kb for kb, _decision in allowed_pairs]
        )
        candidates = [
            self._kb_candidate(
                kb,
                decision,
                runtime_decision=runtime_decisions.get(kb.id),
            )
            for kb, decision in allowed_pairs
        ]

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
        collections = self._collections(requested_collection_ids, None)
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

        route_allowed_collection_ids = route_allowed_collection_ids[:max_collections]

        items = self._collection_items(route_allowed_collection_ids, None)
        route_allowed_collection_id_set = set(route_allowed_collection_ids)
        collections_by_id = {
            collection.id: collection
            for collection in collections
            if collection.id in route_allowed_collection_id_set
        }
        kb_ids = self._dedupe_ids([item.knowledge_base_id for item in items])
        kbs_by_id = self._knowledge_bases_by_id(kb_ids)
        hidden_count += len(kb_ids) - len(kbs_by_id)

        candidates: list[KnowledgeCandidate] = []
        allowed_pairs: list[tuple[KnowledgeBase, KnowledgePermissionDecision]] = []
        kb_decisions = self.permission_helper.bulk_evaluate_kb_use(kbs_by_id.values())
        for kb_id in kb_ids:
            kb = kbs_by_id.get(kb_id)
            if kb is None:
                continue
            decision = kb_decisions[kb.id]
            if decision.allowed:
                allowed_pairs.append((kb, decision))
            elif decision.external_reason_code == "resource.hidden":
                hidden_count += 1
            else:
                unavailable_count += 1
        allowed_pairs = allowed_pairs[:max_candidate_kbs]
        collection_context_by_kb_id = self._collection_context_by_kb_id(
            items,
            collections_by_id,
            allowed_kb_ids={kb.id for kb, _decision in allowed_pairs},
        )
        runtime_decisions = self._bulk_runtime_kb_decisions(
            [kb for kb, _decision in allowed_pairs]
        )
        candidates = [
            self._kb_candidate(
                kb,
                decision,
                runtime_decision=runtime_decisions.get(kb.id),
                extra_safe_metadata=collection_context_by_kb_id.get(kb.id),
            )
            for kb, decision in allowed_pairs
        ]

        return KnowledgeCandidateResolution(
            candidates=candidates,
            hidden_candidate_count_bucket=bucket_count(hidden_count),
            unavailable_candidate_count_bucket=bucket_count(unavailable_count),
            reason_code=None if candidates else "resource.hidden",
        )

    def _collections(
        self,
        collection_ids: Iterable[uuid.UUID] | None,
        max_collections: int | None,
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
        query = query.order_by(
            KnowledgeCollection.name.asc(),
            KnowledgeCollection.id.asc(),
        )
        if max_collections is not None:
            query = query.limit(max_collections)
        return query.all()

    def _collection_items(
        self,
        collection_ids: Iterable[uuid.UUID],
        max_candidate_kbs: int | None,
    ) -> list[KnowledgeCollectionItem]:
        collection_id_list = self._dedupe_ids(collection_ids)
        if not collection_id_list:
            return []
        query = (
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
        )
        if max_candidate_kbs is not None:
            query = query.limit(max_candidate_kbs)
        return query.all()

    def _knowledge_bases_by_id(
        self,
        knowledge_base_ids: Iterable[uuid.UUID],
    ) -> dict[uuid.UUID, KnowledgeBase]:
        ids = self._dedupe_ids(knowledge_base_ids)
        if not ids:
            return {}
        rows = (
            self.db.query(KnowledgeBase)
            .options(
                joinedload(KnowledgeBase.source_identity),
                joinedload(KnowledgeBase.active_document_version),
            )
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
        *,
        runtime_decision: KnowledgePermissionDecision | None = None,
        extra_safe_metadata: dict | None = None,
    ) -> KnowledgeCandidate:
        runtime_availability = "unknown"
        runtime_reason_code = None
        if self.runtime_permission_helper is not None or runtime_decision is not None:
            runtime_decision = runtime_decision or (
                self.runtime_permission_helper.evaluate_kb_use(kb)
            )
            if runtime_decision.allowed:
                runtime_availability = "available"
            else:
                runtime_availability = "unavailable"
                runtime_reason_code = runtime_decision.external_reason_code

        safe_metadata = dict(permission.safe_metadata)
        safe_metadata.update(self._active_version_safe_metadata(kb))
        if extra_safe_metadata:
            safe_metadata.update(extra_safe_metadata)
        if runtime_reason_code:
            safe_metadata["runtime_reason_code"] = runtime_reason_code

        return KnowledgeCandidate(
            candidate_id=kb.id,
            candidate_type="knowledge_base",
            permission=permission,
            runtime_availability=runtime_availability,
            safe_label=self._kb_safe_label(kb),
            safe_metadata=safe_metadata,
        )

    def _bulk_runtime_kb_decisions(
        self,
        kbs: list[KnowledgeBase],
    ) -> dict[uuid.UUID, KnowledgePermissionDecision]:
        if self.runtime_permission_helper is None or not kbs:
            return {}
        return self.runtime_permission_helper.bulk_evaluate_kb_use(kbs)

    def _kb_safe_label(self, kb: KnowledgeBase) -> str | None:
        source_identity = getattr(kb, "source_identity", None)
        if source_identity is None:
            return kb.name
        if getattr(source_identity, "display_policy_state", None) == "approved":
            return getattr(source_identity, "safe_display_name", None)
        return None

    def _active_version_safe_metadata(self, kb: KnowledgeBase) -> dict:
        # Source tier는 권한이 통과된 KB의 active ready version에서만 safe ranking hint로 전달한다.
        # Adapter가 DocumentVersion을 직접 조회하지 않게 하여 permission/candidate 경계를 유지한다.
        version = getattr(kb, "active_document_version", None)
        if version is None or getattr(version, "status", None) != "ready":
            return {}
        source_tier = getattr(version, "source_tier", None)
        if not isinstance(source_tier, str) or not source_tier.strip():
            return {}
        return {"source_tier": source_tier.strip()}

    def _collection_context_by_kb_id(
        self,
        items: list[KnowledgeCollectionItem],
        collections_by_id: dict[uuid.UUID, KnowledgeCollection],
        *,
        allowed_kb_ids: set[uuid.UUID],
    ) -> dict[uuid.UUID, dict]:
        allowed_items = [
            item for item in items if item.knowledge_base_id in allowed_kb_ids
        ]
        linked_count_by_collection_id = Counter(
            item.collection_id for item in allowed_items
        )
        context_by_kb_id: dict[uuid.UUID, dict] = {}
        for item in allowed_items:
            if item.knowledge_base_id in context_by_kb_id:
                continue
            collection = collections_by_id.get(item.collection_id)
            if collection is None:
                continue
            metadata = {
                "collection_id": str(collection.id),
                "route_scope_type": "auto_collection",
                "linked_kb_count_bucket": bucket_count(
                    linked_count_by_collection_id[collection.id]
                ),
            }
            safe_label = self._collection_safe_label(collection)
            if safe_label:
                metadata["collection_safe_label"] = safe_label
            context_by_kb_id[item.knowledge_base_id] = metadata
        return context_by_kb_id

    def _collection_safe_label(self, collection: KnowledgeCollection) -> str | None:
        # Collection 이름은 source-derived metadata일 수 있으므로 raw name을 fallback으로 쓰지 않는다.
        # 승인된 safe_metadata label만 Builder recommendation summary에 전달한다.
        metadata = getattr(collection, "safe_metadata", None) or {}
        for key in ("collection_safe_label", "safe_label", "safe_display_name"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
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
