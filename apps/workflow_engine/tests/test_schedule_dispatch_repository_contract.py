import inspect

from apps.workflow_engine.adapters.schedule_dispatch_repository import (
    SqlAlchemyScheduleAdmissionRepository,
)


def test_admission_repository_declares_canonical_lock_order():
    source = inspect.getsource(
        SqlAlchemyScheduleAdmissionRepository.lock_canonical_bundle
    )

    app_lock = source.index("select(App)")
    deployment_lock = source.index("select(WorkflowDeployment)", app_lock)
    schedule_lock = source.index("select(Schedule)", deployment_lock)
    claim_lock = source.index("select(ScheduleDispatchClaim)", schedule_lock)

    assert app_lock < deployment_lock < schedule_lock < claim_lock
