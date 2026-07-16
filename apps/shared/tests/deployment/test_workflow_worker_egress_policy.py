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


def _load_yaml_documents(relative_path: str) -> list[dict]:
    return [
        document
        for document in yaml.safe_load_all(_read(relative_path))
        if isinstance(document, dict)
    ]


def _port_numbers(rule: dict) -> set[int]:
    return {int(port["port"]) for port in rule.get("ports", [])}


def _ip_block_rule(policy: dict, cidr: str) -> dict:
    for rule in policy["spec"]["egress"]:
        for target in rule.get("to", []):
            if target.get("ipBlock", {}).get("cidr") == cidr:
                return rule
    raise AssertionError(f"missing egress ipBlock: {cidr}")


def _worker_policy(relative_path: str) -> dict:
    policies = [
        document
        for document in _load_yaml_documents(relative_path)
        if document.get("kind") == "NetworkPolicy"
        and document.get("metadata", {}).get("name") == "worker-egress"
    ]
    assert len(policies) == 1
    return policies[0]


def _assert_static_worker_policy(relative_path: str, namespace: str) -> None:
    documents = _load_yaml_documents(relative_path)
    deployments = [
        document for document in documents if document.get("kind") == "Deployment"
    ]
    assert len(deployments) == 1
    pod_spec = deployments[0]["spec"]["template"]["spec"]
    pod_labels = deployments[0]["spec"]["template"]["metadata"]["labels"]
    assert pod_spec.get("hostNetwork", False) is False
    policy = _worker_policy(relative_path)

    assert policy["metadata"]["namespace"] == namespace
    assert policy["spec"]["podSelector"]["matchLabels"] == {"app": "worker"}
    assert all(
        pod_labels.get(key) == value
        for key, value in policy["spec"]["podSelector"]["matchLabels"].items()
    )
    assert policy["spec"]["policyTypes"] == ["Egress"]
    assert policy["spec"]["egress"]
    assert all(rule.get("to") and rule.get("ports") for rule in policy["spec"]["egress"])

    ipv4_rule = _ip_block_rule(policy, "0.0.0.0/0")
    ipv6_rule = _ip_block_rule(policy, "::/0")
    assert _port_numbers(ipv4_rule) == PUBLIC_PORTS
    assert _port_numbers(ipv6_rule) == PUBLIC_PORTS
    assert set(ipv4_rule["to"][0]["ipBlock"]["except"]) == (
        PUBLIC_IPV4_EXCLUSIONS
    )
    assert set(ipv6_rule["to"][0]["ipBlock"]["except"]) == (
        PUBLIC_IPV6_EXCLUSIONS
    )

    dependency_rule = _ip_block_rule(policy, "10.0.0.0/16")
    assert _port_numbers(dependency_rule) == {5432, 6379}

    dns_rules = [
        rule
        for rule in policy["spec"]["egress"]
        if any(
            target.get("namespaceSelector", {}).get("matchLabels", {}).get(
                "kubernetes.io/metadata.name"
            )
            == "kube-system"
            for target in rule.get("to", [])
        )
    ]
    assert len(dns_rules) == 1
    assert _port_numbers(dns_rules[0]) == {53}

    sandbox_rules = [
        rule
        for rule in policy["spec"]["egress"]
        if any(
            target.get("podSelector", {}).get("matchLabels") == {"app": "sandbox"}
            for target in rule.get("to", [])
        )
    ]
    assert len(sandbox_rules) == 1
    assert _port_numbers(sandbox_rules[0]) == {8194}


def test_active_eks_worker_manifests_apply_private_deny_egress_policy() -> None:
    _assert_static_worker_policy(
        "infra/k8s/namespaces/default/worker-deployment.yaml",
        "default",
    )
    _assert_static_worker_policy(
        "infra/k8s/namespaces/dev/worker-deployment.yaml",
        "dev",
    )


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
