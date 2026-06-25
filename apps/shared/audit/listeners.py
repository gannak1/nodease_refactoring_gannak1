"""
계층 B — 데이터 변경 이력 캡처 (SQLAlchemy ORM 이벤트)

추적 대상 모델의 INSERT/UPDATE/DELETE를 자동 감지해 before/after를 기록한다.
- before/after는 SQLAlchemy 네이티브 attribute history로 산출(컬럼별 old/new).
- 민감 필드는 값 대신 마스킹 토큰으로 저장한다.
- actor는 요청 컨텍스트(contextvar)에서 가져오며, 없으면 system으로 기록한다.

발행 자체가 본 트랜잭션을 막지 않도록, 캡처는 before_flush(변경값 확정 시점),
발행은 after_flush(INSERT PK 확정 시점)에서 수행하고 전 구간을 try/except로 감싼다.
"""

import logging

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from apps.shared.audit.context import get_current_actor
from apps.shared.audit.logger import record_audit
from apps.shared.db.models.app import App
from apps.shared.db.models.connection import Connection
from apps.shared.db.models.knowledge import KnowledgeBase
from apps.shared.db.models.llm import LLMCredential
from apps.shared.db.models.user import User

logger = logging.getLogger(__name__)

_MASK = "***changed***"

# 추적 대상 모델 → 감사 로그의 target_type
TRACKED_MODELS = {
    App: "app",
    Connection: "connection",
    LLMCredential: "credential",
    KnowledgeBase: "knowledge",
    User: "user",
}

# 모델별 민감 필드(평문 저장 금지)
SENSITIVE_FIELDS = {
    App: {"auth_secret"},
    Connection: {
        "encrypted_password",
        "encrypted_ssh_password",
        "encrypted_ssh_private_key",
    },
    LLMCredential: {"encrypted_config"},
    User: {"password"},
    KnowledgeBase: set(),
}

def _mask(model_cls, key, value):
    if key in SENSITIVE_FIELDS.get(model_cls, set()):
        return _MASK
    return value


def _all_columns(obj, model_cls):
    """모든 컬럼 값을 dict로 반환(민감 필드 마스킹)."""
    result = {}
    for attr in inspect(obj).mapper.column_attrs:
        key = attr.key
        result[key] = _mask(model_cls, key, getattr(obj, key, None))
    return result


def _changed_columns(obj, model_cls):
    """변경된 컬럼만 before/after dict로 반환(민감 필드 마스킹)."""
    before, after = {}, {}
    state = inspect(obj)
    for attr in state.mapper.column_attrs:
        key = attr.key
        hist = state.attrs[key].history
        if not hist.has_changes():
            continue
        old = hist.deleted[0] if hist.deleted else None
        new = hist.added[0] if hist.added else None
        before[key] = _mask(model_cls, key, old)
        after[key] = _mask(model_cls, key, new)
    return before, after


def _model_of(obj):
    for model_cls in TRACKED_MODELS:
        if isinstance(obj, model_cls):
            return model_cls
    return None


def _before_flush(session, flush_context, instances):
    """변경값을 캡처해 세션에 임시 보관(발행은 after_flush에서)."""
    try:
        pending = session.info.setdefault("_audit_pending", [])

        for obj in session.new:
            model_cls = _model_of(obj)
            if model_cls is None:
                continue
            pending.append(
                (obj, model_cls, "created", None, _all_columns(obj, model_cls))
            )

        for obj in session.dirty:
            model_cls = _model_of(obj)
            if model_cls is None:
                continue
            before, after = _changed_columns(obj, model_cls)
            if not before and not after:
                continue  # 컬럼 변경 없음(관계만 dirty)
            pending.append((obj, model_cls, "updated", before, after))

        for obj in session.deleted:
            model_cls = _model_of(obj)
            if model_cls is None:
                continue
            pending.append(
                (obj, model_cls, "deleted", _all_columns(obj, model_cls), None)
            )
    except Exception as e:  # noqa: BLE001 - 감사 캡처가 flush를 막지 않는다
        logger.error(f"[Audit] before_flush 캡처 실패: {e}")


def _after_flush(session, flush_context):
    """PK 확정 후 감사 이벤트를 발행하고 임시 보관분을 비운다."""
    pending = session.info.pop("_audit_pending", None)
    if not pending:
        return

    actor = get_current_actor()
    if actor is not None:
        actor_id, actor_type, snapshot = actor.actor_id, actor.actor_type, actor.snapshot
    else:
        actor_id, actor_type, snapshot = None, "system", {}

    for obj, model_cls, op, before, after in pending:
        try:
            target_type = TRACKED_MODELS[model_cls]
            target_id = getattr(obj, "id", None)
            metadata = {"actor": snapshot} if snapshot else {}
            record_audit(
                action=f"{target_type}.{op}",
                category="data_change",
                actor_id=actor_id,
                actor_type=actor_type,
                target_type=target_type,
                target_id=target_id,
                before=before,
                after=after,
                metadata=metadata,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"[Audit] after_flush 발행 실패: {e}")


_registered = False


def register_audit_listeners():
    """ORM 이벤트 리스너를 1회 등록한다(앱/워커 부팅 시 호출)."""
    global _registered
    if _registered:
        return
    from sqlalchemy import event

    event.listen(Session, "before_flush", _before_flush)
    event.listen(Session, "after_flush", _after_flush)
    _registered = True
    logger.info("[Audit] ORM 변경 이력 리스너 등록 완료")
