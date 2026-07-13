from pathlib import Path


def test_knowledge_domain_permission_migration_defines_constraints_and_safe_backfill():
    root = Path(__file__).resolve().parents[4]
    path = (
        root
        / "apps"
        / "shared"
        / "alembic"
        / "versions"
        / "b39e0f1a2b43_add_knowledge_domain_permissions.py"
    )
    source = path.read_text(encoding="utf-8")

    assert "team_knowledge_domain_permissions" in source
    assert "user_knowledge_domain_permissions" in source
    assert "catalog_manage" in source
    assert "permission_delegate" in source
    assert "lifecycle_manage" in source
    assert "sync_manage" in source
    assert "organization_memberships" in source
    assert "membership_state = 'active'" in source
    assert "organization_auth_state" in source
    assert "ON CONFLICT" in source
    assert "DO UPDATE SET auth_state = 'manager'" in source
