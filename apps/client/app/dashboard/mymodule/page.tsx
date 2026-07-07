'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  AlertTriangle,
  CheckCircle2,
  DollarSign,
  Edit3,
  ExternalLink,
  Filter,
  Gauge,
  Layers3,
  Plus,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Sparkles,
  TrendingUp,
  Users,
  Wand2,
  X,
} from 'lucide-react';

import CreateAppModal from '@/app/features/app/components/create-app-modal';
import EditAppModal from '@/app/features/app/components/edit-app-modal';
import { appApi, type App } from '@/app/features/app/api/appApi';
import { BudgetStatusBadge } from '@/app/features/budget/components/BudgetStatusBadge';
import { budgetRunBlockMessage } from '@/app/features/budget/utils/budgetGuard';
import {
  moduleOperationsApi,
  type ModuleOperationRow,
  type ModuleOperationsListParams,
  type ModuleRunState,
} from '@/app/features/app/api/moduleOperationsApi';
import { apiClient } from '@/lib/apiClient';
import { workflowApi } from '@/app/features/workflow/api/workflowApi';
import type {
  CostOptimizerParameterRecommendationsResponse,
} from '@/app/features/workflow/types/Api';
import {
  DashboardPageHeader,
  DashboardPanel,
  DashboardSummaryCard,
} from '@/app/features/dashboard/components/DashboardSurface';

type PermissionFilter = 'all' | 'executable' | 'editable' | 'manageable';
type DeploymentFilter = 'all' | 'active' | 'inactive' | 'undeployed';
type RunFilter = 'all' | 'running' | 'failed';

const PAGE_SIZE = 100;

const runLabels: Record<ModuleRunState, string> = {
  running: '실행 중',
  success: '정상',
  failed: '오류',
  not_started: '기록 없음',
  unavailable: '확인 필요',
};

const deploymentLabels: Record<DeploymentFilter, string> = {
  all: '전체',
  active: '배포 중',
  inactive: '배포 꺼짐',
  undeployed: '미배포',
};

const deploymentTone: Record<Exclude<DeploymentFilter, 'all'>, string> = {
  active: 'border-green-200 bg-green-50 text-green-700',
  inactive: 'border-amber-200 bg-amber-50 text-amber-700',
  undeployed: 'border-slate-200 bg-slate-50 text-slate-600',
};

const runTone: Record<ModuleRunState, string> = {
  running: 'border-blue-200 bg-blue-50 text-blue-700',
  success: 'border-green-200 bg-green-50 text-green-700',
  failed: 'border-red-200 bg-red-50 text-red-700',
  not_started: 'border-slate-200 bg-slate-50 text-slate-600',
  unavailable: 'border-slate-200 bg-slate-50 text-slate-600',
};

const formatDate = (value?: string) => {
  if (!value) return '-';
  return new Date(value).toLocaleDateString('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
};

const formatCurrency = (value?: number | null) => {
  if (value == null) return '-';

  return `$${value.toLocaleString('en-US', {
    minimumFractionDigits: 3,
    maximumFractionDigits: 3,
  })}`;
};

type CostOptimizationSignal = {
  monthlyCost: number | null;
  trendPercent: number | null;
  budgetUsageRatio: number | null;
  recommended: boolean;
  reason: string;
};

const costSignalOf = (row: ModuleOperationRow): CostOptimizationSignal => {
  if (row.deploymentState !== 'active') {
    return {
      monthlyCost: 0,
      trendPercent: null,
      budgetUsageRatio: row.app.budget_status?.usage_ratio ?? null,
      recommended: false,
      reason: '배포 중인 워크플로우가 아닙니다.',
    };
  }

  const metrics = row.app.operation_metrics;
  const monthlyCost =
    metrics?.projected_month_cost ?? metrics?.current_month_cost ?? null;
  const trendPercent = metrics?.trend_percent ?? null;
  const budgetUsageRatio = row.app.budget_status?.usage_ratio ?? null;
  const budgetStatus = row.app.budget_status?.status;
  const hasCostData =
    metrics != null &&
    ((metrics.current_month_cost ?? 0) > 0 || (monthlyCost ?? 0) > 0);
  const budgetAtRisk = budgetStatus === 'at_risk' || budgetStatus === 'exceeded';
  const trendAtRisk = trendPercent != null && trendPercent >= 20;
  const recommended = budgetAtRisk || trendAtRisk;

  const reason = recommended
    ? budgetAtRisk
      ? budgetStatus === 'exceeded'
        ? '예산 초과'
        : '예산 초과 위험'
      : '전월 대비 비용 증가'
    : !hasCostData
      ? '운영 비용 데이터 없음'
      : trendPercent == null
        ? '전월 비교 데이터 없음'
        : '안정 범위';

  return {
    monthlyCost,
    trendPercent,
    budgetUsageRatio,
    recommended,
    reason,
  };
};

type LlmOptimizationNode = {
  id: string;
  title: string;
};

const extractWorkflowNodes = (
  workflow: unknown,
): Array<Record<string, unknown>> => {
  if (!workflow || typeof workflow !== 'object') return [];

  const candidate = workflow as {
    nodes?: unknown;
    graph?: { nodes?: unknown };
  };
  const nodes = candidate.nodes || candidate.graph?.nodes || [];

  return Array.isArray(nodes)
    ? nodes.filter((node): node is Record<string, unknown> =>
        Boolean(node && typeof node === 'object'),
      )
    : [];
};

const extractLlmOptimizationNodes = (
  workflow: unknown,
): LlmOptimizationNode[] =>
  extractWorkflowNodes(workflow)
    .filter((node) => node.type === 'llmNode')
    .map((node) => {
      const data =
        node.data && typeof node.data === 'object'
          ? (node.data as Record<string, unknown>)
          : {};

      return {
        id: String(node.id || ''),
        title: String(data.title || 'LLM 노드'),
      };
    })
    .filter((node) => node.id);

const parameterRecommendationLabelOf = (parameterKey: string) =>
  ({
    max_tokens: '최대 응답 길이 줄이기',
    temperature: '출력 안정성 높이기',
    top_p: 'Claude 호환 설정 정리',
    frequency_penalty: '반복 답변 줄이기',
    'rag.top_k': '검색 문서 개수 줄이기',
    'rag.retrieved_context_max_chars': '검색 문서 길이 제한하기',
    'rag.retrieved_context_compression': '검색 문서 압축 켜기',
  })[parameterKey] || parameterKey;

const parameterRecommendationTargetOf = (parameterKey: string) =>
  parameterKey.startsWith('rag.') ? '지식 베이스' : '고급 설정';

const formatRecommendationValue = (
  value: unknown,
  parameterKey?: string,
): string => {
  if (value == null) return '설정 없음';
  if (typeof value === 'number') {
    const formatted = value.toLocaleString('ko-KR');
    if (parameterKey === 'max_tokens') return `${formatted} 토큰`;
    if (parameterKey === 'rag.top_k') return `${formatted}개`;
    if (parameterKey === 'rag.retrieved_context_max_chars') {
      return `${formatted}자`;
    }
    return formatted;
  }
  if (typeof value === 'string') return value || '설정 없음';
  if (typeof value === 'boolean') return value ? '켜짐' : '꺼짐';
  return JSON.stringify(value);
};

const evidenceLabelOf = (key: string) =>
  ({
    sample_count: '운영 로그 수',
    completion_tokens_p95: '대부분의 최근 응답 길이',
    prompt_tokens_p95: '대부분의 최근 입력 길이',
    context_token_estimate_p95: '검색 문서가 차지한 길이',
    retrieved_chunk_count_p95: '불러온 검색 문서 수',
    schema_pass_rate: '스키마 통과율',
    downstream_success_rate: '후속 노드 성공률',
    schema_fail_rate: '스키마 실패율',
    downstream_fail_rate: '후속 노드 실패율',
    truncation_rate: '길이 잘림률',
    retry_rate: '재시도율',
    fallback_rate: 'Fallback 비율',
    repetition_rate: '반복률',
    model_family: '모델 계열',
    compatibility: '호환성',
  })[key] || key;

const formatEvidenceValue = (key: string, value: unknown) => {
  if (typeof value === 'number') {
    if (
      key.endsWith('_rate') ||
      key === 'schema_pass_rate' ||
      key === 'downstream_success_rate'
    ) {
      return `${Math.round(value * 1000) / 10}%`;
    }
    if (key === 'completion_tokens_p95' || key === 'prompt_tokens_p95') {
      return `${value.toLocaleString('ko-KR')}토큰 이하`;
    }
    if (key === 'context_token_estimate_p95') {
      return `${value.toLocaleString('ko-KR')}토큰 정도`;
    }
    if (key === 'retrieved_chunk_count_p95') {
      return `${value.toLocaleString('ko-KR')}개 정도`;
    }
    return value.toLocaleString('ko-KR');
  }
  if (typeof value === 'boolean') return value ? '예' : '아니오';
  if (value == null) return '-';
  return String(value);
};

type OrganizationResponse = {
  id: string;
  name: string;
  is_manager?: boolean;
};

const sourceLabelOf = (row: ModuleOperationRow) => {
  if (!row.app.workflow_id) return '권한 확인 대기';
  if (row.permissionSources.length === 0) return '권한 출처 없음';

  const [firstSource, ...rest] = row.permissionSources;
  const sourceName =
    firstSource.type === 'user'
      ? '개인 직접 권한'
      : firstSource.team_name || '권한 출처';

  return rest.length > 0 ? `${sourceName} 외 ${rest.length}개` : sourceName;
};

const canEditApp = (row: ModuleOperationRow, isOrgManager: boolean) =>
  isOrgManager ||
  (row.permissionStatus === 'loaded' && Boolean(row.permission?.can_manage));

const canToggleDeployment = (row: ModuleOperationRow) =>
  row.permissionStatus === 'loaded' &&
  Boolean(row.permission?.can_deploy || row.permission?.can_manage) &&
  Boolean(row.deployment.deployment_id);

const canOpenModule = (row: ModuleOperationRow) =>
  row.permissionStatus === 'loaded' && Boolean(row.permission?.can_read);

const capabilityParamOf = (
  filter: PermissionFilter,
): ModuleOperationsListParams['capability'] => {
  if (filter === 'executable') return 'execute';
  if (filter === 'editable') return 'write';
  if (filter === 'manageable') return 'manage';
  return undefined;
};

export default function MyModulePage() {
  const router = useRouter();
  const [rows, setRows] = useState<ModuleOperationRow[]>([]);
  const [isOrgManager, setIsOrgManager] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState('');
  const [permissionFilter, setPermissionFilter] =
    useState<PermissionFilter>('all');
  const [deploymentFilter, setDeploymentFilter] =
    useState<DeploymentFilter>('all');
  const [runFilter, setRunFilter] = useState<RunFilter>('all');
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [editingApp, setEditingApp] = useState<App | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState('');
  const [optimizationTarget, setOptimizationTarget] =
    useState<ModuleOperationRow | null>(null);
  const [optimizationNodes, setOptimizationNodes] = useState<
    LlmOptimizationNode[]
  >([]);
  const [isResolvingOptimizationId, setIsResolvingOptimizationId] = useState<
    string | null
  >(null);
  const [appliedOptimizationIds, setAppliedOptimizationIds] = useState<
    Record<string, string[]>
  >({});
  const requestSeqRef = useRef(0);

  const buildListParams = useCallback(
    (offset: number): ModuleOperationsListParams => {
      const trimmedQuery = debouncedSearchQuery.trim();
      return {
        q: trimmedQuery || undefined,
        capability: capabilityParamOf(permissionFilter),
        deployment_state:
          deploymentFilter === 'all' ? undefined : deploymentFilter,
        run_state: runFilter === 'all' ? undefined : runFilter,
        limit: PAGE_SIZE,
        offset,
      };
    },
    [debouncedSearchQuery, deploymentFilter, permissionFilter, runFilter],
  );

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setDebouncedSearchQuery(searchQuery);
    }, 300);

    return () => window.clearTimeout(timeoutId);
  }, [searchQuery]);

  const loadModules = useCallback(
    async ({ offset = 0, append = false } = {}) => {
      const requestSeq = requestSeqRef.current + 1;
      requestSeqRef.current = requestSeq;
      try {
        if (append) {
          setIsLoadingMore(true);
        } else {
          setIsLoading(true);
        }
        setError('');
        const data = await moduleOperationsApi.listModuleOperations(
          buildListParams(offset),
        );
        if (requestSeq !== requestSeqRef.current) return;
        setRows((currentRows) => (append ? [...currentRows, ...data] : data));
        setHasMore(data.length === PAGE_SIZE);

        try {
          const organizationResponse =
            await apiClient.get<OrganizationResponse>('/organizations/current');
          if (requestSeq !== requestSeqRef.current) return;
          setIsOrgManager(Boolean(organizationResponse.data.is_manager));
        } catch {
          if (requestSeq !== requestSeqRef.current) return;
          setIsOrgManager(false);
        }
      } catch {
        if (requestSeq !== requestSeqRef.current) return;
        setError('모듈 운영 현황을 불러오지 못했습니다.');
      } finally {
        if (requestSeq === requestSeqRef.current) {
          setIsLoading(false);
          setIsLoadingMore(false);
        }
      }
    },
    [buildListParams],
  );

  useEffect(() => {
    loadModules();
  }, [loadModules]);

  useEffect(() => {
    const handleOpenModal = () => {
      setIsCreateModalOpen(true);
    };

    window.addEventListener('openCreateAppModal', handleOpenModal);
    return () =>
      window.removeEventListener('openCreateAppModal', handleOpenModal);
  }, []);

  const summary = useMemo(
    () => {
      const activeRows = rows.filter((row) => row.deploymentState === 'active');
      const costSignals = activeRows.map(costSignalOf);
      const monthlyCost = costSignals.reduce(
        (total, signal) => total + (signal.monthlyCost ?? 0),
        0,
      );
      const trendSignals = costSignals.filter(
        (signal) => signal.trendPercent != null,
      );
      const recommended = costSignals.filter((signal) => signal.recommended);
      const atRiskBudget = costSignals.filter(
        (signal) =>
          signal.budgetUsageRatio != null && signal.budgetUsageRatio >= 0.8,
      );
      const averageTrend =
        trendSignals.length > 0
          ? Math.round(
              trendSignals.reduce(
                (total, signal) => total + (signal.trendPercent ?? 0),
                0,
              ) / trendSignals.length,
            )
          : null;

      return {
        active: activeRows.length,
        unavailable: rows.filter(
          (row) =>
            row.dataQuality.permissionSourcesUnavailable ||
            row.dataQuality.latestRunUnavailable,
        ).length,
        monthlyCost,
        recommendedCount: recommended.length,
        atRiskBudgetCount: atRiskBudget.length,
        averageTrend,
        trendSampleCount: trendSignals.length,
      };
    },
    [rows],
  );

  const handleModuleClick = (row: ModuleOperationRow) => {
    if (!canOpenModule(row)) return;
    const targetId = row.app.workflow_id || row.app.id;
    router.push(`/modules/${targetId}`);
  };

  const handleEditApp = async (row: ModuleOperationRow) => {
    if (!canEditApp(row, isOrgManager)) return;
    try {
      const app = await appApi.getApp(row.app.id);
      setEditingApp(app);
    } catch {
      alert('앱 정보를 불러오지 못했습니다.');
    }
  };

  const handleToggleDeployment = async (row: ModuleOperationRow) => {
    if (!canToggleDeployment(row) || !row.deployment.deployment_id) return;

    try {
      await appApi.toggleDeployment(row.deployment.deployment_id);
      loadModules();
    } catch {
      alert('배포 상태 변경에 실패했습니다.');
    }
  };

  const handleMarkOptimizationRecommendationsForReview = (
    row: ModuleOperationRow,
    recommendationIds: string[],
  ) => {
    setAppliedOptimizationIds((current) => ({
      ...current,
      [row.app.id]: recommendationIds,
    }));
    setOptimizationTarget(null);
    setOptimizationNodes([]);
  };

  const handleOpenOptimizationModal = async (row: ModuleOperationRow) => {
    if (!row.app.workflow_id) {
      alert('연결된 workflow가 없어 LLM 노드 최적화 대상을 확인할 수 없습니다.');
      return;
    }

    setIsResolvingOptimizationId(row.app.id);
    try {
      const workflow = await workflowApi.getDraftWorkflow(row.app.workflow_id);
      const llmNodes = extractLlmOptimizationNodes(workflow);

      if (llmNodes.length === 0) {
        alert('이 workflow에는 최적화할 LLM 노드가 없습니다.');
        return;
      }

      setOptimizationNodes(llmNodes);
      setOptimizationTarget(row);
    } catch {
      alert('workflow의 LLM 노드 정보를 불러오지 못했습니다.');
    } finally {
      setIsResolvingOptimizationId(null);
    }
  };

  return (
    <div className="min-h-full bg-slate-50 px-6 py-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <DashboardPageHeader
          icon={Layers3}
          title="내 모듈"
          description="워크플로우 접근 권한, 배포 상태, 실행 흐름을 한 화면에서 확인합니다."
          meta={
            summary.unavailable > 0 && (
              <span className="inline-flex items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-xs font-medium text-amber-700">
                <AlertTriangle className="h-3.5 w-3.5" />
                일부 권한 출처 또는 실행 상태를 확인할 수 없어 확인 필요로 표시됩니다.
              </span>
            )
          }
          action={
            <div className="flex items-center gap-2">
              <button
                onClick={() => loadModules()}
                className="inline-flex h-10 items-center gap-2 rounded-md border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 hover:bg-slate-100"
              >
                <RefreshCw className="h-4 w-4" />
                새로고침
              </button>
              <button
                onClick={() => setIsCreateModalOpen(true)}
                className="inline-flex h-10 items-center gap-2 rounded-md bg-slate-950 px-4 text-sm font-semibold text-white hover:bg-slate-800"
              >
                <Plus className="h-4 w-4" />
                새 모듈
              </button>
            </div>
          }
        />

        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
            {error}
          </div>
        )}

        <section className="grid gap-4 md:grid-cols-4">
          <DashboardSummaryCard
            label="예상 월 비용"
            value={formatCurrency(summary.monthlyCost)}
            icon={DollarSign}
            iconClassName="text-emerald-600"
            description={`${summary.active}개 배포 workflow의 당월 사용량 기준`}
          />
          <DashboardSummaryCard
            label="평균 증가 추세"
            value={
              summary.averageTrend == null
                ? '-'
                : `${summary.averageTrend > 0 ? '+' : ''}${summary.averageTrend}%`
            }
            icon={TrendingUp}
            iconClassName="text-amber-600"
            description={`${summary.trendSampleCount}개 workflow 전월 비용 비교`}
          />
          <DashboardSummaryCard
            label="예산 위험"
            value={`${summary.atRiskBudgetCount}개`}
            icon={Gauge}
            iconClassName="text-red-600"
            description="사용률 80% 이상"
          />
          <DashboardSummaryCard
            label="최적화 권장"
            value={`${summary.recommendedCount}개`}
            icon={Sparkles}
            iconClassName="text-violet-600"
            description="비용/추세/예산 위험 신호"
          />
        </section>

        <DashboardPanel
          title="운영 현황"
          icon={SlidersHorizontal}
          aside={
            <span className="text-xs text-slate-500">
              현재 로드 {rows.length}개{hasMore ? ' 이상' : ''}
            </span>
          }
        >
          <div className="border-b border-slate-100 bg-white px-5 py-4">
            <div className="grid gap-3 lg:grid-cols-[1fr_auto_auto_auto]">
              <label className="relative block">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input
                  type="text"
                  placeholder="모듈명, 설명 검색"
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  className="h-10 w-full rounded-md border border-slate-200 bg-white py-2 pl-9 pr-3 text-sm font-medium text-slate-900 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
                />
              </label>

              <FilterSelect
                label="권한"
                value={permissionFilter}
                onChange={(value) =>
                  setPermissionFilter(value as PermissionFilter)
                }
                options={[
                  ['all', '전체 권한'],
                  ['executable', '실행 가능'],
                  ['editable', '워크플로우 수정 가능'],
                  ['manageable', '워크플로우 관리 가능'],
                ]}
              />
              <FilterSelect
                label="배포"
                value={deploymentFilter}
                onChange={(value) =>
                  setDeploymentFilter(value as DeploymentFilter)
                }
                options={[
                  ['all', '전체 배포'],
                  ['active', '배포 중'],
                  ['inactive', '배포 꺼짐'],
                  ['undeployed', '미배포'],
                ]}
              />
              <FilterSelect
                label="실행"
                value={runFilter}
                onChange={(value) => setRunFilter(value as RunFilter)}
                options={[
                  ['all', '전체 실행'],
                  ['running', '실행 중'],
                  ['failed', '오류만'],
                ]}
              />
            </div>
          </div>

          {isLoading ? (
            <ModuleListSkeleton />
          ) : rows.length === 0 ? (
            <div className="px-5 py-12 text-center">
              <p className="text-sm font-semibold text-slate-700">
                조건에 맞는 모듈이 없습니다.
              </p>
              <button
                onClick={() => {
                  setSearchQuery('');
                  setPermissionFilter('all');
                  setDeploymentFilter('all');
                  setRunFilter('all');
                }}
                className="mt-3 rounded-md border border-slate-300 px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100"
              >
                필터 초기화
              </button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full table-fixed divide-y divide-slate-100">
                <thead className="bg-slate-50 text-left text-xs font-semibold text-slate-500">
                  <tr>
                    <th className="w-[24%] px-5 py-3">워크플로우</th>
                    <th className="w-[13%] px-4 py-3">월 예상 비용</th>
                    <th className="w-[13%] px-4 py-3">증가 추세</th>
                    <th className="w-[14%] px-4 py-3">예산 사용률</th>
                    <th className="w-[15%] px-4 py-3">최적화</th>
                    <th className="w-[11%] px-4 py-3">상태</th>
                    <th className="w-[10%] px-5 py-3 text-right">작업</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {rows.map((row) => (
                    <ModuleOperationTableRow
                      key={row.app.id}
                      row={row}
                      onOpen={() => handleModuleClick(row)}
                      onEdit={() => handleEditApp(row)}
                      onToggleDeployment={() => handleToggleDeployment(row)}
                      onOptimize={() => handleOpenOptimizationModal(row)}
                      isResolvingOptimization={
                        isResolvingOptimizationId === row.app.id
                      }
                      appliedOptimizationCount={
                        appliedOptimizationIds[row.app.id]?.length || 0
                      }
                      isOrgManager={isOrgManager}
                    />
                  ))}
                </tbody>
              </table>
              {hasMore && (
                <div className="border-t border-slate-100 bg-white px-5 py-4 text-center">
                  <button
                    onClick={() =>
                      loadModules({ offset: rows.length, append: true })
                    }
                    disabled={isLoadingMore}
                    className="inline-flex h-10 items-center gap-2 rounded-md border border-slate-300 bg-white px-4 text-sm font-semibold text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <RefreshCw
                      className={`h-4 w-4 ${isLoadingMore ? 'animate-spin' : ''}`}
                    />
                    {isLoadingMore ? '불러오는 중' : '더 보기'}
                  </button>
                </div>
              )}
            </div>
          )}
        </DashboardPanel>
      </div>

      {isCreateModalOpen && (
        <CreateAppModal
          onClose={() => setIsCreateModalOpen(false)}
          onSuccess={() => {
            setIsCreateModalOpen(false);
            loadModules();
          }}
        />
      )}

      {editingApp && (
        <EditAppModal
          app={editingApp}
          onClose={() => setEditingApp(null)}
          onSuccess={() => {
            setEditingApp(null);
            loadModules();
          }}
        />
      )}

      {optimizationTarget && (
        <OptimizationRecommendationModal
          row={optimizationTarget}
          llmNodes={optimizationNodes}
          appliedIds={appliedOptimizationIds[optimizationTarget.app.id] || []}
          onClose={() => {
            setOptimizationTarget(null);
            setOptimizationNodes([]);
          }}
          onMarkForReview={(recommendationIds) =>
            handleMarkOptimizationRecommendationsForReview(
              optimizationTarget,
              recommendationIds,
            )
          }
        />
      )}
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string;
  value: string;
  options: [string, string][];
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex h-10 items-center gap-2 rounded-md border border-slate-200 bg-white pl-3 pr-2 text-sm font-medium text-slate-600 has-disabled:bg-slate-50 has-disabled:text-slate-400">
      <Filter className="h-4 w-4 text-slate-400" />
      <span className="sr-only">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        className="h-full bg-transparent pr-6 text-sm font-semibold text-slate-800 outline-none disabled:cursor-not-allowed disabled:text-slate-400"
      >
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>
            {optionLabel}
          </option>
        ))}
      </select>
    </label>
  );
}

function ModuleOperationTableRow({
  row,
  onOpen,
  onEdit,
  onToggleDeployment,
  onOptimize,
  isResolvingOptimization,
  appliedOptimizationCount,
  isOrgManager,
}: {
  row: ModuleOperationRow;
  onOpen: () => void;
  onEdit: () => void;
  onToggleDeployment: () => void;
  onOptimize: () => void;
  isResolvingOptimization: boolean;
  appliedOptimizationCount: number;
  isOrgManager: boolean;
}) {
  const deploymentState = row.deploymentState;
  const canEdit = canEditApp(row, isOrgManager);
  const canToggle = canToggleDeployment(row);
  const runBlockMessage = budgetRunBlockMessage(row.app.budget_status);
  const costSignal = costSignalOf(row);
  const budgetPercent =
    costSignal.budgetUsageRatio == null
      ? null
      : Math.round(costSignal.budgetUsageRatio * 100);
  const trendPercent = costSignal.trendPercent;

  return (
    <tr className="text-sm text-slate-700 hover:bg-slate-50">
      <td className="px-5 py-4 align-top">
        <button
          onClick={onOpen}
          className="flex min-w-0 items-start gap-3 text-left"
        >
          <span
            className="grid h-10 w-10 shrink-0 place-items-center rounded-lg text-lg shadow-sm"
            style={{ backgroundColor: row.app.icon?.background_color }}
          >
            {row.app.icon?.content || 'N'}
          </span>
          <span className="min-w-0">
            <span className="block truncate font-semibold text-slate-950">
              {row.app.name}
            </span>
            <span className="mt-1 line-clamp-2 block text-xs text-slate-500">
              {row.app.description || '설명 없음'}
            </span>
            {row.app.budget_status && (
              <span className="mt-2 block">
                <BudgetStatusBadge
                  status={row.app.budget_status.status}
                  usageRatio={row.app.budget_status.usage_ratio}
                />
              </span>
            )}
            <span className="mt-2 block text-xs text-slate-400">
              마지막 수정 {formatDate(row.app.updated_at)}
            </span>
          </span>
        </button>
      </td>
      <td className="px-4 py-4 align-top">
        {row.deploymentState === 'active' ? (
          <div>
            <p className="font-semibold text-slate-950">
              {formatCurrency(costSignal.monthlyCost)}
            </p>
            {(costSignal.monthlyCost == null ||
              costSignal.monthlyCost === 0) && (
              <p className="mt-1 text-xs text-slate-500">운영 비용 없음</p>
            )}
          </div>
        ) : (
          <span className="text-xs font-medium text-slate-400">
            배포 후 표시
          </span>
        )}
      </td>
      <td className="px-4 py-4 align-top">
        {row.deploymentState === 'active' && trendPercent != null ? (
          <Badge
            className={
              trendPercent >= 20
                ? 'border-red-200 bg-red-50 text-red-700'
                : trendPercent >= 10
                  ? 'border-amber-200 bg-amber-50 text-amber-700'
                  : 'border-emerald-200 bg-emerald-50 text-emerald-700'
            }
          >
            {trendPercent > 0 ? '+' : ''}
            {Math.round(trendPercent)}%
          </Badge>
        ) : row.deploymentState === 'active' ? (
          <span className="text-xs font-medium text-slate-400">
            비교 데이터 없음
          </span>
        ) : (
          <span className="text-xs font-medium text-slate-400">-</span>
        )}
      </td>
      <td className="px-4 py-4 align-top">
        {row.deploymentState === 'active' && budgetPercent != null ? (
          <div className="min-w-28">
            <div className="flex items-center justify-between gap-2 text-xs font-semibold text-slate-700">
              <span>{budgetPercent}%</span>
              <span
                className={
                  budgetPercent >= 100
                    ? 'text-red-600'
                    : budgetPercent >= 80
                      ? 'text-amber-600'
                      : 'text-emerald-600'
                }
              >
                {budgetPercent >= 100
                  ? '초과'
                  : budgetPercent >= 80
                    ? '위험'
                    : '정상'}
              </span>
            </div>
            <div className="mt-2 h-2 rounded-full bg-slate-100">
              <div
                className={`h-2 rounded-full ${
                  budgetPercent >= 100
                    ? 'bg-red-500'
                    : budgetPercent >= 80
                      ? 'bg-amber-500'
                      : 'bg-emerald-500'
                }`}
                style={{ width: `${Math.min(budgetPercent, 100)}%` }}
              />
            </div>
          </div>
        ) : row.deploymentState === 'active' ? (
          <span className="text-xs font-medium text-slate-400">예산 없음</span>
        ) : (
          <span className="text-xs font-medium text-slate-400">-</span>
        )}
      </td>
      <td className="px-4 py-4 align-top">
        <div className="flex flex-col gap-2">
          {costSignal.recommended ? (
            <button
              type="button"
              onClick={onOptimize}
              disabled={isResolvingOptimization}
              className="inline-flex w-fit items-center gap-1.5 rounded-md border border-violet-200 bg-violet-50 px-2 py-1 text-left text-xs font-semibold text-violet-700 transition-colors hover:border-violet-300 hover:bg-violet-100 disabled:cursor-wait disabled:border-slate-200 disabled:bg-slate-50 disabled:text-slate-400"
            >
              <Sparkles
                className={`h-3.5 w-3.5 ${
                  isResolvingOptimization ? 'animate-pulse' : ''
                }`}
              />
              {isResolvingOptimization ? '확인 중' : '최적화 권장'}
            </button>
          ) : (
            <Badge className="border-slate-200 bg-slate-50 text-slate-600">
              {row.deploymentState === 'active' ? '안정 범위' : '대상 아님'}
            </Badge>
          )}
          {appliedOptimizationCount > 0 && (
            <span className="w-fit rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">
              추천 {appliedOptimizationCount}개 검토 후보
            </span>
          )}
          <span className="text-xs text-slate-500">{costSignal.reason}</span>
          <span className="inline-flex items-center gap-1 text-xs text-slate-500">
            <Users className="h-3.5 w-3.5" />
            {sourceLabelOf(row)}
          </span>
        </div>
      </td>
      <td className="px-4 py-4 align-top">
        <div className="flex flex-col gap-2">
          <Badge className={deploymentTone[deploymentState]}>
            {deploymentLabels[deploymentState]}
          </Badge>
          {row.latestRun.state !== 'success' && (
            <Badge className={runTone[row.latestRun.state]}>
              {runLabels[row.latestRun.state]}
            </Badge>
          )}
          {runBlockMessage && (
            <span
              title={runBlockMessage}
              className="w-fit rounded bg-red-100 px-1 text-[10px] font-bold text-red-700"
            >
              실행 차단
            </span>
          )}
        </div>
      </td>
      <td className="px-5 py-4 align-top">
        <div className="flex justify-end gap-2">
          <IconButton
            label={canOpenModule(row) ? '열기' : '조회 권한 확인 필요'}
            onClick={onOpen}
            disabled={!canOpenModule(row)}
          >
            <ExternalLink className="h-4 w-4" />
          </IconButton>
          <IconButton
            label={canEdit ? '앱 설정 수정' : '앱 설정 관리 권한 필요'}
            onClick={onEdit}
            disabled={!canEdit}
          >
            <Edit3 className="h-4 w-4" />
          </IconButton>
          <IconButton
            label={
              canToggle
                ? '배포 상태 변경'
                : row.deployment.deployment_id
                  ? '배포 권한 필요'
                  : '배포 없음'
            }
            onClick={onToggleDeployment}
            disabled={!canToggle}
          >
            <CheckCircle2 className="h-4 w-4" />
          </IconButton>
        </div>
      </td>
    </tr>
  );
}

function OptimizationRecommendationModal({
  row,
  llmNodes,
  appliedIds,
  onClose,
  onMarkForReview,
}: {
  row: ModuleOperationRow;
  llmNodes: LlmOptimizationNode[];
  appliedIds: string[];
  onClose: () => void;
  onMarkForReview: (recommendationIds: string[]) => void;
}) {
  const [selectedNodeId, setSelectedNodeId] = useState(
    llmNodes[0]?.id || '',
  );
  const selectedNode =
    llmNodes.find((node) => node.id === selectedNodeId) || llmNodes[0];
  const selectedNodeTitle = selectedNode?.title || 'LLM 노드';
  const [recommendationResponse, setRecommendationResponse] =
    useState<CostOptimizerParameterRecommendationsResponse | null>(null);
  const [isLoadingRecommendations, setIsLoadingRecommendations] =
    useState(false);
  const [recommendationError, setRecommendationError] = useState('');
  const recommendations = recommendationResponse?.recommendations || [];
  const [selectedIds, setSelectedIds] = useState<string[]>(
    appliedIds.length > 0
      ? appliedIds
      : recommendations.map((recommendation) => recommendation.parameter_key),
  );

  useEffect(() => {
    if (!row.app.workflow_id || !selectedNodeId) return;

    let active = true;
    setIsLoadingRecommendations(true);
    setRecommendationError('');
    setRecommendationResponse(null);

    workflowApi
      .getCostOptimizerParameterRecommendations(row.app.workflow_id, selectedNodeId)
      .then((response) => {
        if (!active) return;
        setRecommendationResponse(response);
        setSelectedIds(
          appliedIds.length > 0
            ? appliedIds
            : response.recommendations.map(
                (recommendation) => recommendation.parameter_key,
              ),
        );
      })
      .catch(() => {
        if (!active) return;
        setRecommendationError('파라미터 추천 결과를 불러오지 못했습니다.');
        setSelectedIds([]);
      })
      .finally(() => {
        if (active) setIsLoadingRecommendations(false);
      });

    return () => {
      active = false;
    };
  }, [appliedIds, row.app.workflow_id, selectedNodeId]);

  const toggleRecommendation = (id: string) => {
    setSelectedIds((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : [...current, id],
    );
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 px-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="optimization-recommendation-title"
    >
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-5">
          <div>
            <p className="text-xs font-bold text-violet-600">
              비용 최적화 검토
            </p>
            <h2
              id="optimization-recommendation-title"
              className="mt-1 text-xl font-bold text-slate-950"
            >
              LLM 노드 설정 추천
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              {row.app.name}의 운영 로그를 기준으로, 바로 적용하지 않고 먼저
              A/B 검증해볼 설정 후보를 보여줍니다.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50"
            aria-label="나가기"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <div className="mb-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
            {llmNodes.length > 1 ? (
              <label className="block">
                <span className="text-xs font-bold text-slate-600">
                  검토할 LLM 노드
                </span>
                <select
                  value={selectedNodeId}
                  onChange={(event) => setSelectedNodeId(event.target.value)}
                  className="mt-2 h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm font-semibold text-slate-800 outline-none focus:border-violet-400 focus:ring-2 focus:ring-violet-100"
                >
                  {llmNodes.map((node) => (
                    <option key={node.id} value={node.id}>
                      {node.title}
                    </option>
                  ))}
                </select>
                <span className="mt-1 block text-xs text-slate-500">
                  LLM 노드가 여러 개라서 어떤 노드의 설정을 검토할지 먼저
                  선택합니다.
                </span>
              </label>
            ) : (
              <div>
                <span className="text-xs font-bold text-slate-600">
                  검토할 LLM 노드
                </span>
                <p className="mt-1 text-sm font-semibold text-slate-900">
                  {selectedNodeTitle}
                </p>
              </div>
            )}
          </div>

          {isLoadingRecommendations && (
            <div className="rounded-lg border border-slate-200 bg-white px-4 py-6 text-sm font-medium text-slate-500">
              추천 엔진 결과를 불러오는 중입니다.
            </div>
          )}

          {recommendationError && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
              {recommendationError}
            </div>
          )}

          {!isLoadingRecommendations &&
            !recommendationError &&
            recommendationResponse?.analysis_stage === 'insufficient_logs' && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                <p className="font-semibold">
                  배포 후 운영 로그가 부족해 추천을 만들지 않았습니다.
                </p>
                <p className="mt-1">
                  현재 샘플 수:{' '}
                  {formatRecommendationValue(
                    recommendationResponse.profile?.sample_count,
                  )}
                </p>
              </div>
            )}

          {!isLoadingRecommendations &&
            !recommendationError &&
            recommendationResponse?.warnings?.map((warning) => (
              <div
                key={`${warning.code}-${warning.message}`}
                className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
              >
                <span className="font-semibold">추천 제한 안내</span>
                {warning.message && <span className="ml-2">{warning.message}</span>}
              </div>
            ))}

          <div className="space-y-3">
            {recommendations.map((recommendation) => {
              const recommendationId = recommendation.parameter_key;
              const checked = selectedIds.includes(recommendationId);
              return (
                <label
                  key={recommendationId}
                  className={`flex cursor-pointer gap-3 rounded-lg border p-4 transition-colors ${
                    checked
                      ? 'border-violet-200 bg-violet-50/70'
                      : 'border-slate-200 bg-white hover:bg-slate-50'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleRecommendation(recommendationId)}
                    className="mt-1 h-4 w-4 rounded border-slate-300 text-violet-600 focus:ring-violet-500"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="font-bold text-slate-950">
                        {parameterRecommendationLabelOf(
                          recommendation.parameter_key,
                        )}
                      </span>
                      <span className="rounded-md border border-slate-200 bg-white px-1.5 py-0.5 text-[11px] font-semibold text-slate-600">
                        {recommendation.parameter_key}
                      </span>
                      <span className="rounded-md border border-slate-200 bg-white px-1.5 py-0.5 text-[11px] font-semibold text-slate-600">
                        {parameterRecommendationTargetOf(
                          recommendation.parameter_key,
                        )}
                      </span>
                      <span className="rounded-md border border-violet-100 bg-white px-1.5 py-0.5 text-[11px] font-semibold text-violet-700">
                        대상: {selectedNodeTitle}
                      </span>
                    </span>
                    <span className="mt-2 block text-sm leading-6 text-slate-600">
                      {recommendation.reason || '추천 엔진이 생성한 후보입니다.'}
                    </span>
                    <span className="mt-3 grid gap-2 text-xs md:grid-cols-2">
                      <span className="rounded-md border border-slate-200 bg-white px-3 py-2">
                        <span className="block font-semibold text-slate-500">
                          현재 설정
                        </span>
                        <span className="mt-1 block font-medium text-slate-800">
                          {formatRecommendationValue(
                            recommendation.current_value,
                            recommendation.parameter_key,
                          )}
                        </span>
                      </span>
                      <span className="rounded-md border border-violet-200 bg-white px-3 py-2">
                        <span className="block font-semibold text-violet-600">
                          추천 설정
                        </span>
                        <span className="mt-1 block font-medium text-slate-800">
                          {formatRecommendationValue(
                            recommendation.suggested_value,
                            recommendation.parameter_key,
                          )}
                        </span>
                      </span>
                    </span>
                    {recommendation.evidence &&
                      Object.keys(recommendation.evidence).length > 0 && (
                        <span className="mt-3 block rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
                          <span className="block font-semibold text-slate-500">
                            추천 근거
                          </span>
                          <span className="mt-2 grid gap-2 sm:grid-cols-2">
                            {Object.entries(recommendation.evidence).map(
                              ([key, value]) => (
                                <span
                                  key={key}
                                  className="flex items-center justify-between gap-3 rounded-md bg-slate-50 px-2 py-1"
                                >
                                  <span className="text-slate-500">
                                    {evidenceLabelOf(key)}
                                  </span>
                                  <span className="font-semibold text-slate-800">
                                    {formatEvidenceValue(key, value)}
                                  </span>
                                </span>
                              ),
                            )}
                          </span>
                        </span>
                      )}
                  </span>
                </label>
              );
            })}
          </div>

          <div className="mt-5 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
            이 화면에서는 설정을 바로 바꾸지 않습니다. 선택한 추천은 검토
            후보로만 표시되며, 실제 변경은 A/B 검증 화면에서 후보 실행 결과를
            확인한 뒤 적용해야 합니다.
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-100 px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            닫기
          </button>
          <button
            type="button"
            disabled={selectedIds.length === 0}
            onClick={() => onMarkForReview(selectedIds)}
            className="inline-flex items-center gap-2 rounded-md bg-violet-600 px-4 py-2 text-sm font-semibold text-white hover:bg-violet-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            <Wand2 className="h-4 w-4" />
            검토 후보로 표시
          </button>
        </div>
      </div>
    </div>
  );
}

function Badge({
  children,
  className,
}: {
  children: React.ReactNode;
  className: string;
}) {
  return (
    <span
      className={`inline-flex w-fit items-center rounded-md border px-2 py-1 text-xs font-semibold ${className}`}
    >
      {children}
    </span>
  );
}

function IconButton({
  label,
  disabled,
  children,
  onClick,
}: {
  label: string;
  disabled?: boolean;
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="grid h-9 w-9 place-items-center rounded-md border border-slate-200 bg-white text-slate-600 hover:bg-slate-100 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-300"
    >
      {children}
    </button>
  );
}

function ModuleListSkeleton() {
  return (
    <div className="divide-y divide-slate-100">
      {Array.from({ length: 5 }).map((_, index) => (
        <div key={index} className="grid grid-cols-6 gap-4 px-5 py-4">
          <div className="col-span-2 h-12 animate-pulse rounded bg-slate-100" />
          <div className="h-8 animate-pulse rounded bg-slate-100" />
          <div className="h-8 animate-pulse rounded bg-slate-100" />
          <div className="h-8 animate-pulse rounded bg-slate-100" />
          <div className="h-8 animate-pulse rounded bg-slate-100" />
        </div>
      ))}
    </div>
  );
}
