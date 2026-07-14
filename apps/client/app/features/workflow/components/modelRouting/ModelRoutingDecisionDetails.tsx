type ModelRoutingSummary = {
  selectedModel?: string;
  fallbackModel?: string;
  fallbackUsed?: boolean;
  fallbackFromModel?: string;
  fallbackReasonCode?: string;
  actualModel?: string;
  decisionSource?: string;
  reasonCode?: string;
  policyVersion?: string;
  matchedRuleId?: string;
  matchedCohortId?: string;
  semanticRouteLabel?: string;
  semanticCandidateCohortId?: string;
  semanticCandidateLabel?: string;
  semanticSimilarity?: number;
  semanticThreshold?: number;
  semanticRunnerUpScore?: number;
  semanticMargin?: number;
  semanticMinMargin?: number;
  semanticCohortScores: SemanticCohortScore[];
  semanticMatchStatus?: string;
  semanticDecisionSource?: string;
  semanticLexicalScore?: number;
  semanticLexicalSignalCount?: number;
  semanticSafetyOverride?: boolean;
  routeCatalogVersion?: string;
  judgeCalled?: boolean;
  policySource?: string;
  includedInPolicyLearning?: boolean;
};

type SemanticCohortScore = {
  cohortId: string;
  label: string;
  similarity: number;
  threshold: number;
};

type ModelRoutingDecisionDetailsProps = {
  output?: unknown;
  traceMetadata?: unknown;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const stringValue = (value: unknown): string | undefined =>
  typeof value === 'string' && value.trim().length > 0
    ? value.trim()
    : undefined;

const numberValue = (value: unknown): number | undefined =>
  typeof value === 'number' && Number.isFinite(value) ? value : undefined;

const booleanValue = (value: unknown): boolean | undefined =>
  typeof value === 'boolean' ? value : undefined;

const semanticCohortScoresOf = (value: unknown): SemanticCohortScore[] => {
  if (!Array.isArray(value)) return [];

  return value.flatMap((item) => {
    if (!isRecord(item)) return [];
    const cohortId = stringValue(item.cohort_id);
    const label = stringValue(item.label);
    const similarity = numberValue(item.similarity);
    const threshold = numberValue(item.threshold);

    return cohortId &&
      label &&
      similarity !== undefined &&
      threshold !== undefined
      ? [{ cohortId, label, similarity, threshold }]
      : [];
  });
};

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
  return metadata && isRecord(metadata.model_routing_metadata)
    ? metadata.model_routing_metadata
    : null;
};

const modelRoutingSummaryOf = ({
  output,
  traceMetadata,
}: ModelRoutingDecisionDetailsProps): ModelRoutingSummary | null => {
  const routing = routingRecordOf(output, traceMetadata);
  if (!routing) return null;
  const outputRecord = isRecord(output) ? output : null;
  const outputMetadata = isRecord(outputRecord?.metadata)
    ? outputRecord.metadata
    : null;
  const summary = {
    selectedModel:
      stringValue(routing.selected_model) || stringValue(outputRecord?.model),
    fallbackModel: stringValue(routing.fallback_model),
    fallbackUsed:
      booleanValue(routing.fallback_used) ??
      booleanValue(outputMetadata?.fallback_used),
    fallbackFromModel: stringValue(routing.fallback_from_model),
    fallbackReasonCode: stringValue(routing.fallback_reason_code),
    actualModel: stringValue(outputRecord?.model),
    decisionSource: stringValue(routing.decision_source),
    reasonCode: stringValue(routing.reason_code),
    policyVersion: stringValue(routing.policy_version),
    matchedRuleId: stringValue(routing.matched_rule_id),
    matchedCohortId: stringValue(routing.matched_cohort_id),
    semanticRouteLabel: stringValue(routing.semantic_route_label),
    semanticCandidateCohortId: stringValue(
      routing.semantic_candidate_cohort_id,
    ),
    semanticCandidateLabel: stringValue(routing.semantic_candidate_label),
    semanticSimilarity: numberValue(routing.semantic_similarity),
    semanticThreshold: numberValue(routing.semantic_threshold),
    semanticRunnerUpScore: numberValue(routing.semantic_runner_up_score),
    semanticMargin: numberValue(routing.semantic_margin),
    semanticMinMargin: numberValue(routing.semantic_min_margin),
    semanticCohortScores: semanticCohortScoresOf(
      routing.semantic_cohort_scores,
    ),
    semanticMatchStatus: stringValue(routing.semantic_match_status),
    semanticDecisionSource: stringValue(routing.semantic_decision_source),
    semanticLexicalScore: numberValue(routing.semantic_lexical_score),
    semanticLexicalSignalCount: numberValue(
      routing.semantic_lexical_signal_count,
    ),
    semanticSafetyOverride: booleanValue(routing.semantic_safety_override),
    routeCatalogVersion: stringValue(routing.route_catalog_version),
    judgeCalled: booleanValue(routing.judge_called),
    policySource: stringValue(routing.policy_source),
    includedInPolicyLearning: booleanValue(routing.included_in_policy_learning),
  };

  return summary.selectedModel || summary.decisionSource || summary.reasonCode
    ? summary
    : null;
};

const formatRoutingPercent = (value: number): string =>
  `${Math.round(value * 1000) / 10}%`;

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

const semanticJudgementText = (summary: ModelRoutingSummary): string => {
  if (
    summary.semanticDecisionSource === 'safety_override' &&
    summary.semanticSafetyOverride === true
  ) {
    const matchedCount = summary.semanticLexicalSignalCount;
    return matchedCount !== undefined && matchedCount > 0
      ? `정책의 안전 조건 ${matchedCount}개와 일치해 안전 유형을 우선했습니다.`
      : '정책의 안전 조건과 일치해 안전 유형을 우선했습니다.';
  }
  if (summary.semanticMatchStatus === 'ambiguous') {
    return '1위와 2위 의미 점수 차이가 안전 기준보다 작아 기본 모델을 유지했습니다.';
  }
  if (summary.semanticMatchStatus === 'no_match') {
    if (
      summary.semanticSimilarity !== undefined &&
      summary.semanticThreshold !== undefined
    ) {
      return `유사도 ${formatRoutingPercent(summary.semanticSimilarity)}가 선택 기준 ${formatRoutingPercent(summary.semanticThreshold)}에 미달해 기본 모델을 유지했습니다.`;
    }
    return '선택 기준을 통과한 입력 유형이 없어 기본 모델을 유지했습니다.';
  }
  if (summary.semanticMatchStatus === 'unavailable') {
    return '입력 유형을 안전하게 판정하지 못해 기본 모델을 유지했습니다.';
  }
  if (
    summary.semanticMatchStatus === 'matched' &&
    summary.semanticSimilarity !== undefined &&
    summary.semanticThreshold !== undefined
  ) {
    const margin =
      summary.semanticMargin ??
      (summary.semanticRunnerUpScore !== undefined
        ? summary.semanticSimilarity - summary.semanticRunnerUpScore
        : undefined);
    const marginText =
      margin !== undefined
        ? `, 2위와 차이 ${formatRoutingPercent(margin)}p`
        : '';
    return `유사도 ${formatRoutingPercent(summary.semanticSimilarity)} (선택 기준 ${formatRoutingPercent(summary.semanticThreshold)}${marginText})`;
  }
  return '저장된 라우팅 정책의 조건을 적용했습니다.';
};

const routingReasonText = (summary: ModelRoutingSummary): string => {
  if (summary.reasonCode === 'active_policy_unavailable') {
    return summary.policySource === 'active_deployment'
      ? '현재 draft와 같은 활성 배포 정책이 아직 없어 저장 모델을 사용했습니다.'
      : '사용할 수 있는 활성 정책이 없어 저장 모델을 사용했습니다.';
  }
  if (
    summary.semanticDecisionSource === 'safety_override' &&
    summary.semanticSafetyOverride === true
  ) {
    return '비용 절감보다 사고 대응 품질을 우선해 검증된 모델을 선택했습니다.';
  }
  if (
    ['ambiguous', 'no_match', 'unavailable'].includes(
      summary.semanticMatchStatus || '',
    )
  ) {
    return '애매한 입력을 저비용 모델로 보내지 않는 보수적 정책입니다.';
  }
  const reasonCode = summary.reasonCode || '';
  if (
    reasonCode.includes('cost') ||
    reasonCode.includes('low_cost') ||
    reasonCode.includes('positive_net_saving')
  ) {
    return '이 입력 유형에서 품질 기준을 통과한 모델 중 예상 비용이 가장 낮습니다.';
  }
  if (reasonCode.includes('quality') || reasonCode.includes('high_risk')) {
    return '이 입력 유형은 결과 품질 보호가 우선이라 검증된 모델을 선택했습니다.';
  }
  return '검증된 라우팅 정책의 입력 유형 조건에 따라 모델을 선택했습니다.';
};

export function ModelRoutingDecisionDetails({
  output,
  traceMetadata,
}: ModelRoutingDecisionDetailsProps) {
  const summary = modelRoutingSummaryOf({ output, traceMetadata });
  if (!summary) return null;

  const routeLabel =
    summary.semanticMatchStatus === 'matched' && summary.semanticRouteLabel
      ? summary.semanticRouteLabel
      : summary.semanticMatchStatus
        ? '명확히 분류하지 못함'
        : undefined;
  const isDeploymentPolicyTest =
    summary.policySource === 'active_deployment' &&
    summary.includedInPolicyLearning === false;

  return (
    <dl className="grid gap-3 rounded-lg border border-emerald-100 bg-emerald-50/50 px-4 py-3 text-xs dark:border-emerald-900 dark:bg-emerald-950/20 sm:grid-cols-2">
      <div className="sm:col-span-2">
        <dt className="font-semibold text-emerald-700 dark:text-emerald-200">
          {isDeploymentPolicyTest ? '배포 정책 기준 테스트' : '자동 라우팅'}
        </dt>
        <dd className="mt-1 text-gray-700 dark:text-gray-200">
          {isDeploymentPolicyTest
            ? '활성 배포의 저장 정책을 테스트 실행에만 적용했습니다. 이 결과는 정책 학습에 포함되지 않습니다.'
            : '실제 실행에서 선택된 모델과 라우팅 근거입니다.'}
        </dd>
      </div>
      {routeLabel ? (
        <div>
          <dt className="text-gray-500">입력 유형</dt>
          <dd className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
            {routeLabel}
          </dd>
        </div>
      ) : null}
      {summary.semanticMatchStatus !== 'matched' &&
      summary.semanticCandidateLabel ? (
        <div>
          <dt className="text-gray-500">가장 가까운 유형</dt>
          <dd className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
            {summary.semanticCandidateLabel}
          </dd>
        </div>
      ) : null}
      {['ambiguous', 'no_match', 'unavailable'].includes(
        summary.semanticMatchStatus || '',
      ) ? (
        <div>
          <dt className="text-gray-500">매칭 결과</dt>
          <dd className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
            기준 미달로 기본 모델 사용
          </dd>
        </div>
      ) : null}
      <div>
        <dt className="text-gray-500">선택 모델</dt>
        <dd className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
          {summary.selectedModel || '-'}
        </dd>
      </div>
      {summary.semanticCohortScores.length > 0 ? (
        <div className="sm:col-span-2">
          <dt className="text-gray-500">입력군별 유사도</dt>
          <dd className="mt-2 space-y-2">
            {summary.semanticCohortScores.map((cohort, index) => {
              const isMatched =
                summary.semanticMatchStatus === 'matched' &&
                cohort.cohortId === summary.matchedCohortId;
              const isClosest = !isMatched && index === 0;

              return (
                <div
                  key={cohort.cohortId}
                  className="flex items-center justify-between gap-3 rounded-md border border-emerald-100 bg-white/80 px-3 py-2 dark:border-emerald-900 dark:bg-gray-900/70"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-gray-500">{index + 1}위</span>
                      <span className="font-semibold text-gray-900 dark:text-gray-100">
                        {cohort.label}
                      </span>
                      {isMatched ? (
                        <span className="rounded-full bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200">
                          선택됨
                        </span>
                      ) : null}
                      {isClosest ? (
                        <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                          가장 가까움
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="font-semibold text-gray-900 dark:text-gray-100">
                      {formatRoutingPercent(cohort.similarity)}
                    </div>
                    <div className="mt-0.5 text-[10px] text-gray-500">
                      선택 기준 {formatRoutingPercent(cohort.threshold)}
                    </div>
                  </div>
                </div>
              );
            })}
          </dd>
          {summary.semanticMinMargin !== undefined ? (
            <dd className="mt-2 text-[11px] leading-relaxed text-gray-500">
              입력군을 선택하려면 1위와 2위 점수 차이가 최소{' '}
              {formatRoutingPercent(summary.semanticMinMargin)}p 이상이어야
              합니다.
            </dd>
          ) : null}
        </div>
      ) : null}
      <div className="sm:col-span-2">
        <dt className="text-gray-500">판정</dt>
        <dd className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
          {semanticJudgementText(summary)}
        </dd>
      </div>
      <div className="sm:col-span-2">
        <dt className="text-gray-500">선택 이유</dt>
        <dd className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
          {routingReasonText(summary)}
        </dd>
      </div>
      {summary.fallbackModel ? (
        <div className="sm:col-span-2">
          <dt className="text-gray-500">안전 장치</dt>
          <dd className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
            호출 실패 시 검증된 {summary.fallbackModel} 모델로 한 번 전환합니다.
          </dd>
        </div>
      ) : null}
      {summary.fallbackUsed ? (
        <div className="sm:col-span-2 rounded-md border border-amber-200 bg-amber-50 p-3 text-gray-900 dark:border-amber-800 dark:bg-amber-950/20 dark:text-gray-100">
          <dt className="font-semibold text-amber-800 dark:text-amber-200">
            실제 대체 실행
          </dt>
          <dd className="mt-1">
            최초 선택:{' '}
            {summary.fallbackFromModel || summary.selectedModel || '-'}
          </dd>
          <dd>사유: {fallbackReasonText(summary.fallbackReasonCode)}</dd>
          <dd>
            실제 사용: {summary.actualModel || summary.fallbackModel || '-'}
          </dd>
        </div>
      ) : null}
      {summary.policyVersion || summary.routeCatalogVersion ? (
        <div className="sm:col-span-2 flex flex-wrap gap-x-4 gap-y-1 text-gray-500">
          {summary.policyVersion ? (
            <span>정책 버전: {summary.policyVersion}</span>
          ) : null}
          {summary.routeCatalogVersion ? (
            <span>입력 유형 기준: {summary.routeCatalogVersion}</span>
          ) : null}
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
