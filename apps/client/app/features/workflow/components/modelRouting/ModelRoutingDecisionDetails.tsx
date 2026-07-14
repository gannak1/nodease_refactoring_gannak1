type ModelRoutingSummary = {
  selectedModel?: string;
  fallbackModel?: string;
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
  semanticMatchStatus?: string;
  semanticDecisionSource?: string;
  semanticLexicalScore?: number;
  semanticLexicalSignalCount?: number;
  semanticSafetyOverride?: boolean;
  routeCatalogVersion?: string;
  judgeCalled?: boolean;
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
  const summary = {
    selectedModel:
      stringValue(routing.selected_model) ||
      stringValue(outputRecord?.model),
    fallbackModel: stringValue(routing.fallback_model),
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
    semanticMatchStatus: stringValue(routing.semantic_match_status),
    semanticDecisionSource: stringValue(routing.semantic_decision_source),
    semanticLexicalScore: numberValue(routing.semantic_lexical_score),
    semanticLexicalSignalCount: numberValue(
      routing.semantic_lexical_signal_count,
    ),
    semanticSafetyOverride: booleanValue(routing.semantic_safety_override),
    routeCatalogVersion: stringValue(routing.route_catalog_version),
    judgeCalled: booleanValue(routing.judge_called),
  };

  return summary.selectedModel || summary.decisionSource || summary.reasonCode
    ? summary
    : null;
};

const formatRoutingPercent = (value: number): string =>
  `${Math.round(value * 1000) / 10}%`;

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

  return (
    <dl className="grid gap-3 rounded-lg border border-emerald-100 bg-emerald-50/50 px-4 py-3 text-xs dark:border-emerald-900 dark:bg-emerald-950/20 sm:grid-cols-2">
      <div className="sm:col-span-2">
        <dt className="font-semibold text-emerald-700 dark:text-emerald-200">
          자동 라우팅
        </dt>
        <dd className="mt-1 text-gray-700 dark:text-gray-200">
          실제 실행에서 선택된 모델과 라우팅 근거입니다.
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
      <div>
        <dt className="text-gray-500">선택 모델</dt>
        <dd className="mt-1 font-semibold text-gray-900 dark:text-gray-100">
          {summary.selectedModel || '-'}
        </dd>
      </div>
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
            호출 실패 시 검증된 {summary.fallbackModel} 모델로 한 번
            전환합니다.
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
