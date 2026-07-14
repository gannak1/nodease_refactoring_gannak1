import { fireEvent, render, screen, waitFor } from '@testing-library/react';
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

import AdminConsolePage from './page';

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
