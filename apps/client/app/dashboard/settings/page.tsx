'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertCircle,
  CheckCircle,
  ExternalLink,
  Key,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Users,
} from 'lucide-react';
import {
  activeOrganizationHeaders,
  getStoredActiveOrganizationId,
  resolveActiveOrganizationId,
  setActiveOrganizationId,
} from '@/lib/activeOrganization';

type SettingsTab = 'access' | 'credentials' | 'activity';
type ResourceType = 'workflow' | 'llm_credential';
type GranteeType = 'team' | 'user';
type AuthState = 'viewer' | 'operator' | 'builder' | 'manager';

type OrganizationResponse = {
  id: string;
  name: string;
  is_manager: boolean;
};

type UserResponse = {
  id: string;
  email: string;
  name: string;
};

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

type ResourcePermissionEntry = {
  id: string;
  grantee_type: GranteeType;
  grantee_id: string;
  grantee_name: string;
  auth_state: string;
  assigned_at: string;
};

type ResourcePermissionListResponse = {
  resource_type: ResourceType;
  resource_id: string;
  organization_id: string;
  team_permissions: ResourcePermissionEntry[];
  user_permissions: ResourcePermissionEntry[];
};

type LLMModelResponse = {
  id: string;
  name: string;
  model_id_for_api_call?: string;
};

type LLMProviderResponse = {
  id: string;
  name: string;
  description?: string;
  type: string;
  base_url: string;
  doc_url?: string;
  models: LLMModelResponse[];
};

type LLMCredentialResponse = {
  id: string;
  provider_id: string;
  organization_id?: string;
  credential_name: string;
  config_preview?: string;
  is_valid: boolean;
  created_at: string;
};

type AppResponse = {
  id: string;
  name: string;
  workflow_id?: string;
};

type AuditItem = {
  id: string;
  occurred_at: string;
  action: string;
  target_type: string;
  target_id?: string;
  status: string;
};

const API_BASE_URL = '/api/v1';
const AUTH_STATES: AuthState[] = ['viewer', 'operator', 'builder', 'manager'];

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const organizationId = getStoredActiveOrganizationId();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: 'include',
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...activeOrganizationHeaders(organizationId),
      ...(init?.headers || {}),
    },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || body.message || 'Request failed');
  }
  return body as T;
}

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<SettingsTab>('access');
  const [organization, setOrganization] = useState<OrganizationResponse | null>(
    null,
  );
  const [users, setUsers] = useState<UserResponse[]>([]);
  const [teams, setTeams] = useState<TeamResponse[]>([]);
  const [teamMembers, setTeamMembers] = useState<
    Record<string, TeamMemberResponse[]>
  >({});
  const [providers, setProviders] = useState<LLMProviderResponse[]>([]);
  const [credentials, setCredentials] = useState<LLMCredentialResponse[]>([]);
  const [apps, setApps] = useState<AppResponse[]>([]);
  const [auditItems, setAuditItems] = useState<AuditItem[]>([]);
  const [workflowPermissions, setWorkflowPermissions] =
    useState<ResourcePermissionListResponse | null>(null);
  const [credentialPermissions, setCredentialPermissions] =
    useState<ResourcePermissionListResponse | null>(null);

  const [selectedWorkflowId, setSelectedWorkflowId] = useState('');
  const [selectedCredentialId, setSelectedCredentialId] = useState('');
  const [newTeam, setNewTeam] = useState({ name: '', description: '' });
  const [memberForm, setMemberForm] = useState({ teamId: '', userId: '' });
  const [permissionForm, setPermissionForm] = useState<{
    resourceType: ResourceType;
    granteeType: GranteeType;
    granteeId: string;
    authState: AuthState;
  }>({
    resourceType: 'workflow',
    granteeType: 'team',
    granteeId: '',
    authState: 'viewer',
  });
  const [credentialForm, setCredentialForm] = useState({
    providerId: '',
    alias: '',
    apiKey: '',
  });
  const [syncResults, setSyncResults] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const workflowOptions = useMemo(
    () => apps.filter((app) => Boolean(app.workflow_id)),
    [apps],
  );

  const activePermissions =
    permissionForm.resourceType === 'workflow'
      ? workflowPermissions
      : credentialPermissions;

  const loadTeamMembers = async (items: TeamResponse[]) => {
    const entries = await Promise.all(
      items.map(async (team) => {
        const members = await apiRequest<TeamMemberResponse[]>(
          `/teams/${team.id}/members`,
        ).catch(() => []);
        return [team.id, members] as const;
      }),
    );
    setTeamMembers(Object.fromEntries(entries));
  };

  const loadPermissions = async (
    resourceType = permissionForm.resourceType,
    workflowId = selectedWorkflowId,
    credentialId = selectedCredentialId,
  ) => {
    try {
      if (resourceType === 'workflow' && workflowId) {
        const data = await apiRequest<ResourcePermissionListResponse>(
          `/permissions/workflows/${workflowId}`,
        );
        setWorkflowPermissions(data);
      }
      if (resourceType === 'llm_credential' && credentialId) {
        const data = await apiRequest<ResourcePermissionListResponse>(
          `/permissions/llm-credentials/${credentialId}`,
        );
        setCredentialPermissions(data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '권한 조회 실패');
    }
  };

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const organizations =
        await apiRequest<OrganizationResponse[]>('/organizations');
      const organizationId = resolveActiveOrganizationId(organizations);
      if (!organizationId) {
        throw new Error('현재 선택된 조직이 없습니다.');
      }
      const org = await apiRequest<OrganizationResponse>(
        '/organizations/current',
        { headers: activeOrganizationHeaders(organizationId) },
      );
      setActiveOrganizationId(org.id);
      setOrganization(org);

      const [userData, teamData, providerData, credentialData, appData, audit] =
        await Promise.all([
          apiRequest<UserResponse[]>(`/users?organization_id=${org.id}`),
          apiRequest<TeamResponse[]>(`/teams?organization_id=${org.id}`),
          apiRequest<LLMProviderResponse[]>('/llm/providers'),
          apiRequest<LLMCredentialResponse[]>('/llm/credentials'),
          apiRequest<AppResponse[]>('/apps'),
          apiRequest<{ items: AuditItem[] }>('/users/me/audit-logs?limit=30'),
        ]);

      setUsers(userData);
      setTeams(teamData);
      setProviders(providerData);
      setCredentials(credentialData);
      setApps(appData);
      setAuditItems(audit.items || []);
      await loadTeamMembers(teamData);

      const firstWorkflowId =
        selectedWorkflowId ||
        appData.find((app) => app.workflow_id)?.workflow_id ||
        '';
      const firstCredentialId = selectedCredentialId || credentialData[0]?.id || '';
      setSelectedWorkflowId(firstWorkflowId);
      setSelectedCredentialId(firstCredentialId);
      setMemberForm((prev) => ({
        teamId: prev.teamId || teamData[0]?.id || '',
        userId: prev.userId || userData[0]?.id || '',
      }));
      setPermissionForm((prev) => ({
        ...prev,
        granteeId:
          prev.granteeId ||
          (prev.granteeType === 'team' ? teamData[0]?.id : userData[0]?.id) ||
          '',
      }));

      if (firstWorkflowId) {
        await loadPermissions('workflow', firstWorkflowId, firstCredentialId);
      }
      if (firstCredentialId) {
        await loadPermissions('llm_credential', firstWorkflowId, firstCredentialId);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '설정 데이터를 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleCreateTeam = async () => {
    if (!organization || !newTeam.name.trim()) return;
    setSubmitting(true);
    try {
      await apiRequest('/teams', {
        method: 'POST',
        body: JSON.stringify({
          organization_id: organization.id,
          name: newTeam.name.trim(),
          description: newTeam.description.trim() || null,
        }),
      });
      setNewTeam({ name: '', description: '' });
      await loadData();
    } catch (err) {
      alert(err instanceof Error ? err.message : '팀 생성 실패');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeactivateTeam = async (teamId: string) => {
    if (!confirm('이 팀을 비활성화할까요?')) return;
    await apiRequest(`/teams/${teamId}`, { method: 'DELETE' });
    await loadData();
  };

  const handleAddMember = async () => {
    if (!memberForm.teamId || !memberForm.userId) return;
    await apiRequest(`/teams/${memberForm.teamId}/members`, {
      method: 'POST',
      body: JSON.stringify({ user_id: memberForm.userId }),
    });
    const refreshed = await apiRequest<TeamMemberResponse[]>(
      `/teams/${memberForm.teamId}/members`,
    );
    setTeamMembers((prev) => ({ ...prev, [memberForm.teamId]: refreshed }));
  };

  const handleRemoveMember = async (teamId: string, userId: string) => {
    await apiRequest(`/teams/${teamId}/members/${userId}`, { method: 'DELETE' });
    const refreshed = await apiRequest<TeamMemberResponse[]>(
      `/teams/${teamId}/members`,
    );
    setTeamMembers((prev) => ({ ...prev, [teamId]: refreshed }));
  };

  const permissionPath = (
    resourceType: ResourceType,
    granteeType: GranteeType,
    granteeId: string,
  ) => {
    const resourceId =
      resourceType === 'workflow' ? selectedWorkflowId : selectedCredentialId;
    const resourcePath =
      resourceType === 'workflow'
        ? `/permissions/workflows/${resourceId}`
        : `/permissions/llm-credentials/${resourceId}`;
    return `${resourcePath}/${granteeType}s/${granteeId}`;
  };

  const handleGrantPermission = async () => {
    if (!permissionForm.granteeId) return;
    const resourceId =
      permissionForm.resourceType === 'workflow'
        ? selectedWorkflowId
        : selectedCredentialId;
    if (!resourceId) return;
    await apiRequest(
      permissionPath(
        permissionForm.resourceType,
        permissionForm.granteeType,
        permissionForm.granteeId,
      ),
      {
        method: 'PUT',
        body: JSON.stringify({ auth_state: permissionForm.authState }),
      },
    );
    await loadPermissions();
    const audit = await apiRequest<{ items: AuditItem[] }>(
      '/users/me/audit-logs?limit=30',
    );
    setAuditItems(audit.items || []);
  };

  const handleRevokePermission = async (
    resourceType: ResourceType,
    granteeType: GranteeType,
    granteeId: string,
  ) => {
    await apiRequest(permissionPath(resourceType, granteeType, granteeId), {
      method: 'DELETE',
    });
    await loadPermissions(resourceType);
  };

  const handleRegisterCredential = async () => {
    if (!organization || !credentialForm.providerId || !credentialForm.alias) return;
    setSubmitting(true);
    try {
      await apiRequest('/llm/credentials', {
        method: 'POST',
        body: JSON.stringify({
          provider_id: credentialForm.providerId,
          organization_id: organization.id,
          credential_name: credentialForm.alias,
          api_key: credentialForm.apiKey,
        }),
      });
      setCredentialForm({ providerId: '', alias: '', apiKey: '' });
      await loadData();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Credential 등록 실패');
    } finally {
      setSubmitting(false);
    }
  };

  const handleSyncCredential = async (credentialId: string) => {
    setSyncResults((prev) => ({ ...prev, [credentialId]: '동기화 중' }));
    try {
      const result = await apiRequest<{
        remote_models: number;
        verified_models: number;
      }>(`/llm/credentials/${credentialId}/sync-models`, { method: 'POST' });
      setSyncResults((prev) => ({
        ...prev,
        [credentialId]: `${result.verified_models}/${result.remote_models} models`,
      }));
    } catch (err) {
      setSyncResults((prev) => ({
        ...prev,
        [credentialId]: err instanceof Error ? err.message : '실패',
      }));
    }
  };

  const handleDeleteCredential = async (credentialId: string) => {
    if (!confirm('이 credential을 삭제할까요?')) return;
    await apiRequest(`/llm/credentials/${credentialId}`, { method: 'DELETE' });
    await loadData();
  };

  const renderPermissionRows = (rows: ResourcePermissionEntry[]) =>
    rows.length === 0 ? (
      <div className="px-3 py-3 text-sm text-gray-500">부여된 권한 없음</div>
    ) : (
      rows.map((permission) => (
        <div
          key={permission.id}
          className="flex items-center justify-between gap-3 border-t border-gray-100 px-3 py-2"
        >
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-gray-900">
              {permission.grantee_name}
            </p>
            <p className="text-xs text-gray-500">{permission.auth_state}</p>
          </div>
          <button
            onClick={() =>
              handleRevokePermission(
                permissionForm.resourceType,
                permission.grantee_type,
                permission.grantee_id,
              )
            }
            className="rounded-md p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600"
            title="권한 회수"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      ))
    );

  return (
    <div className="min-h-full bg-white p-8">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">설정</h1>
          <p className="mt-1 text-sm text-gray-600">
            {organization
              ? `${organization.name} · ${organization.is_manager ? 'manager' : 'member'}`
              : 'Organization 확인 중'}
          </p>
        </div>
        <button
          onClick={loadData}
          className="inline-flex items-center gap-2 rounded-md border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          <RefreshCw className="h-4 w-4" />
          새로고침
        </button>
      </div>

      <div className="mb-6 border-b border-gray-200">
        <nav className="-mb-px flex gap-6">
          {[
            ['access', '조직 접근'],
            ['credentials', 'LLM Credentials'],
            ['activity', 'Activity'],
          ].map(([key, label]) => (
            <button
              key={key}
              onClick={() => setActiveTab(key as SettingsTab)}
              className={`border-b-2 px-1 pb-3 text-sm font-medium ${
                activeTab === key
                  ? 'border-blue-600 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              {label}
            </button>
          ))}
        </nav>
      </div>

      {error && (
        <div className="mb-6 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <div className="py-16 text-center text-sm text-gray-500">로딩 중...</div>
      ) : activeTab === 'access' ? (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
          <section className="space-y-4">
            <div className="rounded-lg border border-gray-200">
              <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
                <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-900">
                  <Users className="h-4 w-4 text-blue-600" />
                  Teams
                </h2>
                <div className="flex gap-2">
                  <input
                    value={newTeam.name}
                    onChange={(event) =>
                      setNewTeam((prev) => ({
                        ...prev,
                        name: event.target.value,
                      }))
                    }
                    className="h-9 w-40 rounded-md border border-gray-300 px-3 text-sm"
                    placeholder="팀 이름"
                  />
                  <button
                    onClick={handleCreateTeam}
                    disabled={submitting || !newTeam.name.trim()}
                    className="inline-flex h-9 items-center gap-1.5 rounded-md bg-gray-900 px-3 text-sm font-medium text-white disabled:opacity-40"
                  >
                    <Plus className="h-4 w-4" />
                    생성
                  </button>
                </div>
              </div>
              <div>
                {teams.map((team) => (
                  <div
                    key={team.id}
                    className="border-b border-gray-100 px-4 py-4 last:border-b-0"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-medium text-gray-900">{team.name}</p>
                        <p className="text-xs text-gray-500">
                          {team.description || '설명 없음'}
                        </p>
                      </div>
                      <button
                        onClick={() => handleDeactivateTeam(team.id)}
                        className="rounded-md p-1.5 text-gray-400 hover:bg-red-50 hover:text-red-600"
                        title="팀 비활성화"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {(teamMembers[team.id] || []).map((member) => (
                        <span
                          key={member.id}
                          className="inline-flex items-center gap-1 rounded-md bg-gray-100 px-2 py-1 text-xs text-gray-700"
                        >
                          {member.name}
                          <button
                            onClick={() =>
                              handleRemoveMember(team.id, member.user_id)
                            }
                            className="text-gray-400 hover:text-red-600"
                            title="멤버 제거"
                          >
                            <Trash2 className="h-3 w-3" />
                          </button>
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-lg border border-gray-200 p-4">
              <h2 className="mb-3 text-sm font-semibold text-gray-900">
                Member 추가
              </h2>
              <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
                <select
                  value={memberForm.teamId}
                  onChange={(event) =>
                    setMemberForm((prev) => ({
                      ...prev,
                      teamId: event.target.value,
                    }))
                  }
                  className="h-10 rounded-md border border-gray-300 px-3 text-sm"
                >
                  {teams.map((team) => (
                    <option key={team.id} value={team.id}>
                      {team.name}
                    </option>
                  ))}
                </select>
                <select
                  value={memberForm.userId}
                  onChange={(event) =>
                    setMemberForm((prev) => ({
                      ...prev,
                      userId: event.target.value,
                    }))
                  }
                  className="h-10 rounded-md border border-gray-300 px-3 text-sm"
                >
                  {users.map((user) => (
                    <option key={user.id} value={user.id}>
                      {user.name} ({user.email})
                    </option>
                  ))}
                </select>
                <button
                  onClick={handleAddMember}
                  className="h-10 rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700"
                >
                  추가
                </button>
              </div>
            </div>
          </section>

          <section className="rounded-lg border border-gray-200">
            <div className="border-b border-gray-200 px-4 py-3">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-900">
                <ShieldCheck className="h-4 w-4 text-blue-600" />
                Resource Permissions
              </h2>
            </div>
            <div className="space-y-4 p-4">
              <div className="grid grid-cols-2 gap-3">
                <select
                  value={permissionForm.resourceType}
                  onChange={(event) => {
                    const resourceType = event.target.value as ResourceType;
                    setPermissionForm((prev) => ({ ...prev, resourceType }));
                    loadPermissions(resourceType);
                  }}
                  className="h-10 rounded-md border border-gray-300 px-3 text-sm"
                >
                  <option value="workflow">Workflow</option>
                  <option value="llm_credential">LLM Credential</option>
                </select>
                {permissionForm.resourceType === 'workflow' ? (
                  <select
                    value={selectedWorkflowId}
                    onChange={(event) => {
                      setSelectedWorkflowId(event.target.value);
                      loadPermissions('workflow', event.target.value);
                    }}
                    className="h-10 rounded-md border border-gray-300 px-3 text-sm"
                  >
                    {workflowOptions.map((app) => (
                      <option key={app.workflow_id} value={app.workflow_id}>
                        {app.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <select
                    value={selectedCredentialId}
                    onChange={(event) => {
                      setSelectedCredentialId(event.target.value);
                      loadPermissions(
                        'llm_credential',
                        selectedWorkflowId,
                        event.target.value,
                      );
                    }}
                    className="h-10 rounded-md border border-gray-300 px-3 text-sm"
                  >
                    {credentials.map((credential) => (
                      <option key={credential.id} value={credential.id}>
                        {credential.credential_name}
                      </option>
                    ))}
                  </select>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3">
                <select
                  value={permissionForm.granteeType}
                  onChange={(event) => {
                    const granteeType = event.target.value as GranteeType;
                    setPermissionForm((prev) => ({
                      ...prev,
                      granteeType,
                      granteeId:
                        granteeType === 'team'
                          ? teams[0]?.id || ''
                          : users[0]?.id || '',
                    }));
                  }}
                  className="h-10 rounded-md border border-gray-300 px-3 text-sm"
                >
                  <option value="team">Team</option>
                  <option value="user">User direct</option>
                </select>
                <select
                  value={permissionForm.granteeId}
                  onChange={(event) =>
                    setPermissionForm((prev) => ({
                      ...prev,
                      granteeId: event.target.value,
                    }))
                  }
                  className="h-10 rounded-md border border-gray-300 px-3 text-sm"
                >
                  {(permissionForm.granteeType === 'team' ? teams : users).map(
                    (item) => (
                      <option key={item.id} value={item.id}>
                        {'email' in item
                          ? `${item.name} (${item.email})`
                          : item.name}
                      </option>
                    ),
                  )}
                </select>
              </div>

              <div className="grid grid-cols-[1fr_auto] gap-3">
                <select
                  value={permissionForm.authState}
                  onChange={(event) =>
                    setPermissionForm((prev) => ({
                      ...prev,
                      authState: event.target.value as AuthState,
                    }))
                  }
                  className="h-10 rounded-md border border-gray-300 px-3 text-sm"
                >
                  {AUTH_STATES.map((state) => (
                    <option key={state} value={state}>
                      {state}
                    </option>
                  ))}
                </select>
                <button
                  onClick={handleGrantPermission}
                  className="h-10 rounded-md bg-blue-600 px-4 text-sm font-medium text-white hover:bg-blue-700"
                >
                  부여
                </button>
              </div>

              <div className="overflow-hidden rounded-md border border-gray-200">
                <div className="bg-gray-50 px-3 py-2 text-xs font-semibold uppercase text-gray-500">
                  Team permissions
                </div>
                {renderPermissionRows(activePermissions?.team_permissions || [])}
                <div className="border-t border-gray-200 bg-gray-50 px-3 py-2 text-xs font-semibold uppercase text-gray-500">
                  User direct permissions
                </div>
                {renderPermissionRows(activePermissions?.user_permissions || [])}
              </div>
            </div>
          </section>
        </div>
      ) : activeTab === 'credentials' ? (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
          <section className="grid gap-4">
            {providers.map((provider) => {
              const providerCredentials = credentials.filter(
                (credential) => credential.provider_id === provider.id,
              );
              return (
                <div
                  key={provider.id}
                  className="rounded-lg border border-gray-200 bg-white"
                >
                  <div className="flex items-start justify-between gap-4 border-b border-gray-100 px-5 py-4">
                    <div>
                      <div className="flex items-center gap-2">
                        <h2 className="font-semibold capitalize text-gray-900">
                          {provider.name}
                        </h2>
                        {providerCredentials.length > 0 && (
                          <span className="rounded-md bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700">
                            Connected
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-sm text-gray-500">
                        {provider.models.length} models · {provider.base_url}
                      </p>
                    </div>
                    {provider.doc_url && (
                      <a
                        href={provider.doc_url}
                        target="_blank"
                        rel="noreferrer"
                        className="rounded-md p-2 text-gray-500 hover:bg-gray-100"
                        title="Provider 문서"
                      >
                        <ExternalLink className="h-4 w-4" />
                      </a>
                    )}
                  </div>
                  <div className="divide-y divide-gray-100">
                    {providerCredentials.length === 0 ? (
                      <div className="px-5 py-4 text-sm text-gray-500">
                        등록된 credential 없음
                      </div>
                    ) : (
                      providerCredentials.map((credential) => (
                        <div
                          key={credential.id}
                          className="flex items-center justify-between gap-3 px-5 py-3"
                        >
                          <div className="flex min-w-0 items-center gap-3">
                            <div
                              className={`rounded-full p-1.5 ${
                                credential.is_valid
                                  ? 'bg-green-50 text-green-600'
                                  : 'bg-red-50 text-red-600'
                              }`}
                            >
                              {credential.is_valid ? (
                                <CheckCircle className="h-4 w-4" />
                              ) : (
                                <AlertCircle className="h-4 w-4" />
                              )}
                            </div>
                            <div className="min-w-0">
                              <p className="truncate text-sm font-medium text-gray-900">
                                {credential.credential_name}
                              </p>
                              <p className="font-mono text-xs text-gray-500">
                                {credential.config_preview || 'preview 없음'}
                              </p>
                            </div>
                          </div>
                          <div className="flex items-center gap-1">
                            <span className="mr-2 text-xs text-gray-500">
                              {syncResults[credential.id]}
                            </span>
                            <button
                              onClick={() => handleSyncCredential(credential.id)}
                              className="rounded-md p-2 text-gray-500 hover:bg-gray-100"
                              title="모델 동기화"
                            >
                              <RefreshCw className="h-4 w-4" />
                            </button>
                            <button
                              onClick={() => handleDeleteCredential(credential.id)}
                              className="rounded-md p-2 text-gray-500 hover:bg-red-50 hover:text-red-600"
                              title="Credential 삭제"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              );
            })}
          </section>

          <section className="h-fit rounded-lg border border-gray-200 p-5">
            <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-gray-900">
              <Key className="h-4 w-4 text-blue-600" />
              Credential 등록
            </h2>
            <div className="space-y-3">
              <select
                value={credentialForm.providerId}
                onChange={(event) =>
                  setCredentialForm((prev) => ({
                    ...prev,
                    providerId: event.target.value,
                  }))
                }
                className="h-10 w-full rounded-md border border-gray-300 px-3 text-sm"
              >
                <option value="">Provider 선택</option>
                {providers.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.name}
                  </option>
                ))}
              </select>
              <input
                value={credentialForm.alias}
                onChange={(event) =>
                  setCredentialForm((prev) => ({
                    ...prev,
                    alias: event.target.value,
                  }))
                }
                className="h-10 w-full rounded-md border border-gray-300 px-3 text-sm"
                placeholder="별칭"
              />
              <input
                value={credentialForm.apiKey}
                onChange={(event) =>
                  setCredentialForm((prev) => ({
                    ...prev,
                    apiKey: event.target.value,
                  }))
                }
                type="password"
                className="h-10 w-full rounded-md border border-gray-300 px-3 font-mono text-sm"
                placeholder="API key"
              />
              <button
                onClick={handleRegisterCredential}
                disabled={submitting}
                className="h-10 w-full rounded-md bg-blue-600 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                등록 및 모델 동기화
              </button>
            </div>
          </section>
        </div>
      ) : (
        <section className="rounded-lg border border-gray-200">
          <div className="border-b border-gray-200 px-4 py-3">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-900">
              <Activity className="h-4 w-4 text-blue-600" />
              Audit Activity
            </h2>
          </div>
          <div className="divide-y divide-gray-100">
            {auditItems.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-gray-500">
                표시할 activity 없음
              </div>
            ) : (
              auditItems.map((item) => (
                <div
                  key={item.id}
                  className="grid gap-2 px-4 py-3 text-sm sm:grid-cols-[220px_1fr_160px]"
                >
                  <span className="text-gray-500">
                    {new Date(item.occurred_at).toLocaleString()}
                  </span>
                  <span className="font-medium text-gray-900">
                    {item.action} · {item.target_type}
                  </span>
                  <span
                    className={`w-fit rounded-md px-2 py-0.5 text-xs font-medium ${
                      item.status === 'failure'
                        ? 'bg-red-50 text-red-700'
                        : 'bg-gray-100 text-gray-700'
                    }`}
                  >
                    {item.status}
                  </span>
                </div>
              ))
            )}
          </div>
        </section>
      )}
    </div>
  );
}
