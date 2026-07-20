import ast
from pathlib import Path


GATEWAY_ROOT = Path(__file__).resolve().parents[2]


FORBIDDEN_IMPORT_PREFIXES = (
    "apps.gateway.adapters",
    "apps.gateway.services.knowledge_recommendation_retrieval",
)


def _forbidden_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            violations.extend(
                alias.name
                for alias in node.names
                if any(
                    alias.name == prefix or alias.name.startswith(f"{prefix}.")
                    for prefix in FORBIDDEN_IMPORT_PREFIXES
                )
            )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if any(
                module == prefix or module.startswith(f"{prefix}.")
                for prefix in FORBIDDEN_IMPORT_PREFIXES
            ):
                violations.append(module)
    return violations


def test_credential_resolver_does_not_import_adapter_or_p4():
    path = GATEWAY_ROOT / "services" / "knowledge_recommendation_credentials.py"

    assert _forbidden_imports(path) == []
