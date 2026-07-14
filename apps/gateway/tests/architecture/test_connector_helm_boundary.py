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

    assert 'required "secrets.connectorTestAdmissionHmacKey is required' in secret_template
    assert "must contain at least 32 bytes" in secret_template
    assert "CONNECTOR_TEST_ADMISSION_HMAC_KEY" in secret_template
    assert "CONNECTOR_TEST_ADMISSION_HMAC_KEY" in gateway_template
    assert "connectorTestAdmissionHmacKey:" in values
    assert "connectorTestAdmissionHmacKey:" in local_values
