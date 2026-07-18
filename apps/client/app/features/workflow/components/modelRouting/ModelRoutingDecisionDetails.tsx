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

type JudgeSummary = {
  model?: string;
  confidence?: number;
  reasonCode?: string;
  reasonShort?: string;
  candidateModelCount?: number;
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
  judgeCalled?: boolean;
  decisionSource?: string;
  judge?: JudgeSummary;
  policySource?: string;
  includedInPolicyLearning?: boolean;
  runtimeContext: RoutingContext;
  localConfidence?: number;
  localConfidenceThreshold?: number;
  learningMode?: string;
  learningStatus?: string;
  learningOutcomeReason?: string;
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
  const traceRouting = isRecord(traceMetadata)
    ? isRecord(traceMetadata.llm)
      ? traceMetadata.llm
      : traceMetadata
    : null;
  const metadata = isRecord(output) && isRecord(output.metadata)
    ? output.metadata
    : null;
  const outputRouting = metadata && isRecord(metadata.model_routing)
    ? metadata.model_routing
    : metadata && isRecord(metadata.llm)
      ? metadata.llm
      : metadata && isRecord(metadata.model_routing_metadata)
        ? metadata.model_routing_metadata
        : null;

  if (!traceRouting) return outputRouting;
  if (!outputRouting) return traceRouting;

  // Trace에는 안전한 Judge 요약만 남고, output metadata에는 UI용 짧은 사유와
  // 후보 수가 추가된다. trace의 최신 실행값을 우선하되 누락된 Judge 필드만 보완한다.
  const traceJudge = isRecord(traceRouting.judge) ? traceRouting.judge : {};
  const outputJudge = isRecord(outputRouting.judge) ? outputRouting.judge : {};
  return {
    ...outputRouting,
    ...traceRouting,
    judge: {
      ...outputJudge,
      ...traceJudge,
    },
  };
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

const judgeOf = (value: unknown): JudgeSummary | undefined => {
  if (!isRecord(value)) return undefined;
  return {
    model: stringValue(value.model),
    confidence: numberValue(value.confidence),
    reasonCode: stringValue(value.reason_code),
    reasonShort: stringValue(value.reason_short),
    candidateModelCount: numberValue(value.candidate_model_count),
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
  const decisionFactors = isRecord(routing.decision_factors)
    ? routing.decision_factors
    : {};

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
    judgeCalled: booleanValue(routing.judge_called),
    decisionSource: stringValue(routing.decision_source),
    judge: judgeOf(routing.judge),
    policySource: stringValue(routing.policy_source),
    includedInPolicyLearning: booleanValue(routing.included_in_policy_learning),
    runtimeContext: contextOf(routing.runtime_context || routing),
    localConfidence: numberValue(decisionFactors.local_confidence),
    localConfidenceThreshold: numberValue(
      decisionFactors.local_confidence_threshold,
    ),
    learningMode: stringValue(decisionFactors.learning_mode),
    learningStatus: stringValue(routing.learning_status),
    learningOutcomeReason: stringValue(routing.learning_outcome_reason),
  };

  return summary.selectedModel || summary.reasonCode ? summary : null;
};

const lengthBucketLabel = (bucket?: string): string => {
  if (bucket === 'short') return '짧은 입력';
  if (bucket === 'medium') return '보통 입력';
  if (bucket === 'long') return '긴 입력';
  return '입력 길이 정보 없음';
};

const reasonText = (reasonCode?: string): string => {
  switch (reasonCode) {
    case 'judge_bootstrap_required':
      return '학습 초기 단계라 Judge가 현재 요청과 후보 모델을 비교해 선택했습니다.';
    case 'local_router_confident':
      return '이전 Judge 선택과 성공 실행을 학습한 로컬 라우터가 충분한 확신으로 선택했습니다.';
    case 'local_router_uncertain':
      return '로컬 라우터의 확신이 기준보다 낮아 Judge가 최종 선택했습니다.';
    case 'runtime_judge_unavailable':
      return 'Judge를 사용할 수 없어 기본 모델로 안전하게 실행했습니다.';
    case 'legacy_policy_ignored':
      return '지원이 끝난 과거 정책은 실행하지 않고 저장된 기본 모델을 사용했습니다.';
    case 'active_policy_unavailable':
    case 'policy_unavailable':
      return 'Judge-first 활성 정책이 없어 저장된 기본 모델을 사용했습니다.';
    default:
      return 'Judge-first 정책의 모델 선택 결과입니다.';
  }
};

const fallbackReasonText = (reasonCode?: string): string => {
  if (reasonCode === 'runtime_client_unavailable') return '모델 호출 준비 실패';
  if (reasonCode === 'provider_call_failed') return 'Provider 호출 실패';
  return '호출 실패';
};

export function ModelRoutingDecisionDetails({
  output,
  traceMetadata,
}: ModelRoutingDecisionDetailsProps) {
  const summary = summaryOf({ output, traceMetadata });
  if (!summary) return null;

  const isJudgeFirst =
    summary.strategyId === 'judge_bootstrap_incremental_v1';
  const isDeploymentPolicyTest =
    summary.policySource === 'active_deployment' &&
    summary.includedInPolicyLearning === false;
  const context = summary.runtimeContext;

  return (
    <dl className="grid gap-3 rounded-lg border border-emerald-100 bg-emerald-50/50 px-4 py-3 text-xs dark:border-emerald-900 dark:bg-emerald-950/20 sm:grid-cols-2">
      <div className="sm:col-span-2">
        <dt className="font-semibold text-emerald-700 dark:text-emerald-200">
          {isDeploymentPolicyTest
            ? '배포 정책 기준 테스트'
            : isJudgeFirst
              ? 'Judge-first + 점진적 로컬 학습'
              : '기본 모델 실행'}
        </dt>
        <dd className="mt-1 text-gray-700 dark:text-gray-200">
          {isDeploymentPolicyTest
            ? '활성 배포 정책을 테스트에만 적용했습니다. 이 결과는 로컬 라우터 학습에 포함되지 않습니다.'
            : summary.decisionSource === 'runtime_judge'
              ? '이번 요청과 사용 가능한 후보 모델을 Judge가 함께 검토해 선택했습니다.'
              : summary.decisionSource === 'local_router'
                ? '누적된 Judge 선택을 학습한 로컬 라우터가 먼저 선택했습니다.'
                : 'Judge-first 정책을 적용할 수 없어 저장된 기본 모델로 실행했습니다.'}
        </dd>
      </div>

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

      {isJudgeFirst && summary.judge ? (
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
          <dd className="mt-2 grid gap-2 sm:grid-cols-2">
            <span className="rounded border border-violet-200 bg-white px-2 py-1">
              사유: {summary.judge.reasonShort || '-'}
            </span>
            <span className="rounded border border-violet-200 bg-white px-2 py-1">
              검토 후보 모델 {summary.judge.candidateModelCount ?? '-'}개
            </span>
          </dd>
          <dd className="mt-1 text-gray-500">
            판단 코드: {summary.judge.reasonCode || '-'}
            {summary.judge.cost === undefined
              ? ''
              : ` · Judge 비용 $${summary.judge.cost.toFixed(6)}`}
          </dd>
        </div>
      ) : null}

      {isJudgeFirst && summary.learningMode ? (
        <div className="sm:col-span-2 text-gray-500">
          학습 방식:{' '}
          {summary.learningMode === 'local_first'
            ? '로컬 라우터 우선'
            : 'Judge 학습 중'}
          {summary.localConfidence !== undefined
            ? ` · 로컬 확신도 ${(summary.localConfidence * 100).toFixed(1)}%`
            : ''}
          {summary.localConfidenceThreshold !== undefined
            ? ` · 선택 기준 ${(summary.localConfidenceThreshold * 100).toFixed(1)}%`
            : ''}
        </div>
      ) : null}

      {isJudgeFirst && summary.learningStatus === 'pending_contract' ? (
        <div className="sm:col-span-2 rounded-md border border-sky-200 bg-sky-50 p-3 text-sky-950 dark:border-sky-900 dark:bg-sky-950/20 dark:text-sky-100">
          실행 결과 계약을 확인한 뒤 학습에 반영합니다.
        </div>
      ) : null}
      {isJudgeFirst && summary.learningStatus === 'accepted' ? (
        <div className="sm:col-span-2 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-emerald-950 dark:border-emerald-900 dark:bg-emerald-950/20 dark:text-emerald-100">
          스키마와 후속 단계 조건을 통과해 이 선택을 로컬 학습에 반영했습니다.
        </div>
      ) : null}
      {isJudgeFirst && summary.learningStatus === 'rejected' ? (
        <div className="sm:col-span-2 rounded-md border border-rose-200 bg-rose-50 p-3 text-rose-950 dark:border-rose-900 dark:bg-rose-950/20 dark:text-rose-100">
          {summary.learningOutcomeReason === 'schema_failed'
            ? '스키마 또는 후속 단계 조건을 통과하지 못해 학습에서 제외되었습니다.'
            : '실행 계약을 통과하지 못해 학습에서 제외되었습니다.'}
        </div>
      ) : null}

      {summary.policyVersion ? (
        <div className="sm:col-span-2 text-gray-500">
          정책 버전: {summary.policyVersion}
        </div>
      ) : null}
      {summary.judgeCalled === false ? (
        <div className="sm:col-span-2 text-gray-500">
          실행 중 Judge 호출 안 함
        </div>
      ) : null}
    </dl>
  );
}
