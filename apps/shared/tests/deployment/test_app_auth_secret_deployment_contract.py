from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[4]


def test_checked_in_gateway_manifests_keep_lifecycle_gate_disabled():
    for relative_path in (
        "infra/k8s/namespaces/default/gateway-deployment.yaml",
        "infra/k8s/namespaces/dev/gateway-deployment.yaml",
    ):
        documents = yaml.safe_load_all(
            (ROOT / relative_path).read_text(encoding="utf-8")
        )
        deployment = next(
            document
            for document in documents
            if document.get("kind") == "Deployment"
            and document.get("metadata", {}).get("name") == "api-server"
        )
        environment = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
        lifecycle_mode = next(
            item["value"]
            for item in environment
            if item["name"] == "APP_AUTH_SECRET_LIFECYCLE_MODE"
        )
        assert lifecycle_mode == "disabled"


def test_compose_requires_explicit_lifecycle_activation():
    compose = (ROOT / "docker/docker-compose.yml").read_text(encoding="utf-8")
    assert (
        "APP_AUTH_SECRET_LIFECYCLE_MODE: ${APP_AUTH_SECRET_LIFECYCLE_MODE:-disabled}"
    ) in compose


def test_helm_gateway_defaults_and_wires_lifecycle_gate():
    chart = ROOT / "infra/helm/moduly"
    values = yaml.safe_load((chart / "values.yaml").read_text(encoding="utf-8"))
    assert values["gateway"]["env"]["APP_AUTH_SECRET_LIFECYCLE_MODE"] == "disabled"

    configmap = (chart / "templates/configmap.yaml").read_text(encoding="utf-8")
    assert "APP_AUTH_SECRET_LIFECYCLE_MODE:" in configmap
    assert ".Values.gateway.env.APP_AUTH_SECRET_LIFECYCLE_MODE" in configmap

    deployment = (chart / "templates/gateway-deployment.yaml").read_text(
        encoding="utf-8"
    )
    assert "- name: APP_AUTH_SECRET_LIFECYCLE_MODE" in deployment
    assert "key: APP_AUTH_SECRET_LIFECYCLE_MODE" in deployment
