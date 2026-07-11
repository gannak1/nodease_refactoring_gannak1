"""Add organization-scoped Mail credentials and permissions.

Revision ID: fc1d2e3f4a5b
Revises: ff5c6d7e8f90
Create Date: 2026-07-11 20:00:00.000000
"""

from typing import Sequence, Union

from apps.shared.db.models.mail_credential import MailCredential
from apps.shared.db.models.team import (
    TeamMailCredentialPermission,
    UserMailCredentialPermission,
)

from alembic import op

revision: str = "fc1d2e3f4a5b"
down_revision: Union[str, Sequence[str], None] = "ff5c6d7e8f90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    MailCredential.__table__.create(bind=bind, checkfirst=True)
    TeamMailCredentialPermission.__table__.create(bind=bind, checkfirst=True)
    UserMailCredentialPermission.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    UserMailCredentialPermission.__table__.drop(bind=bind, checkfirst=True)
    TeamMailCredentialPermission.__table__.drop(bind=bind, checkfirst=True)
    MailCredential.__table__.drop(bind=bind, checkfirst=True)
