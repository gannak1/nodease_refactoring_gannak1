import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPOSITORY_ROOT / path).read_text(encoding="utf-8")


def _load(path: str) -> dict:
    return yaml.safe_load(_read(path))


def test_direct_gateway_example_uses_supported_storage_contract():
    example_lines = _read("dev/.env.example").splitlines()

    assert any(
        line.strip() in {"STORAGE_TYPE=LOCAL", "STORAGE_TYPE=CLOUD"}
        for line in example_lines
    ), "Direct Gateway example must select a supported storage mode"
    assert not any(
        re.search(r"\bPROD\b", line) for line in example_lines
    ), "Legacy PROD storage mode must not be documented"


def test_helm_storage_configuration_has_one_root_authority():
    defaults = _load("infra/helm/moduly/values.yaml")
    production = _load("infra/helm/moduly/values-production.yaml")

    assert defaults["storage"] == {
        "type": "LOCAL",
        "bucketName": "",
        "region": "",
    }
    assert production["storage"] == {
        "type": "CLOUD",
        "bucketName": "",
        "region": "",
    }

    for values in (defaults, production):
        assert "STORAGE_TYPE" not in values["gateway"]["env"]
        assert "S3_BUCKET_NAME" not in values["gateway"]["env"]
        assert "AWS_REGION" not in values["gateway"]["env"]
        assert "S3_BUCKET_NAME" not in values["worker"]["env"]
        assert "AWS_REGION" not in values["worker"]["env"]


def test_helm_storage_templates_use_root_authority_and_render_validation():
    helpers = _read("infra/helm/moduly/templates/_helpers.tpl")
    configmap = _read("infra/helm/moduly/templates/configmap.yaml")

    assert 'define "moduly.validateStorage"' in helpers
    assert "storage.type must be LOCAL or CLOUD" in helpers
    assert "storage.bucketName is required when storage.type is CLOUD" in helpers
    assert "storage.region is required when storage.type is CLOUD" in helpers
    assert "legacy component storage keys are unsupported" in helpers
    for legacy_key in ("STORAGE_TYPE", "S3_BUCKET_NAME", "AWS_REGION"):
        assert f'hasKey .Values.gateway.env "{legacy_key}"' in helpers
    for legacy_key in ("S3_BUCKET_NAME", "AWS_REGION"):
        assert f'hasKey .Values.worker.env "{legacy_key}"' in helpers
    assert 'include "moduly.validateStorage" .' in configmap
    assert 'include "moduly.storageType" .' in configmap
    assert '.Values.storage.bucketName | trim | quote' in configmap
    assert '.Values.storage.region | trim | quote' in configmap
    assert 'default "ap-northeast-2"' not in configmap

    for template_name in (
        "gateway-deployment.yaml",
        "worker-deployment.yaml",
        "knowledge-worker-deployment.yaml",
        "knowledge-storage-pvc.yaml",
        "NOTES.txt",
    ):
        template = _read(f"infra/helm/moduly/templates/{template_name}")
        assert ".Values.gateway.env.STORAGE_TYPE" not in template
        assert ".Values.gateway.env.S3_BUCKET_NAME" not in template
        assert ".Values.worker.env.S3_BUCKET_NAME" not in template


def test_cloud_only_storage_env_references_share_one_template_condition():
    cloud_block_pattern = re.compile(
        r'\{\{- if eq \$storageType "CLOUD" \}\}(.*?)\{\{- end \}\}',
        re.DOTALL,
    )

    for template_name in (
        "gateway-deployment.yaml",
        "worker-deployment.yaml",
        "knowledge-worker-deployment.yaml",
    ):
        template = _read(f"infra/helm/moduly/templates/{template_name}")
        cloud_blocks = cloud_block_pattern.findall(template)
        assert any(
            "name: S3_BUCKET_NAME" in block and "name: AWS_REGION" in block
            for block in cloud_blocks
        ), f"{template_name} must gate both CLOUD-only environment references"


@pytest.mark.parametrize(
    ("values_files", "expected_cloud_env"),
    [
        (("tests/ci/fixtures/helm-values-ci.yaml",), False),
        (
            (
                "infra/helm/moduly/values-production.yaml",
                "tests/ci/fixtures/helm-values-ci.yaml",
            ),
            True,
        ),
    ],
)
def test_rendered_storage_consumers_reference_existing_configmap_keys(
    values_files: tuple[str, ...],
    expected_cloud_env: bool,
):
    if os.getenv("NODEASE_RUN_HELM_INTEGRATION_TESTS") != "1":
        pytest.skip("Helm integration contract is owned by deployment validation")

    helm = shutil.which("helm")
    if helm is None:
        pytest.fail("Deployment validation enabled the Helm contract without Helm")

    command = [
        helm,
        "template",
        "nodease-storage-contract",
        str(REPOSITORY_ROOT / "infra" / "helm" / "moduly"),
        "--set",
        "knowledgeWorker.enabled=true",
    ]
    if not expected_cloud_env:
        command.extend(("--set", "knowledgeWorker.localStorage.enabled=true"))
    for values_file in values_files:
        command.extend(("-f", str(REPOSITORY_ROOT / values_file)))

    completed = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, "Helm storage contract render failed"

    manifests = [
        document
        for document in yaml.safe_load_all(completed.stdout)
        if isinstance(document, dict)
    ]
    configmaps = {
        manifest["metadata"]["name"]: manifest.get("data", {})
        for manifest in manifests
        if manifest.get("kind") == "ConfigMap"
    }
    storage_consumers = {
        "gateway": None,
        "worker": None,
        "knowledge-worker": None,
    }

    for manifest in manifests:
        if manifest.get("kind") != "Deployment":
            continue
        for container in (
            manifest.get("spec", {})
            .get("template", {})
            .get("spec", {})
            .get("containers", [])
        ):
            container_name = container.get("name")
            if container_name not in storage_consumers:
                continue
            env_by_name = {item.get("name"): item for item in container.get("env", [])}
            storage_consumers[container_name] = env_by_name

            expected_names = {"STORAGE_TYPE"}
            if expected_cloud_env:
                expected_names.update({"S3_BUCKET_NAME", "AWS_REGION"})
            assert expected_names <= env_by_name.keys()
            if not expected_cloud_env:
                assert "S3_BUCKET_NAME" not in env_by_name
                assert "AWS_REGION" not in env_by_name

            for env_name in expected_names:
                reference = env_by_name[env_name]["valueFrom"]["configMapKeyRef"]
                assert reference["name"] in configmaps
                assert reference["key"] in configmaps[reference["name"]]

    assert all(value is not None for value in storage_consumers.values())


def test_ci_renders_complete_cloud_config_and_rejects_each_invalid_boundary():
    fixture = _load("tests/ci/fixtures/helm-values-ci.yaml")
    workflow = _read(".github/workflows/pr-quality-gate.yml")

    assert fixture["storage"] == {
        "bucketName": "ci-static-render-placeholder",
        "region": "region-ci-1",
    }
    assert "assert_invalid_storage_configuration" in workflow
    assert "storage.type=REMOTE" in workflow
    assert "storage.bucketName=" in workflow
    assert "storage.region=" in workflow
    assert "gateway.env.STORAGE_TYPE=CLOUD" in workflow
    assert "worker.env.S3_BUCKET_NAME=legacy-bucket" in workflow
