"""Add persisted LLM node model routing policy lifecycle

Revision ID: fb8c9d0e1f23
Revises: fa7b8c9d0e12
Create Date: 2026-07-10 16:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

from apps.shared.db.models.model_routing_policy import (
    LLMNodeModelRoutingPolicy,
    LLMNodeModelRoutingPolicyRunEvent,
    LLMNodeModelRoutingPolicyUpdate,
)


revision: str = "fb8c9d0e1f23"
down_revision: Union[str, Sequence[str], None] = "fa7b8c9d0e12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 이전 개발 DB에는 테이블만 수동 생성되고 alembic revision은 기록되지 않은
    # 상태가 존재한다. checkfirst로 그 DB는 보존하고, 새 환경에는 model과 같은
    # schema를 생성한다.
    bind = op.get_bind()
    LLMNodeModelRoutingPolicy.__table__.create(bind=bind, checkfirst=True)
    LLMNodeModelRoutingPolicyUpdate.__table__.create(bind=bind, checkfirst=True)
    LLMNodeModelRoutingPolicyRunEvent.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    LLMNodeModelRoutingPolicyRunEvent.__table__.drop(bind=bind, checkfirst=True)
    LLMNodeModelRoutingPolicyUpdate.__table__.drop(bind=bind, checkfirst=True)
    LLMNodeModelRoutingPolicy.__table__.drop(bind=bind, checkfirst=True)
