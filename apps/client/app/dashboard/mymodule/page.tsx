'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  Edit3,
  ExternalLink,
  Filter,
  Layers3,
  Plus,
  RefreshCw,
  Rocket,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Users,
} from 'lucide-react';

import CreateAppModal from '@/app/features/app/components/create-app-modal';
import EditAppModal from '@/app/features/app/components/edit-app-modal';
import { appApi, type App } from '@/app/features/app/api/appApi';
import {
  moduleOperationsApi,
  type ModuleOperationRow,
  type ModuleOperationsListParams,
  type ModuleRunState,
} from '@/app/features/app/api/moduleOperationsApi';
import { apiClient } from '@/lib/apiClient';
import {
  DashboardPageHeader,
  DashboardPanel,
  DashboardSummaryCard,
} from '@/app/features/dashboard/components/DashboardSurface';

type PermissionFilter = 'all' | 'executable' | 'editable' | 'manageable';
type DeploymentFilter = 'all' | 'active' | 'inactive' | 'undeployed';
type RunFilter = 'all' | 'running' | 'failed';

const PAGE_SIZE = 100;

const permissionLabels: Record<string, string> = {
  manager: '워크플로우 관리 가능',
  builder: '워크플로우 수정 가능',
  operator: '실행 가능',
  viewer: '조회 가능',
  none: '권한 없음',
};

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

const permissionTone = (row: ModuleOperationRow) => {
  if (row.permissionError) return 'border-red-200 bg-red-50 text-red-700';
  if (row.permission?.can_manage) {
    return 'border-violet-200 bg-violet-50 text-violet-700';
  }
  if (row.permission?.can_write) {
    return 'border-blue-200 bg-blue-50 text-blue-700';
  }
  if (row.permission?.can_execute) {
    return 'border-amber-200 bg-amber-50 text-amber-700';
  }
  if (row.permission?.can_read) {
    return 'border-slate-200 bg-slate-50 text-slate-700';
  }
  return 'border-slate-200 bg-slate-50 text-slate-500';
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

type OrganizationResponse = {
  id: string;
  name: string;
  is_manager?: boolean;
};

const permissionLabelOf = (row: ModuleOperationRow) => {
  if (!row.app.workflow_id) return '워크플로우 준비 중';
  if (row.permissionError) return row.permissionError;
  const authState = row.permission?.auth_state || 'none';
  return permissionLabels[authState] || authState;
};

const sourceLabelOf = (row: ModuleOperationRow) => {
  if (!row.app.workflow_id) return '권한 확인 대기';
  if (row.permissionSources.length === 0) return '출처 연동 예정';

  const [firstSource, ...rest] = row.permissionSources;
  const sourceName =
    firstSource.team_name ||
    firstSource.user_name ||
    (firstSource.type === 'user' ? '개인 직접 권한' : '권한 출처');

  return rest.length > 0 ? `${sourceName} 외 ${rest.length}개` : sourceName;
};

const canEditApp = (row: ModuleOperationRow, isOrgManager: boolean) =>
  isOrgManager ||
  (row.permissionStatus === 'loaded' && Boolean(row.permission?.can_manage));

const canWriteWorkflow = (row: ModuleOperationRow) =>
  row.permissionStatus === 'loaded' && Boolean(row.permission?.can_write);

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
    () => ({
      active: rows.filter((row) => row.deploymentState === 'active').length,
      undeployed: rows.filter((row) => row.deploymentState === 'undeployed')
        .length,
      failed: rows.filter((row) => row.latestRun.state === 'failed').length,
      running: rows.filter((row) => row.latestRun.state === 'running').length,
      editable: rows.filter(canWriteWorkflow).length,
      manageable: rows.filter((row) => canEditApp(row, isOrgManager)).length,
      runUnavailable: rows.filter((row) => row.dataQuality.latestRunUnavailable)
        .length,
      unavailable: rows.filter(
        (row) =>
          row.dataQuality.permissionSourcesUnavailable ||
          row.dataQuality.latestRunUnavailable,
      ).length,
    }),
    [isOrgManager, rows],
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
            label="배포 중"
            value={`${summary.active}개`}
            icon={Rocket}
            iconClassName="text-green-600"
            description="현재 로드된 결과 기준"
          />
          <DashboardSummaryCard
            label="최근 오류"
            value={`${summary.failed}개`}
            icon={AlertTriangle}
            iconClassName="text-red-600"
            description="현재 로드된 결과 기준"
          />
          <DashboardSummaryCard
            label="실행 중"
            value={`${summary.running}개`}
            icon={Clock3}
            description="현재 로드된 결과 기준"
          />
          <DashboardSummaryCard
            label="앱 설정 관리"
            value={`${summary.manageable}개`}
            icon={ShieldCheck}
            iconClassName="text-violet-600"
            description={`로드된 결과 중 수정 가능 ${summary.editable}개`}
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
                    <th className="w-[30%] px-5 py-3">모듈</th>
                    <th className="w-[14%] px-4 py-3">소유자</th>
                    <th className="w-[16%] px-4 py-3">내 권한</th>
                    <th className="w-[14%] px-4 py-3">배포</th>
                    <th className="w-[14%] px-4 py-3">실행 상태</th>
                    <th className="w-[12%] px-5 py-3 text-right">작업</th>
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
  isOrgManager,
}: {
  row: ModuleOperationRow;
  onOpen: () => void;
  onEdit: () => void;
  onToggleDeployment: () => void;
  isOrgManager: boolean;
}) {
  const deploymentState = row.deploymentState;
  const canEdit = canEditApp(row, isOrgManager);
  const canToggle = canToggleDeployment(row);

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
            <span className="mt-2 block text-xs text-slate-400">
              마지막 수정 {formatDate(row.app.updated_at)}
            </span>
          </span>
        </button>
      </td>
      <td className="px-4 py-4 align-top">
        <span className="font-medium text-slate-700">
          {row.app.owner_name || '알 수 없음'}
        </span>
      </td>
      <td className="px-4 py-4 align-top">
        <div className="flex flex-col gap-2">
          <Badge className={permissionTone(row)}>{permissionLabelOf(row)}</Badge>
          <span className="inline-flex items-center gap-1 text-xs text-slate-500">
            <Users className="h-3.5 w-3.5" />
            {sourceLabelOf(row)}
            {row.dataQuality.permissionSourcesUnavailable && (
              <span className="rounded bg-amber-100 px-1 text-[10px] font-bold text-amber-700">
                예정
              </span>
            )}
          </span>
        </div>
      </td>
      <td className="px-4 py-4 align-top">
        <Badge className={deploymentTone[deploymentState]}>
          {deploymentLabels[deploymentState]}
        </Badge>
        {row.deployment.type && (
          <p className="mt-2 text-xs text-slate-500">
            {row.deployment.type}
          </p>
        )}
      </td>
      <td className="px-4 py-4 align-top">
        <div className="flex flex-col gap-2">
          <Badge className={runTone[row.latestRun.state]}>
            {runLabels[row.latestRun.state]}
          </Badge>
          <span className="text-xs text-slate-500">
            {formatDate(row.latestRun.started_at)}
          </span>
          {row.dataQuality.latestRunUnavailable && (
            <span className="w-fit rounded bg-amber-100 px-1 text-[10px] font-bold text-amber-700">
              예정
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
