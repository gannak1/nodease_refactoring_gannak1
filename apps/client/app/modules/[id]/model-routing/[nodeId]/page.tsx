'use client';

import { useEffect, useMemo, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  FlaskConical,
  History,
  Loader2,
  Route,
  Sparkles,
  Timer,
} from 'lucide-react';

import { workflowApi } from '@/app/features/workflow/api/workflowApi';
import type {
  CostOptimizerBaselineRow,
  CostOptimizerCandidateSummary,
  CostOptimizerExperimentSummary,
} from '@/app/features/workflow/types/Api';

type RoutingStrategy = 'auto' | 'price' | 'latency';
type RecommendationStatus =
  | 'select_strategy'
  | 'unavailable'
  | 'verification_required'
  | 'ready';

type CandidateEvidence = {
  experiment: CostOptimizerExperimentSummary;
  candidate: CostOptimizerCandidateSummary;
  baselineCost: number | null;
  baselineTokens: number | null;
  baselineLatencyMs: number | null;
  costReductionRate: number | null;
  tokenReductionRate: number | null;
  latencyReductionRate: number | null;
  latencyChangeMs: number | null;
};

type RecommendationState = {
  status: RecommendationStatus;
  title: string;
  description: string;
  evidence: CandidateEvidence | null;
};

const strategyOptions: Array<{
  id: RoutingStrategy;
  title: string;
  description: string;
}> = [
  {
    id: 'auto',
    title: '자동 균형',
    description: '비용, 지연 시간, schema/downstream 안정성을 함께 봅니다.',
  },
  {
    id: 'price',
    title: '비용 우선',
    description: '품질 gate를 통과한 후보 중 비용 절감 폭을 가장 크게 봅니다.',
  },
  {
    id: 'latency',
    title: '속도 우선',
    description: '품질 gate를 통과한 후보 중 지연 시간 개선을 우선합니다.',
  },
];

const routeParam = (value: string | string[] | undefined) =>
  Array.isArray(value) ? value[0] : value || '';

const readNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null;

const formatCost = (value: number | null | undefined) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-';
  return `$${value.toFixed(6).replace(/0+$/, '').replace(/\.$/, '')}`;
};

const formatMetric = (value: number | null | undefined, suffix = '') => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-';
  return `${value.toLocaleString('ko-KR')}${suffix}`;
};

const formatLatency = (value: number | null | undefined) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-';
  if (Math.abs(value) < 1000) return `${Math.round(value)}ms`;
  return `${(value / 1000).toFixed(1)}s`;
};

const formatRate = (value: number | null | undefined) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-';
  return `${Math.round(value * 1000) / 10}%`;
};

const formatSignedLatency = (value: number | null | undefined) => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-';
  const prefix = value > 0 ? '+' : '';
  return `${prefix}${formatLatency(value)}`;
};

const formatDate = (value: string | null | undefined) => {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
};

const qualityLabelOf = (candidate: CostOptimizerCandidateSummary) => {
  if (candidate.status !== 'success') return '실패 후보';
  if (candidate.schema_status === 'failed') return 'Schema 실패';
  if (candidate.downstream_state === 'incompatible') return '후속 노드 위험';
  if (candidate.schema_status === 'pass') return 'Schema 통과';
  if (candidate.downstream_state === 'compatible') return '후속 노드 호환';
  return '추가 검증 필요';
};

const hasQualityGate = (candidate: CostOptimizerCandidateSummary) => {
  if (candidate.status !== 'success') return false;
  if (candidate.schema_status === 'failed') return false;
  if (candidate.downstream_state === 'incompatible') return false;
  return true;
};

const isLowerCostCandidate = (
  candidate: CostOptimizerCandidateSummary,
  baselineCost: number | null,
) => {
  const candidateCost = readNumber(candidate.total_cost);
  if (!hasQualityGate(candidate)) return false;
  if (baselineCost === null || candidateCost === null) return false;
  return candidateCost < baselineCost;
};

const candidateEvidenceFromExperiments = (
  experiments: CostOptimizerExperimentSummary[],
  latestBaseline: CostOptimizerBaselineRow | null,
) =>
  experiments.flatMap((experiment) => {
    const baselineCost =
      readNumber(experiment.baseline_summary?.cost) ??
      readNumber(latestBaseline?.cost);
    const baselineTokens =
      readNumber(experiment.baseline_summary?.total_tokens) ??
      readNumber(latestBaseline?.total_tokens);
    const baselineLatencyMs =
      readNumber(experiment.baseline_summary?.latency_ms) ??
      readNumber(latestBaseline?.latency_ms);

    return experiment.candidates
      .filter((candidate) => isLowerCostCandidate(candidate, baselineCost))
      .map((candidate) => {
        const candidateCost = readNumber(candidate.total_cost);
        const candidateTokens = readNumber(candidate.total_tokens);
        const candidateLatencyMs = readNumber(candidate.latency_ms);
        return {
          experiment,
          candidate,
          baselineCost,
          baselineTokens,
          baselineLatencyMs,
          costReductionRate:
            baselineCost && candidateCost !== null
              ? (baselineCost - candidateCost) / baselineCost
              : null,
          tokenReductionRate:
            baselineTokens && candidateTokens !== null
              ? (baselineTokens - candidateTokens) / baselineTokens
              : null,
          latencyReductionRate:
            baselineLatencyMs && candidateLatencyMs !== null
              ? (baselineLatencyMs - candidateLatencyMs) / baselineLatencyMs
              : null,
          latencyChangeMs:
            baselineLatencyMs !== null && candidateLatencyMs !== null
              ? candidateLatencyMs - baselineLatencyMs
              : null,
        };
      });
  });

const scoreEvidence = (
  evidence: CandidateEvidence,
  strategy: RoutingStrategy,
) => {
  const cost = evidence.costReductionRate ?? -1;
  const tokens = evidence.tokenReductionRate ?? 0;
  const latency = evidence.latencyReductionRate ?? -0.25;

  if (strategy === 'price') {
    return cost * 100 + Math.max(latency, -0.5) * 10 + tokens * 5;
  }
  if (strategy === 'latency') {
    return latency * 100 + cost * 30 + tokens * 5;
  }
  return cost * 50 + Math.max(latency, -0.5) * 25 + tokens * 10;
};

const selectEvidence = (
  experiments: CostOptimizerExperimentSummary[],
  latestBaseline: CostOptimizerBaselineRow | null,
  strategy: RoutingStrategy,
) => {
  const evidences = candidateEvidenceFromExperiments(
    experiments,
    latestBaseline,
  );

  return (
    evidences.sort(
      (a, b) => scoreEvidence(b, strategy) - scoreEvidence(a, strategy),
    )[0] ?? null
  );
};

const buildRecommendationState = (
  strategy: RoutingStrategy | null,
  latestBaseline: CostOptimizerBaselineRow | null,
  experiments: CostOptimizerExperimentSummary[],
): RecommendationState => {
  if (!strategy) {
    return {
      status: 'select_strategy',
      title: '라우팅 전략을 선택하세요',
      description:
        '모델 추천은 비용, 속도, 안정성 중 무엇을 우선할지 정한 뒤 계산합니다.',
      evidence: null,
    };
  }

  if (!latestBaseline) {
    return {
      status: 'unavailable',
      title: '분석할 운영 로그가 없습니다',
      description:
        '배포 후 target LLM 노드의 성공 실행 로그가 있어야 현재 모델의 기준 비용과 지연 시간을 잡을 수 있습니다.',
      evidence: null,
    };
  }

  const evidence = selectEvidence(experiments, latestBaseline, strategy);

  if (!evidence) {
    return {
      status: 'verification_required',
      title: '후보 검증이 먼저 필요합니다',
      description:
        '현재 운영 로그는 기존 모델의 성능만 보여줍니다. 대체 모델이 같은 입력에서 품질을 유지하는지는 후보 실험을 실행해야 확인할 수 있습니다.',
      evidence: null,
    };
  }

  return {
    status: 'ready',
    title: '적용 검토 가능한 추천 후보가 있습니다',
    description:
      '성공한 후보 실험 중 비용이 더 낮고 schema/downstream 치명 문제가 없는 후보를 찾았습니다.',
    evidence,
  };
};

const statusStyle = (status: RecommendationStatus) => {
  if (status === 'ready') {
    return {
      card: 'border-emerald-200 bg-emerald-50 text-emerald-900',
      pill: 'bg-emerald-100 text-emerald-800',
      icon: <CheckCircle2 className="h-4 w-4" />,
      label: '적용 검토 가능',
    };
  }
  if (status === 'verification_required') {
    return {
      card: 'border-amber-200 bg-amber-50 text-amber-900',
      pill: 'bg-amber-100 text-amber-800',
      icon: <AlertTriangle className="h-4 w-4" />,
      label: '후보 검증 필요',
    };
  }
  if (status === 'unavailable') {
    return {
      card: 'border-red-200 bg-red-50 text-red-900',
      pill: 'bg-red-100 text-red-800',
      icon: <AlertTriangle className="h-4 w-4" />,
      label: '분석 불가',
    };
  }
  return {
    card: 'border-blue-200 bg-blue-50 text-blue-900',
    pill: 'bg-blue-100 text-blue-800',
    icon: <Sparkles className="h-4 w-4" />,
    label: '전략 선택',
  };
};

export default function ModelRoutingOptimizationPage() {
  const params = useParams();
  const router = useRouter();
  const workflowId = routeParam(params.id);
  const nodeId = routeParam(params.nodeId);
  const [latestBaseline, setLatestBaseline] =
    useState<CostOptimizerBaselineRow | null>(null);
  const [experiments, setExperiments] = useState<CostOptimizerExperimentSummary[]>(
    [],
  );
  const [selectedStrategy, setSelectedStrategy] =
    useState<RoutingStrategy | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    const load = async () => {
      setIsLoading(true);
      setErrorMessage(null);
      try {
        const [latestResult, historyResult] = await Promise.allSettled([
          workflowApi.getCostOptimizerLatestBaseline(workflowId, nodeId),
          workflowApi.listCostOptimizerExperiments(workflowId, nodeId, {
            limit: 50,
            offset: 0,
          }),
        ]);

        if (!active) return;

        setLatestBaseline(
          latestResult.status === 'fulfilled' ? latestResult.value.baseline : null,
        );
        setExperiments(
          historyResult.status === 'fulfilled' ? historyResult.value.items : [],
        );

        if (
          latestResult.status === 'rejected' &&
          historyResult.status === 'rejected'
        ) {
          setErrorMessage('운영 로그와 이전 후보 실험 이력을 불러오지 못했습니다.');
        }
      } finally {
        if (active) setIsLoading(false);
      }
    };

    if (workflowId && nodeId) {
      void load();
    }

    return () => {
      active = false;
    };
  }, [nodeId, workflowId]);

  const recommendation = useMemo(
    () => buildRecommendationState(selectedStrategy, latestBaseline, experiments),
    [experiments, latestBaseline, selectedStrategy],
  );
  const style = statusStyle(recommendation.status);
  const currentModel = latestBaseline?.model || '최근 운영 모델 없음';
  const successfulCandidates = experiments.reduce(
    (count, experiment) =>
      count +
      experiment.candidates.filter((candidate) => candidate.status === 'success')
        .length,
    0,
  );
  const qualityCandidates = candidateEvidenceFromExperiments(
    experiments,
    latestBaseline,
  );
  const evidence = recommendation.evidence;

  return (
    <main className="min-h-screen bg-slate-100 text-slate-950">
      <header className="border-b border-slate-200 bg-white px-6 py-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => router.push(`/modules/${workflowId}?node=${nodeId}`)}
              className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50"
            >
              <ArrowLeft className="h-4 w-4" />
              노드로 돌아가기
            </button>
            <div>
              <div className="text-xs font-bold uppercase tracking-wide text-emerald-700">
                Model Routing Optimization
              </div>
              <h1 className="text-xl font-bold text-slate-950">
                모델 라우팅 최적화
              </h1>
              <p className="text-xs font-medium text-slate-500">
                {workflowId} · {nodeId}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() =>
              router.push(`/modules/${workflowId}/cost-optimizer/${nodeId}`)
            }
            className="inline-flex items-center gap-2 rounded-md border border-emerald-600 bg-emerald-600 px-3 py-2 text-sm font-bold text-white shadow-sm hover:bg-emerald-700"
          >
            <FlaskConical className="h-4 w-4" />
            후보 실험 만들기
          </button>
        </div>
      </header>

      <section className="mx-auto flex w-full max-w-7xl flex-col gap-4 px-6 py-6">
        {errorMessage ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
            {errorMessage}
          </div>
        ) : null}

        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-700">
                <Route className="h-3.5 w-3.5" />
                사용자 클릭 기반 추천
              </div>
              <h2 className="mt-3 text-lg font-bold text-slate-950">
                전략을 선택하면 운영 로그와 후보 실험 이력을 분석합니다
              </h2>
              <p className="mt-1 max-w-3xl text-sm leading-relaxed text-slate-600">
                기존 운영 로그만으로는 대체 모델의 품질을 알 수 없습니다. 따라서
                후보 실험이 없는 경우에는 모델을 바로 추천하지 않고 검증 필요
                상태로 안내합니다.
              </p>
            </div>
            {isLoading ? (
              <span className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1.5 text-xs font-bold text-slate-600">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                분석 데이터 로딩 중
              </span>
            ) : (
              <span
                className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-bold ${style.pill}`}
              >
                {style.icon}
                {style.label}
              </span>
            )}
          </div>
        </section>

        <section className="grid gap-3 md:grid-cols-3">
          {strategyOptions.map((strategy) => (
            <button
              key={strategy.id}
              type="button"
              onClick={() => setSelectedStrategy(strategy.id)}
              className={`rounded-lg border p-4 text-left shadow-sm transition ${
                selectedStrategy === strategy.id
                  ? 'border-emerald-500 bg-emerald-50 ring-2 ring-emerald-100'
                  : 'border-slate-200 bg-white hover:border-emerald-300 hover:bg-emerald-50/40'
              }`}
            >
              <div className="text-sm font-bold text-slate-950">
                {strategy.title}
              </div>
              <p className="mt-1 text-xs leading-relaxed text-slate-600">
                {strategy.description}
              </p>
            </button>
          ))}
        </section>

        <section className="grid gap-4 lg:grid-cols-3">
          <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <div className="text-xs font-bold uppercase tracking-wide text-slate-400">
              현재 운영 기준
            </div>
            <div className="mt-3 text-lg font-bold text-slate-950">
              {currentModel}
            </div>
            <dl className="mt-4 grid gap-2 text-sm">
              <div className="flex justify-between gap-3">
                <dt className="text-slate-500">최근 로그</dt>
                <dd className="font-semibold text-slate-800">
                  {latestBaseline
                    ? formatDate(latestBaseline.run_started_at)
                    : '없음'}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-slate-500">비용</dt>
                <dd className="font-semibold text-slate-800">
                  {formatCost(latestBaseline?.cost)}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-slate-500">토큰</dt>
                <dd className="font-semibold text-slate-800">
                  {formatMetric(latestBaseline?.total_tokens)}
                </dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-slate-500">실행 시간</dt>
                <dd className="font-semibold text-slate-800">
                  {formatLatency(latestBaseline?.latency_ms)}
                </dd>
              </div>
            </dl>
          </div>

          <div
            className={`rounded-lg border p-4 shadow-sm lg:col-span-2 ${style.card}`}
          >
            <div className="flex items-center gap-2 text-sm font-bold">
              {style.icon}
              추천 상태
            </div>
            <h3 className="mt-3 text-xl font-bold">{recommendation.title}</h3>
            <p className="mt-2 text-sm leading-relaxed">
              {recommendation.description}
            </p>

            {evidence ? (
              <div className="mt-5 grid gap-4 md:grid-cols-[1fr_1.35fr]">
                <div>
                  <div className="text-xs font-bold uppercase tracking-wide opacity-70">
                    추천 후보
                  </div>
                  <div className="mt-2 text-2xl font-bold">
                    {evidence.candidate.model_id || '후보 모델'}
                  </div>
                  <p className="mt-2 text-sm leading-relaxed opacity-80">
                    {qualityLabelOf(evidence.candidate)} 후보입니다. 바로 자동
                    적용하지 않고, 기존 후보 실험 결과를 확인한 뒤 적용을
                    검토합니다.
                  </p>
                </div>
                <dl className="grid gap-2 text-sm">
                  <div className="flex justify-between gap-3 rounded-md bg-white/70 px-3 py-2">
                    <dt className="font-semibold">예상 비용 절감</dt>
                    <dd className="font-bold">
                      {formatRate(evidence.costReductionRate)}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-3 rounded-md bg-white/70 px-3 py-2">
                    <dt className="font-semibold">토큰 변화</dt>
                    <dd className="font-bold">
                      {formatRate(evidence.tokenReductionRate)}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-3 rounded-md bg-white/70 px-3 py-2">
                    <dt className="font-semibold">실행 시간 변화</dt>
                    <dd className="font-bold">
                      {formatSignedLatency(evidence.latencyChangeMs)}
                    </dd>
                  </div>
                  <div className="flex justify-between gap-3 rounded-md bg-white/70 px-3 py-2">
                    <dt className="font-semibold">Judge</dt>
                    <dd className="font-bold">
                      {evidence.candidate.schema_status === 'pass' ||
                      evidence.candidate.downstream_state === 'compatible'
                        ? '필요 시 표본 평가'
                        : '적용 전 평가 권장'}
                    </dd>
                  </div>
                </dl>
              </div>
            ) : null}

            <div className="mt-5 flex flex-wrap gap-2">
              {recommendation.status === 'ready' ? (
                <button
                  type="button"
                  onClick={() =>
                    router.push(`/modules/${workflowId}/cost-optimizer/${nodeId}`)
                  }
                  className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-3 py-2 text-sm font-bold text-white shadow-sm hover:bg-emerald-700"
                >
                  <CheckCircle2 className="h-4 w-4" />
                  A/B 결과에서 적용 검토
                </button>
              ) : null}
              {recommendation.status === 'verification_required' ? (
                <button
                  type="button"
                  onClick={() =>
                    router.push(`/modules/${workflowId}/cost-optimizer/${nodeId}`)
                  }
                  className="inline-flex items-center gap-2 rounded-md bg-amber-600 px-3 py-2 text-sm font-bold text-white shadow-sm hover:bg-amber-700"
                >
                  <FlaskConical className="h-4 w-4" />
                  후보 실험 실행
                </button>
              ) : null}
            </div>
          </div>
        </section>

        <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="grid gap-3 md:grid-cols-3">
            <div className="rounded-md bg-slate-50 p-3">
              <div className="text-xs font-bold text-slate-500">후보 실험</div>
              <div className="mt-1 text-xl font-bold text-slate-950">
                {experiments.length}
              </div>
            </div>
            <div className="rounded-md bg-slate-50 p-3">
              <div className="text-xs font-bold text-slate-500">성공 후보</div>
              <div className="mt-1 text-xl font-bold text-slate-950">
                {successfulCandidates}
              </div>
            </div>
            <div className="rounded-md bg-slate-50 p-3">
              <div className="text-xs font-bold text-slate-500">
                추천 가능 후보
              </div>
              <div className="mt-1 text-xl font-bold text-slate-950">
                {qualityCandidates.length}
              </div>
            </div>
          </div>
        </section>

        <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm font-bold text-slate-950">
              <History className="h-4 w-4 text-slate-500" />
              후보 실험 이력
            </div>
            <span className="text-xs font-semibold text-slate-500">
              추천은 성공, 비용 절감, schema/downstream gate를 통과한 후보만
              사용합니다.
            </span>
          </div>

          <div className="mt-4 overflow-x-auto rounded-md border border-slate-200">
            <table className="w-full min-w-[760px] text-left text-sm">
              <thead className="bg-slate-50 text-xs font-bold text-slate-500">
                <tr>
                  <th className="px-3 py-2">실행 시각</th>
                  <th className="px-3 py-2">모델</th>
                  <th className="px-3 py-2">비용</th>
                  <th className="px-3 py-2">토큰</th>
                  <th className="px-3 py-2">시간</th>
                  <th className="px-3 py-2">품질 근거</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {experiments.flatMap((experiment) =>
                  experiment.candidates.map((candidate) => (
                    <tr key={`${experiment.experiment_id}-${candidate.candidate_id}`}>
                      <td className="px-3 py-2 text-slate-600">
                        {formatDate(candidate.created_at || experiment.created_at)}
                      </td>
                      <td className="px-3 py-2 font-semibold text-slate-950">
                        {candidate.model_id || '-'}
                      </td>
                      <td className="px-3 py-2">{formatCost(candidate.total_cost)}</td>
                      <td className="px-3 py-2">
                        {formatMetric(candidate.total_tokens)}
                      </td>
                      <td className="px-3 py-2">
                        {formatLatency(candidate.latency_ms)}
                      </td>
                      <td className="px-3 py-2">
                        <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-bold text-slate-600">
                          {qualityLabelOf(candidate)}
                        </span>
                      </td>
                    </tr>
                  )),
                )}
                {!isLoading && experiments.length === 0 ? (
                  <tr>
                    <td
                      colSpan={6}
                      className="px-3 py-8 text-center text-sm text-slate-500"
                    >
                      아직 분석할 후보 실험 이력이 없습니다.
                    </td>
                  </tr>
                ) : null}
                {isLoading ? (
                  <tr>
                    <td
                      colSpan={6}
                      className="px-3 py-8 text-center text-sm text-slate-500"
                    >
                      <span className="inline-flex items-center gap-2">
                        <Timer className="h-4 w-4 animate-pulse" />
                        이력을 불러오는 중입니다.
                      </span>
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>
      </section>
    </main>
  );
}
