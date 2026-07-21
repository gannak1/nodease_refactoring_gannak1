# ADR-0065: EKS 지원 표면 제거와 공급자 중립 배포 경계

Status: Accepted

## Context

Nodease 저장소에는 AWS EKS 전용 GitHub Actions workflow, raw Kubernetes manifest와 Terraform 구성이 함께 존재했지만 실제 지원·검증·운영 책임자가 확정되지 않았다. 이 구성은 특정 AWS account, ECR, ALB, IRSA, RDS와 storage class를 전제로 했고, Docker Compose 및 Helm과 별도의 배포 계약을 중복 유지했다.

이 상태에서 dev에서 main으로의 승격은 사용자가 지원되는 경로와 단순 잔존 artifact를 구분하기 어렵게 한다. 특히 schedule dispatch의 claim/drain 전환 workflow는 실제 Pod 수렴, drain과 immutable image identity를 함께 보장해야 하므로, 검증되지 않은 provider-specific workflow를 형식적으로 유지하거나 수동 명령으로 대체할 수 없다.

Helm chart와 GHCR image publisher는 서로 연결된 실제 소비 경로다. 반면 checked-in Helm render snapshot은 source of truth가 아니며 현재 values/template과 쉽게 어긋난다.

## Options considered

### 1. 기존 EKS 구성을 즉시 복구해 공식 지원한다

- 장점: 기존 workflow와 Terraform 투자를 유지할 수 있다.
- 단점: 실제 AWS environment, OIDC, secret, cluster/CNI, rollout 운영 책임과 통합 증거가 없으므로 현재 이슈 범위를 넘는다.

### 2. EKS artifact를 남겨 두되 비공식으로 표시한다

- 장점: 삭제 변경이 작다.
- 단점: stale workflow가 다시 실행되거나 문서와 CI가 지원 대상으로 오인할 수 있다. 보안·운영 계약이 중복되고 drift를 지속한다.

### 3. EKS 전용 표면을 제거하고 지원 경계를 좁힌다

- 장점: 실제 검증 가능한 Docker Compose와 공급자 중립 Helm만 source of truth로 유지한다. 재도입 조건을 명확히 할 수 있다.
- 단점: provider-neutral coordinated CD가 추가되기 전까지 non-disabled schedule 운영 활성화는 지원할 수 없다.

## Decision

Option 3을 채택한다.

1. 공식 배포 artifact는 Docker Compose와 infra/helm/moduly의 공급자 중립 Helm chart다.
2. 다음 EKS 전용 표면을 제거한다.
   - .github/workflows/deploy-dev-namespace.yml
   - .github/workflows/deploy-eks-*.yml
   - infra/k8s/**
   - infra/terraform/**
3. source of truth가 아닌 checked-in infra/helm/moduly/rendered.yaml을 제거한다. CI가 기본 및 production values를 매번 렌더링하고 schema를 검사한다.
4. publish-images.yml은 Helm의 실제 image source이므로 유지하되 ghcr.io/nodease namespace를 사용한다.
5. values-production.yaml은 provider-neutral reference로 유지한다.
   - provider account, endpoint, domain, IAM annotation과 storage class를 포함하지 않는다.
   - ingress는 기본 비활성이고 operator가 class, TLS, trusted proxy CIDR과 host를 명시해야 한다.
   - secret 값은 저장소에 두지 않으며 외부 secret manager 또는 배포 시 주입을 요구한다.
   - workload identity는 chart root `serviceAccount` 한 곳에서만 설정하며 Gateway, Workflow Worker와 Knowledge Worker가 같은 ServiceAccount를 명시적으로 사용한다.
6. Helm과 Compose의 schedule dispatch 기본값은 disabled다. 현재 지원 표면에는 안전한 coordinated CD가 없으므로 claim/drain 활성화는 fail-closed한다.
   - Helm은 non-disabled 값을 render 단계에서 거부하고 Compose는 mode와 fingerprint를 `disabled`로 고정해 shell 또는 `.env` 값으로 활성화하지 못하게 한다.
   - runtime ledger, readiness, transition preflight와 drain domain 코드는 삭제하지 않는다.
   - non-disabled activation은 immutable image identity, Logger/Gateway/Worker 순서, 실제 Pod 수렴과 안정 drain을 제공하는 별도 provider-neutral CD 결정과 구현 후에만 다시 지원한다.
7. Knowledge ingestion worker는 본 결정에서 활성화하지 않는다. production knowledgeWorker.enabled: false를 유지하고 활성화 완결성은 MBA-359가 소유한다.
8. PR 품질 게이트는 legacy dev namespace workflow, `deploy-eks-*` workflow와 `infra/k8s/**`, `infra/terraform/**`의 재도입을 거부한다.
   - GitHub workflow 금지는 `.yml`과 `.yaml` 확장자를 동일하게 처리하며 파일 stem/prefix로 판정한다.
   - Helm 기본/production values에 대해 lint와 render를 수행한다.
   - 렌더 결과는 kubeconform v0.7.0과 Kubernetes 1.31 compatibility baseline으로 검사한다. 이는 EKS 지원 선언이 아니다.
9. EKS를 다시 지원하려면 새 ADR과 이슈에서 cloud ownership, OIDC/secret, cluster/CNI, migration, rollback, schedule coordinated rollout, 실제 environment integration evidence를 함께 제시해야 한다.

## Security and protected-resource boundaries

| Boundary | Result | Evidence |
| --- | --- | --- |
| Secret/credential 원문 | 완료 | production values에는 빈 secret reference만 유지하고 provider account/ARN을 제거한다. |
| External provider I/O | 완료 | 검증되지 않은 EKS workflow 실행 표면을 제거한다. GHCR publisher만 실제 Helm consumer와 함께 유지한다. |
| Preflight/runtime 일치 | 완료 | Helm render schema 검증과 unsupported-surface guard가 PR gate에 연결된다. |
| Lifecycle | 완료 | schedule disabled만 지원하고 non-disabled mode는 Helm render 단계에서 fail-closed한다. |
| Authorization/RBAC | 해당 없음 | MBA-337은 애플리케이션 resource permission을 변경하지 않는다. |
| Audit/redaction | 해당 없음 | 새 runtime event나 payload 저장 경로를 추가하지 않는다. |
| Knowledge worker activation | 후속 이슈 | MBA-359. 현재 production default는 비활성이다. |
| Provider-neutral coordinated CD | 후속 이슈 | 별도 ADR/이슈와 실제 운영 증거가 필요하다. |

## Consequences

- 사용자는 로컬·단일 서버는 Docker Compose, Kubernetes packaging은 provider-neutral Helm으로 판단할 수 있다.
- Helm을 특정 managed Kubernetes에 설치하는 것은 가능하지만, 해당 cloud의 provisioning·ingress·identity·storage는 저장소가 공식 지원하거나 자동 구성하지 않는다.
- non-disabled distributed schedule 실행을 production에서 활성화할 공식 경로가 당분간 없다. 이를 수동 kubectl 절차로 우회해서는 안 된다.
- CI는 제거된 표면의 삭제 PR에서도 guard를 실행하고, 이후 같은 경로가 다시 추적되면 실패한다.
- provider-specific 운영 배포를 추가할 때는 dormant sample이 아니라 소유권과 검증 증거를 갖춘 별도 기능으로 도입해야 한다.

## Affected files

- .github/workflows/pr-quality-gate.yml
- .github/workflows/publish-images.yml
- scripts/ci/changed_scope.py
- scripts/ci/check_supported_deployment_surface.py
- infra/helm/moduly/values.yaml
- infra/helm/moduly/values-production.yaml
- docs/architecture.md
- docs/engineering/ci-quality-gates.md
- docs/features/deployment/*
- docs/features/workflow/*

## Follow-up review notes

- provider-neutral coordinated CD가 제안되면 ADR-0029의 rollout safety invariant를 축소하지 말고 본 ADR의 현재 비지원 판정을 명시적으로 대체해야 한다.
- managed Kubernetes 지원을 다시 추가할 때 Helm compatibility와 cloud provisioning 지원을 별도 항목으로 표시해야 한다.
