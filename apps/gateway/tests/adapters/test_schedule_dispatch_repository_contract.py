from apps.gateway.adapters.db.schedule_dispatch_repository import (
    SqlAlchemyScheduleDispatchRepository,
)


def test_due_schedule_query_excludes_missing_organization_provenance():
    statement = SqlAlchemyScheduleDispatchRepository._active_schedule_statement()
    where_sql = " ".join(str(clause) for clause in statement._where_criteria)

    assert "organization_id IS NOT NULL" in where_sql
