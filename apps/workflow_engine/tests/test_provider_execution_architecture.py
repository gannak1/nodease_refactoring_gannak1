from __future__ import annotations

import ast
from pathlib import Path


def test_llm_node_depends_on_provider_application_port_not_capability_service():
    source_path = (
        Path(__file__).parents[1] / "workflow" / "nodes" / "llm" / "llm_node.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "apps.shared.services.provider_execution_capability" not in imported_modules
    assert "apps.shared.domain.provider_execution_capability" not in imported_modules
    assert "apps.workflow_engine.composition.provider_execution" not in imported_modules
    assert not any(
        module.startswith("apps.workflow_engine.adapters.provider_")
        for module in imported_modules
    )


def test_legacy_llm_service_does_not_own_capability_contract():
    source_path = Path(__file__).parents[1] / "services" / "llm_service.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "apps.shared.services.provider_execution_capability" not in imported_modules
    assert "apps.shared.domain.provider_execution_capability" not in imported_modules


def test_provider_runtime_router_does_not_own_strategy_implementations():
    source_path = Path(__file__).parents[1] / "adapters" / "provider_execution.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert "apps.shared.services.provider_execution_capability" not in imported_modules
    assert "apps.shared.domain.provider_execution_capability" not in imported_modules
    assert "apps.workflow_engine.services.llm_service" not in imported_modules


def test_capability_adapter_is_the_only_workflow_shared_capability_owner():
    workflow_root = Path(__file__).parents[1]
    owners = set()
    capability_modules = {
        "apps.shared.services.provider_execution_capability",
        "apps.shared.domain.provider_execution_capability",
    }

    for source_path in workflow_root.rglob("*.py"):
        if "tests" in source_path.relative_to(workflow_root).parts:
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        if capability_modules.intersection(imported_modules):
            owners.add(source_path.relative_to(workflow_root).as_posix())

    assert owners == {"adapters/provider_execution_capability.py"}
