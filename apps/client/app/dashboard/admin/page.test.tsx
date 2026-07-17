import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const navigationMock = vi.hoisted(() => ({
  searchParams: 'tab=organization-structure&view=members',
  push: vi.fn(),
  replace: vi.fn(),
}));

const apiClientMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}));

const organizationApiMock = vi.hoisted(() => ({
  getCurrentOrganization: vi.fn(),
  listMembers: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => '/dashboard/admin',
  useRouter: () => ({
    push: navigationMock.push,
    replace: navigationMock.replace,
  }),
  useSearchParams: () => new URLSearchParams(navigationMock.searchParams),
}));

vi.mock('@/lib/apiClient', () => ({ apiClient: apiClientMock }));

vi.mock('@/app/features/auth/api/authApi', () => ({
  authApi: {
    me: vi.fn().mockResolvedValue({ user: { id: 'user-1' } }),
  },
}));

vi.mock('@/app/features/organization/api/organizationApi', () => ({
  organizationApi: organizationApiMock,
}));

vi.mock('@/app/features/workflow/api/mailCredentialApi', () => ({
  mailCredentialApi: { listAvailable: vi.fn().mockResolvedValue([]) },
}));

vi.mock('@/app/features/knowledge/api/knowledgeApi', () => ({
  knowledgeApi: { getKnowledgeBases: vi.fn().mockResolvedValue([]) },
}));

vi.mock('@/app/features/admin/components/AdminSummaryCards', () => ({
  AdminSummaryCards: () => null,
}));

import AdminConsolePage, { PermissionsTab } from './page';

const member = {
  id: 'membership-1',
  organization_id: 'org-1',
  user_id: 'user-1',
  user_email: 'member@example.com',
  user_name: '김멤버',
  membership_state: 'active',
  organization_auth_state: 'manager',
  invited_at: '2026-07-01T00:00:00Z',
  accepted_at: '2026-07-01T00:00:00Z',
  suspended_at: null,
  removed_at: null,
};

const team = {
  id: 'team-1',
  organization_id: 'org-1',
  name: '개발팀',
  description: '제품 개발',
  is_active: true,
};

const members = Array.from({ length: 21 }, (_, index) => ({
  ...member,
  id: `membership-${index + 1}`,
  user_id: `user-${index + 1}`,
  user_email: `member-${index + 1}@example.com`,
  user_name: `김멤버${index + 1}`,
}));

const teams = Array.from({ length: 21 }, (_, index) => ({
  ...team,
  id: `team-${index + 1}`,
  name: `개발팀${index + 1}`,
}));

describe('AdminConsolePage 조직 구성 상태 보존', () => {
  beforeEach(() => {
    navigationMock.searchParams = 'tab=organization-structure&view=members';
    navigationMock.push.mockReset();
    navigationMock.replace.mockReset();
    apiClientMock.get.mockReset();
    organizationApiMock.getCurrentOrganization.mockResolvedValue({
      id: 'org-1',
      name: 'Nodease',
      is_manager: true,
    });
    organizationApiMock.listMembers.mockImplementation(
      (_organizationId: string, state?: string) =>
        Promise.resolve(state === 'removed' ? [] : members),
    );
    apiClientMock.get.mockImplementation((path: string) => {
      if (path === '/teams') return Promise.resolve({ data: teams });
      return Promise.resolve({ data: [] });
    });
  });

  it('보기를 전환해도 멤버와 팀의 검색·필터·페이지 상태를 각각 유지한다', async () => {
    const { rerender } = render(<AdminConsolePage />);

    const memberSearch = await screen.findByPlaceholderText('이름, email 검색');
    fireEvent.change(memberSearch, { target: { value: '멤버' } });
    fireEvent.change(screen.getByDisplayValue('전체 상태'), {
      target: { value: 'active' },
    });
    fireEvent.click(screen.getByRole('button', { name: '다음' }));
    expect(screen.getByText('21개 중 page 2/2')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '초대' })).toBeInTheDocument();
    expect(
      screen.queryByPlaceholderText('팀 이름, 설명 검색'),
    ).not.toBeInTheDocument();

    navigationMock.searchParams = 'tab=organization-structure&view=teams';
    rerender(<AdminConsolePage />);

    const teamSearch = await screen.findByPlaceholderText('팀 이름, 설명 검색');
    fireEvent.change(teamSearch, { target: { value: '팀' } });
    fireEvent.change(screen.getByDisplayValue('전체 상태'), {
      target: { value: 'active' },
    });
    fireEvent.click(screen.getByRole('button', { name: '다음' }));
    expect(screen.getByText('21개 중 page 2/2')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '팀 생성' })).toBeInTheDocument();
    expect(screen.queryByPlaceholderText('이름, email 검색')).not.toBeInTheDocument();

    navigationMock.searchParams = 'tab=organization-structure&view=members';
    rerender(<AdminConsolePage />);

    await waitFor(() =>
      expect(screen.getByPlaceholderText('이름, email 검색')).toHaveValue(
        '멤버',
      ),
    );
    expect(screen.getByDisplayValue('활성')).toBeInTheDocument();
    expect(screen.getByText('21개 중 page 2/2')).toBeInTheDocument();

    navigationMock.searchParams = 'tab=organization-structure&view=teams';
    rerender(<AdminConsolePage />);

    await waitFor(() =>
      expect(screen.getByPlaceholderText('팀 이름, 설명 검색')).toHaveValue(
        '팀',
      ),
    );
    expect(screen.getByDisplayValue('활성')).toBeInTheDocument();
    expect(screen.getByText('21개 중 page 2/2')).toBeInTheDocument();
  });

  it('일반 멤버에게 조직 구성과 관리 데이터를 노출하지 않는다', async () => {
    organizationApiMock.getCurrentOrganization.mockResolvedValue({
      id: 'org-1',
      name: 'Nodease',
      is_manager: false,
    });

    render(<AdminConsolePage />);

    expect(await screen.findByText('관리 권한 없음')).toBeInTheDocument();
    expect(
      screen.queryByRole('group', { name: '조직 구성 보기' }),
    ).not.toBeInTheDocument();
    expect(apiClientMock.get).not.toHaveBeenCalled();
  });

  it('관리자 탭에 조직 설정 메뉴를 표시하지 않는다', async () => {
    render(<AdminConsolePage />);

    expect(
      await screen.findByRole('button', { name: '조직 구성' }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '조직 설정' }),
    ).not.toBeInTheDocument();
  });

  it('요약 카드에서 연결된 관리 탭으로 이동할 수 있다', async () => {
    render(<AdminConsolePage />);

    expect(
      await screen.findByRole('link', {
        name: '활성 멤버 조직 구성 멤버 보기에서 확인',
      }),
    ).toHaveAttribute(
      'href',
      '/dashboard/admin?tab=organization-structure&view=members',
    );
    expect(
      screen.getByRole('link', {
        name: '활성 팀 조직 구성 팀 보기에서 확인',
      }),
    ).toHaveAttribute(
      'href',
      '/dashboard/admin?tab=organization-structure&view=teams',
    );
    expect(
      screen.getByRole('link', {
        name: 'LLM Credentials 탭에서 확인',
      }),
    ).toHaveAttribute('href', '/dashboard/admin?tab=credentials');
    expect(
      screen.getByRole('link', { name: '지식 기반 탭에서 확인' }),
    ).toHaveAttribute('href', '/dashboard/admin?tab=knowledge');
  });
});

describe('PermissionsTab 표 기반 권한 부여', () => {
  const renderPermissionsTab = (overrides = {}) => {
    const onGrant = vi.fn();
    const onSelectResource = vi.fn();

    render(
      <PermissionsTab
        resourceType="workflow"
        workflowOptions={[
          {
            id: 'app-1',
            name: 'Enterprise 고객 티켓 처리',
            workflow_id: 'workflow-1',
          },
          {
            id: 'app-2',
            name: '사내 문서 질문 응답 봇',
            workflow_id: 'workflow-2',
          },
        ]}
        selectedWorkflowId="workflow-1"
        knowledgeBases={[]}
        selectedKnowledgeBaseId=""
        credentials={[]}
        selectedCredentialId=""
        mailCredentials={[]}
        selectedMailCredentialId=""
        activeTeams={[team]}
        activeMembers={[]}
        granteeType="team"
        granteeId="team-1"
        authState="viewer"
        permissionList={{
          resource_type: 'workflow',
          resource_id: 'workflow-1',
          organization_id: 'org-1',
          team_permissions: [],
          user_permissions: [],
        }}
        actionPending={false}
        onSelectResource={onSelectResource}
        onGrant={onGrant}
        onRevoke={vi.fn()}
        {...overrides}
      />,
    );

    return { onGrant, onSelectResource };
  };

  it('권한 부여 버튼으로 표 선택 모달을 열고 저장한다', async () => {
    const { onGrant } = renderPermissionsTab();

    expect(
      screen.queryByRole('dialog', { name: '리소스 권한 부여' }),
    ).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: '권한 부여' })).toHaveLength(1);
    expect(
      screen.queryByRole('button', { name: '리소스·권한 변경' }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '권한 부여' }));

    const dialog = screen.getByRole('dialog', { name: '리소스 권한 부여' });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByRole('table', { name: '권한 대상 리소스' })).toBeInTheDocument();
    expect(screen.getByRole('table', { name: '권한 부여 대상' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '선택한 권한 부여' }));
    await waitFor(() =>
      expect(onGrant).toHaveBeenCalledWith({
        resourceType: 'workflow',
        resourceId: 'workflow-1',
        granteeType: 'team',
        granteeId: 'team-1',
        authState: 'viewer',
      }),
    );
    expect(
      screen.queryByRole('dialog', { name: '리소스 권한 부여' }),
    ).not.toBeInTheDocument();
  });

  it('모달 선택과 취소는 페이지의 조회 리소스를 바꾸지 않는다', () => {
    const { onGrant } = renderPermissionsTab();
    fireEvent.click(screen.getByRole('button', { name: '권한 부여' }));

    fireEvent.change(screen.getByRole('searchbox', { name: '리소스 검색' }), {
      target: { value: '사내 문서' },
    });
    const resourceTable = screen.getByRole('table', {
      name: '권한 대상 리소스',
    });
    expect(
      within(resourceTable).queryByText('Enterprise 고객 티켓 처리'),
    ).not.toBeInTheDocument();
    expect(
      within(resourceTable).getByText('사내 문서 질문 응답 봇'),
    ).toBeVisible();

    fireEvent.click(
      screen.getByRole('radio', { name: '사내 문서 질문 응답 봇 선택' }),
    );
    expect(onGrant).not.toHaveBeenCalled();
    expect(screen.getByText('Enterprise 고객 티켓 처리')).toBeVisible();

    fireEvent.click(screen.getByRole('button', { name: '취소' }));
    expect(
      screen.queryByRole('dialog', { name: '리소스 권한 부여' }),
    ).not.toBeInTheDocument();
    expect(screen.getByText('Enterprise 고객 티켓 처리')).toBeVisible();
  });

  it('본문 리소스 필터로 저장 없이 권한 조회 대상을 바꾼다', () => {
    const { onGrant, onSelectResource } = renderPermissionsTab();

    fireEvent.click(screen.getByRole('button', { name: '리소스 필터 변경' }));
    fireEvent.change(
      screen.getByRole('searchbox', { name: '조회 리소스 검색' }),
      { target: { value: '사내 문서' } },
    );
    fireEvent.click(
      screen.getByRole('option', { name: '사내 문서 질문 응답 봇' }),
    );

    expect(onSelectResource).toHaveBeenCalledWith('workflow', 'workflow-2');
    expect(onGrant).not.toHaveBeenCalled();
  });

  it('새 리소스 응답을 기다리는 동안 이전 리소스의 회수 버튼을 숨긴다', () => {
    renderPermissionsTab({
      selectedWorkflowId: 'workflow-2',
      permissionList: {
        resource_type: 'workflow',
        resource_id: 'workflow-1',
        organization_id: 'org-1',
        team_permissions: [
          {
            id: 'permission-1',
            grantee_type: 'team',
            grantee_id: 'team-1',
            grantee_name: '개발팀',
            auth_state: 'viewer',
            assigned_at: '2026-07-18T00:00:00Z',
          },
        ],
        user_permissions: [],
      },
    });

    expect(screen.queryByRole('button', { name: '회수' })).not.toBeInTheDocument();
    expect(screen.queryByText('개발팀')).not.toBeInTheDocument();
  });
});
