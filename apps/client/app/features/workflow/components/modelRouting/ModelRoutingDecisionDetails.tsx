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
  routingBasis?: string;
  complexityScore?: number;
  complexityUncertainty?: number;
  difficulty?: string;
  difficultyScore?: number;
  confidence?: number;
  localConfidence?: number;
  localConfidenceThreshold?: number;
  learningMode?: string;
};

type JudgeSummary = {
  model?: string;
  confidence?: number;
  reasonCode?: string;
  cost?: number;
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
  decisionSource?: string;
  judge?: JudgeSummary;
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
  const selectedModelScore = isRecord(value.selected_model_score)
    ? value.selected_model_score
    : {};
  return {
    profile: stringValue(value.profile),
    evaluatedCandidateCount:
      numberValue(value.evaluated_candidate_count) ??
      numberValue(value.compared_model_count),
    excludedCandidateCount: numberValue(value.excluded_candidate_count),
    qualityLowerBound:
      numberValue(selectedModelScore.quality_lower_bound) ??
      numberValue(value.selected_quality_lower_bound),
    expectedTotalCostUsd:
      numberValue(selectedModelScore.expected_total_cost_usd) ??
      numberValue(value.selected_expected_cost_usd),
    expectedLatencyMs:
      numberValue(selectedModelScore.expected_latency_ms) ??
      numberValue(value.selected_expected_latency_ms),
    priorSource:
      stringValue(selectedModelScore.prior_source) ??
      stringValue(value.profile_source),
    routingBasis: stringValue(value.routing_basis),
    complexityScore: numberValue(value.complexity_score),
    complexityUncertainty: numberValue(value.complexity_uncertainty),
    difficulty: stringValue(value.difficulty),
    difficultyScore: numberValue(value.difficulty_score),
    confidence: numberValue(value.confidence),
    localConfidence: numberValue(value.local_confidence),
    localConfidenceThreshold: numberValue(value.local_confidence_threshold),
    learningMode: stringValue(value.learning_mode),
  };
};

const judgeOf = (value: unknown): JudgeSummary | undefined => {
  if (!isRecord(value)) return undefined;
  return {
    model: stringValue(value.model),
    confidence: numberValue(value.confidence),
    reasonCode: stringValue(value.reason_code),
    cost: numberValue(value.cost),
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
    decisionSource: stringValue(routing.decision_source),
    judge: judgeOf(routing.judge),
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
    case 'complexity_regression_global_profile':
      return '요청 복잡도 점수에 필요한 품질을 만족한 후보 중 예상 비용과 지연이 가장 적절한 모델을 선택했습니다.';
    case 'bootstrap_global_profile_economy':
      return '이번 요청의 난이도 점수가 경제형 범위여서, 품질 기준 안에서 비용 효율이 높은 후보를 선택했습니다.';
    case 'bootstrap_global_profile_balanced':
      return '이번 요청의 난이도 점수가 균형형 범위여서, 품질과 비용·응답 속도를 함께 고려한 후보를 선택했습니다.';
    case 'bootstrap_global_profile_advanced':
      return '이번 요청의 난이도 점수가 고성능 범위여서, 더 높은 추론·정확도 요구를 만족하는 후보를 선택했습니다.';
    case 'bootstrap_task_complexity_economy':
      return '현재 작업은 경제형 모델로 처리할 수 있다고 판단해 비용 효율이 높은 후보를 선택했습니다.';
    case 'bootstrap_task_complexity_balanced':
      return '현재 작업의 복잡도와 비용·응답 속도를 함께 고려해 균형형 후보를 선택했습니다.';
    case 'bootstrap_task_complexity_advanced':
      return '현재 작업에는 더 높은 추론·정확도 요구가 있다고 판단해 고성능 후보를 선택했습니다.';
    case 'prior_guided_utility_selected':
      return '품질 하한을 만족한 후보 중 예상 비용과 지연 시간을 함께 비교해 선택했습니다.';
    case 'prior_guided_constraints_safe_default':
      return '요구 조건을 만족하는 더 나은 후보가 없어 안전한 기본 모델을 유지했습니다.';
    case 'judge_bootstrap_required':
      return '초기 학습 표본을 만들기 위해 Judge가 현재 요청에 맞는 후보 모델을 선택했습니다.';
    case 'local_router_confident':
      return '이전 Judge 선택과 운영 결과를 학습한 로컬 라우터가 충분한 확신으로 모델을 선택했습니다.';
    case 'local_router_uncertain':
      return '로컬 라우터의 확신이 부족해 Judge가 최종 선택을 확인했습니다.';
    case 'runtime_judge_unavailable':
      return 'Judge를 사용할 수 없어 안전한 기본 모델로 실행했습니다.';
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
  const isBootstrapTaskComplexity =
    summary.strategyId === 'bootstrap_task_complexity_v2';
  const isRequestComplexity =
    summary.strategyId === 'bootstrap_request_complexity_v3';
  const isComplexityRegression =
    summary.strategyId === 'bootstrap_request_complexity_regression_v4';
  const isComplexityRouting = isRequestComplexity || isComplexityRegression;
  const isJudgeBootstrap =
    summary.strategyId === 'judge_bootstrap_incremental_v1';
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
            : isJudgeBootstrap
              ? 'Judge 기반 점진 학습 자동 라우팅'
              : isComplexityRegression
              ? '요청 복잡도 점수 기반 자동 라우팅'
              : isRequestComplexity
                ? '요청 난이도 기반 자동 라우팅'
              : isBootstrapTaskComplexity
              ? '작업 복잡도 기반 자동 라우팅'
            : isPriorGuided
              ? '사전 지식 기반 적응형 라우팅'
              : '자동 라우팅'}
        </dt>
        <dd className="mt-1 text-gray-700 dark:text-gray-200">
          {isDeploymentPolicyTest
            ? '활성 배포의 저장 정책을 테스트 실행에만 적용했습니다. 이 결과는 정책 학습에 포함되지 않습니다.'
            : isJudgeBootstrap
              ? summary.decisionSource === 'test_policy_preview'
                ? '테스트 화면에서는 Judge를 호출하지 않습니다. 실제 배포 실행 전에 예상 기본 모델만 표시합니다.'
                : summary.decisionSource === 'runtime_judge'
                  ? '초기 학습 표본을 만들기 위해 이번 요청에서만 Judge가 후보 모델을 선택했습니다.'
                  : '이전 Judge 선택과 운영 결과를 학습한 로컬 라우터가 먼저 모델을 선택했습니다.'
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

      {isComplexityRouting &&
      (factors.complexityScore !== undefined ||
        factors.difficultyScore !== undefined) ? (
        <div className="sm:col-span-2 rounded-md border border-emerald-200 bg-white p-3 dark:border-emerald-900 dark:bg-gray-900">
          <dt className="font-semibold text-gray-700 dark:text-gray-200">
            이번 요청의 복잡도 판정
          </dt>
          <dd className="mt-2 flex flex-wrap gap-2 text-gray-700 dark:text-gray-200">
            <span className="rounded bg-emerald-50 px-2 py-1">
              복잡도 점수{' '}
              {Math.round(
                factors.complexityScore ?? factors.difficultyScore ?? 0,
              )}
              /100
            </span>
            {factors.complexityUncertainty !== undefined ? (
              <span className="rounded bg-emerald-50 px-2 py-1">
                예측 오차 ±{Math.round(factors.complexityUncertainty)}점
              </span>
            ) : null}
            {!isComplexityRegression && factors.difficulty ? (
              <span className="rounded bg-emerald-50 px-2 py-1">
                등급 {factors.difficulty}
              </span>
            ) : null}
            {factors.confidence !== undefined ? (
              <span className="rounded bg-emerald-50 px-2 py-1">
                분류 신뢰도 {(factors.confidence * 100).toFixed(1)}%
              </span>
            ) : null}
          </dd>
          <dd className="mt-2 text-gray-500">
            변수 치환이 끝난 프롬프트와 이번 입력을 함께 읽어 계산했습니다. 요청 원문과 RAG 문서 원문은 이 화면이나 실행 로그에 저장하지 않습니다.
          </dd>
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

      {isJudgeBootstrap && summary.judge ? (
        <div className="sm:col-span-2 rounded-md border border-violet-200 bg-violet-50/60 p-3 text-gray-900 dark:border-violet-900 dark:bg-violet-950/20 dark:text-gray-100">
          <dt className="font-semibold text-violet-900 dark:text-violet-100">
            이번 Judge 판단
          </dt>
          <dd className="mt-1 text-gray-700 dark:text-gray-200">
            Judge 모델: {summary.judge.model || '-'} · 판단 확신도{' '}
            {summary.judge.confidence === undefined
              ? '-'
              : `${(summary.judge.confidence * 100).toFixed(1)}%`}
          </dd>
          <dd className="mt-1 text-gray-500">
            판단 코드: {summary.judge.reasonCode || '-'}
            {summary.judge.cost === undefined
              ? ''
              : ` · Judge 비용 $${summary.judge.cost.toFixed(6)}`}
          </dd>
        </div>
      ) : null}
      {isJudgeBootstrap && factors.learningMode ? (
        <div className="sm:col-span-2 text-gray-500">
          학습 방식: {factors.learningMode === 'local_first' ? '로컬 라우터 우선' : 'Judge 학습 중'}
          {factors.localConfidence !== undefined
            ? ` · 로컬 확신도 ${(factors.localConfidence * 100).toFixed(1)}%`
            : ''}
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
