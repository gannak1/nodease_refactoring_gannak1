import uuid
from types import SimpleNamespace

from apps.gateway.services.knowledge_collection_picker_query_service import (
    MAX_LLM_SELECTABLE_COLLECTION_SCAN,
    KnowledgeCollectionPickerQueryService,
)


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self.limit_value = None

    def options(self, *_args):
        return self

    def filter(self, *criteria):
        self.filters.extend(criteria)
        return self

    def order_by(self, *_args):
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def all(self):
        return self.rows


class _Db:
    def __init__(self, rows):
        self.query_value = _Query(rows)

    def query(self, _model):
        return self.query_value


def _collection(*, organization_id, safe_metadata=None, source_identity=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=organization_id,
        lifecycle_state="active",
        name="RAW COLLECTION NAME",
        description="RAW DESCRIPTION",
        safe_metadata=safe_metadata or {},
        source_identity_id=(uuid.uuid4() if source_identity is not None else None),
        source_identity=source_identity,
    )


def test_picker_returns_only_route_allowed_minimal_projection(monkeypatch):
    organization_id = uuid.uuid4()
    allowed = _collection(
        organization_id=organization_id,
        safe_metadata={"safe_label": "사내 규정"},
    )
    denied = _collection(
        organization_id=organization_id,
        safe_metadata={"safe_label": "숨김 문서"},
    )
    db = _Db([allowed, denied])
    service = KnowledgeCollectionPickerQueryService(
        db,
        user_id=uuid.uuid4(),
        organization_id=organization_id,
    )
    monkeypatch.setattr(
        service.permission_helper,
        "bulk_evaluate_collection_action",
        lambda collections, action: {
            allowed.id: SimpleNamespace(allowed=True),
            denied.id: SimpleNamespace(allowed=False),
        },
    )

    response = service.list_llm_selectable()

    assert response.model_dump(mode="json") == {
        "collections": [{"id": str(allowed.id), "safe_label": "사내 규정"}]
    }
    assert db.query_value.limit_value == MAX_LLM_SELECTABLE_COLLECTION_SCAN
    assert len(db.query_value.filters) == 2
    assert "RAW COLLECTION NAME" not in response.model_dump_json()
    assert "RAW DESCRIPTION" not in response.model_dump_json()


def test_source_managed_label_requires_active_approved_display_policy(monkeypatch):
    organization_id = uuid.uuid4()
    approved = _collection(
        organization_id=organization_id,
        source_identity=SimpleNamespace(
            display_policy_state="approved",
            is_active=True,
            safe_display_name="공개 승인 라벨",
        ),
    )
    unapproved = _collection(
        organization_id=organization_id,
        source_identity=SimpleNamespace(
            display_policy_state="unreviewed",
            is_active=True,
            safe_display_name="노출 금지 라벨",
        ),
    )
    db = _Db([approved, unapproved])
    service = KnowledgeCollectionPickerQueryService(
        db,
        user_id=uuid.uuid4(),
        organization_id=organization_id,
    )
    monkeypatch.setattr(
        service.permission_helper,
        "bulk_evaluate_collection_action",
        lambda collections, action: {
            collection.id: SimpleNamespace(allowed=True)
            for collection in collections
        },
    )

    response = service.list_llm_selectable()

    assert [item.safe_label for item in response.collections] == [
        "공개 승인 라벨",
        None,
    ]
