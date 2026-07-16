type ModelRoutingDecisionDetailsProps = {
  output?: unknown;
  traceMetadata?: unknown;
};

type RoutingContext = {
  inputLengthBucket?: string;
  outputFormat?: string;
  schemaRequired?: boolean;
  knowledgeEnabled?: boolean;
  hasFileInput?: boolean;
};

type RoutingDecisionFactors = {
  profile?: string;
  evaluatedCandidateCount?: number;
  excludedCandidateCount?: number;
  qualityLowerBound?: number;
  expectedTotalCostUsd?: number;
  expectedLatencyMs?: number;
  priorSource?: string;
};

type ModelRoutingSummary = {
  strategyId?: string;
  selectedModel?: string;
  fallbackModel?: string;
  fallbackUsed?: boolean;
  fallbackFromModel?: string;
  fallbackReasonCode?: string;
  actualModel?: string;
  reasonCode?: string;
  policyVersion?: string;
  matchedRuleId?: string;
  judgeCalled?: boolean;
  policySource?: string;
  includedInPolicyLearning?: boolean;
  runtimeContext: RoutingContext;
  decisionFactors: RoutingDecisionFactors;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const stringValue = (value: unknown): string | undefined =>
  typeof value === 'string' && value.trim() ? value.trim() : undefined;

const booleanValue = (value: unknown): boolean | undefined =>
  typeof value === 'boolean' ? value : undefined;

const numberValue = (value: unknown): number | undefined =>
  typeof value === 'number' && Number.isFinite(value) ? value : undefined;

const routingRecordOf = (
  output: unknown,
  traceMetadata: unknown,
): Record<string, unknown> | null => {
  if (isRecord(traceMetadata)) {
    return isRecord(traceMetadata.llm) ? traceMetadata.llm : traceMetadata;
  }
  if (!isRecord(output)) return null;
  const metadata = isRecord(output.metadata) ? output.metadata : null;
  if (metadata && isRecord(metadata.model_routing)) {
    return metadata.model_routing;
  }
  if (metadata && isRecord(metadata.llm)) {
    return metadata.llm;
  }
  return metadata && isRecord(metadata.model_routing_metadata)
    ? metadata.model_routing_metadata
    : null;
};

const contextOf = (value: unknown): RoutingContext => {
  if (!isRecord(value)) return {};
  return {
    inputLengthBucket: stringValue(value.input_length_bucket),
    outputFormat: stringValue(value.output_format),
    schemaRequired: booleanValue(value.schema_required),
    knowledgeEnabled: booleanValue(value.knowledge_enabled),
    hasFileInput: booleanValue(value.has_file_input),
  };
};

const decisionFactorsOf = (value: unknown): RoutingDecisionFactors => {
  if (!isRecord(value)) return {};
  const score = isRecord(value.selected_model_score)
    ? value.selected_model_score
    : {};
  return {
    profile: stringValue(value.profile),
    evaluatedCandidateCount: numberValue(value.evaluated_candidate_count),
    excludedCandidateCount: numberValue(value.excluded_candidate_count),
    qualityLowerBound: numberValue(score.quality_lower_bound),
    expectedTotalCostUsd: numberValue(score.expected_total_cost_usd),
    expectedLatencyMs: numberValue(score.expected_latency_ms),
    priorSource: stringValue(score.prior_source),
  };
};

const summaryOf = ({
  output,
  traceMetadata,
}: ModelRoutingDecisionDetailsProps): ModelRoutingSummary | null => {
  const routing = routingRecordOf(output, traceMetadata);
  if (!routing) return null;
  const outputRecord = isRecord(output) ? output : null;
  const outputMetadata = isRecord(outputRecord?.metadata)
    ? outputRecord.metadata
    : null;

  const summary: ModelRoutingSummary = {
    strategyId: stringValue(routing.strategy_id),
    selectedModel:
      stringValue(routing.selected_model) || stringValue(outputRecord?.model),
    fallbackModel: stringValue(routing.fallback_model),
    fallbackUsed:
      booleanValue(routing.fallback_used) ??
      booleanValue(outputMetadata?.fallback_used),
    fallbackFromModel: stringValue(routing.fallback_from_model),
    fallbackReasonCode: stringValue(routing.fallback_reason_code),
    actualModel: stringValue(outputRecord?.model),
    reasonCode: stringValue(routing.reason_code),
    policyVersion: stringValue(routing.policy_version),
    matchedRuleId: stringValue(routing.matched_rule_id),
    judgeCalled: booleanValue(routing.judge_called),
    policySource: stringValue(routing.policy_source),
    includedInPolicyLearning: booleanValue(routing.included_in_policy_learning),
    runtimeContext: contextOf(routing.runtime_context || routing),
    decisionFactors: decisionFactorsOf(routing.decision_factors),
  };

  return summary.selectedModel || summary.reasonCode ? summary : null;
};

const lengthBucketLabel = (bucket?: string): string => {
  switch (bucket) {
    case 'short':
      return '짧은 입력';
    case 'medium':
      return '보통 입력';
    case 'long':
      return '긴 입력';
    default:
      return '입력 길이 정보 없음';
  }
};

const reasonText = (reasonCode?: string): string => {
  switch (reasonCode) {
    case 'prior_guided_utility_selected':
      return '품질 하한을 만족한 후보 중 예상 비용과 지연 시간을 함께 비교해 선택했습니다.';
    case 'prior_guided_constraints_safe_default':
      return '요구 조건을 만족하는 더 나은 후보가 없어 안전한 기본 모델을 유지했습니다.';
    case 'active_policy_unavailable':
    case 'policy_unavailable':
      return '사용할 수 있는 활성 정책이 없어 저장된 기본 모델을 사용했습니다.';
    default:
      return '저장된 사전 지식과 운영 통계를 반영한 정책 규칙을 적용했습니다.';
  }
};

const fallbackReasonText = (reasonCode?: string): string => {
  switch (reasonCode) {
    case 'runtime_client_unavailable':
      return '모델 호출 준비 실패';
    case 'provider_call_failed':
      return 'Provider 호출 실패';
    default:
      return '호출 실패';
  }
};

const priorSourceText = (source?: string): string => {
  switch (source) {
    case 'model_catalog_family_prior':
      return '모델 카탈로그 사전 지식';
    default:
      return source || '근거 출처 정보 없음';
  }
};

export function ModelRoutingDecisionDetails({
  output,
  traceMetadata,
}: ModelRoutingDecisionDetailsProps) {
  const summary = summaryOf({ output, traceMetadata });
  if (!summary) return null;

  const isPriorGuided = summary.strategyId === 'prior_guided_adaptive_v1';
  const isDeploymentPolicyTest =
    summary.policySource === 'active_deployment' &&
    summary.includedInPolicyLearning === false;
  const context = summary.runtimeContext;
  const factors = summary.decisionFactors;
  const hasDecisionFactors =
    factors.evaluatedCandidateCount !== undefined ||
    factors.qualityLowerBound !== undefined ||
    factors.expectedTotalCostUsd !== undefined ||
    factors.expectedLatencyMs !== undefined;

  return (
    <dl className="grid gap-3 rounded-lg border border-emerald-100 bg-emerald-50/50 px-4 py-3 text-xs dark:border-emerald-900 dark:bg-emerald-950/20 sm:grid-cols-2">
      <div className="sm:col-span-2">
        <dt className="font-semibold text-emerald-700 dark:text-emerald-200">
          {isDeploymentPolicyTest
            ? '배포 정책 기준 테스트'
            : isPriorGuided
              ? '사전 지식 기반 적응형 라우팅'
              : '자동 라우팅'}
        </dt>
        <dd className="mt-1 text-gray-700 dark:text-gray-200">
          {isDeploymentPolicyTest
            ? '활성 배포의 저장 정책을 테스트 실행에만 적용했습니다. 이 결과는 정책 학습에 포함되지 않습니다.'
            : '실행 중 Judge를 호출하지 않고 저장된 정책으로 모델을 선택했습니다.'}
        </dd>
      </div>

      {hasDecisionFactors ? (
        <div className="sm:col-span-2 rounded-md border border-emerald-200 bg-white p-3 dark:border-emerald-900 dark:bg-gray-900">
          <dt className="font-semibold text-gray-700 dark:text-gray-200">
            모델 비교 근거
          </dt>
          <dd className="mt-2 flex flex-wrap gap-2 text-gray-700 dark:text-gray-200">
            {factors.evaluatedCandidateCount !== undefined ? (
              <span className="rounded bg-emerald-50 px-2 py-1">
                검토 모델 {factors.evaluatedCandidateCount}개
              </span>
            ) : null}
            {factors.excludedCandidateCount !== undefined ? (
              <span className="rounded bg-gray-100 px-2 py-1">
                조건 제외 {factors.excludedCandidateCount}개
              </span>
            ) : null}
            {factors.qualityLowerBound !== undefined ? (
              <span className="rounded bg-emerald-50 px-2 py-1">
                품질 하한 {(factors.qualityLowerBound * 100).toFixed(1)}%
              </span>
            ) : null}
            {factors.expectedTotalCostUsd !== undefined ? (
              <span className="rounded bg-emerald-50 px-2 py-1">
                예상 비용 ${factors.expectedTotalCostUsd.toFixed(6)}
              </span>
            ) : null}
            {factors.expectedLatencyMs !== undefined ? (
              <span className="rounded bg-emerald-50 px-2 py-1">
                예상 지연 {Math.round(factors.expectedLatencyMs)}ms
              </span>
            ) : null}
          </dd>
          {factors.priorSource ? (
            <dd className="mt-2 text-gray-500">
              근거 출처: {priorSourceText(factors.priorSource)}
            </dd>
          ) : null}
        </div>
      ) : null}

      <div>
        <dt className="text-gray-500">입력 길이</dt>
        <dd className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
          {lengthBucketLabel(context.inputLengthBucket)}
        </dd>
      </div>
      <div>
        <dt className="text-gray-500">선택 모델</dt>
        <dd className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
          {summary.selectedModel || '-'}
        </dd>
      </div>

      <div className="sm:col-span-2 flex flex-wrap gap-2">
        {context.outputFormat === 'json' && context.schemaRequired ? (
          <span className="rounded border border-emerald-200 bg-white px-2 py-1 font-medium text-emerald-800">
            JSON 스키마 필요
          </span>
        ) : null}
        <span className="rounded border border-emerald-200 bg-white px-2 py-1 font-medium text-emerald-800">
          {context.knowledgeEnabled
            ? '지식 베이스 사용'
            : '지식 베이스 사용 안 함'}
        </span>
        {context.hasFileInput ? (
          <span className="rounded border border-emerald-200 bg-white px-2 py-1 font-medium text-emerald-800">
            파일 입력 포함
          </span>
        ) : null}
      </div>

      <div className="sm:col-span-2">
        <dt className="text-gray-500">선택 이유</dt>
        <dd className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
          {reasonText(summary.reasonCode)}
        </dd>
      </div>

      {summary.fallbackModel ? (
        <div className="sm:col-span-2">
          <dt className="text-gray-500">안전 장치</dt>
          <dd className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
            호출 실패 시 {summary.fallbackModel} 모델로 한 번 전환합니다.
          </dd>
        </div>
      ) : null}
      {summary.fallbackUsed ? (
        <div className="sm:col-span-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-gray-900 dark:border-amber-800 dark:bg-amber-950/20 dark:text-gray-100">
          <dt className="font-semibold text-amber-800 dark:text-amber-200">
            실제 대체 실행
          </dt>
          <dd className="mt-1">
            최초 선택: {summary.fallbackFromModel || summary.selectedModel || '-'}
          </dd>
          <dd>사유: {fallbackReasonText(summary.fallbackReasonCode)}</dd>
          <dd>실제 사용: {summary.actualModel || summary.fallbackModel || '-'}</dd>
        </div>
      ) : null}

      {summary.policyVersion || summary.matchedRuleId ? (
        <div className="sm:col-span-2 flex flex-wrap gap-x-4 gap-y-1 text-gray-500">
          {summary.policyVersion ? <span>정책 버전: {summary.policyVersion}</span> : null}
          {summary.matchedRuleId ? <span>적용 규칙: {summary.matchedRuleId}</span> : null}
        </div>
      ) : null}
      {summary.judgeCalled === false ? (
        <div className="sm:col-span-2 text-gray-500">실행 중 Judge 호출 안 함</div>
      ) : null}
    </dl>
  );
}
