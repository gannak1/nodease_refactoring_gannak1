from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def _read(path: str) -> str:
    return (REPOSITORY_ROOT / path).read_text(encoding="utf-8")


def _load(path: str) -> dict:
    return yaml.safe_load(_read(path))


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
