import ast
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]

PUBLIC_IPV4_EXCLUSIONS = {
    "0.0.0.0/8",
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.0.0.0/24",
    "192.0.2.0/24",
    "192.88.99.0/24",
    "192.168.0.0/16",
    "198.18.0.0/15",
    "198.51.100.0/24",
    "203.0.113.0/24",
    "224.0.0.0/4",
    "240.0.0.0/4",
}
PUBLIC_IPV6_EXCLUSIONS = {
    "::/96",
    "::/128",
    "::1/128",
    "::ffff:0:0/96",
    "64:ff9b::/96",
    "64:ff9b:1::/48",
    "100::/64",
    "2001::/23",
    "2001:db8::/32",
    "2002::/16",
    "3ffe::/16",
    "3fff::/20",
    "5f00::/16",
    "fc00::/7",
    "fe80::/10",
    "fec0::/10",
    "ff00::/8",
}
PUBLIC_PORTS = {80, 443, 143, 993}


def _read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def test_helm_worker_policy_is_default_on_and_rejects_unsafe_catch_all() -> None:
    values = yaml.safe_load(_read("infra/helm/moduly/values.yaml"))
    production = yaml.safe_load(_read("infra/helm/moduly/values-production.yaml"))
    template = _read("infra/helm/moduly/templates/worker-networkpolicy.yaml")

    assert values["worker"]["networkPolicy"]["enabled"] is True
    assert production["worker"]["networkPolicy"]["enabled"] is True
    assert production["worker"]["networkPolicy"]["externalDatabaseCidrs"] == [
        "10.0.0.0/16"
    ]
    assert 'eq $cidr "0.0.0.0/0"' in template
    assert 'eq $cidr "::/0"' in template
    assert "externalDatabaseCidrs is required" in template
    assert "externalRedisCidrs is required" in template
    assert "external dependency CIDRs cannot be empty" in template
    assert "- {}" not in template
    assert "hostNetwork: true" not in _read(
        "infra/helm/moduly/templates/worker-deployment.yaml"
    )

    for cidr in PUBLIC_IPV4_EXCLUSIONS | PUBLIC_IPV6_EXCLUSIONS:
        assert f"- {cidr}" in template
    for port in PUBLIC_PORTS | {53, 5432, 6379, 8194}:
        assert f"port: {port}" in template


def test_generic_http_production_path_cannot_construct_httpx_client_directly() -> None:
    guarded_files = (
        "apps/workflow_engine/adapters/providers/generic_http.py",
        "apps/workflow_engine/workflow/nodes/http/http_node.py",
    )

    for relative_path in guarded_files:
        tree = ast.parse(_read(relative_path), filename=relative_path)
        direct_clients = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "httpx"
            and node.func.attr == "Client"
        ]
        assert direct_clients == []

    node_source = _read(
        "apps/workflow_engine/workflow/nodes/http/http_node.py"
    )
    composition_source = _read("apps/workflow_engine/composition/generic_http.py")
    assert "build_generic_http_effect_adapter" in node_source
    assert "GuardedHttpxOutboundAdapter" in composition_source
