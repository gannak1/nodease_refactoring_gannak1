'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  ArrowRight,
  CheckCircle,
  RefreshCw,
  ShieldCheck,
  Users,
  Workflow,
  Zap,
} from 'lucide-react';
import {
  activeOrganizationHeaders,
  getStoredActiveOrganizationId,
  resolveActiveOrganizationId,
  setActiveOrganizationId,
} from '@/lib/activeOrganization';

type OrganizationResponse = {
  id: string;
  name: string;
  is_manager: boolean;
};

type AppResponse = {
  id: string;
  name: string;
  workflow_id?: string;
};

type TeamResponse = {
  id: string;
  name: string;
  description?: string;
  is_active: boolean;
};

type TeamMemberResponse = {
  id: string;
  user_id: string;
  email: string;
  name: string;
};

type WorkflowPermissionResponse = {
  workflow_id: string;
  auth_state: string;
  can_read: boolean;
  can_write: boolean;
  can_execute: boolean;
  can_manage: boolean;
};

type WorkflowAccessRow = {
  app: AppResponse;
  permission?: WorkflowPermissionResponse;
  permissionError?: string;
};

const API_BASE_URL = '/api/v1';

async function apiRequest<T>(
  path: string,
  organizationId = getStoredActiveOrganizationId(),
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...activeOrganizationHeaders(organizationId),
    },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(
      body.error?.message || body.detail || body.message || 'Request failed',
    );
  }
  return body as T;
}

const permissionLabel = (permission?: WorkflowPermissionResponse) =>
  permission?.auth_state || '확인 필요';

const permissionTone = (permission?: WorkflowPermissionResponse) => {
  if (!permission) return 'bg-gray-100 text-gray-700';
  if (permission.can_manage) return 'bg-blue-50 text-blue-700';
  if (permission.can_write) return 'bg-green-50 text-green-700';
  if (permission.can_execute) return 'bg-amber-50 text-amber-700';
  return 'bg-gray-100 text-gray-700';
};

export default function DashboardHomePage() {
  const router = useRouter();
  const [organization, setOrganization] = useState<OrganizationResponse | null>(
    null,
  );
  const [teams, setTeams] = useState<TeamResponse[]>([]);
  const [teamMembers, setTeamMembers] = useState<
    Record<string, TeamMemberResponse[]>
  >({});
  const [workflowRows, setWorkflowRows] = useState<WorkflowAccessRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const activeTeams = useMemo(
    () => teams.filter((team) => team.is_active),
    [teams],
  );
  const inactiveTeams = useMemo(
    () => teams.filter((team) => !team.is_active),
    [teams],
  );
  const totalMembers = useMemo(
    () =>
      Object.values(teamMembers).reduce(
        (total, members) => total + members.length,
        0,
      ),
    [teamMembers],
  );

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const organizations =
        await apiRequest<OrganizationResponse[]>('/organizations', null);
      const organizationId = resolveActiveOrganizationId(organizations);
      if (!organizationId) {
        throw new Error('현재 선택된 조직이 없습니다.');
      }

      const org = await apiRequest<OrganizationResponse>(
        '/organizations/current',
        organizationId,
      );
      setActiveOrganizationId(org.id);
      setOrganization(org);

      const apps = await apiRequest<AppResponse[]>('/apps', org.id);
      const rows = await Promise.all(
        apps
          .filter((app) => Boolean(app.workflow_id))
          .map(async (app) => {
            try {
              const permission = await apiRequest<WorkflowPermissionResponse>(
                `/workflows/${app.workflow_id}/permissions/me`,
                org.id,
              );
              return { app, permission };
            } catch (err) {
              return {
                app,
                permissionError:
                  err instanceof Error ? err.message : '권한 조회 실패',
              };
            }
          }),
      );
      setWorkflowRows(rows);

      if (!org.is_manager) {
        setTeams([]);
        setTeamMembers({});
        return;
      }

      const teamData = await apiRequest<TeamResponse[]>(
        `/teams?organization_id=${org.id}`,
        org.id,
      );
      setTeams(teamData);

      const memberEntries = await Promise.all(
        teamData.map(async (team) => {
          const members = await apiRequest<TeamMemberResponse[]>(
            `/teams/${team.id}/members`,
            org.id,
          ).catch(() => []);
          return [team.id, members] as const;
        }),
      );
      setTeamMembers(Object.fromEntries(memberEntries));
    } catch (err) {
      setError(err instanceof Error ? err.message : '홈 데이터를 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  return (
    <div className="min-h-full bg-slate-50 px-6 py-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-slate-950">홈</h1>
            <p className="mt-1 text-sm text-slate-600">
              {organization
                ? `${organization.name} · ${
                    organization.is_manager ? 'manager' : 'member'
                  }`
                : 'Organization 확인 중'}
            </p>
          </div>
          <button
            onClick={loadData}
            className="inline-flex h-10 items-center gap-2 rounded-md border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 hover:bg-slate-100"
          >
            <RefreshCw className="h-4 w-4" />
            새로고침
          </button>
        </header>

        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {loading ? (
          <div className="rounded-lg border border-slate-200 bg-white px-6 py-16 text-center text-sm text-slate-500">
            로딩 중...
          </div>
        ) : (
          <>
            <section className="grid gap-4 md:grid-cols-3">
              <div className="rounded-lg border border-slate-200 bg-white p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-slate-500">
                      Organization
                    </p>
                    <p className="mt-1 text-lg font-semibold text-slate-950">
                      {organization?.name || '-'}
                    </p>
                  </div>
                  <ShieldCheck className="h-5 w-5 text-blue-600" />
                </div>
              </div>

              <div className="rounded-lg border border-slate-200 bg-white p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-slate-500">Role</p>
                    <p className="mt-1 text-lg font-semibold text-slate-950">
                      {organization?.is_manager ? 'manager' : 'member'}
                    </p>
                  </div>
                  <CheckCircle className="h-5 w-5 text-green-600" />
                </div>
              </div>

              <div className="rounded-lg border border-slate-200 bg-white p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium text-slate-500">
                      Workflow access
                    </p>
                    <p className="mt-1 text-lg font-semibold text-slate-950">
                      {workflowRows.length}
                    </p>
                  </div>
                  <Workflow className="h-5 w-5 text-violet-600" />
                </div>
              </div>
            </section>

            {organization?.is_manager && (
              <section className="grid gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
                <div className="rounded-lg border border-slate-200 bg-white p-5">
                  <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-950">
                    <Users className="h-4 w-4 text-blue-600" />
                    Team summary
                  </h2>
                  <div className="mt-4 grid grid-cols-3 gap-3">
                    <div>
                      <p className="text-xs text-slate-500">Active</p>
                      <p className="mt-1 text-xl font-semibold text-slate-950">
                        {activeTeams.length}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-slate-500">Inactive</p>
                      <p className="mt-1 text-xl font-semibold text-slate-950">
                        {inactiveTeams.length}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-slate-500">Members</p>
                      <p className="mt-1 text-xl font-semibold text-slate-950">
                        {totalMembers}
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={() => router.push('/dashboard/settings')}
                    className="mt-5 inline-flex h-9 items-center gap-2 rounded-md bg-slate-950 px-3 text-sm font-medium text-white hover:bg-slate-800"
                  >
                    조직 접근 관리
                    <ArrowRight className="h-4 w-4" />
                  </button>
                </div>

                <div className="rounded-lg border border-slate-200 bg-white">
                  <div className="border-b border-slate-200 px-5 py-3">
                    <h2 className="text-sm font-semibold text-slate-950">
                      Teams
                    </h2>
                  </div>
                  <div className="divide-y divide-slate-100">
                    {teams.length === 0 ? (
                      <div className="px-5 py-8 text-center text-sm text-slate-500">
                        표시할 team 없음
                      </div>
                    ) : (
                      teams.map((team) => (
                        <div
                          key={team.id}
                          className="grid gap-3 px-5 py-3 sm:grid-cols-[1fr_auto]"
                        >
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <p className="truncate text-sm font-semibold text-slate-950">
                                {team.name}
                              </p>
                              {!team.is_active && (
                                <span className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
                                  비활성
                                </span>
                              )}
                            </div>
                            <p className="mt-1 text-xs text-slate-500">
                              {team.description || '설명 없음'}
                            </p>
                          </div>
                          <p className="text-sm text-slate-600">
                            {(teamMembers[team.id] || []).length} members
                          </p>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </section>
            )}

            <section className="rounded-lg border border-slate-200 bg-white">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-5 py-3">
                <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-950">
                  <Zap className="h-4 w-4 text-blue-600" />
                  Workflow access
                </h2>
                {!organization?.is_manager && (
                  <span className="text-xs text-slate-500">
                    접근 가능한 workflow만 표시
                  </span>
                )}
              </div>
              <div className="divide-y divide-slate-100">
                {workflowRows.length === 0 ? (
                  <div className="px-5 py-8 text-center text-sm text-slate-500">
                    접근 가능한 workflow 없음
                  </div>
                ) : (
                  workflowRows.map(({ app, permission, permissionError }) => (
                    <div
                      key={app.id}
                      className="grid gap-3 px-5 py-3 sm:grid-cols-[1fr_auto]"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-slate-950">
                          {app.name}
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                          {permissionError || '권한 상태 확인됨'}
                        </p>
                      </div>
                      <span
                        className={`h-fit rounded-md px-2 py-1 text-xs font-medium ${permissionTone(
                          permission,
                        )}`}
                      >
                        {permissionLabel(permission)}
                      </span>
                    </div>
                  ))
                )}
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
