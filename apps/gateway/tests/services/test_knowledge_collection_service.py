import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from apps.gateway.services.knowledge_collection_service import (
    KnowledgeCollectionService,
    KnowledgeCollectionServiceError,
)
from apps.shared.db.models.audit_log import AuditLog
from apps.shared.db.models.knowledge import KnowledgeCollection
from apps.shared.schemas.knowledge import (
    KnowledgeCollectionCreateRequest,
    KnowledgeCollectionItemLinkRequest,
    KnowledgeCollectionPermissionBundleGrantRequest,
    KnowledgeCollectionResponse,
    KnowledgeCollectionUpdateRequest,
    KnowledgeCollectionVisibilityRequest,
)


class _FakeDb:
    def __init__(self):
        self.committed = False
        self.refreshed = []
        self.added = []
        self.operations = []

    def add(self, value):
        self.added.append(value)
        self.operations.append(("add", type(value)))

    def commit(self):
        self.committed = True
        self.operations.append(("commit", None))

    def refresh(self, value):
        self.refreshed.append(value)


class _SubjectQuery:
    def __init__(self, rows):
        self.rows = rows

    def join(self, *_args, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return self.rows


class _SubjectDb:
    def __init__(self, teams, users):
        self.teams = teams
        self.users = users

    def query(self, model):
        return _SubjectQuery(self.teams if model.__name__ == "Team" else self.users)


def _service(monkeypatch, db=None):
    service = KnowledgeCollectionService(
        db or _FakeDb(),
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(service, "_record_collection_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_has_domain_action", lambda action: False)
    monkeypatch.setattr(
        service,
        "_collection_has_source_managed_items",
        lambda collection_id: False,
    )
    return service


def _collection(collection_id=None):
    return SimpleNamespace(
        id=collection_id or uuid.uuid4(),
        organization_id=uuid.uuid4(),
        name="HR",
        description=None,
        is_system_managed=False,
        sync_state="manual",
        lifecycle_state="active",
        safe_metadata={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def _collection_response(collection):
    return KnowledgeCollectionResponse(
        id=collection.id,
        organization_id=collection.organization_id,
        name=collection.name,
        visibility="public"
        if collection.safe_metadata.get("visibility") == "public"
        else "private",
        linked_kb_count_bucket="0",
        active_kb_count_bucket="0",
        created_at=collection.created_at,
        updated_at=collection.updated_at,
    )


def test_safe_metadata_rejects_raw_source_keys(monkeypatch):
    service = _service(monkeypatch)

    with pytest.raises(KnowledgeCollectionServiceError) as exc_info:
        service._sanitize_safe_metadata({"raw_source_url": "https://internal"})

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "validation.failed"


def test_create_collection_rejects_blank_name_after_normalization(monkeypatch):
    service = _service(monkeypatch)
    monkeypatch.setattr(service, "_require_org_manager_or_domain", lambda action: None)

    with pytest.raises(KnowledgeCollectionServiceError) as exc_info:
        service.create_collection(KnowledgeCollectionCreateRequest(name="   \t  "))

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "validation.failed"
    assert exc_info.value.details == {"field": "name"}


def test_delegated_collection_create_commits_collection_and_audit_together(monkeypatch):
    db = _FakeDb()
    service = KnowledgeCollectionService(
        db,
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(service, "_is_org_manager", lambda: False)
    monkeypatch.setattr(
        service,
        "_has_domain_action",
        lambda action: action == "catalog_manage",
    )
    monkeypatch.setattr(
        service,
        "_collection_response",
        lambda collection: SimpleNamespace(id=collection.id),
    )

    result = service.create_collection(KnowledgeCollectionCreateRequest(name="HR"))

    assert result.id is not None
    assert isinstance(db.added[0], KnowledgeCollection)
    assert isinstance(db.added[1], AuditLog)
    assert db.operations == [
        ("add", KnowledgeCollection),
        ("add", AuditLog),
        ("commit", None),
    ]
    assert db.added[0].safe_metadata == {}


def test_catalog_delegate_can_manage_private_membership_without_kb_content_grant(
    monkeypatch,
):
    service = _service(monkeypatch)
    collection = _collection()
    kb = SimpleNamespace(id=uuid.uuid4(), source_identity_id=None)
    monkeypatch.setattr(
        service,
        "_has_domain_action",
        lambda action: action == "catalog_manage",
    )
    monkeypatch.setattr(
        service,
        "_require_collection_action",
        lambda *_args, **_kwargs: pytest.fail("resource manage should not be required"),
    )
    monkeypatch.setattr(
        service,
        "_require_kb_manage",
        lambda *_args, **_kwargs: pytest.fail("KB content manage should not be required"),
    )

    service._require_collection_membership_mutation(collection, kb=kb)


def test_public_membership_requires_org_manager_ack_and_blocks_source_managed_link(
    monkeypatch,
):
    service = _service(monkeypatch)
    collection = _collection()
    collection.safe_metadata = {"visibility": "public"}
    source_kb = SimpleNamespace(id=uuid.uuid4(), source_identity_id=uuid.uuid4())
    monkeypatch.setattr(service, "_require_org_manager", lambda: None)

    with pytest.raises(KnowledgeCollectionServiceError) as missing_ack:
        service._require_collection_membership_mutation(
            collection,
            kb=source_kb,
            adds_public_exposure=True,
        )
    assert missing_ack.value.status_code == 400

    with pytest.raises(KnowledgeCollectionServiceError) as source_block:
        service._require_collection_membership_mutation(
            collection,
            kb=source_kb,
            acknowledged_public_runtime_exposure=True,
            adds_public_exposure=True,
        )
    assert source_block.value.status_code == 409
    assert source_block.value.details == {
        "policy_reason": "source_public_exposure_required"
    }


def test_collection_role_bundle_writes_explicit_actions_in_one_transaction(monkeypatch):
    db = _FakeDb()
    service = KnowledgeCollectionService(
        db,
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
    )
    collection = _collection()
    actions = []

    monkeypatch.setattr(service, "_collection_or_hidden", lambda _id: collection)
    monkeypatch.setattr(
        service,
        "_require_collection_permission_authority",
        lambda _collection: "resource_manager",
    )
    monkeypatch.setattr(
        service,
        "_block_collection_delegate_self_escalation",
        lambda *_args, **_kwargs: None,
    )

    def fake_grant(_collection, grant):
        actions.append(grant.permission_action)
        row = SimpleNamespace(id=uuid.uuid4())
        db.add(row)
        return row, True

    monkeypatch.setattr(service, "_grant_team_permission", fake_grant)
    monkeypatch.setattr(
        service,
        "_team_permission_response",
        lambda row: SimpleNamespace(permission_id=row.id),
    )

    result = service.grant_permission_bundle(
        collection.id,
        KnowledgeCollectionPermissionBundleGrantRequest(
            subject_type="team",
            subject_id=uuid.uuid4(),
            role_bundle="workflow_router",
        ),
    )

    assert actions == ["read", "route"]
    assert len(result) == 2
    assert sum(1 for operation in db.operations if operation == ("commit", None)) == 1
    assert isinstance(db.added[-1], AuditLog)
    assert db.operations[-1] == ("commit", None)


def test_domain_delegation_subjects_return_safe_team_and_user_labels(monkeypatch):
    db = _SubjectDb(
        teams=[SimpleNamespace(id=uuid.uuid4(), name="Knowledge Team")],
        users=[
            SimpleNamespace(
                id=uuid.uuid4(),
                name=None,
                email="raw-email-must-not-be-returned@example.com",
            )
        ],
    )
    service = KnowledgeCollectionService(
        db,
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(service, "_require_org_manager", lambda: None)

    result = service.list_domain_delegation_subjects()

    assert result.teams[0].subject_safe_label == "Knowledge Team"
    assert result.users[0].subject_safe_label == "User"
    assert "@" not in str(result.model_dump())


def test_update_collection_rejects_blank_name_after_normalization(monkeypatch):
    service = _service(monkeypatch)
    collection = _collection()
    monkeypatch.setattr(service, "_collection_or_hidden", lambda collection_id: collection)
    monkeypatch.setattr(service, "_require_collection_action", lambda collection, action: None)

    with pytest.raises(KnowledgeCollectionServiceError) as exc_info:
        service.update_collection(
            collection.id,
            KnowledgeCollectionUpdateRequest(name=" \n "),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "validation.failed"
    assert exc_info.value.details == {"field": "name"}


def test_team_manage_revoke_detects_current_users_last_management_path(monkeypatch):
    service = _service(monkeypatch)
    team_id = uuid.uuid4()
    row = SimpleNamespace(
        id=uuid.uuid4(),
        team_id=team_id,
        permission_action="manage",
    )
    monkeypatch.setattr(service, "_is_org_manager", lambda: False)
    monkeypatch.setattr(service, "_active_team_ids", lambda: {team_id})
    monkeypatch.setattr(
        service,
        "_has_alternate_collection_manage_path",
        lambda collection_id, *, exclude_permission_id: False,
    )

    assert (
        service._would_revoke_current_user_last_manage_path(
            uuid.uuid4(),
            "team",
            row,
        )
        is True
    )


def test_team_manage_revoke_allows_when_alternate_management_path_exists(monkeypatch):
    service = _service(monkeypatch)
    team_id = uuid.uuid4()
    row = SimpleNamespace(
        id=uuid.uuid4(),
        team_id=team_id,
        permission_action="manage",
    )
    monkeypatch.setattr(service, "_is_org_manager", lambda: False)
    monkeypatch.setattr(service, "_active_team_ids", lambda: {team_id})
    monkeypatch.setattr(
        service,
        "_has_alternate_collection_manage_path",
        lambda collection_id, *, exclude_permission_id: True,
    )

    assert (
        service._would_revoke_current_user_last_manage_path(
            uuid.uuid4(),
            "team",
            row,
        )
        is False
    )


def test_public_visibility_requires_acknowledgement(monkeypatch):
    service = _service(monkeypatch)
    collection = _collection()
    monkeypatch.setattr(service, "_collection_or_hidden", lambda collection_id: collection)
    monkeypatch.setattr(service, "_require_org_manager", lambda: None)

    with pytest.raises(KnowledgeCollectionServiceError) as exc_info:
        service.update_visibility(
            collection.id,
            KnowledgeCollectionVisibilityRequest(
                visibility="public",
                acknowledged_public_runtime_exposure=False,
            ),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.details == {"field": "acknowledged_public_runtime_exposure"}


def test_public_visibility_blocks_source_managed_items_without_approval_primitive(
    monkeypatch,
):
    service = _service(monkeypatch)
    collection = _collection()
    monkeypatch.setattr(service, "_collection_or_hidden", lambda collection_id: collection)
    monkeypatch.setattr(service, "_require_org_manager", lambda: None)
    monkeypatch.setattr(
        service,
        "_collection_has_source_managed_items",
        lambda collection_id: True,
    )

    with pytest.raises(KnowledgeCollectionServiceError) as exc_info:
        service.update_visibility(
            collection.id,
            KnowledgeCollectionVisibilityRequest(
                visibility="public",
                acknowledged_public_runtime_exposure=True,
            ),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "policy.blocked"
    assert exc_info.value.details == {
        "policy_reason": "source_public_exposure_required"
    }


def test_public_visibility_sets_only_candidate_flag(monkeypatch):
    db = _FakeDb()
    service = _service(monkeypatch, db=db)
    collection = _collection()
    monkeypatch.setattr(service, "_collection_or_hidden", lambda collection_id: collection)
    monkeypatch.setattr(service, "_require_org_manager", lambda: None)
    monkeypatch.setattr(service, "_collection_response", _collection_response)

    result = service.update_visibility(
        collection.id,
        KnowledgeCollectionVisibilityRequest(
            visibility="public",
            acknowledged_public_runtime_exposure=True,
        ),
    )

    assert db.committed is True
    assert collection.safe_metadata["visibility"] == "public"
    assert result.collection.visibility == "public"
    assert result.public_runtime_effect == "anonymous_public_only_candidate"


def test_link_item_requires_collection_manage_and_kb_manage(monkeypatch):
    service = _service(monkeypatch)
    collection = _collection()
    kb = SimpleNamespace(id=uuid.uuid4(), lifecycle_state="active")
    calls = []
    monkeypatch.setattr(service, "_collection_or_hidden", lambda collection_id: collection)
    monkeypatch.setattr(
        service,
        "_require_collection_action",
        lambda collection, action: calls.append((collection.id, action)),
    )
    monkeypatch.setattr(service, "_knowledge_base_or_hidden", lambda kb_id: kb)
    monkeypatch.setattr(service, "_kb_manage_allowed", lambda kb: False)

    with pytest.raises(KnowledgeCollectionServiceError) as exc_info:
        service.link_item(
            collection.id,
            KnowledgeCollectionItemLinkRequest(knowledge_base_id=kb.id),
        )

    assert calls == [(collection.id, "manage")]
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "permission.denied"


def test_link_candidates_apply_limit_after_manage_filter(monkeypatch):
    service = _service(monkeypatch)
    collection = _collection()
    denied_kbs = [
        SimpleNamespace(id=uuid.uuid4(), name=f"Hidden {index}", lifecycle_state="active")
        for index in range(100)
    ]
    allowed_kb = SimpleNamespace(id=uuid.uuid4(), name="Allowed", lifecycle_state="active")
    pages = [denied_kbs, [allowed_kb]]
    calls = []

    monkeypatch.setattr(service, "_collection_or_hidden", lambda collection_id: collection)
    monkeypatch.setattr(service, "_require_collection_action", lambda collection, action: None)
    monkeypatch.setattr(service, "_linked_kb_ids", lambda collection_id: set())
    monkeypatch.setattr(
        service,
        "_link_candidate_kb_page",
        lambda *, limit, offset: calls.append((limit, offset)) or pages.pop(0)
        if pages
        else [],
    )
    monkeypatch.setattr(service, "_kb_manage_allowed", lambda kb: kb.id == allowed_kb.id)

    candidates = service.list_link_candidates(collection.id, limit=1)

    assert [candidate.knowledge_base_id for candidate in candidates] == [allowed_kb.id]
    assert len(calls) == 2


def test_link_candidates_redacts_source_managed_kb_name_without_approved_display_policy(
    monkeypatch,
):
    service = _service(monkeypatch)
    collection = _collection()
    kb = SimpleNamespace(
        id=uuid.uuid4(),
        name="Internal HR Source Name",
        lifecycle_state="active",
        source_identity=SimpleNamespace(
            display_policy_state="unreviewed",
            safe_display_name="Reviewed HR Label",
        ),
    )

    monkeypatch.setattr(service, "_collection_or_hidden", lambda collection_id: collection)
    monkeypatch.setattr(service, "_require_collection_action", lambda collection, action: None)
    monkeypatch.setattr(service, "_linked_kb_ids", lambda collection_id: set())
    monkeypatch.setattr(service, "_link_candidate_kb_page", lambda *, limit, offset: [kb])
    monkeypatch.setattr(service, "_kb_manage_allowed", lambda kb: True)

    candidates = service.list_link_candidates(collection.id, limit=1)

    assert candidates[0].safe_label == "Knowledge Base"


def test_link_candidates_use_approved_source_safe_display_name(monkeypatch):
    service = _service(monkeypatch)
    collection = _collection()
    kb = SimpleNamespace(
        id=uuid.uuid4(),
        name="Internal HR Source Name",
        lifecycle_state="active",
        source_identity=SimpleNamespace(
            display_policy_state="approved",
            safe_display_name="Reviewed HR Label",
        ),
    )

    monkeypatch.setattr(service, "_collection_or_hidden", lambda collection_id: collection)
    monkeypatch.setattr(service, "_require_collection_action", lambda collection, action: None)
    monkeypatch.setattr(service, "_linked_kb_ids", lambda collection_id: set())
    monkeypatch.setattr(service, "_link_candidate_kb_page", lambda *, limit, offset: [kb])
    monkeypatch.setattr(service, "_kb_manage_allowed", lambda kb: True)

    candidates = service.list_link_candidates(collection.id, limit=1)

    assert candidates[0].safe_label == "Reviewed HR Label"
