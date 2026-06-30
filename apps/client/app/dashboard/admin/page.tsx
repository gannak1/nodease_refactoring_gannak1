'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  BookOpen,
  Building2,
  Database,
  Key,
  Lock,
  RefreshCw,
  ShieldCheck,
  SlidersHorizontal,
  Users,
} from 'lucide-react';
import { apiClient } from '@/lib/apiClient';
import { ACTIVE_ORGANIZATION_CHANGED_EVENT } from '@/lib/activeOrganization';
import { organizationApi } from '@/app/features/organization/api/organizationApi';
import { MemberStateBadge } from '@/app/features/organization/components/MemberStateBadge';
import { OrganizationAuthBadge } from '@/app/features/organization/components/OrganizationAuthBadge';
import type {
  MembershipState,
  OrganizationMember,
  OrganizationResponse,
} from '@/app/features/organization/types/Organization';
import {
  DashboardPageHeader,
  DashboardPanel,
  DashboardSummaryCard,
} from '@/app/features/dashboard/components/DashboardSurface';
import {
  knowledgeApi,
  type KnowledgeBaseResponse,
} from '@/app/features/knowledge/api/knowledgeApi';

type AdminTab =
  | 'members'
  | 'teams'
  | 'permissions'
  | 'credentials'
  | 'knowledge'
  | 'audit'
  | 'organization';

type TeamResponse = {
  id: string;
  organization_id: string;
  name: string;
  description?: string;
  is_active: boolean;
};

type TeamMemberResponse = {
  id: string;
  user_id: string;
  email: string;
  name: string;
  assigned_at: string;
};

type LLMProviderResponse = {
  id: string;
  name: string;
  base_url: string;
  models: { id: string; name: string }[];
};

type LLMCredentialResponse = {
  id: string;
  provider_id: string;
  credential_name: string;
  config_preview?: string;
  is_valid: boolean;
  created_at: string;
};

type AuditItem = {
  id: string;
  occurred_at: string;
  action: string;
  target_type: string;
  target_id?: string;
  status: string;
};

const tabs: Array<{ key: AdminTab; label: string }> = [
  { key: 'members', label: '멤버' },
  { key: 'teams', label: '팀' },
  { key: 'permissions', label: '권한' },
  { key: 'credentials', label: 'LLM Credentials' },
  { key: 'knowledge', label: '지식 기반' },
  { key: 'audit', label: '감사 로그' },
  { key: 'organization', label: '조직 설정' },
];

const stateOrder: Record<MembershipState, number> = {
  active: 0,
  invited: 1,
  suspended: 2,
  removed: 3,
};

const formatDateTime = (value?: string | null) =>
  value ? new Date(value).toLocaleString() : '-';

export default function AdminConsolePage() {
  const [activeTab, setActiveTab] = useState<AdminTab>('members');
  const [organization, setOrganization] = useState<OrganizationResponse | null>(
    null,
  );
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [teams, setTeams] = useState<TeamResponse[]>([]);
  const [teamMembers, setTeamMembers] = useState<
    Record<string, TeamMemberResponse[]>
  >({});
  const [providers, setProviders] = useState<LLMProviderResponse[]>([]);
  const [credentials, setCredentials] = useState<LLMCredentialResponse[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseResponse[]>(
    [],
  );
  const [auditItems, setAuditItems] = useState<AuditItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const memberCounts = useMemo(
    () =>
      members.reduce<Record<MembershipState, number>>(
        (counts, member) => ({
          ...counts,
          [member.membership_state]: counts[member.membership_state] + 1,
        }),
        { invited: 0, active: 0, suspended: 0, removed: 0 },
      ),
    [members],
  );

  const activeTeams = useMemo(
    () => teams.filter((team) => team.is_active),
    [teams],
  );

  const totalTeamAssignments = useMemo(
    () =>
      Object.values(teamMembers).reduce(
        (total, current) => total + current.length,
        0,
      ),
    [teamMembers],
  );

  const sortedMembers = useMemo(
    () =>
      [...members].sort((left, right) => {
        const stateDiff =
          stateOrder[left.membership_state] - stateOrder[right.membership_state];
        if (stateDiff !== 0) return stateDiff;
        return left.user_name.localeCompare(right.user_name);
      }),
    [members],
  );

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const org = await organizationApi.getCurrentOrganization();
      setOrganization(org);

      if (!org.is_manager) {
        setMembers([]);
        setTeams([]);
        setTeamMembers({});
        setProviders([]);
        setCredentials([]);
        setKnowledgeBases([]);
        setAuditItems([]);
        return;
      }

      const [memberData, teamData] = await Promise.all([
        organizationApi.listMembers(org.id),
        apiClient
          .get<TeamResponse[]>('/teams', {
            params: { organization_id: org.id },
          })
          .then((response) => response.data),
      ]);

      setMembers(memberData);
      setTeams(teamData);

      const [providerData, credentialData, knowledgeData, auditData] =
        await Promise.all([
          apiClient
            .get<LLMProviderResponse[]>('/llm/providers')
            .then((response) => response.data)
            .catch(() => []),
          apiClient
            .get<LLMCredentialResponse[]>('/llm/credentials')
            .then((response) => response.data)
            .catch(() => []),
          knowledgeApi.getKnowledgeBases().catch(() => []),
          apiClient
            .get<{ items: AuditItem[] }>('/users/me/audit-logs', {
              params: { limit: 30 },
            })
            .then((response) => response.data.items || [])
            .catch(() => []),
        ]);

      setProviders(providerData);
      setCredentials(credentialData);
      setKnowledgeBases(knowledgeData);
      setAuditItems(auditData);

      const memberEntries = await Promise.all(
        teamData.map(async (team) => {
          const teamMemberData = await apiClient
            .get<TeamMemberResponse[]>(`/teams/${team.id}/members`)
            .then((response) => response.data)
            .catch(() => []);
          return [team.id, teamMemberData] as const;
        }),
      );
      setTeamMembers(Object.fromEntries(memberEntries));
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : '관리 콘솔 데이터를 불러오지 못했습니다.',
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    window.addEventListener(ACTIVE_ORGANIZATION_CHANGED_EVENT, loadData);
    return () =>
      window.removeEventListener(ACTIVE_ORGANIZATION_CHANGED_EVENT, loadData);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!loading && organization && !organization.is_manager) {
    return (
      <AdminShell
        organization={organization}
        onRefresh={loadData}
        badge={<OrganizationAuthBadge state="member" />}
      >
        <DashboardPanel title="관리 권한 없음" icon={Lock}>
          <div className="px-6 py-12 text-sm text-slate-600">
            현재 조직의 관리자만 이 화면에 접근할 수 있습니다. 멤버 계정에서는
            사이드바의 관리 메뉴가 표시되지 않아야 합니다.
          </div>
        </DashboardPanel>
      </AdminShell>
    );
  }

  return (
    <AdminShell
      organization={organization}
      onRefresh={loadData}
      badge={
        organization && (
          <OrganizationAuthBadge
            state={organization.is_manager ? 'manager' : 'member'}
          />
        )
      }
    >
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="rounded-lg border border-slate-200 bg-white px-6 py-16 text-center text-sm text-slate-500">
          관리 콘솔을 불러오는 중...
        </div>
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <DashboardSummaryCard
              label="활성 멤버"
              value={memberCounts.active}
              icon={Users}
              description={`초대 ${memberCounts.invited} · 정지 ${memberCounts.suspended} · 제거 ${memberCounts.removed}`}
            />
            <DashboardSummaryCard
              label="활성 팀"
              value={activeTeams.length}
              icon={Building2}
              description={`팀 배정 ${totalTeamAssignments}건`}
            />
            <DashboardSummaryCard
              label="LLM Credentials"
              value={credentials.length}
              icon={Key}
              description={`${providers.length}개 provider 기준`}
            />
            <DashboardSummaryCard
              label="지식 기반"
              value={knowledgeBases.length}
              icon={Database}
              description="권한 관리는 후속 API 확인 필요"
            />
          </div>

          <div className="border-b border-slate-200">
            <nav className="-mb-px flex gap-5 overflow-x-auto">
              {tabs.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`whitespace-nowrap border-b-2 px-1 pb-3 text-sm font-semibold ${
                    activeTab === tab.key
                      ? 'border-slate-950 text-slate-950'
                      : 'border-transparent text-slate-500 hover:text-slate-800'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </nav>
          </div>

          {activeTab === 'members' && (
            <MembersTab members={sortedMembers} />
          )}
          {activeTab === 'teams' && (
            <TeamsTab teams={teams} teamMembers={teamMembers} />
          )}
          {activeTab === 'permissions' && <PermissionsTab />}
          {activeTab === 'credentials' && (
            <CredentialsTab
              providers={providers}
              credentials={credentials}
            />
          )}
          {activeTab === 'knowledge' && (
            <KnowledgeTab knowledgeBases={knowledgeBases} />
          )}
          {activeTab === 'audit' && <AuditTab auditItems={auditItems} />}
          {activeTab === 'organization' && (
            <OrganizationTab organization={organization} />
          )}
        </>
      )}
    </AdminShell>
  );
}

function AdminShell({
  organization,
  badge,
  onRefresh,
  children,
}: {
  organization: OrganizationResponse | null;
  badge?: React.ReactNode;
  onRefresh: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-full bg-slate-50 px-6 py-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <DashboardPageHeader
          icon={ShieldCheck}
          title="관리"
          description="조직 멤버, 팀, 권한과 운영 리소스를 관리합니다."
          badge={badge}
          meta={
            <div className="flex min-w-0 items-center gap-2 text-xs text-slate-500">
              <Building2 className="h-3.5 w-3.5 shrink-0 text-blue-600" />
              <span className="truncate">
                {organization?.name || '조직 확인 중'}
              </span>
            </div>
          }
          action={
            <button
              onClick={onRefresh}
              className="inline-flex h-10 items-center gap-2 rounded-md border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 hover:bg-slate-100"
            >
              <RefreshCw className="h-4 w-4" />
              새로고침
            </button>
          }
        />
        {children}
      </div>
    </div>
  );
}

function MembersTab({ members }: { members: OrganizationMember[] }) {
  return (
    <DashboardPanel
      title="멤버"
      icon={Users}
      aside={
        <button
          disabled
          className="h-9 rounded-md bg-slate-950 px-3 text-sm font-semibold text-white opacity-40"
          title="초대 UI flow 연결 후 활성화"
        >
          초대
        </button>
      }
    >
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
            <tr>
              <th className="px-5 py-3">이름</th>
              <th className="px-5 py-3">상태</th>
              <th className="px-5 py-3">조직 권한</th>
              <th className="px-5 py-3">초대</th>
              <th className="px-5 py-3">수락</th>
              <th className="px-5 py-3">작업</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {members.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-5 py-10 text-center text-slate-500">
                  표시할 멤버가 없습니다.
                </td>
              </tr>
            ) : (
              members.map((member) => (
                <tr key={member.id} className="bg-white">
                  <td className="px-5 py-4">
                    <div className="min-w-0">
                      <p className="font-semibold text-slate-950">
                        {member.user_name}
                      </p>
                      <p className="text-xs text-slate-500">
                        {member.user_email}
                      </p>
                    </div>
                  </td>
                  <td className="px-5 py-4">
                    <MemberStateBadge state={member.membership_state} />
                  </td>
                  <td className="px-5 py-4">
                    <OrganizationAuthBadge
                      state={member.organization_auth_state}
                    />
                  </td>
                  <td className="px-5 py-4 text-xs text-slate-500">
                    {formatDateTime(member.invited_at)}
                  </td>
                  <td className="px-5 py-4 text-xs text-slate-500">
                    {formatDateTime(member.accepted_at)}
                  </td>
                  <td className="px-5 py-4">
                    <button
                      disabled
                      className="rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-400"
                    >
                      관리 예정
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </DashboardPanel>
  );
}

function TeamsTab({
  teams,
  teamMembers,
}: {
  teams: TeamResponse[];
  teamMembers: Record<string, TeamMemberResponse[]>;
}) {
  return (
    <DashboardPanel
      title="팀"
      icon={Building2}
      aside={
        <button
          disabled
          className="h-9 rounded-md bg-slate-950 px-3 text-sm font-semibold text-white opacity-40"
        >
          팀 생성
        </button>
      }
    >
      <div className="divide-y divide-slate-100">
        {teams.length === 0 ? (
          <div className="px-5 py-10 text-center text-sm text-slate-500">
            표시할 팀이 없습니다.
          </div>
        ) : (
          teams.map((team) => (
            <div
              key={team.id}
              className="grid gap-4 px-5 py-4 md:grid-cols-[minmax(0,1fr)_260px]"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-semibold text-slate-950">{team.name}</p>
                  <span
                    className={`rounded-md px-2 py-0.5 text-xs font-semibold ${
                      team.is_active
                        ? 'bg-green-50 text-green-700'
                        : 'bg-slate-100 text-slate-600'
                    }`}
                  >
                    {team.is_active ? '활성' : '비활성'}
                  </span>
                </div>
                <p className="mt-1 text-sm text-slate-500">
                  {team.description || '설명 없음'}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {(teamMembers[team.id] || []).length === 0 ? (
                  <span className="text-xs text-slate-400">멤버 없음</span>
                ) : (
                  (teamMembers[team.id] || []).map((member) => (
                    <span
                      key={member.id}
                      className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700"
                    >
                      {member.name}
                    </span>
                  ))
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </DashboardPanel>
  );
}

function PermissionsTab() {
  return (
    <DashboardPanel title="권한" icon={SlidersHorizontal}>
      <Placeholder
        title="권한 관리 UI 이동 예정"
        description="현재 Settings의 workflow/team/user direct permission 관리 UI를 Admin Console로 옮기는 단계에서 실제 grant/update/revoke action을 연결합니다."
      />
    </DashboardPanel>
  );
}

function CredentialsTab({
  providers,
  credentials,
}: {
  providers: LLMProviderResponse[];
  credentials: LLMCredentialResponse[];
}) {
  return (
    <DashboardPanel
      title="LLM Credentials"
      icon={Key}
      aside={
        <div className="flex items-center gap-3">
          <span className="text-xs font-medium text-slate-500">
            active organization 기준
          </span>
          <button
            disabled
            className="h-9 rounded-md bg-slate-950 px-3 text-sm font-semibold text-white opacity-40"
          >
            Credential 등록
          </button>
        </div>
      }
    >
      <div className="divide-y divide-slate-100">
        {providers.length === 0 ? (
          <div className="px-5 py-10 text-center text-sm text-slate-500">
            provider 정보를 불러오지 못했거나 등록된 provider가 없습니다.
          </div>
        ) : (
          providers.map((provider) => {
            const providerCredentials = credentials.filter(
              (credential) => credential.provider_id === provider.id,
            );
            return (
              <div
                key={provider.id}
                className="grid gap-4 px-5 py-4 md:grid-cols-[minmax(0,1fr)_320px]"
              >
                <div>
                  <p className="font-semibold capitalize text-slate-950">
                    {provider.name}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    {provider.models.length} models · {provider.base_url}
                  </p>
                </div>
                <div className="space-y-2">
                  {providerCredentials.length === 0 ? (
                    <span className="text-xs text-slate-400">
                      연결된 credential 없음
                    </span>
                  ) : (
                    providerCredentials.map((credential) => (
                      <div
                        key={credential.id}
                        className="flex items-center justify-between gap-3 rounded-md border border-slate-200 px-3 py-2"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-slate-900">
                            {credential.credential_name}
                          </p>
                          <p className="font-mono text-xs text-slate-500">
                            {credential.config_preview || 'preview 없음'}
                          </p>
                        </div>
                        <span
                          className={`rounded-md px-2 py-0.5 text-xs font-semibold ${
                            credential.is_valid
                              ? 'bg-green-50 text-green-700'
                              : 'bg-red-50 text-red-700'
                          }`}
                        >
                          {credential.is_valid ? 'valid' : 'invalid'}
                        </span>
                      </div>
                    ))
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </DashboardPanel>
  );
}

function KnowledgeTab({
  knowledgeBases,
}: {
  knowledgeBases: KnowledgeBaseResponse[];
}) {
  return (
    <DashboardPanel
      title="지식 기반"
      icon={BookOpen}
      aside={
        <span className="text-xs font-medium text-slate-500">
          기존 지식 기반 목록 기준
        </span>
      }
    >
      <div className="divide-y divide-slate-100">
        {knowledgeBases.length === 0 ? (
          <Placeholder
            title="표시할 지식 기반이 없습니다"
            description="지식 기반 권한 관리 action은 API 범위 확인 후 연결합니다."
          />
        ) : (
          knowledgeBases.map((base) => (
            <div
              key={base.id}
              className="grid gap-3 px-5 py-4 md:grid-cols-[minmax(0,1fr)_160px_160px]"
            >
              <div className="min-w-0">
                <p className="truncate font-semibold text-slate-950">
                  {base.name}
                </p>
                <p className="mt-1 text-sm text-slate-500">
                  {base.description || '설명 없음'}
                </p>
              </div>
              <span className="text-sm text-slate-600">
                문서 {base.document_count}개
              </span>
              <button
                disabled
                className="h-9 rounded-md border border-slate-200 px-3 text-sm font-semibold text-slate-400"
              >
                권한 관리 예정
              </button>
            </div>
          ))
        )}
      </div>
    </DashboardPanel>
  );
}

function AuditTab({ auditItems }: { auditItems: AuditItem[] }) {
  return (
    <DashboardPanel
      title="감사 로그"
      icon={Activity}
      aside={
        <span className="text-xs font-medium text-amber-700">
          현재는 내 활동 로그 기준
        </span>
      }
    >
      <div className="divide-y divide-slate-100">
        {auditItems.length === 0 ? (
          <Placeholder
            title="표시할 활동이 없습니다"
            description="조직 전체 audit API가 확정되면 이 탭을 조직 감사 로그 기준으로 전환합니다."
          />
        ) : (
          auditItems.map((item) => (
            <div
              key={item.id}
              className="grid gap-2 px-5 py-3 text-sm md:grid-cols-[180px_minmax(0,1fr)_120px]"
            >
              <span className="text-xs text-slate-500">
                {formatDateTime(item.occurred_at)}
              </span>
              <span className="font-medium text-slate-900">
                {item.action} · {item.target_type}
              </span>
              <span
                className={`w-fit rounded-md px-2 py-0.5 text-xs font-semibold ${
                  item.status === 'failure'
                    ? 'bg-red-50 text-red-700'
                    : 'bg-slate-100 text-slate-700'
                }`}
              >
                {item.status}
              </span>
            </div>
          ))
        )}
      </div>
    </DashboardPanel>
  );
}

function OrganizationTab({
  organization,
}: {
  organization: OrganizationResponse | null;
}) {
  return (
    <DashboardPanel title="조직 설정" icon={Building2}>
      <div className="grid gap-4 px-5 py-5 md:grid-cols-2">
        <div className="rounded-md border border-slate-200 bg-slate-50 p-4">
          <p className="text-xs font-semibold uppercase text-slate-500">
            조직명
          </p>
          <p className="mt-2 font-semibold text-slate-950">
            {organization?.name || '확인 중'}
          </p>
        </div>
        <div className="rounded-md border border-amber-200 bg-amber-50 p-4">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 text-amber-700" />
            <p className="text-sm leading-6 text-amber-800">
              조직명 수정, 기본 팀, 위험 action은 정책과 API 범위 확정 후
              연결합니다.
            </p>
          </div>
        </div>
      </div>
    </DashboardPanel>
  );
}

function Placeholder({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="px-6 py-12 text-center">
      <p className="font-semibold text-slate-900">{title}</p>
      <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-slate-500">
        {description}
      </p>
    </div>
  );
}
