from types import SimpleNamespace

from apps.gateway import lifespan as lifespan_module


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _FakeConnection:
    def __init__(self, statements):
        self.statements = statements
        self.options = None

    def execution_options(self, **kwargs):
        self.options = kwargs
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement):
        sql = str(statement)
        self.statements.append(sql)
        if "to_regtype" in sql:
            return _ScalarResult("deploymenttype")
        return _ScalarResult(None)


class _FakeEngine:
    def __init__(self, dialect_name="postgresql"):
        self.dialect = SimpleNamespace(name=dialect_name)
        self.statements = []
        self.connection = _FakeConnection(self.statements)
        self.connect_called = False

    def connect(self):
        self.connect_called = True
        return self.connection


def test_ensure_deployment_type_enum_values_adds_chatbot(monkeypatch):
    fake_engine = _FakeEngine()
    monkeypatch.setattr(lifespan_module, "engine", fake_engine)

    lifespan_module._ensure_deployment_type_enum_values()

    assert fake_engine.connection.options == {"isolation_level": "AUTOCOMMIT"}
    assert any(
        "ALTER TYPE deploymenttype ADD VALUE IF NOT EXISTS 'CHATBOT'" in statement
        for statement in fake_engine.statements
    )


def test_ensure_deployment_type_enum_values_skips_non_postgresql(monkeypatch):
    fake_engine = _FakeEngine(dialect_name="sqlite")
    monkeypatch.setattr(lifespan_module, "engine", fake_engine)

    lifespan_module._ensure_deployment_type_enum_values()

    assert fake_engine.connect_called is False
