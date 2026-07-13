from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from apps.shared.db.models.organization_membership import ORGANIZATION_AUTH_MEMBER
from apps.shared.permissions import AUTH_STATE_MANAGER, AUTH_STATE_OPERATOR
from apps.shared.services.knowledge_permission_service import KnowledgePermissionHelper

ORG_ID = UUID(int=100)
USER_ID = UUID(int=101)


def _collection(value: int):
    return SimpleNamespace(
        id=UUID(int=value),
        organization_id=ORG_ID,
        lifecycle_state="active",
        sync_state="manual",
        is_system_managed=False,
        safe_metadata={},
    )


def _source_kb():
    return SimpleNamespace(
        id=UUID(int=300),
        organization_id=ORG_ID,
        lifecycle_state="active",
        sync_state="synced",
        source_identity_id=UUID(int=301),
    )


def _provenance(*, action):
    return SimpleNamespace(
        source_acl_state="fresh",
        requester_source_authorization="allowed",
        freshness_epoch=7,
        freshness_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        source_permission_action=action,
    )


class _BulkCollectionHelper(KnowledgePermissionHelper):
    def __init__(self, *, auth_state=ORGANIZATION_AUTH_MEMBER):
        super().__init__(object(), user_id=USER_ID, organization_id=ORG_ID)
        self.auth_state = auth_state
        self.bulk_calls = []
        self.single_calls = []

    def _organization_auth_state(self):
        return self.auth_state

    def _bulk_collection_action_ids(self, collection_ids, action):
        self.bulk_calls.append((tuple(collection_ids), action))
        return {collection_ids[0]}

    def _collection_has_action(self, collection_id, action):
        self.single_calls.append((collection_id, action))
        raise AssertionError("bulk evaluation must not call the single-row path")


def test_bulk_collection_route_uses_one_bulk_permission_projection():
    collections = [_collection(1), _collection(2)]
    helper = _BulkCollectionHelper()

    decisions = helper.bulk_evaluate_collection_action(collections, "route")

    assert decisions[collections[0].id].allowed is True
    assert decisions[collections[1].id].allowed is False
    assert decisions[collections[1].id].external_reason_code == "permission.denied"
    assert helper.bulk_calls == [((collections[0].id, collections[1].id), "route")]
    assert helper.single_calls == []


def test_bulk_collection_manager_override_skips_permission_rows():
    collections = [_collection(1), _collection(2)]
    helper = _BulkCollectionHelper(auth_state=AUTH_STATE_MANAGER)

    decisions = helper.bulk_evaluate_collection_action(collections, "route")

    assert all(decision.allowed for decision in decisions.values())
    assert helper.bulk_calls == []
    assert helper.single_calls == []


def test_bulk_collection_invalid_action_is_fixed_safe_denial():
    collection = _collection(1)
    helper = _BulkCollectionHelper()

    decision = helper.bulk_evaluate_collection_action([collection], "content")[
        collection.id
    ]

    assert decision.allowed is False
    assert decision.reason_code == "permission.invalid_action"
    assert decision.external_reason_code == "resource.hidden"
    assert helper.bulk_calls == []


class _SourceActionHelper(KnowledgePermissionHelper):
    def __init__(self, provenance):
        super().__init__(None, user_id=USER_ID, organization_id=ORG_ID)
        self.provenance = provenance

    def _effective_kb_use_auth_state(self, kb):
        del kb
        return AUTH_STATE_OPERATOR

    def _latest_source_authorization(self, kb):
        del kb
        return self.provenance


@pytest.mark.parametrize("action", ["read", "view", "use", "retrieve", "search"])
def test_materialized_source_retrieval_action_is_compatible(action):
    decision = _SourceActionHelper(_provenance(action=action)).evaluate_kb_use(
        _source_kb()
    )

    assert decision.allowed is True
    assert decision.freshness_epoch == 7


@pytest.mark.parametrize("action", [None, "", "write", "admin", "delete", "unknown"])
def test_materialized_source_non_retrieval_action_fails_closed(action):
    decision = _SourceActionHelper(_provenance(action=action)).evaluate_kb_use(
        _source_kb()
    )

    assert decision.allowed is False
    assert decision.reason_code == "source_authorization.operation_unverified"
    assert decision.external_reason_code == "resource.hidden"
