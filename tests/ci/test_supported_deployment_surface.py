from pathlib import Path

import yaml

from scripts.ci.check_supported_deployment_surface import (
    find_unsupported_deployment_paths,
    tracked_paths,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_repository_contains_no_unsupported_eks_deployment_surface():

    assert find_unsupported_deployment_paths(tracked_paths(REPOSITORY_ROOT)) == []


def test_support_guard_matches_only_removed_eks_surfaces():
    paths = [
        ".github/workflows/deploy-dev-namespace.yml",
        ".github/workflows/deploy-dev-namespace.yaml",
        ".github/workflows/deploy-eks-frontend.yml",
        ".github/workflows/deploy-eks-gateway.yml",
        ".github/workflows/deploy-eks-gateway.yaml",
        ".github/workflows/deploy-eks-logger.yml",
        ".github/workflows/deploy-eks-sandbox.yml",
        ".github/workflows/deploy-eks-worker.yml",
        ".github/workflows/deploy-eks-schedule-coordinated.yml",
        ".github/workflows/deploy-eks-reintroduced.yml",
        "infra/k8s/namespaces/default/gateway.yaml",
        "infra/terraform/eks.tf",
        "infra/helm/moduly/values.yaml",
        "docker/docker-compose.yml",
    ]

    assert find_unsupported_deployment_paths(paths) == paths[:12]


def test_production_values_are_provider_neutral():
    values = (
        REPOSITORY_ROOT / "infra" / "helm" / "moduly" / "values-production.yaml"
    ).read_text(encoding="utf-8")

    forbidden_markers = (
        "AWS EKS",
        ".dkr.ecr.",
        "eks.amazonaws.com/role-arn",
        "alb.ingress.kubernetes.io",
        'storageClass: "gp3"',
        "912894834396",
        "moduly-ai.cloud",
    )
    for marker in forbidden_markers:
        assert marker not in values
    assert "Provider-neutral production reference" in values
    assert "enabled: false  # Operator must explicitly configure ingress." in values


def test_image_publisher_and_helm_defaults_use_nodease_ghcr_namespace():
    publisher = (
        REPOSITORY_ROOT / ".github" / "workflows" / "publish-images.yml"
    ).read_text(encoding="utf-8")
    values = (
        REPOSITORY_ROOT / "infra" / "helm" / "moduly" / "values.yaml"
    ).read_text(encoding="utf-8")

    assert "ghcr.io/nodease" in publisher
    assert "ghcr.io/jungle-scope" not in publisher
    assert "ghcr.io/nodease" in values
    assert "ghcr.io/jungle-scope" not in values


def test_storage_consumers_use_the_chart_service_account_contract():
    production_values = yaml.safe_load(
        (
            REPOSITORY_ROOT
            / "infra"
            / "helm"
            / "moduly"
            / "values-production.yaml"
        ).read_text(encoding="utf-8")
    )
    service_account = (
        REPOSITORY_ROOT
        / "infra"
        / "helm"
        / "moduly"
        / "templates"
        / "serviceaccount.yaml"
    ).read_text(encoding="utf-8")

    assert "serviceAccount" not in production_values["gateway"]
    assert production_values["serviceAccount"] == {
        "create": True,
        "annotations": {},
        "name": "",
    }
    assert ".Values.serviceAccount.annotations" in service_account

    for template_name in (
        "gateway-deployment.yaml",
        "worker-deployment.yaml",
        "knowledge-worker-deployment.yaml",
    ):
        deployment = (
            REPOSITORY_ROOT
            / "infra"
            / "helm"
            / "moduly"
            / "templates"
            / template_name
        ).read_text(encoding="utf-8")
        assert 'serviceAccountName: {{ include "moduly.serviceAccountName" . }}' in (
            deployment
        )
