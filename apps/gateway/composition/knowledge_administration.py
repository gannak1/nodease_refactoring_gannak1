from sqlalchemy.orm import Session

from apps.gateway.adapters.audit.knowledge_domain_permissions import (
    SqlAlchemyKnowledgeDomainPermissionAudit,
)
from apps.gateway.adapters.db.knowledge_domain_permissions import (
    SqlAlchemyKnowledgeDomainAuthorization,
    SqlAlchemyKnowledgeDomainPermissionRepository,
)
from apps.gateway.adapters.db.sqlalchemy_unit_of_work import SqlAlchemyUnitOfWork
from apps.gateway.application.knowledge_administration.domain_permissions import (
    KnowledgeDomainPermissionUseCase,
)


def build_knowledge_domain_permission_use_case(
    db: Session,
) -> KnowledgeDomainPermissionUseCase:
    return KnowledgeDomainPermissionUseCase(
        SqlAlchemyKnowledgeDomainAuthorization(db),
        SqlAlchemyKnowledgeDomainPermissionRepository(db),
        SqlAlchemyKnowledgeDomainPermissionAudit(db),
        SqlAlchemyUnitOfWork(db),
    )
