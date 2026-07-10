import inspect

from apps.gateway import lifespan as lifespan_module


def test_gateway_lifespan_does_not_apply_orm_or_enum_schema_ddl():
    source = inspect.getsource(lifespan_module)

    assert "Base.metadata.create_all" not in source
    assert "ALTER TYPE" not in source
    assert "_ensure_deployment_type_enum_values" not in source
    assert "require_schedule_dispatch_migration_ready" in source
