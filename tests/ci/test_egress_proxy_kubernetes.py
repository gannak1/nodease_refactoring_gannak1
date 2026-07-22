from __future__ import annotations

import ipaddress
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
RELEASE_NAME = "nodease-egress-ci"
PROXY_SERVICE = f"{RELEASE_NAME}-moduly-egress-proxy"
CURL_IMAGE = (
    "curlimages/curl:8.12.1@sha256:"
    "94e9e444bcba979c2ea12e27ae39bee4cd10bc7041a472c4727a558e213744e6"
)


def _run(
    *args: str,
    input_text: str | None = None,
    check: bool = True,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=check,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _require_integration_environment() -> None:
    if os.getenv("NODEASE_RUN_EGRESS_PROXY_KUBERNETES") != "1":
        pytest.skip("Kubernetes egress integration is delegated to remote CI")
    missing = [name for name in ("helm", "kubectl") if shutil.which(name) is None]
    assert not missing, "required Kubernetes integration tools are unavailable"


def _render_proxy_resources(
    *, enforcement_phase: str = "final"
) -> list[dict[str, Any]]:
    rendered = _run(
        "helm",
        "template",
        RELEASE_NAME,
        "infra/helm/moduly",
        "-f",
        "tests/ci/fixtures/helm-values-ci.yaml",
        "--set-string",
        f"egressProxy.networkPolicy.enforcementPhase={enforcement_phase}",
    ).stdout
    documents = [
        document
        for document in yaml.safe_load_all(rendered)
        if isinstance(document, dict)
    ]
    selected_names = {
        PROXY_SERVICE,
        f"{RELEASE_NAME}-moduly-egress-proxy-ingress",
        f"{RELEASE_NAME}-moduly-gateway-proxy-only-egress",
        f"{RELEASE_NAME}-moduly-knowledge-worker-proxy-only-egress",
        f"{RELEASE_NAME}-moduly-worker-egress",
        f"{RELEASE_NAME}-moduly-logger-internal-only-egress",
        f"{RELEASE_NAME}-moduly-beat-internal-only-egress",
        f"{RELEASE_NAME}-moduly-frontend-internal-only-egress",
        f"{RELEASE_NAME}-moduly-egress-proxy-egress",
    }
    selected = [
        document
        for document in documents
        if document.get("metadata", {}).get("name") in selected_names
    ]
    selected_kinds = {(item["kind"], item["metadata"]["name"]) for item in selected}
    assert ("ConfigMap", PROXY_SERVICE) in selected_kinds
    assert ("Service", PROXY_SERVICE) in selected_kinds
    assert ("Deployment", PROXY_SERVICE) in selected_kinds
    assert sum(kind == "NetworkPolicy" for kind, _name in selected_kinds) == 8
    return selected


def _probe_pod(name: str, component: str) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "labels": {
                "app.kubernetes.io/name": "moduly",
                "app.kubernetes.io/instance": RELEASE_NAME,
                "app.kubernetes.io/component": component,
                "nodease.io/egress-mode": "proxy-v1",
            },
        },
        "spec": {
            "automountServiceAccountToken": False,
            "restartPolicy": "Never",
            "containers": [
                {
                    "name": "probe",
                    "image": CURL_IMAGE,
                    "command": ["sleep", "600"],
                    "securityContext": {
                        "allowPrivilegeEscalation": False,
                        "capabilities": {"drop": ["ALL"]},
                        "runAsNonRoot": True,
                        "runAsUser": 100,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                }
            ],
        },
    }


def _apply(documents: list[dict[str, Any]]) -> None:
    payload = yaml.safe_dump_all(documents, sort_keys=False)
    result = _run(
        "kubectl",
        "apply",
        "-f",
        "-",
        input_text=payload,
        check=False,
    )
    assert result.returncode == 0, (
        "kubectl apply failed: " + result.stderr.strip()[-4096:]
    )


def _exec_curl(pod: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return _run(
        "kubectl",
        "exec",
        pod,
        "--",
        "curl",
        "--fail",
        "--silent",
        "--show-error",
        "--connect-timeout",
        "5",
        "--max-time",
        "12",
        *arguments,
        check=False,
        timeout=30,
    )


def _ipv4_from_nslookup(
    output: str,
    predicate: Callable[[ipaddress.IPv4Address], bool],
    *,
    prefer_last: bool = False,
) -> str:
    matches: list[str] = []
    for candidate in re.findall(r"(?<![\w:])(?:\d{1,3}\.){3}\d{1,3}(?![\w:])", output):
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if isinstance(address, ipaddress.IPv4Address) and predicate(address):
            matches.append(str(address))
    if matches:
        return matches[-1] if prefer_last else matches[0]
    raise AssertionError("DNS lookup did not return a matching IPv4 address")


def _public_ipv4_from_nslookup(output: str) -> str:
    return _ipv4_from_nslookup(output, lambda address: address.is_global)


def _private_ipv4_from_nslookup(output: str) -> str:
    # nslookup prints its private DNS server before the answer. Prefer the
    # final matching address so the service endpoint is not mistaken for DNS.
    return _ipv4_from_nslookup(
        output, lambda address: address.is_private, prefer_last=True
    )


def _mapped_ipv4_address(address: str) -> str:
    parsed = ipaddress.ip_address(address)
    if not isinstance(parsed, ipaddress.IPv4Address):
        raise ValueError(f"expected an IPv4 address, got {address!r}")
    return f"::ffff:{parsed}"


def _mapped_resolve(hostname: str, port: int, address: str) -> str:
    return f"{hostname}:{port}:[{_mapped_ipv4_address(address)}]"


def _resolve_public_ipv4(pod: str, hostname: str) -> str:
    result = _run(
        "kubectl",
        "exec",
        pod,
        "--",
        "nslookup",
        hostname,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, f"{pod} could not resolve the probe hostname"
    return _public_ipv4_from_nslookup(f"{result.stdout}\n{result.stderr}")


def test_nslookup_parser_selects_only_public_ipv4_destination() -> None:
    output = """
Server:         10.96.0.10
Address:        10.96.0.10:53

Non-authoritative answer:
Name:   example.com
Address: 2606:2800:220:1:248:1893:25c8:1946
Name:   example.com
Address: 93.184.216.34
"""

    assert _public_ipv4_from_nslookup(output) == "93.184.216.34"


def test_mapped_ipv4_resolve_rejects_ipv6_and_formats_ipv4_mapping() -> None:
    assert _mapped_ipv4_address("93.184.216.34") == "::ffff:93.184.216.34"
    assert _mapped_resolve("example.com", 443, "93.184.216.34") == (
        "example.com:443:[::ffff:93.184.216.34]"
    )

    with pytest.raises(ValueError, match="expected an IPv4 address"):
        _mapped_ipv4_address("2001:db8::1")


def test_nslookup_parser_selects_private_ipv4_destination() -> None:
    output = """
Server:         10.96.0.10
Address:        10.96.0.10:53

Name:   kubernetes.default.svc.cluster.local
Address: 10.96.0.1
"""

    assert _private_ipv4_from_nslookup(output) == "10.96.0.1"


def test_canary_policy_selects_only_proxy_revision_and_final_covers_component() -> None:
    _require_integration_environment()

    selectors: dict[str, dict[str, str]] = {}
    policy_name = f"{RELEASE_NAME}-moduly-gateway-proxy-only-egress"
    for phase in ("canary", "final"):
        resources = _render_proxy_resources(enforcement_phase=phase)
        policy = next(
            item for item in resources if item["metadata"]["name"] == policy_name
        )
        selectors[phase] = policy["spec"]["podSelector"]["matchLabels"]

    assert selectors["canary"]["nodease.io/egress-mode"] == "proxy-v1"
    assert "nodease.io/egress-mode" not in selectors["final"]


def test_calico_enforces_proxy_only_public_https_and_proxy_source_boundary() -> None:
    _require_integration_environment()
    _apply(_render_proxy_resources())
    _run(
        "kubectl",
        "rollout",
        "status",
        f"deployment/{PROXY_SERVICE}",
        "--timeout=240s",
        timeout=270,
    )

    proxy_clients = {
        "gateway-egress-probe": 3128,
        "knowledge-egress-probe": 3128,
        "worker-egress-probe": 3129,
    }
    internal_only = {
        "logger-egress-probe": "logger",
        "beat-egress-probe": "beat",
        "frontend-egress-probe": "frontend",
    }
    probes = [
        _probe_pod("gateway-egress-probe", "gateway"),
        _probe_pod("knowledge-egress-probe", "knowledge-worker"),
        _probe_pod("worker-egress-probe", "worker"),
        *[_probe_pod(name, component) for name, component in internal_only.items()],
        _probe_pod("unauthorized-egress-probe", "sandbox"),
    ]
    _apply(probes)
    for pod in (*proxy_clients, *internal_only, "unauthorized-egress-probe"):
        _run(
            "kubectl",
            "wait",
            "--for=condition=Ready",
            f"pod/{pod}",
            "--timeout=120s",
            timeout=150,
        )

    for pod, proxy_port in proxy_clients.items():
        example_ipv4 = _resolve_public_ipv4(pod, "example.com")
        direct = _exec_curl(
            pod,
            "--resolve",
            f"example.com:443:{example_ipv4}",
            "https://example.com/",
        )
        assert direct.returncode != 0, f"{pod} retained direct HTTPS egress"

        proxied = _exec_curl(
            pod,
            "--proxy",
            f"http://{PROXY_SERVICE}:{proxy_port}",
            "https://example.com/",
        )
        assert proxied.returncode == 0, f"{pod} could not use its proxy listener"

    # The sandbox-labelled probe is intentionally outside the proxy-only
    # policies. Prove the CNI/kernel can route IPv4-mapped destinations before
    # treating failures from protected workloads as policy enforcement.
    control_pod = "unauthorized-egress-probe"
    public_ipv4 = _resolve_public_ipv4(control_pod, "example.com")
    control_public = _exec_curl(
        control_pod,
        "--resolve",
        _mapped_resolve("example.com", 443, public_ipv4),
        "https://example.com/",
    )
    assert control_public.returncode == 0, (
        "unrestricted control pod could not reach mapped public IPv4"
    )

    private_ipv4_result = _run(
        "kubectl",
        "exec",
        control_pod,
        "--",
        "nslookup",
        "kubernetes.default.svc",
        check=False,
        timeout=30,
    )
    assert private_ipv4_result.returncode == 0, (
        "control pod could not resolve the Kubernetes private service"
    )
    private_ipv4 = _private_ipv4_from_nslookup(
        f"{private_ipv4_result.stdout}\n{private_ipv4_result.stderr}"
    )
    control_private = _exec_curl(
        control_pod,
        "--no-fail",
        "--insecure",
        "--resolve",
        _mapped_resolve("kubernetes.default.svc", 443, private_ipv4),
        "https://kubernetes.default.svc/healthz",
    )
    assert control_private.returncode == 0, (
        "unrestricted control pod could not reach mapped private IPv4"
    )

    protected_probes = tuple(proxy_clients)
    for pod in protected_probes:
        mapped_public = _exec_curl(
            pod,
            "--resolve",
            _mapped_resolve("example.com", 443, public_ipv4),
            "https://example.com/",
        )
        assert mapped_public.returncode != 0, (
            f"{pod} retained direct mapped public HTTPS egress"
        )

        mapped_private = _exec_curl(
            pod,
            "--insecure",
            "--resolve",
            _mapped_resolve("kubernetes.default.svc", 443, private_ipv4),
            "https://kubernetes.default.svc/healthz",
        )
        assert mapped_private.returncode != 0, (
            f"{pod} retained direct mapped private egress"
        )

        mapped_metadata = _exec_curl(
            pod,
            "--resolve",
            _mapped_resolve("metadata.invalid", 80, "169.254.169.254"),
            "http://metadata.invalid/",
        )
        assert mapped_metadata.returncode != 0, (
            f"{pod} retained direct mapped metadata egress"
        )

    connector_ipv4 = _resolve_public_ipv4(control_pod, "portquiz.net")
    for pod in protected_probes:
        connector_tunnel = _exec_curl(
            pod,
            "--verbose",
            "--proxytunnel",
            "--proxy",
            f"http://{PROXY_SERVICE}:3130",
            f"telnet://{connector_ipv4}:5432",
        )
        assert "200 Connection established" in connector_tunnel.stderr, (
            f"{pod} could not use the dedicated Connector DB tunnel"
        )

    connector_ssh = _exec_curl(
        "gateway-egress-probe",
        "--verbose",
        "--proxytunnel",
        "--proxy",
        f"http://{PROXY_SERVICE}:3130",
        f"telnet://{connector_ipv4}:22",
    )
    assert "200 Connection established" in connector_ssh.stderr, (
        "Connector listener rejected the approved SSH port"
    )

    connector_web = _exec_curl(
        "gateway-egress-probe",
        "--proxy",
        f"http://{PROXY_SERVICE}:3130",
        "https://example.com/",
    )
    assert connector_web.returncode != 0, (
        "Connector listener allowed general HTTPS tunneling"
    )

    workflow_http = _exec_curl(
        "worker-egress-probe",
        "--proxy",
        f"http://{PROXY_SERVICE}:3129",
        "http://example.com/",
    )
    assert workflow_http.returncode == 0, "Workflow HTTP listener rejected port 80"

    # portquiz is a credential-free TCP reachability target that listens on
    # arbitrary ports; no IMAP payload or provider account is used here.
    imap_ipv4 = _resolve_public_ipv4("worker-egress-probe", "portquiz.net")
    for imap_port in (143, 993):
        imap_tunnel = _exec_curl(
            "worker-egress-probe",
            "--verbose",
            "--proxytunnel",
            "--proxy",
            f"http://{PROXY_SERVICE}:3129",
            f"telnet://{imap_ipv4}:{imap_port}",
        )
        assert "200 Connection established" in imap_tunnel.stderr, (
            f"Workflow IPv4 IMAP CONNECT failed for port {imap_port}"
        )

    gateway_http = _exec_curl(
        "gateway-egress-probe",
        "--proxy",
        f"http://{PROXY_SERVICE}:3128",
        "http://example.com/",
    )
    assert gateway_http.returncode != 0, "Gateway listener allowed plain HTTP"

    for pod in internal_only:
        example_ipv4 = _resolve_public_ipv4(pod, "example.com")
        direct = _exec_curl(
            pod,
            "--resolve",
            f"example.com:443:{example_ipv4}",
            "https://example.com/",
        )
        assert direct.returncode != 0, f"{pod} retained public HTTPS egress"

    unauthorized = _exec_curl(
        "unauthorized-egress-probe",
        "--proxy",
        f"http://{PROXY_SERVICE}:3128",
        "https://example.com/",
    )
    assert unauthorized.returncode != 0, "unauthorized workload reached Squid"
