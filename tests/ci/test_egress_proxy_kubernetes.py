from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

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
    _run("kubectl", "apply", "-f", "-", input_text=payload)


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
        direct = _exec_curl(pod, "https://example.com/")
        assert direct.returncode != 0, f"{pod} retained direct HTTPS egress"

        proxied = _exec_curl(
            pod,
            "--proxy",
            f"http://{PROXY_SERVICE}:{proxy_port}",
            "https://example.com/",
        )
        assert proxied.returncode == 0, f"{pod} could not use its proxy listener"

    workflow_http = _exec_curl(
        "worker-egress-probe",
        "--proxy",
        f"http://{PROXY_SERVICE}:3129",
        "http://example.com/",
    )
    assert workflow_http.returncode == 0, "Workflow HTTP listener rejected port 80"

    gateway_http = _exec_curl(
        "gateway-egress-probe",
        "--proxy",
        f"http://{PROXY_SERVICE}:3128",
        "http://example.com/",
    )
    assert gateway_http.returncode != 0, "Gateway listener allowed plain HTTP"

    for pod in internal_only:
        direct = _exec_curl(pod, "https://example.com/")
        assert direct.returncode != 0, f"{pod} retained public HTTPS egress"

    unauthorized = _exec_curl(
        "unauthorized-egress-probe",
        "--proxy",
        f"http://{PROXY_SERVICE}:3128",
        "https://example.com/",
    )
    assert unauthorized.returncode != 0, "unauthorized workload reached Squid"
