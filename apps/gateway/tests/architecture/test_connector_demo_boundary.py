from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_connector_demo_is_an_explicit_compose_override() -> None:
    base_compose = _read("docker/docker-compose.yml")
    demo_compose = _read("docker/docker-compose.connector-demo.yml")

    assert "CONNECTOR_TEST_TRUSTED_LOCAL_TARGETS" not in base_compose
    assert "connector-test-tls-init:" in demo_compose
    assert "connector-test-postgres:" in demo_compose
    assert 'profiles: ["connector-demo"]' in demo_compose
    assert (
        'CONNECTOR_TEST_TRUSTED_LOCAL_TARGETS: "connector-test-postgres:5432"'
        in demo_compose
    )
    assert 'CONNECTOR_TEST_ALLOWED_PORTS: "5432"' in demo_compose
    assert "54322" not in demo_compose
    assert 'CONNECTOR_TEST_TRUSTED_LOCAL_CA_FILE: "/run/connector-test-ca/ca.crt"' in (
        demo_compose
    )
    assert "../local/connector-test-tls/docker:/run/connector-test-ca:ro" in (
        demo_compose
    )


def test_host_run_demo_uses_separate_profile_and_published_port() -> None:
    development_compose = _read("dev/docker-compose.yml")
    development_environment = _read("dev/.env.example")

    assert "connector-test-tls-init:" in development_compose
    assert "connector-test-postgres:" in development_compose
    assert "connector-test-redis:" in development_compose
    assert 'profiles: ["connector-demo"]' in development_compose
    assert '"127.0.0.1:55432:5432"' in development_compose
    assert '"127.0.0.1:56379:6379"' in development_compose
    assert (
        "CONNECTOR_TEST_TRUSTED_LOCAL_TARGETS=localhost:55432"
        in development_environment
    )
    assert "CONNECTOR_TEST_ALLOWED_PORTS=5432,55432" in development_environment
    assert (
        "CONNECTOR_TEST_TRUSTED_LOCAL_CA_FILE=" in development_environment
    )


def test_demo_host_ports_are_bound_to_loopback_only() -> None:
    development_compose = _read("dev/docker-compose.yml")
    demo_compose = _read("docker/docker-compose.connector-demo.yml")

    assert '"127.0.0.1:55432:5432"' in development_compose
    assert '"127.0.0.1:56379:6379"' in development_compose
    assert '"127.0.0.1:55432:5432"' in demo_compose
    assert '\n      - "55432:5432"' not in development_compose
    assert '\n      - "56379:6379"' not in development_compose
    assert '\n      - "55432:5432"' not in demo_compose


def test_private_signing_material_is_not_mounted_into_gateway() -> None:
    demo_compose = _read("docker/docker-compose.connector-demo.yml")
    gateway_section = demo_compose.split("  gateway:", 1)[1].split("\nvolumes:", 1)[0]
    postgres_section = demo_compose.split("  connector-test-postgres:", 1)[1].split(
        "  gateway:", 1
    )[0]

    assert "connector_test_ca_private" not in gateway_section
    assert "connector_test_server_tls" not in gateway_section
    assert "connector_test_ca_private" not in postgres_section
    assert "connector_test_server_tls:/tls/server:ro" in postgres_section


def test_production_templates_do_not_expose_trusted_local_overrides() -> None:
    production_values = _read("infra/helm/moduly/values-production.yaml")
    gateway_template = _read("infra/helm/moduly/templates/gateway-deployment.yaml")

    for setting_name in (
        "CONNECTOR_TEST_TRUSTED_LOCAL_TARGETS",
        "CONNECTOR_TEST_TRUSTED_LOCAL_CA_FILE",
    ):
        assert setting_name not in production_values
        assert setting_name not in gateway_template


def test_certificate_material_is_generated_at_runtime_only() -> None:
    dockerfile = _read("docker/connector-test-postgres/Dockerfile")
    generator = _read("docker/connector-test-postgres/generate-certificates.sh")

    assert "openssl" in dockerfile
    assert "openssl genpkey" in generator
    assert "subjectAltName=DNS:connector-test-postgres,DNS:localhost" in generator
    assert "BEGIN PRIVATE KEY" not in generator
    assert "BEGIN CERTIFICATE" not in generator
    assert "cat /tls/server/demo-password" not in generator


def test_demo_credential_helper_never_prints_the_credential() -> None:
    helper = _read("scripts/copy_connector_demo_password.ps1")

    assert "Set-Clipboard" in helper
    assert 'Write-Output "Connector demo credential copied to the clipboard."' in helper
    assert "Write-Output $password" not in helper


def test_docker_runtime_verifier_projects_only_canonical_status() -> None:
    verifier = _read("scripts/verify_connector_demo_runtime.py")

    assert 'print("connector-demo-runtime=ok")' in verifier
    assert "connector-demo-runtime=failed:" in verifier
    assert "print(password" not in verifier
    assert "print(redis_url" not in verifier
    assert "print(ca_file" not in verifier
