import importlib.util
import sys
import types
from pathlib import Path

from sqlalchemy import BigInteger, CheckConstraint, DateTime
from sqlalchemy.dialects.postgresql import JSONB


def _load_model_module(module_name: str, relative_path: str):
    root = Path(__file__).resolve().parents[2]
    packages = {
        "apps": root / "apps",
        "apps.shared": root / "apps" / "shared",
        "apps.shared.db": root / "apps" / "shared" / "db",
        "apps.shared.db.models": root / "apps" / "shared" / "db" / "models",
    }
    for name, path in packages.items():
        module = sys.modules.get(name) or types.ModuleType(name)
        module.__path__ = [str(path)]
        sys.modules[name] = module
        if "." in name:
            parent_name, child_name = name.rsplit(".", 1)
            setattr(sys.modules[parent_name], child_name, module)

    base_spec = importlib.util.spec_from_file_location(
        "apps.shared.db.base",
        root / "apps" / "shared" / "db" / "base.py",
    )
    base_module = importlib.util.module_from_spec(base_spec)
    sys.modules["apps.shared.db.base"] = base_module
    base_spec.loader.exec_module(base_module)
    sys.modules["apps.shared.db"].base = base_module

    spec = importlib.util.spec_from_file_location(
        module_name,
        root / relative_path,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    if "." in module_name:
        parent_name, child_name = module_name.rsplit(".", 1)
        setattr(sys.modules[parent_name], child_name, module)
    return module


def test_user_no_longer_has_direct_organization_id():
    user = _load_model_module(
        "apps.shared.db.models.user",
        "apps/shared/db/models/user.py",
    )

    assert "organization_id" not in user.User.__table__.columns


def test_user_account_state_timestamps_are_nullable_timezone_columns():
    user = _load_model_module(
        "apps.shared.db.models.user",
        "apps/shared/db/models/user.py",
    )

    for column_name in ("deactivated_at", "last_login_at"):
        column = user.User.__table__.columns[column_name]
        assert isinstance(column.type, DateTime)
        assert column.type.timezone is True
        assert column.nullable is True


def test_organization_no_longer_has_parent_or_structure_model():
    organization = _load_model_module(
        "apps.shared.db.models.organization",
        "apps/shared/db/models/organization.py",
    )

    assert "parent_id" not in organization.Organization.__table__.columns
    assert not hasattr(organization, "OrganizationStructure")


def test_organization_options_and_flags_columns():
    organization = _load_model_module(
        "apps.shared.db.models.organization",
        "apps/shared/db/models/organization.py",
    )

    assert "option" not in organization.Organization.__table__.columns

    options_column = organization.Organization.__table__.columns["options"]
    assert isinstance(options_column.type, JSONB)
    assert options_column.nullable is False

    flags_column = organization.Organization.__table__.columns["flags"]
    assert isinstance(flags_column.type, BigInteger)
    assert flags_column.nullable is False

    assert any(
        isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_organization_flags_nonnegative"
        for constraint in organization.Organization.__table__.constraints
    )
