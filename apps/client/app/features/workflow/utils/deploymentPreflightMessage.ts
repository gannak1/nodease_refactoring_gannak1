import type { DeploymentPreflightResponse } from '../types/Deployment';

export function formatDeploymentPreflightMessage(
  preflight: DeploymentPreflightResponse,
): string {
  const reason =
    preflight.safe_summary.blocked_reason || 'deployment_preflight_blocked';
  const affected = preflight.safe_summary.affected_kb_count_bucket;
  const actions = preflight.required_actions
    .map((action) => action.label)
    .filter(Boolean);

  return [
    `배포 전 검사에서 차단되었습니다. (${reason})`,
    affected !== '0' ? `영향 KB 수: ${affected}` : null,
    actions.length ? `필요 조치: ${actions.join(', ')}` : null,
  ]
    .filter(Boolean)
    .join('\n');
}

export function deploymentApiErrorMessage(
  error: unknown,
  fallback = '배포 중 오류가 발생했습니다.',
): string {
  const errorObject = asRecord(error);
  const response = asRecord(errorObject.response);
  const data = asRecord(response.data);
  const detail = data.detail;
  if (typeof detail === 'string') {
    return detail;
  }
  const detailObject = asRecord(detail);
  const detailError = asRecord(detailObject.error);
  const preflight = detailError.preflight as
    | DeploymentPreflightResponse
    | undefined;
  if (preflight?.status === 'blocked') {
    return formatDeploymentPreflightMessage(preflight);
  }
  if (typeof detailError.message === 'string') {
    return detailError.message;
  }
  if (typeof errorObject.message === 'string') {
    return errorObject.message;
  }
  return fallback;
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null
    ? (value as Record<string, unknown>)
    : {};
}
