from __future__ import annotations

from pathlib import Path

import yaml
from apps.shared.services.egress_guard import _PUBLIC_EGRESS_DENIED_NETWORKS

ROOT = Path(__file__).resolve().parents[4]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_squid_configuration_is_pinned_fail_closed_and_does_not_retain_payloads() -> (
    None
):
    dockerfile = _read("docker/proxy/Dockerfile")
    config = _read("docker/proxy/squid.conf")
    helm_config = _read("infra/helm/moduly/files/squid.conf")

    assert helm_config == config
    assert "ubuntu/squid:6.6-24.04_edge@sha256:" in dockerfile
    assert "ubuntu:latest" not in dockerfile
    assert "apt-get" not in dockerfile
    assert "dns_v4_first" not in config
    assert "http_port 3128 name=https_only" in config
    assert "http_port 3129 name=http_compatible" in config
    assert "http_access deny manager" in config
    assert "http_access deny blocked_destination" in config
    assert "acl blocked_destination dst ::ffff:0:0/96" in config
    assert config.rstrip().endswith("http_access deny all")
    assert "access_log none" in config
    assert "cache_store_log none" in config
    assert "cache deny all" in config
    assert "ssl_bump" not in config


def test_proxy_and_network_policy_use_the_application_denied_cidr_registry() -> None:
    expected_cidrs = {str(network) for network in _PUBLIC_EGRESS_DENIED_NETWORKS}
    config = _read("docker/proxy/squid.conf")
    squid_cidrs = {
        line.removeprefix("acl blocked_destination dst ").strip()
        for line in config.splitlines()
        if line.startswith("acl blocked_destination dst ")
    }

    assert squid_cidrs == expected_cidrs
    for path in (
        "infra/helm/moduly/templates/proxy-only-networkpolicies.yaml",
        "infra/helm/moduly/templates/worker-networkpolicy.yaml",
    ):
        policy = _read(path)
        for cidr in expected_cidrs:
            assert f"- {cidr}" in policy


def test_compose_target_workloads_have_no_direct_egress_or_ambient_proxy() -> None:
    compose = yaml.safe_load(_read("docker/docker-compose.yml"))
    services = compose["services"]
    networks = compose["networks"]

    assert networks["moduly-network"]["internal"] is True
    assert networks["proxy-https-clients"]["internal"] is True
    assert networks["proxy-http-clients"]["internal"] is True
    assert networks["proxy-egress"].get("internal") is not True

    expected = {
        "gateway": ("proxy-https-clients", "http://proxy:3128"),
        "knowledge_worker": ("proxy-https-clients", "http://proxy:3128"),
        "workflow_engine": ("proxy-http-clients", "http://proxy:3129"),
    }
    for service_name, (proxy_network, proxy_url) in expected.items():
        service = services[service_name]
        environment = service["environment"]
        assert service["networks"] == ["moduly-network", proxy_network]
        assert environment["OUTBOUND_TRANSPORT_MODE"] == "proxy_guarded_external"
        assert environment["OUTBOUND_PROXY_URL"] == proxy_url
        assert environment["OUTBOUND_PROXY_ALLOWED_HOSTS"] == "proxy"
        assert environment["OUTBOUND_PROXY_POLICY_REVISION"] == "proxy-v1"
        assert "HTTP_PROXY" not in environment
        assert "HTTPS_PROXY" not in environment
        assert "NO_PROXY" not in environment
        assert service["depends_on"]["proxy"]["condition"] == "service_healthy"

    proxy = services["proxy"]
    assert "ports" not in proxy
    assert proxy["networks"] == [
        "proxy-https-clients",
        "proxy-http-clients",
        "proxy-egress",
    ]
    assert proxy["read_only"] is True
    assert proxy["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in proxy["security_opt"]
    assert set(proxy["tmpfs"]) >= {
        "/run/squid",
        "/var/log/squid",
        "/var/spool/squid",
    }
    assert proxy["healthcheck"]["test"] == [
        "CMD",
        "bash",
        "-ec",
        "exec 3<>/dev/tcp/127.0.0.1/3128",
    ]


def test_helm_production_reference_requires_ha_proxy_only_egress() -> None:
    values = yaml.safe_load(_read("infra/helm/moduly/values.yaml"))
    production = yaml.safe_load(_read("infra/helm/moduly/values-production.yaml"))
    configmap = _read("infra/helm/moduly/templates/egress-proxy-configmap.yaml")
    squid_config = _read("infra/helm/moduly/files/squid.conf")
    deployment = _read("infra/helm/moduly/templates/egress-proxy-deployment.yaml")
    service = _read("infra/helm/moduly/templates/egress-proxy-service.yaml")
    pdb = _read("infra/helm/moduly/templates/egress-proxy-pdb.yaml")
    policies = _read("infra/helm/moduly/templates/proxy-only-networkpolicies.yaml")
    worker_policy = _read("infra/helm/moduly/templates/worker-networkpolicy.yaml")
    helpers = _read("infra/helm/moduly/templates/_helpers.tpl")
    gateway_deployment = _read("infra/helm/moduly/templates/gateway-deployment.yaml")
    worker_deployment = _read("infra/helm/moduly/templates/worker-deployment.yaml")
    knowledge_deployment = _read(
        "infra/helm/moduly/templates/knowledge-worker-deployment.yaml"
    )

    assert values["egressProxy"]["enabled"] is True
    assert production["egressProxy"]["enabled"] is True
    assert production["egressProxy"]["replicaCount"] >= 2
    assert production["egressProxy"]["image"]["digest"].startswith("sha256:")
    assert production["egressProxy"]["networkPolicy"]["enforced"] is True
    assert '.Files.Get "files/squid.conf"' in configmap
    assert "access_log none" in squid_config
    assert "cache deny all" in squid_config
    assert "@{{ .Values.egressProxy.image.digest }}" in deployment
    assert "checksum/proxy-config" in deployment
    assert "maxUnavailable: 0" in deployment
    assert "maxSurge: 1" in deployment
    assert "topologySpreadConstraints:" in deployment
    assert "topologyKey: kubernetes.io/hostname" in deployment
    assert "whenUnsatisfiable: DoNotSchedule" in deployment
    assert "readOnlyRootFilesystem: true" in deployment
    assert "allowPrivilegeEscalation: false" in deployment
    assert "drop:" in deployment and "- ALL" in deployment
    assert "seccompProfile:" in deployment
    assert "runAsNonRoot: true" in deployment
    assert "nodease.io/egress-mode: proxy-v1" in deployment
    assert "readinessProbe:" in deployment
    assert "livenessProbe:" in deployment
    assert "clusterIP: None" not in service
    assert "minAvailable: 1" in pdb
    assert 'component" "gateway' in policies
    assert 'component" "knowledge-worker' in policies
    assert 'component" "worker' in policies
    assert "port: 3128" in policies
    assert "port: 3129" in policies
    assert "port: 80" not in worker_policy
    assert "port: 443" not in worker_policy
    assert "port: 143" in worker_policy
    assert "port: 993" in worker_policy
    assert "cidr: 0.0.0.0/0" in policies
    assert "cidr: ::/0" in policies
    proxy_ingress = policies.split("---", maxsplit=1)[0]
    assert 'component" "sandbox' not in proxy_ingress

    assert "production public HTTP workloads require egressProxy.enabled" in helpers
    assert "production egressProxy.replicaCount must be at least 2" in helpers
    assert (
        "production egressProxy network policy must be enabled and enforced" in helpers
    )
    assert "production Worker proxy-only network policy must be enabled" in helpers
    assert "egressProxy authorized source CIDRs cannot be empty" in helpers

    workload_contracts = (
        (gateway_deployment, "httpsPort"),
        (knowledge_deployment, "httpsPort"),
        (worker_deployment, "httpCompatiblePort"),
    )
    for workload, listener_value in workload_contracts:
        assert "nodease.io/egress-mode: proxy-v1" in workload
        assert "moduly.outboundProxyEnv" in workload
        assert listener_value in workload
        assert "- name: NODE_ENV" in workload
        assert "key: NODE_ENV" in workload
        assert "HTTP_PROXY" not in workload
        assert "HTTPS_PROXY" not in workload
        assert "NO_PROXY" not in workload


def test_helm_proxy_only_policy_has_no_direct_public_route_for_target_workloads() -> (
    None
):
    workload_policies = _read(
        "infra/helm/moduly/templates/proxy-only-networkpolicies.yaml"
    )
    worker_policy = _read("infra/helm/moduly/templates/worker-networkpolicy.yaml")

    assert "gateway-proxy-only-egress" in workload_policies
    assert "knowledge-worker-proxy-only-egress" in workload_policies
    assert "egress-proxy-ingress" in workload_policies
    assert "egress-proxy-egress" in workload_policies
    assert "port: 3128" in workload_policies
    assert "port: 3129" in worker_policy

    # Only the proxy is allowed to open public web ports. Target workloads
    # must reach those destinations through the internal ClusterIP Service.
    proxy_egress = workload_policies.split("egress-proxy-egress", maxsplit=1)[1]
    target_egress = workload_policies.split("egress-proxy-egress", maxsplit=1)[0]
    assert "cidr: 0.0.0.0/0" in proxy_egress
    assert "cidr: ::/0" in proxy_egress
    assert "cidr: 0.0.0.0/0" not in target_egress
    assert "cidr: ::/0" not in target_egress


def test_helm_non_http_workloads_are_default_deny_with_only_internal_dependencies() -> (
    None
):
    policies = _read("infra/helm/moduly/templates/proxy-only-networkpolicies.yaml")

    expected_policies = {
        "logger-internal-only-egress": {"5432", "6379"},
        "beat-internal-only-egress": {"6379"},
        "frontend-internal-only-egress": {
            "{{ .Values.gateway.service.port }}",
        },
    }
    for policy_name, ports in expected_policies.items():
        assert policy_name in policies
        policy = policies.split(policy_name, maxsplit=1)[1].split("---", maxsplit=1)[0]
        assert "policyTypes:" in policy
        assert "- Egress" in policy
        assert "cidr: 0.0.0.0/0" not in policy
        assert "cidr: ::/0" not in policy
        for port in ports:
            assert f"port: {port}" in policy

    frontend_policy = policies.split("frontend-internal-only-egress", maxsplit=1)[
        1
    ].split("---", maxsplit=1)[0]
    assert 'component" "gateway' in frontend_policy
    assert "port: 3128" not in frontend_policy
    assert "port: 3129" not in frontend_policy


def test_helm_proxy_rollout_phase_is_visible_on_enforced_workloads() -> None:
    helpers = _read("infra/helm/moduly/templates/_helpers.tpl")
    assert 'define "moduly.egressWorkloadSelectorLabel"' in helpers
    assert 'eq .Values.egressProxy.networkPolicy.enforcementPhase "canary"' in (helpers)

    for path in (
        "infra/helm/moduly/templates/gateway-deployment.yaml",
        "infra/helm/moduly/templates/worker-deployment.yaml",
        "infra/helm/moduly/templates/knowledge-worker-deployment.yaml",
        "infra/helm/moduly/templates/egress-proxy-deployment.yaml",
    ):
        deployment = _read(path)
        assert "nodease.io/egress-enforcement-phase" in deployment
        assert ".Values.egressProxy.networkPolicy.enforcementPhase" in deployment

    for path in (
        "infra/helm/moduly/templates/proxy-only-networkpolicies.yaml",
        "infra/helm/moduly/templates/worker-networkpolicy.yaml",
    ):
        policy = _read(path)
        assert "moduly.egressWorkloadSelectorLabel" in policy


def test_kind_calico_pod_cidr_matches_the_proxy_source_acl_fixture() -> None:
    kind_config = yaml.safe_load(
        _read("tests/ci/fixtures/egress-proxy/kind-calico.yaml")
    )
    helm_values = yaml.safe_load(_read("tests/ci/fixtures/helm-values-ci.yaml"))

    pod_subnet = kind_config["networking"]["podSubnet"]
    authorized_sources = helm_values["egressProxy"]["networkPolicy"][
        "authorizedSourceCidrs"
    ]

    assert authorized_sources == [pod_subnet]
