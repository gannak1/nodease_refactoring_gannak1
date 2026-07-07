import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from apps.gateway.services.knowledge_collection_service import (
    KnowledgeCollectionService,
    KnowledgeCollectionServiceError,
)
from apps.shared.schemas.knowledge import (
    KnowledgeCollectionCreateRequest,
    KnowledgeCollectionItemLinkRequest,
    KnowledgeCollectionResponse,
    KnowledgeCollectionUpdateRequest,
    KnowledgeCollectionVisibilityRequest,
)


class _FakeDb:
    def __init__(self):
        self.committed = False
        self.refreshed = []

    def commit(self):
        self.committed = True

    def refresh(self, value):
        self.refreshed.append(value)


def _service(monkeypatch, db=None):
    service = KnowledgeCollectionService(
        db or _FakeDb(),
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(service, "_record_collection_audit", lambda *args, **kwargs: None)
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
    monkeypatch.setattr(service, "_require_org_manager", lambda: None)

    with pytest.raises(KnowledgeCollectionServiceError) as exc_info:
        service.create_collection(KnowledgeCollectionCreateRequest(name="   \t  "))

    assert exc_info.value.status_code == 400
    assert exc_info.value.code == "validation.failed"
    assert exc_info.value.details == {"field": "name"}


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
