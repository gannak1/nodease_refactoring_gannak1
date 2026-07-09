'use client';

import { useEffect, useMemo, useState } from 'react';
import { isAxiosError } from 'axios';
import {
  AlertTriangle,
  BookOpen,
  Building2,
  Database,
  Key,
  Lock,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  UserPlus,
  Users,
  X,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiClient } from '@/lib/apiClient';
import { ACTIVE_ORGANIZATION_CHANGED_EVENT } from '@/lib/activeOrganization';
import { AdminSummaryCards } from '@/app/features/admin/components/AdminSummaryCards';
import { AuditSearchTab } from '@/app/features/admin/components/AuditSearchTab';
import { PermissionRequestsTab } from '@/app/features/admin/components/PermissionRequestsTab';
import { UsageTab } from '@/app/features/admin/components/UsageTab';
import { authApi } from '@/app/features/auth/api/authApi';
import { organizationApi } from '@/app/features/organization/api/organizationApi';
import { ActiveOrganizationMemberPicker } from '@/app/features/organization/components/ActiveOrganizationMemberPicker';
import { MemberStateBadge } from '@/app/features/organization/components/MemberStateBadge';
import { OrganizationAuthBadge } from '@/app/features/organization/components/OrganizationAuthBadge';
import { getMemberActionLocks } from '@/app/features/organization/utils/memberActionLocks';
import type {
  MembershipState,
  OrganizationAuthState,
  OrganizationMember,
  OrganizationMemberRemoveResponse,
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
  | 'permission-requests'
  | 'usage'
  | 'credentials'
  | 'knowledge'
  | 'audit'
  | 'organization';

type TeamResponse = {
  id: string;
  organization_id: string;
  name: string;
  description?: string | null;
  is_active: boolean;
  is_auto_add?: boolean;
  deactivated_at?: string | null;
};

type TeamMemberResponse = {
  id: string;
  user_id: string;
  email: string;
  name: string;
  assigned_at: string;
};

type AppResponse = {
  id: string;
  name: string;
  workflow_id?: string | null;
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

type ResourceType = 'workflow' | 'knowledge_base' | 'llm_credential';
type GranteeType = 'team' | 'user';
type ResourceAuthState = 'viewer' | 'operator' | 'builder' | 'manager';

type ResourcePermissionEntry = {
  id: string;
  grantee_type: GranteeType;
  grantee_id: string;
  grantee_name: string;
  auth_state: ResourceAuthState;
  assigned_at: string;
};

type ResourcePermissionListResponse = {
  resource_type: ResourceType;
  resource_id: string;
  organization_id: string;
  team_permissions: ResourcePermissionEntry[];
  user_permissions: ResourcePermissionEntry[];
};

type ConfirmState = {
  title: string;
  description: string;
  confirmLabel: string;
  tone?: 'default' | 'danger';
  details?: string[];
  onConfirm: () => Promise<void>;
};

type TeamEditorState =
  | { mode: 'create'; team?: undefined }
  | { mode: 'edit'; team: TeamResponse };

const tabs: Array<{ key: AdminTab; label: string }> = [
  { key: 'members', label: '멤버' },
  { key: 'teams', label: '팀' },
  { key: 'permissions', label: '권한' },
  { key: 'permission-requests', label: '권한 신청' },
  { key: 'usage', label: '비용' },
  { key: 'credentials', label: 'LLM Credentials' },
  { key: 'knowledge', label: '지식 기반' },
  { key: 'audit', label: '감사 로그' },
  { key: 'organization', label: '조직 설정' },
];

const PAGE_SIZE = 20;
const AUTH_STATES: OrganizationAuthState[] = ['member', 'manager'];
const RESOURCE_AUTH_STATES: ResourceAuthState[] = [
  'viewer',
  'operator',
  'builder',
  'manager',
];

const stateOrder: Record<MembershipState, number> = {
  active: 0,
  invited: 1,
  suspended: 2,
  removed: 3,
};

const formatDateTime = (value?: string | null) =>
  value ? new Date(value).toLocaleString() : '-';

const getErrorMessage = (error: unknown, fallback: string) => {
  if (isAxiosError(error)) {
    const data = error.response?.data as
      | { detail?: string; message?: string; error?: { message?: string } }
      | undefined;
    return data?.detail || data?.message || data?.error?.message || error.message;
  }
  return error instanceof Error ? error.message : fallback;
};

const uniqueMembers = (items: OrganizationMember[]) =>
  Array.from(new Map(items.map((member) => [member.id, member])).values());

const normalizeText = (value?: string | null) => (value || '').toLowerCase();

const paginate = <T,>(items: T[], page: number) =>
  items.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

export default function AdminConsolePage() {
  const [activeTab, setActiveTab] = useState<AdminTab>('members');
  const [organization, setOrganization] = useState<OrganizationResponse | null>(
    null,
  );
  const [currentUserId, setCurrentUserId] = useState<string | null>(null);
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [teams, setTeams] = useState<TeamResponse[]>([]);
  const [teamMembers, setTeamMembers] = useState<
    Record<string, TeamMemberResponse[]>
  >({});
  const [teamMemberLoadErrors, setTeamMemberLoadErrors] = useState<
    Record<string, boolean>
  >({});
  const [apps, setApps] = useState<AppResponse[]>([]);
  const [providers, setProviders] = useState<LLMProviderResponse[]>([]);
  const [credentials, setCredentials] = useState<LLMCredentialResponse[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseResponse[]>(
    [],
  );
  const [workflowPermissions, setWorkflowPermissions] =
    useState<ResourcePermissionListResponse | null>(null);
  const [knowledgePermissions, setKnowledgePermissions] =
    useState<ResourcePermissionListResponse | null>(null);
  const [credentialPermissions, setCredentialPermissions] =
    useState<ResourcePermissionListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [memberQuery, setMemberQuery] = useState('');
  const [memberStateFilter, setMemberStateFilter] = useState<
    MembershipState | 'all'
  >('all');
  const [memberAuthFilter, setMemberAuthFilter] = useState<
    OrganizationAuthState | 'all'
  >('all');
  const [memberPage, setMemberPage] = useState(1);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteForm, setInviteForm] = useState({
    userId: '',
    authState: 'member' as OrganizationAuthState,
  });

  const [teamQuery, setTeamQuery] = useState('');
  const [teamStateFilter, setTeamStateFilter] = useState<
    'all' | 'active' | 'inactive'
  >('all');
  const [teamMemberFilter, setTeamMemberFilter] = useState<
    'all' | 'has_members' | 'empty'
  >('all');
  const [teamPage, setTeamPage] = useState(1);
  const [teamEditor, setTeamEditor] = useState<TeamEditorState | null>(null);
  const [teamForm, setTeamForm] = useState({
    name: '',
    description: '',
    isAutoAdd: false,
  });
  const [selectedTeamId, setSelectedTeamId] = useState<string | null>(null);
  const [teamMemberUserId, setTeamMemberUserId] = useState('');

  const [permissionResourceType, setPermissionResourceType] =
    useState<ResourceType>('workflow');
  const [selectedWorkflowId, setSelectedWorkflowId] = useState('');
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState('');
  const [selectedCredentialId, setSelectedCredentialId] = useState('');
  const [permissionGranteeType, setPermissionGranteeType] =
    useState<GranteeType>('team');
  const [permissionGranteeId, setPermissionGranteeId] = useState('');
  const [permissionAuthState, setPermissionAuthState] =
    useState<ResourceAuthState>('viewer');

  const [credentialPanelOpen, setCredentialPanelOpen] = useState(false);
  const [credentialForm, setCredentialForm] = useState({
    providerId: '',
    credentialName: '',
    apiKey: '',
  });

  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);
  const [actionPending, setActionPending] = useState(false);

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

  const activeMembers = useMemo(
    () => members.filter((member) => member.membership_state === 'active'),
    [members],
  );

  const activeTeams = useMemo(
    () => teams.filter((team) => team.is_active),
    [teams],
  );

  const workflowOptions = useMemo(
    () => apps.filter((app) => Boolean(app.workflow_id)),
    [apps],
  );

  const selectedPermissionList =
    permissionResourceType === 'workflow'
      ? workflowPermissions
      : permissionResourceType === 'knowledge_base'
        ? knowledgePermissions
        : credentialPermissions;

  const permissionResourceId =
    permissionResourceType === 'workflow'
      ? selectedWorkflowId
      : permissionResourceType === 'knowledge_base'
        ? selectedKnowledgeBaseId
        : selectedCredentialId;

  const activeManagerCount = useMemo(
    () =>
      members.filter(
        (member) =>
          member.membership_state === 'active' &&
          member.organization_auth_state === 'manager',
      ).length,
    [members],
  );

  const totalTeamAssignments = useMemo(
    () =>
      Object.values(teamMembers).reduce(
        (total, current) => total + current.length,
        0,
      ),
    [teamMembers],
  );

  const filteredMembers = useMemo(() => {
    const query = normalizeText(memberQuery);
    return [...members]
      .filter((member) => {
        if (
          memberStateFilter !== 'all' &&
          member.membership_state !== memberStateFilter
        ) {
          return false;
        }
        if (
          memberAuthFilter !== 'all' &&
          member.organization_auth_state !== memberAuthFilter
        ) {
          return false;
        }
        if (!query) return true;
        return (
          normalizeText(member.user_name).includes(query) ||
          normalizeText(member.user_email).includes(query)
        );
      })
      .sort((left, right) => {
        const stateDiff =
          stateOrder[left.membership_state] - stateOrder[right.membership_state];
        if (stateDiff !== 0) return stateDiff;
        return left.user_name.localeCompare(right.user_name);
      });
  }, [memberAuthFilter, memberQuery, memberStateFilter, members]);

  const filteredTeams = useMemo(() => {
    const query = normalizeText(teamQuery);
    return teams
      .filter((team) => {
        if (teamStateFilter === 'active' && !team.is_active) return false;
        if (teamStateFilter === 'inactive' && team.is_active) return false;
        const memberLoadFailed = teamMemberLoadErrors[team.id] === true;
        const count = teamMembers[team.id]?.length || 0;
        if (memberLoadFailed && teamMemberFilter !== 'all') return false;
        if (teamMemberFilter === 'has_members' && count === 0) return false;
        if (teamMemberFilter === 'empty' && count > 0) return false;
        if (!query) return true;
        return (
          normalizeText(team.name).includes(query) ||
          normalizeText(team.description).includes(query)
        );
      })
      .sort((left, right) => {
        if (left.is_active !== right.is_active) return left.is_active ? -1 : 1;
        return left.name.localeCompare(right.name);
      });
  }, [
    teamMemberFilter,
    teamMemberLoadErrors,
    teamMembers,
    teamQuery,
    teamStateFilter,
    teams,
  ]);

  const selectedTeam = useMemo(
    () => teams.find((team) => team.id === selectedTeamId) || null,
    [selectedTeamId, teams],
  );

  const selectedTeamMemberUserIds = useMemo(
    () => (selectedTeamId ? teamMembers[selectedTeamId] || [] : []).map(
      (member) => member.user_id,
    ),
    [selectedTeamId, teamMembers],
  );

  const loadTeamMembers = async (items: TeamResponse[]) => {
    const entries = await Promise.all(
      items.map(async (team) => {
        try {
          const response = await apiClient.get<TeamMemberResponse[]>(
            `/teams/${team.id}/members`,
          );
          return [team.id, response.data, false] as const;
        } catch {
          return [team.id, [], true] as const;
        }
      }),
    );
    setTeamMembers(
      entries.reduce<Record<string, TeamMemberResponse[]>>(
        (acc, [teamId, items]) => ({ ...acc, [teamId]: [...items] }),
        {},
      ),
    );
    setTeamMemberLoadErrors(
      Object.fromEntries(
        entries
          .filter(([, , failed]) => failed)
          .map(([teamId]) => [teamId, true]),
      ),
    );
  };

  const loadPermissions = async (
    resourceType = permissionResourceType,
    workflowId = selectedWorkflowId,
    knowledgeBaseId = selectedKnowledgeBaseId,
    credentialId = selectedCredentialId,
  ) => {
    try {
      if (resourceType === 'workflow' && workflowId) {
        const response = await apiClient.get<ResourcePermissionListResponse>(
          `/permissions/workflows/${workflowId}`,
        );
        setWorkflowPermissions(response.data);
        return;
      }
      if (resourceType === 'knowledge_base' && knowledgeBaseId) {
        const response = await apiClient.get<ResourcePermissionListResponse>(
          `/permissions/knowledge-bases/${knowledgeBaseId}`,
        );
        setKnowledgePermissions(response.data);
        return;
      }
      if (resourceType === 'llm_credential' && credentialId) {
        const response = await apiClient.get<ResourcePermissionListResponse>(
          `/permissions/llm-credentials/${credentialId}`,
        );
        setCredentialPermissions(response.data);
        return;
      }
      if (resourceType === 'workflow') setWorkflowPermissions(null);
      if (resourceType === 'knowledge_base') setKnowledgePermissions(null);
      if (resourceType === 'llm_credential') setCredentialPermissions(null);
    } catch (err) {
      toast.error(getErrorMessage(err, '권한 목록을 불러오지 못했습니다.'));
      if (resourceType === 'workflow') setWorkflowPermissions(null);
      if (resourceType === 'knowledge_base') setKnowledgePermissions(null);
      if (resourceType === 'llm_credential') setCredentialPermissions(null);
    }
  };

  const refreshCredentials = async () => {
    const response = await apiClient.get<LLMCredentialResponse[]>(
      '/llm/credentials',
    );
    setCredentials(response.data);
    return response.data;
  };

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [org, me] = await Promise.all([
        organizationApi.getCurrentOrganization(),
        authApi.me().catch(() => null),
      ]);
      setOrganization(org);
      setCurrentUserId(me?.user.id || null);

      if (!org.is_manager) {
        setMembers([]);
        setTeams([]);
        setTeamMembers({});
        setTeamMemberLoadErrors({});
        setApps([]);
        setProviders([]);
        setCredentials([]);
        setWorkflowPermissions(null);
        setKnowledgePermissions(null);
        setCredentialPermissions(null);
        setKnowledgeBases([]);
        return;
      }

      const [defaultMembers, removedMembers, teamData] = await Promise.all([
        organizationApi.listMembers(org.id),
        organizationApi.listMembers(org.id, 'removed').catch(() => []),
        apiClient
          .get<TeamResponse[]>('/teams', {
            params: { organization_id: org.id, limit: 100 },
          })
          .then((response) => response.data),
      ]);

      setMembers(uniqueMembers([...defaultMembers, ...removedMembers]));
      setTeams(teamData);

      const [providerData, credentialData, appData, knowledgeData] =
        await Promise.all([
          apiClient
            .get<LLMProviderResponse[]>('/llm/providers')
            .then((response) => response.data)
            .catch(() => []),
          apiClient
            .get<LLMCredentialResponse[]>('/llm/credentials')
            .then((response) => response.data)
            .catch(() => []),
          apiClient
            .get<AppResponse[]>('/apps')
            .then((response) => response.data)
            .catch(() => []),
          knowledgeApi.getKnowledgeBases().catch(() => []),
        ]);

      setProviders(providerData);
      setCredentials(credentialData);
      setApps(appData);
      setKnowledgeBases(knowledgeData);
      const firstWorkflowId =
        selectedWorkflowId ||
        appData.find((app) => app.workflow_id)?.workflow_id ||
        '';
      const firstKnowledgeBaseId =
        selectedKnowledgeBaseId || knowledgeData[0]?.id || '';
      const firstCredentialId = selectedCredentialId || credentialData[0]?.id || '';
      setSelectedWorkflowId(firstWorkflowId);
      setSelectedKnowledgeBaseId(firstKnowledgeBaseId);
      setSelectedCredentialId(firstCredentialId);
      await Promise.all([
        loadPermissions(
          'workflow',
          firstWorkflowId,
          firstKnowledgeBaseId,
          firstCredentialId,
        ),
        loadPermissions(
          'knowledge_base',
          firstWorkflowId,
          firstKnowledgeBaseId,
          firstCredentialId,
        ),
        loadPermissions(
          'llm_credential',
          firstWorkflowId,
          firstKnowledgeBaseId,
          firstCredentialId,
        ),
      ]);
      await loadTeamMembers(teamData);
    } catch (err) {
      setError(getErrorMessage(err, '관리 콘솔 데이터를 불러오지 못했습니다.'));
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

  useEffect(() => {
    setMemberPage(1);
  }, [memberAuthFilter, memberQuery, memberStateFilter]);

  useEffect(() => {
    setTeamPage(1);
  }, [teamMemberFilter, teamQuery, teamStateFilter]);

  useEffect(() => {
    if (!selectedTeamId) return;
    const nextCandidate = activeMembers.find(
      (member) => !selectedTeamMemberUserIds.includes(member.user_id),
    );
    setTeamMemberUserId(nextCandidate?.user_id || '');
  }, [activeMembers, selectedTeamId, selectedTeamMemberUserIds]);

  useEffect(() => {
    if (!selectedWorkflowId && workflowOptions.length > 0) {
      setSelectedWorkflowId(workflowOptions[0].workflow_id || '');
    }
  }, [selectedWorkflowId, workflowOptions]);

  useEffect(() => {
    if (!selectedKnowledgeBaseId && knowledgeBases.length > 0) {
      setSelectedKnowledgeBaseId(knowledgeBases[0].id);
    }
  }, [knowledgeBases, selectedKnowledgeBaseId]);

  useEffect(() => {
    if (!selectedCredentialId && credentials.length > 0) {
      setSelectedCredentialId(credentials[0].id);
    }
  }, [credentials, selectedCredentialId]);

  useEffect(() => {
    if (!credentialForm.providerId && providers.length > 0) {
      setCredentialForm((prev) => ({ ...prev, providerId: providers[0].id }));
    }
  }, [credentialForm.providerId, providers]);

  useEffect(() => {
    if (permissionGranteeType === 'team') {
      const currentTeam = activeTeams.some(
        (team) => team.id === permissionGranteeId,
      );
      if (!currentTeam) setPermissionGranteeId(activeTeams[0]?.id || '');
      return;
    }
    const currentMember = activeMembers.some(
      (member) => member.user_id === permissionGranteeId,
    );
    if (!currentMember) setPermissionGranteeId(activeMembers[0]?.user_id || '');
  }, [activeMembers, activeTeams, permissionGranteeId, permissionGranteeType]);

  useEffect(() => {
    if (!organization?.is_manager) return;
    loadPermissions(permissionResourceType);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    organization?.is_manager,
    permissionResourceType,
    selectedWorkflowId,
    selectedKnowledgeBaseId,
    selectedCredentialId,
  ]);

  const refreshMembers = async () => {
    if (!organization) return;
    const [defaultMembers, removedMembers] = await Promise.all([
      organizationApi.listMembers(organization.id),
      organizationApi.listMembers(organization.id, 'removed').catch(() => []),
    ]);
    setMembers(uniqueMembers([...defaultMembers, ...removedMembers]));
  };

  const refreshTeams = async () => {
    const response = await apiClient.get<TeamResponse[]>('/teams', {
      params: { organization_id: organization?.id, limit: 100 },
    });
    setTeams(response.data);
    await loadTeamMembers(response.data);
  };

  const refreshTeamMember = async (teamId: string) => {
    try {
      const response = await apiClient.get<TeamMemberResponse[]>(
        `/teams/${teamId}/members`,
      );
      setTeamMembers((prev) => ({ ...prev, [teamId]: response.data }));
      setTeamMemberLoadErrors((prev) => {
        const next = { ...prev };
        delete next[teamId];
        return next;
      });
    } catch {
      setTeamMemberLoadErrors((prev) => ({ ...prev, [teamId]: true }));
    }
  };

  const runAction = async (action: () => Promise<void>) => {
    setActionPending(true);
    try {
      await action();
      return true;
    } catch (err) {
      toast.error(getErrorMessage(err, '작업에 실패했습니다.'));
      return false;
    } finally {
      setActionPending(false);
    }
  };

  const openConfirm = (state: ConfirmState) => setConfirmState(state);

  const handleConfirm = async () => {
    if (!confirmState) return;
    const success = await runAction(confirmState.onConfirm);
    if (success) {
      setConfirmState(null);
    }
  };

  const updateMember = async (
    member: OrganizationMember,
    payload: Parameters<typeof organizationApi.updateMember>[2],
    successMessage: string,
  ) => {
    if (!organization) return;
    await organizationApi.updateMember(organization.id, member.user_id, payload);
    toast.success(successMessage);
    await refreshMembers();
  };

  const removeMember = async (member: OrganizationMember) => {
    if (!organization) return;
    const result = await organizationApi.removeMember(
      organization.id,
      member.user_id,
    );
    const summary = removeSummary(result);
    setNotice(summary);
    toast.success(summary);
    await Promise.all([refreshMembers(), refreshTeams()]);
  };

  const submitInvite = async () => {
    if (!organization || !inviteForm.userId.trim()) return;
    await runAction(async () => {
      await organizationApi.inviteMember(organization.id, {
        user_id: inviteForm.userId.trim(),
        organization_auth_state: inviteForm.authState,
      });
      toast.success('멤버 초대를 생성했습니다.');
      setInviteOpen(false);
      setInviteForm({ userId: '', authState: 'member' });
      await refreshMembers();
    });
  };

  const openTeamEditor = (state: TeamEditorState) => {
    setTeamEditor(state);
    setTeamForm({
      name: state.team?.name || '',
      description: state.team?.description || '',
      isAutoAdd: state.team?.is_auto_add || false,
    });
  };

  const submitTeamForm = async () => {
    if (!teamForm.name.trim()) return;
    await runAction(async () => {
      if (teamEditor?.mode === 'edit') {
        await apiClient.patch(`/teams/${teamEditor.team.id}`, {
          name: teamForm.name.trim(),
          description: teamForm.description.trim() || null,
          is_auto_add: teamForm.isAutoAdd,
        });
        toast.success('팀을 수정했습니다.');
      } else {
        await apiClient.post('/teams', {
          name: teamForm.name.trim(),
          description: teamForm.description.trim() || null,
          is_auto_add: teamForm.isAutoAdd,
        });
        toast.success('팀을 생성했습니다.');
      }
      setTeamEditor(null);
      await refreshTeams();
    });
  };

  const deactivateTeam = async (team: TeamResponse) => {
    await apiClient.delete(`/teams/${team.id}`);
    toast.success('팀을 비활성화했습니다.');
    await refreshTeams();
  };

  const addTeamMember = async () => {
    if (!selectedTeamId || !teamMemberUserId) return;
    await runAction(async () => {
      await apiClient.post(`/teams/${selectedTeamId}/members`, {
        user_id: teamMemberUserId,
      });
      toast.success('팀 멤버를 추가했습니다.');
      await refreshTeamMember(selectedTeamId);
    });
  };

  const removeTeamMember = async (teamId: string, member: TeamMemberResponse) => {
    await apiClient.delete(`/teams/${teamId}/members/${member.user_id}`);
    toast.success('팀 멤버를 제거했습니다.');
    await refreshTeamMember(teamId);
  };

  const permissionPath = (
    resourceType: ResourceType,
    granteeType: GranteeType,
    granteeId: string,
  ) => {
    const resourceId =
      resourceType === 'workflow'
        ? selectedWorkflowId
        : resourceType === 'knowledge_base'
          ? selectedKnowledgeBaseId
          : selectedCredentialId;
    const resourcePath =
      resourceType === 'workflow'
        ? `/permissions/workflows/${resourceId}`
        : resourceType === 'knowledge_base'
          ? `/permissions/knowledge-bases/${resourceId}`
          : `/permissions/llm-credentials/${resourceId}`;
    return `${resourcePath}/${granteeType}s/${granteeId}`;
  };

  const grantPermission = async () => {
    if (!permissionResourceId || !permissionGranteeId) return;
    await runAction(async () => {
      await apiClient.put(
        permissionPath(
          permissionResourceType,
          permissionGranteeType,
          permissionGranteeId,
        ),
        { auth_state: permissionAuthState },
      );
      toast.success('권한을 저장했습니다.');
      await loadPermissions(permissionResourceType);
    });
  };

  const revokePermission = async (
    resourceType: ResourceType,
    granteeType: GranteeType,
    granteeId: string,
  ) => {
    await apiClient.delete(permissionPath(resourceType, granteeType, granteeId));
    toast.success('권한을 회수했습니다.');
    await loadPermissions(resourceType);
  };

  const submitCredential = async () => {
    if (
      !organization ||
      !credentialForm.providerId ||
      !credentialForm.credentialName.trim() ||
      !credentialForm.apiKey.trim()
    ) {
      return;
    }
    await runAction(async () => {
      await apiClient.post('/llm/credentials', {
        provider_id: credentialForm.providerId,
        organization_id: organization.id,
        credential_name: credentialForm.credentialName.trim(),
        api_key: credentialForm.apiKey.trim(),
      });
      toast.success('Credential을 등록했습니다.');
      setCredentialPanelOpen(false);
      setCredentialForm({
        providerId: providers[0]?.id || '',
        credentialName: '',
        apiKey: '',
      });
      const nextCredentials = await refreshCredentials();
      const nextCredentialId = nextCredentials[0]?.id || '';
      setSelectedCredentialId(nextCredentialId);
      await loadPermissions(
        'llm_credential',
        selectedWorkflowId,
        selectedKnowledgeBaseId,
        nextCredentialId,
      );
    });
  };

  const deleteCredential = async (credential: LLMCredentialResponse) => {
    await apiClient.delete(`/llm/credentials/${credential.id}`);
    toast.success('Credential을 삭제했습니다.');
    const nextCredentials = await refreshCredentials();
    const nextCredentialId =
      selectedCredentialId === credential.id
        ? nextCredentials[0]?.id || ''
        : selectedCredentialId;
    setSelectedCredentialId(nextCredentialId);
    await loadPermissions(
      'llm_credential',
      selectedWorkflowId,
      selectedKnowledgeBaseId,
      nextCredentialId,
    );
  };

  const syncCredentialModels = async (credential: LLMCredentialResponse) => {
    await apiClient.post(`/llm/credentials/${credential.id}/sync-models`);
    toast.success('모델 목록을 동기화했습니다.');
    await refreshCredentials();
  };

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
      {notice && (
        <div className="flex items-start justify-between gap-3 rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
          <span>{notice}</span>
          <button
            onClick={() => setNotice(null)}
            className="rounded p-0.5 text-green-700 hover:bg-green-100"
            title="알림 닫기"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {loading ? (
        <div className="rounded-lg border border-slate-200 bg-white px-6 py-16 text-center text-sm text-slate-500">
          관리 콘솔을 불러오는 중...
        </div>
      ) : (
        <>
          <AdminSummaryCards />

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
              description="팀/사용자 권한 관리 가능"
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
            <MembersTab
              members={filteredMembers}
              page={memberPage}
              onPageChange={setMemberPage}
              query={memberQuery}
              onQueryChange={setMemberQuery}
              stateFilter={memberStateFilter}
              onStateFilterChange={setMemberStateFilter}
              authFilter={memberAuthFilter}
              onAuthFilterChange={setMemberAuthFilter}
              onInvite={() => setInviteOpen(true)}
              currentUserId={currentUserId}
              activeManagerCount={activeManagerCount}
              actionPending={actionPending}
              onUpdateMember={(member, payload, message) =>
                payload.organization_auth_state
                  ? openConfirm({
                      title:
                        payload.organization_auth_state === 'manager'
                          ? '관리자로 승격할까요?'
                          : '멤버로 강등할까요?',
                      description:
                        payload.organization_auth_state === 'manager'
                          ? '이 사용자는 조직 멤버와 팀, 권한 관리 화면에 접근할 수 있습니다.'
                          : '이 사용자는 더 이상 조직 관리 화면에 접근할 수 없습니다.',
                      confirmLabel:
                        payload.organization_auth_state === 'manager'
                          ? '승격'
                          : '강등',
                      details: [`${member.user_name} (${member.user_email})`],
                      onConfirm: () => updateMember(member, payload, message),
                    })
                  : runAction(() => updateMember(member, payload, message))
              }
              onRemoveMember={(member) =>
                openConfirm({
                  title: '멤버를 제거할까요?',
                  description:
                    '멤버를 제거하면 팀 배정과 직접 권한이 함께 정리됩니다.',
                  confirmLabel: '제거',
                  tone: 'danger',
                  details: [
                    `${member.user_name} (${member.user_email})`,
                    '팀 멤버십, workflow 직접 권한, LLM credential 직접 권한 cleanup이 실행됩니다.',
                  ],
                  onConfirm: () => removeMember(member),
                })
              }
            />
          )}
          {activeTab === 'teams' && (
            <TeamsTab
              teams={filteredTeams}
              page={teamPage}
              onPageChange={setTeamPage}
              query={teamQuery}
              onQueryChange={setTeamQuery}
              stateFilter={teamStateFilter}
              onStateFilterChange={setTeamStateFilter}
              memberFilter={teamMemberFilter}
              onMemberFilterChange={setTeamMemberFilter}
              teamMembers={teamMembers}
              teamMemberLoadErrors={teamMemberLoadErrors}
              isLimited={teams.length >= 100}
              onCreateTeam={() => openTeamEditor({ mode: 'create' })}
              onEditTeam={(team) => openTeamEditor({ mode: 'edit', team })}
              onDeactivateTeam={(team) =>
                openConfirm({
                  title: '팀을 비활성화할까요?',
                  description:
                    '팀은 삭제되지 않고 비활성 상태가 됩니다. 비활성 팀에는 멤버 추가와 권한 부여를 하지 않습니다.',
                  confirmLabel: '비활성화',
                  tone: 'danger',
                  details: [
                    team.name,
                    `현재 멤버 ${teamMembers[team.id]?.length || 0}명`,
                  ],
                  onConfirm: () => deactivateTeam(team),
                })
              }
              onOpenTeam={setSelectedTeamId}
            />
          )}
          {activeTab === 'permissions' && (
            <PermissionsTab
              resourceType={permissionResourceType}
              onResourceTypeChange={setPermissionResourceType}
              workflowOptions={workflowOptions}
              selectedWorkflowId={selectedWorkflowId}
              onSelectedWorkflowIdChange={setSelectedWorkflowId}
              knowledgeBases={knowledgeBases}
              selectedKnowledgeBaseId={selectedKnowledgeBaseId}
              onSelectedKnowledgeBaseIdChange={setSelectedKnowledgeBaseId}
              credentials={credentials}
              selectedCredentialId={selectedCredentialId}
              onSelectedCredentialIdChange={setSelectedCredentialId}
              activeTeams={activeTeams}
              activeMembers={activeMembers}
              granteeType={permissionGranteeType}
              onGranteeTypeChange={setPermissionGranteeType}
              granteeId={permissionGranteeId}
              onGranteeIdChange={setPermissionGranteeId}
              authState={permissionAuthState}
              onAuthStateChange={setPermissionAuthState}
              permissionList={selectedPermissionList}
              actionPending={actionPending}
              onGrant={grantPermission}
              onRevoke={(resourceType, granteeType, granteeId, label) =>
                openConfirm({
                  title: '권한을 회수할까요?',
                  description: '선택한 대상의 resource 권한이 제거됩니다.',
                  confirmLabel: '회수',
                  tone: 'danger',
                  details: [label],
                  onConfirm: () =>
                    revokePermission(resourceType, granteeType, granteeId),
                })
              }
            />
          )}
          {activeTab === 'credentials' && (
            <CredentialsTab
              providers={providers}
              credentials={credentials}
              actionPending={actionPending}
              onOpenCreate={() => setCredentialPanelOpen(true)}
              onManagePermission={(credentialId) => {
                setSelectedCredentialId(credentialId);
                setPermissionResourceType('llm_credential');
                setActiveTab('permissions');
              }}
              onSync={(credential) =>
                runAction(() => syncCredentialModels(credential))
              }
              onDelete={(credential) =>
                openConfirm({
                  title: 'Credential을 삭제할까요?',
                  description:
                    '삭제 후 이 credential을 사용하는 workflow 실행이 실패할 수 있습니다.',
                  confirmLabel: '삭제',
                  tone: 'danger',
                  details: [credential.credential_name],
                  onConfirm: () => deleteCredential(credential),
                })
              }
            />
          )}
          {activeTab === 'knowledge' && (
            <KnowledgeTab
              knowledgeBases={knowledgeBases}
              onManagePermissions={(knowledgeBaseId) => {
                setSelectedKnowledgeBaseId(knowledgeBaseId);
                setPermissionResourceType('knowledge_base');
                setActiveTab('permissions');
              }}
            />
          )}
          {activeTab === 'permission-requests' && (
            <PermissionRequestsTab members={members} />
          )}
          {activeTab === 'usage' && <UsageTab />}
          {activeTab === 'audit' && <AuditSearchTab members={members} />}
          {activeTab === 'organization' && (
            <OrganizationTab organization={organization} />
          )}
        </>
      )}

      {inviteOpen && (
        <SidePanel title="멤버 초대" onClose={() => setInviteOpen(false)}>
          <div className="space-y-4">
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-800">
              현재 API는 가입된 user id만 초대할 수 있습니다. email 검색 초대는
              별도 user directory API가 필요합니다. 가입 user UUID는 DB 또는
              관리 도구에서 확인해야 합니다.
            </div>
            <LabelledField label="User ID">
              <input
                value={inviteForm.userId}
                onChange={(event) =>
                  setInviteForm((prev) => ({
                    ...prev,
                    userId: event.target.value,
                  }))
                }
                className="h-10 w-full rounded-md border border-slate-300 px-3 text-sm"
                placeholder="초대할 가입 user UUID"
              />
            </LabelledField>
            <LabelledField label="조직 권한">
              <select
                value={inviteForm.authState}
                onChange={(event) =>
                  setInviteForm((prev) => ({
                    ...prev,
                    authState: event.target.value as OrganizationAuthState,
                  }))
                }
                className="h-10 w-full rounded-md border border-slate-300 px-3 text-sm"
              >
                {AUTH_STATES.map((state) => (
                  <option key={state} value={state}>
                    {state === 'manager' ? '관리자' : '멤버'}
                  </option>
                ))}
              </select>
            </LabelledField>
            <PanelActions
              onCancel={() => setInviteOpen(false)}
              onSubmit={submitInvite}
              submitLabel="초대"
              disabled={!inviteForm.userId.trim() || actionPending}
            />
          </div>
        </SidePanel>
      )}

      {teamEditor && (
        <SidePanel
          title={teamEditor.mode === 'edit' ? '팀 수정' : '팀 생성'}
          onClose={() => setTeamEditor(null)}
        >
          <div className="space-y-4">
            <LabelledField label="팀 이름">
              <input
                value={teamForm.name}
                onChange={(event) =>
                  setTeamForm((prev) => ({ ...prev, name: event.target.value }))
                }
                className="h-10 w-full rounded-md border border-slate-300 px-3 text-sm"
                placeholder="팀 이름"
              />
            </LabelledField>
            <LabelledField label="설명">
              <textarea
                value={teamForm.description}
                onChange={(event) =>
                  setTeamForm((prev) => ({
                    ...prev,
                    description: event.target.value,
                  }))
                }
                className="min-h-24 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                placeholder="팀 설명"
              />
            </LabelledField>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={teamForm.isAutoAdd}
                onChange={(event) =>
                  setTeamForm((prev) => ({
                    ...prev,
                    isAutoAdd: event.target.checked,
                  }))
                }
              />
              신규 멤버 자동 추가
            </label>
            <PanelActions
              onCancel={() => setTeamEditor(null)}
              onSubmit={submitTeamForm}
              submitLabel={teamEditor.mode === 'edit' ? '수정' : '생성'}
              disabled={!teamForm.name.trim() || actionPending}
            />
          </div>
        </SidePanel>
      )}

      {selectedTeam && (
        <SidePanel title={selectedTeam.name} onClose={() => setSelectedTeamId(null)}>
          <div className="space-y-5">
            <div>
              <div className="flex items-center gap-2">
                <span
                  className={`rounded-md px-2 py-0.5 text-xs font-semibold ${
                    selectedTeam.is_active
                      ? 'bg-green-50 text-green-700'
                      : 'bg-slate-100 text-slate-600'
                  }`}
                >
                  {selectedTeam.is_active ? '활성' : '비활성'}
                </span>
                <span className="text-xs text-slate-500">
                  멤버 {teamMembers[selectedTeam.id]?.length || 0}명
                </span>
              </div>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                {selectedTeam.description || '설명 없음'}
              </p>
            </div>

            {selectedTeam.is_active ? (
              <div className="rounded-md border border-slate-200 p-3">
                <p className="mb-2 text-sm font-semibold text-slate-900">
                  멤버 추가
                </p>
                <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
                  <ActiveOrganizationMemberPicker
                    members={activeMembers}
                    value={teamMemberUserId}
                    onChange={setTeamMemberUserId}
                    excludedUserIds={selectedTeamMemberUserIds}
                    emptyLabel="추가 가능한 활성 멤버 없음"
                  />
                  <button
                    onClick={addTeamMember}
                    disabled={!teamMemberUserId || actionPending}
                    className="h-10 rounded-md bg-slate-950 px-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    추가
                  </button>
                </div>
              </div>
            ) : (
              <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                비활성 팀에는 멤버를 추가할 수 없습니다.
              </div>
            )}

            <div>
              <p className="mb-2 text-sm font-semibold text-slate-900">
                팀 멤버
              </p>
              {teamMemberLoadErrors[selectedTeam.id] ? (
                <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  멤버를 불러오지 못했습니다.
                </div>
              ) : (teamMembers[selectedTeam.id] || []).length === 0 ? (
                <div className="rounded-md border border-slate-200 px-3 py-6 text-center text-sm text-slate-500">
                  소속 멤버가 없습니다.
                </div>
              ) : (
                <div className="divide-y divide-slate-100 rounded-md border border-slate-200">
                  {(teamMembers[selectedTeam.id] || []).map((member) => (
                    <div
                      key={member.id}
                      className="flex items-center justify-between gap-3 px-3 py-2"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-slate-900">
                          {member.name}
                        </p>
                        <p className="truncate text-xs text-slate-500">
                          {member.email}
                        </p>
                      </div>
                      <button
                        onClick={() =>
                          openConfirm({
                            title: '팀 멤버를 제거할까요?',
                            description:
                              '이 작업은 organization membership을 제거하지 않고 팀 배정만 제거합니다.',
                            confirmLabel: '제거',
                            tone: 'danger',
                            details: [`${member.name} (${member.email})`],
                            onConfirm: () =>
                              removeTeamMember(selectedTeam.id, member),
                          })
                        }
                        className="rounded-md border border-slate-200 p-2 text-slate-500 hover:border-red-200 hover:bg-red-50 hover:text-red-700"
                        title="팀 멤버 제거"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </SidePanel>
      )}

      {credentialPanelOpen && (
        <SidePanel
          title="Credential 등록"
          onClose={() => setCredentialPanelOpen(false)}
        >
          <div className="space-y-4">
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-800">
              API key 원문은 저장 후 다시 표시하지 않습니다. 조직에서 사용할
              provider와 식별 가능한 이름을 함께 입력하세요.
            </div>
            <LabelledField label="Provider">
              <select
                value={credentialForm.providerId}
                onChange={(event) =>
                  setCredentialForm((prev) => ({
                    ...prev,
                    providerId: event.target.value,
                  }))
                }
                className="h-10 w-full rounded-md border border-slate-300 px-3 text-sm"
              >
                {providers.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.name}
                  </option>
                ))}
              </select>
            </LabelledField>
            <LabelledField label="Credential 이름">
              <input
                value={credentialForm.credentialName}
                onChange={(event) =>
                  setCredentialForm((prev) => ({
                    ...prev,
                    credentialName: event.target.value,
                  }))
                }
                className="h-10 w-full rounded-md border border-slate-300 px-3 text-sm"
                placeholder="예: OpenAI 운영 키"
              />
            </LabelledField>
            <LabelledField label="API Key">
              <input
                value={credentialForm.apiKey}
                onChange={(event) =>
                  setCredentialForm((prev) => ({
                    ...prev,
                    apiKey: event.target.value,
                  }))
                }
                className="h-10 w-full rounded-md border border-slate-300 px-3 text-sm"
                placeholder="sk-..."
                type="password"
              />
            </LabelledField>
            <PanelActions
              onCancel={() => setCredentialPanelOpen(false)}
              onSubmit={submitCredential}
              submitLabel="등록"
              disabled={
                actionPending ||
                !credentialForm.providerId ||
                !credentialForm.credentialName.trim() ||
                !credentialForm.apiKey.trim()
              }
            />
          </div>
        </SidePanel>
      )}

      {confirmState && (
        <ConfirmDialog
          state={confirmState}
          pending={actionPending}
          onCancel={() => setConfirmState(null)}
          onConfirm={handleConfirm}
        />
      )}
    </AdminShell>
  );
}

const removeSummary = (result: OrganizationMemberRemoveResponse) =>
  `멤버를 제거했습니다. 팀 ${result.removed_team_memberships}건, workflow ${result.revoked_user_permissions.workflow}건, credential ${result.revoked_user_permissions.llm_credential}건을 정리했습니다.`;

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

function MembersTab({
  members,
  page,
  onPageChange,
  query,
  onQueryChange,
  stateFilter,
  onStateFilterChange,
  authFilter,
  onAuthFilterChange,
  onInvite,
  currentUserId,
  activeManagerCount,
  actionPending,
  onUpdateMember,
  onRemoveMember,
}: {
  members: OrganizationMember[];
  page: number;
  onPageChange: (page: number) => void;
  query: string;
  onQueryChange: (query: string) => void;
  stateFilter: MembershipState | 'all';
  onStateFilterChange: (state: MembershipState | 'all') => void;
  authFilter: OrganizationAuthState | 'all';
  onAuthFilterChange: (state: OrganizationAuthState | 'all') => void;
  onInvite: () => void;
  currentUserId: string | null;
  activeManagerCount: number;
  actionPending: boolean;
  onUpdateMember: (
    member: OrganizationMember,
    payload: {
      membership_state?: 'active' | 'suspended' | null;
      organization_auth_state?: OrganizationAuthState | null;
    },
    message: string,
  ) => void;
  onRemoveMember: (member: OrganizationMember) => void;
}) {
  const pageItems = paginate(members, page);
  const totalPages = Math.max(1, Math.ceil(members.length / PAGE_SIZE));

  return (
    <DashboardPanel
      title="멤버"
      icon={Users}
      aside={
        <button
          onClick={onInvite}
          className="inline-flex h-9 items-center gap-2 rounded-md bg-slate-950 px-3 text-sm font-semibold text-white hover:bg-slate-800"
        >
          <UserPlus className="h-4 w-4" />
          초대
        </button>
      }
    >
      <ListToolbar
        query={query}
        onQueryChange={onQueryChange}
        placeholder="이름, email 검색"
        resultText={`결과 ${members.length}명`}
      >
        <select
          value={stateFilter}
          onChange={(event) =>
            onStateFilterChange(event.target.value as MembershipState | 'all')
          }
          className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
        >
          <option value="all">전체 상태</option>
          <option value="active">활성</option>
          <option value="invited">초대 중</option>
          <option value="suspended">정지</option>
          <option value="removed">제거</option>
        </select>
        <select
          value={authFilter}
          onChange={(event) =>
            onAuthFilterChange(event.target.value as OrganizationAuthState | 'all')
          }
          className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
        >
          <option value="all">전체 권한</option>
          <option value="manager">관리자</option>
          <option value="member">멤버</option>
        </select>
      </ListToolbar>

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
            {pageItems.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-5 py-10 text-center text-slate-500">
                  조건에 맞는 멤버가 없습니다.
                </td>
              </tr>
            ) : (
              pageItems.map((member) => {
                const isSelf = currentUserId === member.user_id;
                const isSelfUnknown = currentUserId === null;
                const isLastActiveManager =
                  member.membership_state === 'active' &&
                  member.organization_auth_state === 'manager' &&
                  activeManagerCount <= 1;
                return (
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
                      <MemberActions
                        member={member}
                        isSelf={isSelf}
                        isSelfUnknown={isSelfUnknown}
                        isLastActiveManager={isLastActiveManager}
                        actionPending={actionPending}
                        onUpdateMember={onUpdateMember}
                        onRemoveMember={onRemoveMember}
                      />
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      <Pagination
        page={page}
        totalPages={totalPages}
        totalItems={members.length}
        onPageChange={onPageChange}
      />
    </DashboardPanel>
  );
}

function MemberActions({
  member,
  isSelf,
  isSelfUnknown,
  isLastActiveManager,
  actionPending,
  onUpdateMember,
  onRemoveMember,
}: {
  member: OrganizationMember;
  isSelf: boolean;
  isSelfUnknown: boolean;
  isLastActiveManager: boolean;
  actionPending: boolean;
  onUpdateMember: (
    member: OrganizationMember,
    payload: {
      membership_state?: 'active' | 'suspended' | null;
      organization_auth_state?: OrganizationAuthState | null;
    },
    message: string,
  ) => void;
  onRemoveMember: (member: OrganizationMember) => void;
}) {
  if (member.membership_state === 'removed') {
    return <span className="text-xs text-slate-400">제거됨</span>;
  }
  const actionLocks = getMemberActionLocks({
    isSelf,
    isSelfUnknown,
    isLastActiveManager,
    actionPending,
  });

  return (
    <div className="flex flex-wrap gap-1.5">
      {member.membership_state === 'active' && (
        <button
          onClick={() =>
            onUpdateMember(
              member,
              { membership_state: 'suspended' },
              '멤버를 정지했습니다.',
            )
          }
          disabled={actionLocks.statusAction.disabled}
          title={actionLocks.statusAction.title}
          className="rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          정지
        </button>
      )}
      {member.membership_state === 'suspended' && (
        <button
          onClick={() =>
            onUpdateMember(
              member,
              { membership_state: 'active' },
              '멤버를 재활성화했습니다.',
            )
          }
          disabled={actionLocks.statusAction.disabled}
          title={actionLocks.statusAction.title}
          className="rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          재활성화
        </button>
      )}
      {member.membership_state === 'active' &&
        member.organization_auth_state === 'member' && (
          <button
            onClick={() =>
              onUpdateMember(
                member,
                { organization_auth_state: 'manager' },
                '관리자로 승격했습니다.',
              )
            }
            disabled={actionLocks.memberUpdateAction.disabled}
            title={actionLocks.memberUpdateAction.title}
            className="rounded-md border border-blue-200 px-2 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            관리자 승격
          </button>
        )}
      {member.membership_state === 'active' &&
        member.organization_auth_state === 'manager' && (
          <button
            onClick={() =>
              onUpdateMember(
                member,
                { organization_auth_state: 'member' },
                '멤버로 강등했습니다.',
              )
            }
            disabled={actionLocks.managerOrRemoveAction.disabled}
            title={actionLocks.managerOrRemoveAction.title}
            className="rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            멤버로 강등
          </button>
        )}
      <button
        onClick={() => onRemoveMember(member)}
        disabled={actionLocks.managerOrRemoveAction.disabled}
        title={actionLocks.managerOrRemoveAction.title}
        className="rounded-md border border-red-200 px-2 py-1 text-xs font-semibold text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40"
      >
        제거
      </button>
    </div>
  );
}

function TeamsTab({
  teams,
  page,
  onPageChange,
  query,
  onQueryChange,
  stateFilter,
  onStateFilterChange,
  memberFilter,
  onMemberFilterChange,
  teamMembers,
  teamMemberLoadErrors,
  isLimited,
  onCreateTeam,
  onEditTeam,
  onDeactivateTeam,
  onOpenTeam,
}: {
  teams: TeamResponse[];
  page: number;
  onPageChange: (page: number) => void;
  query: string;
  onQueryChange: (query: string) => void;
  stateFilter: 'all' | 'active' | 'inactive';
  onStateFilterChange: (state: 'all' | 'active' | 'inactive') => void;
  memberFilter: 'all' | 'has_members' | 'empty';
  onMemberFilterChange: (state: 'all' | 'has_members' | 'empty') => void;
  teamMembers: Record<string, TeamMemberResponse[]>;
  teamMemberLoadErrors: Record<string, boolean>;
  isLimited: boolean;
  onCreateTeam: () => void;
  onEditTeam: (team: TeamResponse) => void;
  onDeactivateTeam: (team: TeamResponse) => void;
  onOpenTeam: (teamId: string) => void;
}) {
  const pageItems = paginate(teams, page);
  const totalPages = Math.max(1, Math.ceil(teams.length / PAGE_SIZE));

  return (
    <DashboardPanel
      title="팀"
      icon={Building2}
      aside={
        <button
          onClick={onCreateTeam}
          className="inline-flex h-9 items-center gap-2 rounded-md bg-slate-950 px-3 text-sm font-semibold text-white hover:bg-slate-800"
        >
          <Plus className="h-4 w-4" />
          팀 생성
        </button>
      }
    >
      <ListToolbar
        query={query}
        onQueryChange={onQueryChange}
        placeholder="팀 이름, 설명 검색"
        resultText={`결과 ${teams.length}개`}
      >
        <select
          value={stateFilter}
          onChange={(event) =>
            onStateFilterChange(event.target.value as 'all' | 'active' | 'inactive')
          }
          className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
        >
          <option value="all">전체 상태</option>
          <option value="active">활성</option>
          <option value="inactive">비활성</option>
        </select>
        <select
          value={memberFilter}
          onChange={(event) =>
            onMemberFilterChange(
              event.target.value as 'all' | 'has_members' | 'empty',
            )
          }
          className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
        >
          <option value="all">전체 멤버</option>
          <option value="has_members">멤버 있음</option>
          <option value="empty">멤버 없음</option>
        </select>
      </ListToolbar>
      {isLimited && (
        <div className="border-b border-amber-100 bg-amber-50 px-5 py-2 text-xs text-amber-800">
          현재 팀 목록은 API limit 100개 기준입니다. 100개 이상 조직은 서버
          pagination 연결 전까지 일부 팀이 보이지 않을 수 있습니다.
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
            <tr>
              <th className="px-5 py-3">팀</th>
              <th className="px-5 py-3">상태</th>
              <th className="px-5 py-3">멤버</th>
              <th className="px-5 py-3">작업</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {pageItems.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-5 py-10 text-center text-slate-500">
                  조건에 맞는 팀이 없습니다.
                </td>
              </tr>
            ) : (
              pageItems.map((team) => {
                const members = teamMembers[team.id] || [];
                return (
                  <tr key={team.id} className="bg-white">
                    <td className="px-5 py-4">
                      <div className="min-w-0">
                        <p className="font-semibold text-slate-950">{team.name}</p>
                        <p className="mt-1 text-xs text-slate-500">
                          {team.description || '설명 없음'}
                        </p>
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <span
                        className={`rounded-md px-2 py-0.5 text-xs font-semibold ${
                          team.is_active
                            ? 'bg-green-50 text-green-700'
                            : 'bg-slate-100 text-slate-600'
                        }`}
                      >
                        {team.is_active ? '활성' : '비활성'}
                      </span>
                    </td>
                    <td className="px-5 py-4">
                      {teamMemberLoadErrors[team.id] ? (
                        <span className="text-xs text-red-600">
                          멤버를 불러오지 못함
                        </span>
                      ) : members.length === 0 ? (
                        <span className="text-xs text-slate-400">멤버 없음</span>
                      ) : (
                        <div className="flex flex-wrap gap-1.5">
                          {members.slice(0, 3).map((member) => (
                            <span
                              key={member.id}
                              className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700"
                            >
                              {member.name}
                            </span>
                          ))}
                          {members.length > 3 && (
                            <span className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-500">
                              +{members.length - 3}
                            </span>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="px-5 py-4">
                      <div className="flex flex-wrap gap-1.5">
                        <button
                          onClick={() => onOpenTeam(team.id)}
                          className="rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50"
                        >
                          상세
                        </button>
                        <button
                          onClick={() => onEditTeam(team)}
                          className="rounded-md border border-slate-200 p-1.5 text-slate-500 hover:bg-slate-50"
                          title="팀 수정"
                        >
                          <Pencil className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => onDeactivateTeam(team)}
                          disabled={!team.is_active}
                          className="rounded-md border border-red-200 p-1.5 text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40"
                          title="팀 비활성화"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      <Pagination
        page={page}
        totalPages={totalPages}
        totalItems={teams.length}
        onPageChange={onPageChange}
      />
    </DashboardPanel>
  );
}

function PermissionsTab({
  resourceType,
  onResourceTypeChange,
  workflowOptions,
  selectedWorkflowId,
  onSelectedWorkflowIdChange,
  knowledgeBases,
  selectedKnowledgeBaseId,
  onSelectedKnowledgeBaseIdChange,
  credentials,
  selectedCredentialId,
  onSelectedCredentialIdChange,
  activeTeams,
  activeMembers,
  granteeType,
  onGranteeTypeChange,
  granteeId,
  onGranteeIdChange,
  authState,
  onAuthStateChange,
  permissionList,
  actionPending,
  onGrant,
  onRevoke,
}: {
  resourceType: ResourceType;
  onResourceTypeChange: (value: ResourceType) => void;
  workflowOptions: AppResponse[];
  selectedWorkflowId: string;
  onSelectedWorkflowIdChange: (value: string) => void;
  knowledgeBases: KnowledgeBaseResponse[];
  selectedKnowledgeBaseId: string;
  onSelectedKnowledgeBaseIdChange: (value: string) => void;
  credentials: LLMCredentialResponse[];
  selectedCredentialId: string;
  onSelectedCredentialIdChange: (value: string) => void;
  activeTeams: TeamResponse[];
  activeMembers: OrganizationMember[];
  granteeType: GranteeType;
  onGranteeTypeChange: (value: GranteeType) => void;
  granteeId: string;
  onGranteeIdChange: (value: string) => void;
  authState: ResourceAuthState;
  onAuthStateChange: (value: ResourceAuthState) => void;
  permissionList: ResourcePermissionListResponse | null;
  actionPending: boolean;
  onGrant: () => void;
  onRevoke: (
    resourceType: ResourceType,
    granteeType: GranteeType,
    granteeId: string,
    label: string,
  ) => void;
}) {
  const resourceMissing =
    resourceType === 'workflow'
      ? !selectedWorkflowId
      : resourceType === 'knowledge_base'
        ? !selectedKnowledgeBaseId
        : !selectedCredentialId;
  const granteeOptionsMissing =
    granteeType === 'team' ? activeTeams.length === 0 : activeMembers.length === 0;
  const resourceLabel =
    resourceType === 'workflow'
      ? 'Workflow 권한'
      : resourceType === 'knowledge_base'
        ? 'Knowledge Base 권한'
        : 'Credential 권한';

  return (
    <DashboardPanel
      title="권한"
      icon={SlidersHorizontal}
      aside={
        <span className="text-xs font-medium text-slate-500">
          {resourceLabel}
        </span>
      }
    >
      <div className="grid gap-4 border-b border-slate-100 px-5 py-4 xl:grid-cols-[220px_minmax(0,1fr)_180px_minmax(0,1fr)_160px_auto]">
        <select
          value={resourceType}
          onChange={(event) =>
            onResourceTypeChange(event.target.value as ResourceType)
          }
          className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
        >
          <option value="workflow">Workflow</option>
          <option value="knowledge_base">Knowledge Base</option>
          <option value="llm_credential">LLM Credential</option>
        </select>
        {resourceType === 'workflow' ? (
          <select
            value={selectedWorkflowId}
            onChange={(event) => onSelectedWorkflowIdChange(event.target.value)}
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
          >
            {workflowOptions.length === 0 ? (
              <option value="">선택 가능한 workflow 없음</option>
            ) : (
              workflowOptions.map((app) => (
                <option key={app.id} value={app.workflow_id || ''}>
                  {app.name}
                </option>
              ))
            )}
          </select>
        ) : resourceType === 'knowledge_base' ? (
          <select
            value={selectedKnowledgeBaseId}
            onChange={(event) =>
              onSelectedKnowledgeBaseIdChange(event.target.value)
            }
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
          >
            {knowledgeBases.length === 0 ? (
              <option value="">선택 가능한 지식 기반 없음</option>
            ) : (
              knowledgeBases.map((knowledgeBase) => (
                <option key={knowledgeBase.id} value={knowledgeBase.id}>
                  {knowledgeBase.name}
                </option>
              ))
            )}
          </select>
        ) : (
          <select
            value={selectedCredentialId}
            onChange={(event) => onSelectedCredentialIdChange(event.target.value)}
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
          >
            {credentials.length === 0 ? (
              <option value="">선택 가능한 credential 없음</option>
            ) : (
              credentials.map((credential) => (
                <option key={credential.id} value={credential.id}>
                  {credential.credential_name}
                </option>
              ))
            )}
          </select>
        )}
        <select
          value={granteeType}
          onChange={(event) =>
            onGranteeTypeChange(event.target.value as GranteeType)
          }
          className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
        >
          <option value="team">Team</option>
          <option value="user">User direct</option>
        </select>
        {granteeType === 'team' ? (
          <select
            value={granteeId}
            onChange={(event) => onGranteeIdChange(event.target.value)}
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
          >
            {activeTeams.length === 0 ? (
              <option value="">활성 팀 없음</option>
            ) : (
              activeTeams.map((team) => (
                <option key={team.id} value={team.id}>
                  {team.name}
                </option>
              ))
            )}
          </select>
        ) : (
          <ActiveOrganizationMemberPicker
            members={activeMembers}
            value={granteeId}
            onChange={onGranteeIdChange}
            placeholder="권한 대상 멤버"
            emptyLabel="활성 멤버 없음"
          />
        )}
        <select
          value={authState}
          onChange={(event) =>
            onAuthStateChange(event.target.value as ResourceAuthState)
          }
          className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
        >
          {RESOURCE_AUTH_STATES.map((state) => (
            <option key={state} value={state}>
              {resourcePermissionLabel(resourceType, state)}
            </option>
          ))}
        </select>
        <button
          onClick={onGrant}
          disabled={
            actionPending ||
            resourceMissing ||
            granteeOptionsMissing ||
            !granteeId
          }
          className="h-10 rounded-md bg-slate-950 px-4 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
        >
          저장
        </button>
      </div>

      {resourceMissing ? (
        <Placeholder
          title="선택 가능한 resource가 없습니다"
          description="Workflow, Knowledge Base, LLM Credential이 생성되면 권한을 부여할 수 있습니다."
        />
      ) : (
        <div className="grid gap-4 px-5 py-5 lg:grid-cols-2">
          <PermissionList
            title="Team permissions"
            rows={permissionList?.team_permissions || []}
            resourceType={resourceType}
            granteeType="team"
            onRevoke={onRevoke}
          />
          <PermissionList
            title="User direct permissions"
            rows={permissionList?.user_permissions || []}
            resourceType={resourceType}
            granteeType="user"
            onRevoke={onRevoke}
          />
        </div>
      )}
    </DashboardPanel>
  );
}

function CredentialsTab({
  providers,
  credentials,
  actionPending,
  onOpenCreate,
  onManagePermission,
  onSync,
  onDelete,
}: {
  providers: LLMProviderResponse[];
  credentials: LLMCredentialResponse[];
  actionPending: boolean;
  onOpenCreate: () => void;
  onManagePermission: (credentialId: string) => void;
  onSync: (credential: LLMCredentialResponse) => void;
  onDelete: (credential: LLMCredentialResponse) => void;
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
            onClick={onOpenCreate}
            disabled={providers.length === 0 || actionPending}
            className="h-9 rounded-md bg-slate-950 px-3 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
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
                        <div className="flex shrink-0 gap-1">
                          <button
                            onClick={() => onManagePermission(credential.id)}
                            className="rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50"
                          >
                            권한
                          </button>
                          <button
                            onClick={() => onSync(credential)}
                            disabled={actionPending}
                            className="rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
                          >
                            Sync
                          </button>
                          <button
                            onClick={() => onDelete(credential)}
                            disabled={actionPending}
                            className="rounded-md border border-red-200 px-2 py-1 text-xs font-semibold text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40"
                          >
                            삭제
                          </button>
                        </div>
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

function resourcePermissionLabel(
  resourceType: ResourceType,
  state: ResourceAuthState,
) {
  if (resourceType === 'llm_credential') {
    const labels: Record<ResourceAuthState, string> = {
      viewer: 'Credential 조회 가능',
      operator: 'Credential 사용 가능',
      builder: 'Credential 수정 가능',
      manager: 'Credential 관리 가능',
    };
    return labels[state];
  }
  if (resourceType === 'knowledge_base') {
    const labels: Record<ResourceAuthState, string> = {
      viewer: 'KB 조회 가능',
      operator: 'KB 사용 가능',
      builder: 'KB 수정 가능',
      manager: 'KB 관리 가능',
    };
    return labels[state];
  }
  const labels: Record<ResourceAuthState, string> = {
    viewer: 'Workflow 조회 가능',
    operator: 'Workflow 실행 가능',
    builder: 'Workflow 수정 가능',
    manager: 'Workflow 관리 가능',
  };
  return labels[state];
}

function PermissionList({
  title,
  rows,
  resourceType,
  granteeType,
  onRevoke,
}: {
  title: string;
  rows: ResourcePermissionEntry[];
  resourceType: ResourceType;
  granteeType: GranteeType;
  onRevoke: (
    resourceType: ResourceType,
    granteeType: GranteeType,
    granteeId: string,
    label: string,
  ) => void;
}) {
  return (
    <div className="overflow-hidden rounded-md border border-slate-200">
      <div className="border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase text-slate-500">
        {title}
      </div>
      {rows.length === 0 ? (
        <div className="px-4 py-8 text-center text-sm text-slate-500">
          부여된 권한이 없습니다.
        </div>
      ) : (
        <div className="divide-y divide-slate-100">
          {rows.map((row) => (
            <div
              key={row.id}
              className="flex items-center justify-between gap-3 px-4 py-3"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-950">
                  {row.grantee_name}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  {resourcePermissionLabel(resourceType, row.auth_state)} ·{' '}
                  {formatDateTime(row.assigned_at)}
                </p>
              </div>
              <button
                onClick={() =>
                  onRevoke(
                    resourceType,
                    granteeType,
                    row.grantee_id,
                    `${row.grantee_name} · ${resourcePermissionLabel(
                      resourceType,
                      row.auth_state,
                    )}`,
                  )
                }
                className="rounded-md border border-red-200 px-2 py-1 text-xs font-semibold text-red-700 hover:bg-red-50"
              >
                회수
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function KnowledgeTab({
  knowledgeBases,
  onManagePermissions,
}: {
  knowledgeBases: KnowledgeBaseResponse[];
  onManagePermissions: (knowledgeBaseId: string) => void;
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
            description="지식 기반이 생성되면 권한을 관리할 수 있습니다."
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
                onClick={() => onManagePermissions(base.id)}
                className="h-9 rounded-md border border-slate-300 px-3 text-sm font-semibold text-slate-700 hover:bg-slate-50"
              >
                권한 관리
              </button>
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

function ListToolbar({
  query,
  onQueryChange,
  placeholder,
  resultText,
  children,
}: {
  query: string;
  onQueryChange: (query: string) => void;
  placeholder: string;
  resultText: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 border-b border-slate-100 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
      <div className="relative min-w-0 flex-1">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          className="h-10 w-full rounded-md border border-slate-300 bg-white pl-9 pr-3 text-sm"
          placeholder={placeholder}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {children}
        <span className="text-xs font-medium text-slate-500">{resultText}</span>
      </div>
    </div>
  );
}

function Pagination({
  page,
  totalPages,
  totalItems,
  onPageChange,
}: {
  page: number;
  totalPages: number;
  totalItems: number;
  onPageChange: (page: number) => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-5 py-3 text-sm">
      <span className="text-slate-500">
        {totalItems}개 중 page {page}/{totalPages}
      </span>
      <div className="flex gap-2">
        <button
          onClick={() => onPageChange(Math.max(1, page - 1))}
          disabled={page <= 1}
          className="h-8 rounded-md border border-slate-200 px-3 text-xs font-semibold text-slate-600 disabled:cursor-not-allowed disabled:opacity-40"
        >
          이전
        </button>
        <button
          onClick={() => onPageChange(Math.min(totalPages, page + 1))}
          disabled={page >= totalPages}
          className="h-8 rounded-md border border-slate-200 px-3 text-xs font-semibold text-slate-600 disabled:cursor-not-allowed disabled:opacity-40"
        >
          다음
        </button>
      </div>
    </div>
  );
}

function SidePanel({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/30">
      <div className="h-full w-full max-w-xl overflow-y-auto bg-white shadow-xl">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-200 bg-white px-5 py-4">
          <h2 className="text-base font-semibold text-slate-950">{title}</h2>
          <button
            onClick={onClose}
            className="rounded-md p-2 text-slate-500 hover:bg-slate-100"
            title="닫기"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="px-5 py-5">{children}</div>
      </div>
    </div>
  );
}

function ConfirmDialog({
  state,
  pending,
  onCancel,
  onConfirm,
}: {
  state: ConfirmState;
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const isDanger = state.tone === 'danger';
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/40 px-4">
      <div className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl">
        <h2 className="text-base font-semibold text-slate-950">{state.title}</h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          {state.description}
        </p>
        {state.details && state.details.length > 0 && (
          <ul className="mt-3 space-y-1 rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-600">
            {state.details.map((detail) => (
              <li key={detail}>{detail}</li>
            ))}
          </ul>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <button
            onClick={onCancel}
            disabled={pending}
            className="h-9 rounded-md border border-slate-300 px-3 text-sm font-semibold text-slate-700 disabled:opacity-40"
          >
            취소
          </button>
          <button
            onClick={onConfirm}
            disabled={pending}
            className={`h-9 rounded-md px-3 text-sm font-semibold text-white disabled:opacity-40 ${
              isDanger
                ? 'bg-red-600 hover:bg-red-700'
                : 'bg-slate-950 hover:bg-slate-800'
            }`}
          >
            {state.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function LabelledField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-semibold text-slate-800">
        {label}
      </span>
      {children}
    </label>
  );
}

function PanelActions({
  onCancel,
  onSubmit,
  submitLabel,
  disabled,
}: {
  onCancel: () => void;
  onSubmit: () => void;
  submitLabel: string;
  disabled?: boolean;
}) {
  return (
    <div className="flex justify-end gap-2 border-t border-slate-200 pt-4">
      <button
        onClick={onCancel}
        className="h-10 rounded-md border border-slate-300 px-4 text-sm font-semibold text-slate-700 hover:bg-slate-50"
      >
        취소
      </button>
      <button
        onClick={onSubmit}
        disabled={disabled}
        className="h-10 rounded-md bg-slate-950 px-4 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {submitLabel}
      </button>
    </div>
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
