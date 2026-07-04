import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from apps.gateway.services.knowledge_candidate_resolver import (
    KnowledgeCandidateResolver,
    bucket_count,
)
from apps.shared.schemas.knowledge import KnowledgeCandidateResolveRequest
from apps.shared.db.models.organization_membership import ORGANIZATION_AUTH_MEMBER
from apps.shared.permissions import AUTH_STATE_OPERATOR
from apps.shared.services.knowledge_permission_service import KnowledgePermissionHelper


ORG_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
USER_ID = uuid.UUID("20000000-0000-0000-0000-000000000001")


def _collection(collection_id: uuid.UUID | None = None, *, actions=None):
    return SimpleNamespace(
        id=collection_id or uuid.uuid4(),
        organization_id=ORG_ID,
        lifecycle_state="active",
        sync_state="synced",
        is_system_managed=False,
        safe_metadata={},
        _actions=set(actions or []),
    )


def _kb(kb_id: uuid.UUID | None = None, *, source_managed=False):
    return SimpleNamespace(
        id=kb_id or uuid.uuid4(),
        organization_id=ORG_ID,
        name="Manual KB",
        lifecycle_state="active",
        sync_state="synced",
        source_identity_id=uuid.uuid4() if source_managed else None,
        source_identity=None,
    )


def _source_identity():
    return SimpleNamespace(
        display_policy_state="pending",
        safe_display_name="Safe approved label",
        raw_source_url="https://internal.example/private",
        raw_source_path="/sensitive/path",
        raw_source_title="Sensitive title",
    )


def _source_provenance(
    *,
    source_acl_state="fresh",
    requester_source_authorization="allowed",
    freshness_epoch=1,
    expires_at=None,
):
    return SimpleNamespace(
        source_acl_state=source_acl_state,
        requester_source_authorization=requester_source_authorization,
        freshness_epoch=freshness_epoch,
        freshness_expires_at=expires_at
        if expires_at is not None
        else datetime.now(timezone.utc) + timedelta(hours=1),
    )


class FakePermissionHelper(KnowledgePermissionHelper):
    def __init__(
        self,
        *,
        collection_actions=None,
        kb_auth_state=AUTH_STATE_OPERATOR,
        source_policy_auth_state="none",
        source_provenance=None,
    ):
        super().__init__(None, user_id=USER_ID, organization_id=ORG_ID)
        self.collection_actions = collection_actions or {}
        self.kb_auth_state = kb_auth_state
        self.source_policy_auth_state = source_policy_auth_state
        self.source_provenance = source_provenance
        self.collection_action_calls = []
        self.bulk_kb_calls = []

    def _organization_auth_state(self):
        return ORGANIZATION_AUTH_MEMBER

    def _collection_has_action(self, collection_id, action):
        self.collection_action_calls.append((collection_id, action))
        return action in self.collection_actions.get(collection_id, set())

    def _manual_kb_auth_state(self, kb):
        return self.kb_auth_state

    def _source_policy_kb_use_auth_state(self, kb):
        return self.source_policy_auth_state

    def _latest_source_authorization(self, kb):
        return self.source_provenance

    def _now(self):
        return datetime(2026, 7, 4, tzinfo=timezone.utc)

    def _prepare_bulk_kb_context(self, kbs):
        return None

    def bulk_evaluate_kb_use(self, kbs):
        kb_list = list(kbs)
        self.bulk_kb_calls.append([kb.id for kb in kb_list])
        return super().bulk_evaluate_kb_use(kb_list)


class FakeResolver(KnowledgeCandidateResolver):
    def __init__(
        self,
        *,
        helper,
        runtime_helper=None,
        collections=None,
        items=None,
        kbs=None,
    ):
        super().__init__(
            None,
            user_id=USER_ID,
            organization_id=ORG_ID,
            permission_helper=helper,
            runtime_permission_helper=runtime_helper,
        )
        self._fake_collections = list(collections or [])
        self._fake_items = list(items or [])
        self._fake_kbs = {kb.id: kb for kb in (kbs or [])}
        self.requested_item_collection_ids = None

    def _collections(self, collection_ids, max_collections):
        if collection_ids is None:
            return self._fake_collections[:max_collections]
        requested = set(collection_ids)
        return [
            collection
            for collection in self._fake_collections
            if collection.id in requested
        ][:max_collections]

    def _collection_items(self, collection_ids, max_candidate_kbs):
        allowed_collection_ids = set(collection_ids)
        self.requested_item_collection_ids = allowed_collection_ids
        return [
            item
            for item in self._fake_items
            if item.collection_id in allowed_collection_ids
        ][:max_candidate_kbs]

    def _knowledge_bases_by_id(self, knowledge_base_ids):
        return {
            kb_id: self._fake_kbs[kb_id]
            for kb_id in knowledge_base_ids
            if kb_id in self._fake_kbs
        }


def test_collection_read_does_not_allow_route():
    collection = _collection(actions={"read"})
    helper = FakePermissionHelper(
        collection_actions={collection.id: {"read"}},
    )

    read_decision = helper.evaluate_collection_action(collection, "read")
    route_decision = helper.evaluate_collection_action(collection, "route")

    assert read_decision.allowed is True
    assert route_decision.allowed is False
    assert route_decision.reason_code == "collection_route_denied"
    assert route_decision.external_reason_code == "permission.denied"


def test_explicit_kb_mode_does_not_require_collection_route():
    kb = _kb()
    helper = FakePermissionHelper()
    resolver = FakeResolver(helper=helper, kbs=[kb])

    result = resolver.resolve_explicit_kbs([kb.id])

    assert [candidate.candidate_id for candidate in result.candidates] == [kb.id]
    assert helper.collection_action_calls == []
    assert helper.bulk_kb_calls == [[kb.id]]
    assert result.hidden_candidate_count_bucket == "0"


def test_auto_collection_mode_uses_only_route_allowed_collections():
    allowed_collection = _collection()
    denied_collection = _collection()
    allowed_kb = _kb()
    denied_kb = _kb()
    helper = FakePermissionHelper(
        collection_actions={allowed_collection.id: {"route"}},
    )
    items = [
        SimpleNamespace(
            collection_id=allowed_collection.id,
            knowledge_base_id=allowed_kb.id,
        ),
        SimpleNamespace(
            collection_id=denied_collection.id,
            knowledge_base_id=denied_kb.id,
        ),
    ]
    resolver = FakeResolver(
        helper=helper,
        collections=[allowed_collection, denied_collection],
        items=items,
        kbs=[allowed_kb, denied_kb],
    )

    result = resolver.resolve_auto_collection_candidates()

    assert [candidate.candidate_id for candidate in result.candidates] == [
        allowed_kb.id
    ]
    assert resolver.requested_item_collection_ids == {allowed_collection.id}
    assert result.unavailable_candidate_count_bucket == "1"


def test_auto_collection_mode_buckets_missing_requested_collection():
    existing_collection = _collection()
    kb = _kb()
    helper = FakePermissionHelper(
        collection_actions={existing_collection.id: {"route"}},
    )
    resolver = FakeResolver(
        helper=helper,
        collections=[existing_collection],
        items=[
            SimpleNamespace(
                collection_id=existing_collection.id,
                knowledge_base_id=kb.id,
            )
        ],
        kbs=[kb],
    )

    result = resolver.resolve_auto_collection_candidates(
        collection_ids=[existing_collection.id, uuid.uuid4()]
    )

    assert [candidate.candidate_id for candidate in result.candidates] == [kb.id]
    assert result.hidden_candidate_count_bucket == "1"


def test_auto_collection_candidate_cap_is_deterministic():
    collection = _collection()
    kbs = [_kb() for _ in range(3)]
    helper = FakePermissionHelper(collection_actions={collection.id: {"route"}})
    resolver = FakeResolver(
        helper=helper,
        collections=[collection],
        items=[
            SimpleNamespace(
                collection_id=collection.id,
                knowledge_base_id=kb.id,
            )
            for kb in kbs
        ],
        kbs=kbs,
    )

    result = resolver.resolve_auto_collection_candidates(max_candidate_kbs=2)

    assert [candidate.candidate_id for candidate in result.candidates] == [
        kbs[0].id,
        kbs[1].id,
    ]
    assert result.hidden_candidate_count_bucket == "0"
    assert result.unavailable_candidate_count_bucket == "0"


def test_kb_use_source_acl_stale_fails_closed_after_kb_use_grant():
    kb = _kb(source_managed=True)
    helper = FakePermissionHelper(
        kb_auth_state=AUTH_STATE_OPERATOR,
        source_provenance=_source_provenance(
            source_acl_state="fresh",
            requester_source_authorization="allowed",
            expires_at=datetime(2026, 7, 3, tzinfo=timezone.utc),
        ),
    )

    decision = helper.evaluate_kb_use(kb)

    assert decision.allowed is False
    assert decision.source_acl_state == "stale"
    assert decision.requester_source_authorization == "allowed"
    assert decision.reason_code == "source_acl.stale"
    assert decision.external_reason_code == "resource.hidden"
    assert "knowledge_base_id" not in decision.safe_metadata


def test_requester_source_authorization_denied_is_separate_from_acl_state():
    kb = _kb(source_managed=True)
    helper = FakePermissionHelper(
        kb_auth_state=AUTH_STATE_OPERATOR,
        source_provenance=_source_provenance(
            source_acl_state="fresh",
            requester_source_authorization="denied",
            freshness_epoch=7,
        ),
    )

    decision = helper.evaluate_kb_use(kb)

    assert decision.allowed is False
    assert decision.source_acl_state == "fresh"
    assert decision.requester_source_authorization == "denied"
    assert decision.freshness_epoch == 7
    assert decision.reason_code == "source_authorization.denied"
    assert decision.external_reason_code == "resource.hidden"
    assert "knowledge_base_id" not in decision.safe_metadata


def test_source_policy_grant_does_not_bypass_source_acl_gate():
    kb = _kb(source_managed=True)
    helper = FakePermissionHelper(
        kb_auth_state="none",
        source_policy_auth_state=AUTH_STATE_OPERATOR,
        source_provenance=_source_provenance(
            source_acl_state="revoked",
            requester_source_authorization="allowed",
        ),
    )

    decision = helper.evaluate_kb_use(kb)

    assert decision.allowed is False
    assert decision.effective_auth_state == AUTH_STATE_OPERATOR
    assert decision.source_acl_state == "revoked"
    assert decision.external_reason_code == "resource.hidden"


def test_bucket_count_uses_safe_ranges():
    assert bucket_count(0) == "0"
    assert bucket_count(1) == "1"
    assert bucket_count(5) == "2-10"
    assert bucket_count(50) == "11-100"
    assert bucket_count(500) == "100+"


def test_candidate_resolution_request_caps_builder_fanout():
    request = KnowledgeCandidateResolveRequest(
        mode="auto_collection",
        max_collections=100,
        max_candidate_kbs=5000,
    )

    assert request.max_collections == 100
    assert request.max_candidate_kbs == 5000

    try:
        KnowledgeCandidateResolveRequest(
            mode="auto_collection",
            max_collections=101,
        )
    except ValueError as exc:
        assert "max_collections" in str(exc)
    else:  # pragma: no cover - pydantic must reject over-cap values
        raise AssertionError("max_collections cap was not enforced")


def test_builder_candidate_hides_unapproved_source_display_metadata():
    kb = _kb(source_managed=True)
    kb.source_identity = _source_identity()
    helper = FakePermissionHelper(
        kb_auth_state=AUTH_STATE_OPERATOR,
        source_provenance=_source_provenance(),
    )
    resolver = FakeResolver(helper=helper, kbs=[kb])

    result = resolver.resolve_explicit_kbs([kb.id])

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.safe_label is None
    assert "raw_source_url" not in candidate.safe_metadata
    assert "raw_source_path" not in candidate.safe_metadata
    assert "raw_source_title" not in candidate.safe_metadata


def test_builder_candidate_uses_approved_safe_display_label_only():
    kb = _kb(source_managed=True)
    kb.source_identity = _source_identity()
    kb.source_identity.display_policy_state = "approved"
    helper = FakePermissionHelper(
        kb_auth_state=AUTH_STATE_OPERATOR,
        source_provenance=_source_provenance(),
    )
    resolver = FakeResolver(helper=helper, kbs=[kb])

    result = resolver.resolve_explicit_kbs([kb.id])

    assert len(result.candidates) == 1
    assert result.candidates[0].safe_label == "Safe approved label"


def test_builder_candidate_runtime_availability_unknown_without_intended_subject():
    kb = _kb()
    actor_helper = FakePermissionHelper(kb_auth_state=AUTH_STATE_OPERATOR)
    resolver = FakeResolver(helper=actor_helper, kbs=[kb])

    result = resolver.resolve_explicit_kbs([kb.id])

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.runtime_availability == "unknown"
    assert "runtime_reason_code" not in candidate.safe_metadata


def test_builder_candidate_marks_runtime_unavailable_for_intended_subject():
    kb = _kb()
    actor_helper = FakePermissionHelper(kb_auth_state=AUTH_STATE_OPERATOR)
    runtime_helper = FakePermissionHelper(kb_auth_state="none")
    resolver = FakeResolver(helper=actor_helper, runtime_helper=runtime_helper, kbs=[kb])

    result = resolver.resolve_explicit_kbs([kb.id])

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.runtime_availability == "unavailable"
    assert candidate.safe_metadata["runtime_reason_code"] == "permission.denied"
    assert "knowledge_base_id" in candidate.permission.safe_metadata
    assert runtime_helper.bulk_kb_calls == [[kb.id]]


def test_bulk_kb_use_uses_prefetched_context_and_restores_it():
    kb = _kb(source_managed=True)
    provenance = _source_provenance(freshness_epoch=13)

    class BulkContextHelper(KnowledgePermissionHelper):
        def __init__(self):
            super().__init__(None, user_id=USER_ID, organization_id=ORG_ID)
            self.prepare_calls = 0

        def _organization_auth_state(self):
            return ORGANIZATION_AUTH_MEMBER

        def _prepare_bulk_kb_context(self, kbs):
            self.prepare_calls += 1
            self._bulk_manual_auth_state_by_kb_id = {
                item.id: AUTH_STATE_OPERATOR for item in kbs
            }
            self._bulk_source_policy_allowed_kb_ids = set()
            self._bulk_source_authorization_by_key = {
                (item.id, item.source_identity_id): provenance for item in kbs
            }

        def _now(self):
            return datetime(2026, 7, 4, tzinfo=timezone.utc)

    helper = BulkContextHelper()

    decisions = helper.bulk_evaluate_kb_use([kb])

    assert helper.prepare_calls == 1
    assert decisions[kb.id].allowed is True
    assert decisions[kb.id].source_acl_state == "fresh"
    assert decisions[kb.id].freshness_epoch == 13
    assert helper._bulk_manual_auth_state_by_kb_id is None
    assert helper._bulk_source_policy_allowed_kb_ids is None
    assert helper._bulk_source_authorization_by_key is None
