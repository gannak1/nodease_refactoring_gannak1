from pathlib import Path


def test_helm_requires_and_injects_dedicated_connector_admission_key() -> None:
    root = Path(__file__).parents[4]
    secret_template = (
        root / "infra" / "helm" / "moduly" / "templates" / "secrets.yaml"
    ).read_text(encoding="utf-8")
    gateway_template = (
        root
        / "infra"
        / "helm"
        / "moduly"
        / "templates"
        / "gateway-deployment.yaml"
    ).read_text(encoding="utf-8")
    values = (root / "infra" / "helm" / "moduly" / "values.yaml").read_text(
        encoding="utf-8"
    )
    local_values = (
        root / "infra" / "helm" / "moduly" / "values-local.yaml"
    ).read_text(encoding="utf-8")
    production_values = (
        root / "infra" / "helm" / "moduly" / "values-production.yaml"
    ).read_text(encoding="utf-8")

    assert 'required "secrets.connectorTestAdmissionHmacKey is required' in secret_template
    assert "must contain at least 32 bytes" in secret_template
    assert "CONNECTOR_TEST_ADMISSION_HMAC_KEY" in secret_template
    assert "CONNECTOR_TEST_ADMISSION_HMAC_KEY" in gateway_template
    assert "connectorTestAdmissionHmacKey:" in values
    assert "connectorTestAdmissionHmacKey:" in local_values
    assert 'required "connectorTest.allowedPorts is required"' in gateway_template
    assert "CONNECTOR_TEST_ALLOWED_PORTS" in gateway_template
    assert "allowedPorts:\n    - 5432" in values
    assert "allowedPorts:\n    - 5432" in production_values
    assert "allowedPorts:\n    - 5432\n    - 54322\n    - 55432" in local_values


def test_gateway_image_provides_system_ca_for_strict_postgres_probe() -> None:
    dockerfile = (
        Path(__file__).parents[4] / "docker" / "gateway" / "Dockerfile"
    ).read_text(encoding="utf-8")

    assert "ca-certificates" in dockerfile
    assert "libpq5" in dockerfile


def test_local_profiles_include_active_docker_postgres_ports() -> None:
    root = Path(__file__).parents[4]
    expected = "5432,54322,55432"
    compose = (root / "docker" / "docker-compose.yml").read_text(encoding="utf-8")
    dev_example = (root / "dev" / ".env.example").read_text(encoding="utf-8")
    docker_example = (root / "docker" / ".env.example").read_text(encoding="utf-8")

    assert f"CONNECTOR_TEST_ALLOWED_PORTS:-{expected}" in compose
    assert f"CONNECTOR_TEST_ALLOWED_PORTS={expected}" in dev_example
    assert f"CONNECTOR_TEST_ALLOWED_PORTS={expected}" in docker_example
