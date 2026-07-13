import type { DeploymentPreflightResponse } from '../types/Deployment';

export function formatDeploymentPreflightMessage(
  preflight: DeploymentPreflightResponse,
): string {
  const reason =
    preflight.safe_summary.blocked_reason || 'deployment_preflight_blocked';
  const affected = preflight.safe_summary.affected_kb_count_bucket;
  const affectedCollections =
    preflight.safe_summary.affected_collection_count_bucket ?? '0';
  const actions = preflight.required_actions
    .map((action) => action.label)
    .filter(Boolean);

  return [
    preflight.status === 'warning'
      ? `배포 전 검사 경고가 있습니다. (${reason})`
      : `배포 전 검사에서 차단되었습니다. (${reason})`,
    affected !== '0' ? `영향 KB 수: ${affected}` : null,
    affectedCollections !== '0'
      ? `영향 Collection 수: ${affectedCollections}`
      : null,
    preflight.safe_summary.candidate_budget_limited
      ? '실행 시 지식 후보가 최대 후보 수로 제한될 수 있습니다.'
      : null,
    actions.length ? `필요 조치: ${actions.join(', ')}` : null,
  ]
    .filter(Boolean)
    .join('\n');
}

function formatSafePreflightFields(
  blockedReason: string | null | undefined,
  affectedKbCountBucket: string,
  actionLabels: string[],
): string {
  const reason = blockedReason || 'deployment_preflight_blocked';
  const actions = actionLabels.filter(Boolean);

  return [
    `실행 준비 검사에서 차단되었습니다. (${reason})`,
    affectedKbCountBucket !== '0'
      ? `영향 KB 수: ${affectedKbCountBucket}`
      : null,
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
  const preflightMessage = safeBlockedPreflightMessage(detailError.preflight);
  if (preflightMessage) {
    return preflightMessage;
  }
  if (typeof detailError.message === 'string') {
    return detailError.message;
  }
  if (typeof errorObject.message === 'string') {
    return errorObject.message;
  }
  return fallback;
}

function safeBlockedPreflightMessage(value: unknown): string | null {
  const preflight = asRecord(value);
  if (preflight.status !== 'blocked') return null;

  const summary = asRecord(preflight.safe_summary);
  const affected = summary.affected_kb_count_bucket;
  const blockedReason = summary.blocked_reason;
  const actions = preflight.required_actions;
  if (
    typeof affected !== 'string' ||
    (blockedReason !== null && typeof blockedReason !== 'string') ||
    !Array.isArray(actions)
  ) {
    return null;
  }

  const actionLabels = actions
    .map((action) => asRecord(action).label)
    .filter((label): label is string => typeof label === 'string' && !!label);
  return formatSafePreflightFields(blockedReason, affected, actionLabels);
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null
    ? (value as Record<string, unknown>)
    : {};
}
