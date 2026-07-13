import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
}));

const activeOrganizationMock = vi.hoisted(() => ({
  getStoredActiveOrganizationId: vi.fn(),
  setActiveOrganizationId: vi.fn(),
}));

vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    className,
  }: {
    href: string;
    children: ReactNode;
    className?: string;
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

vi.mock('next/navigation', () => ({
  usePathname: () => '/dashboard',
  useRouter: () => routerMock,
}));

vi.mock('../../auth/api/authApi', () => ({
  authApi: {
    me: vi.fn(),
    logout: vi.fn(),
  },
}));

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    get: vi.fn(),
  },
}));

vi.mock('@/lib/activeOrganization', () => ({
  ACTIVE_ORGANIZATION_CHANGED_EVENT: 'nodease-active-organization-changed',
  getStoredActiveOrganizationId:
    activeOrganizationMock.getStoredActiveOrganizationId,
  setActiveOrganizationId: activeOrganizationMock.setActiveOrganizationId,
}));

vi.mock('../../notifications/api/notificationsApi', () => ({
  notificationsApi: {
    listNotifications: vi.fn(),
    createEventSource: vi.fn(),
  },
}));

vi.mock('../../notifications/components/NotificationOverlay', () => ({
  NotificationOverlay: ({ onClose }: { onClose: () => void }) => (
    <div role="dialog" aria-label="알림">
      <button onClick={onClose}>닫기</button>
    </div>
  ),
}));

import { authApi } from '../../auth/api/authApi';
import { apiClient } from '@/lib/apiClient';
import { notificationsApi } from '../../notifications/api/notificationsApi';
import type { ModuleOperationAppSummary } from '../../app/api/moduleOperationsApi';
import Sidebar from './Sidebar';

type SidebarOrganizationFixture = {
  id: string;
  name: string;
  is_manager: boolean;
};

type SidebarDefaults = {
  currentOrganization?: SidebarOrganizationFixture;
  organizations?: SidebarOrganizationFixture[];
  operationRows?: Array<{ app: ModuleOperationAppSummary }>;
};

const managerOrganization: SidebarOrganizationFixture = {
  id: 'org-manager',
  name: 'Acme',
  is_manager: true,
};

const memberOrganization: SidebarOrganizationFixture = {
  id: 'org-member',
  name: 'Beta',
  is_manager: false,
};

const currentUserResponse: Awaited<ReturnType<typeof authApi.me>> = {
  user: {
    id: 'user-1',
    name: '홍길동',
    email: 'hong@example.com',
    emailVerified: true,
    role: 'user',
    isActive: true,
    createdAt: '2026-07-10T00:00:00Z',
    updatedAt: '2026-07-10T00:00:00Z',
  },
  session: {
    token: '[REDACTED]',
    expiresAt: '2026-07-11T00:00:00Z',
  },
};

const fakeEventSource = () => ({
  addEventListener: vi.fn(),
  close: vi.fn(),
});

const mockSidebarDefaults = ({
  currentOrganization = managerOrganization,
  organizations = [managerOrganization, memberOrganization],
  operationRows = [],
}: SidebarDefaults = {}) => {
  activeOrganizationMock.getStoredActiveOrganizationId.mockReturnValue(
    currentOrganization.id,
  );
  vi.mocked(authApi.me).mockResolvedValue(currentUserResponse);
  vi.mocked(notificationsApi.listNotifications).mockResolvedValue({ items: [] });
  vi.mocked(notificationsApi.createEventSource).mockReturnValue(
    fakeEventSource() as unknown as EventSource,
  );
  vi.mocked(apiClient.get).mockImplementation((path) => {
    if (path === '/organizations/current') {
      return Promise.resolve({ data: currentOrganization });
    }
    if (path === '/organizations') {
      return Promise.resolve({ data: organizations });
    }
    if (path === '/apps/operations') {
      return Promise.resolve({ data: operationRows });
    }
    return Promise.reject(new Error(`Unexpected path: ${path}`));
  });
};

beforeEach(() => {
  routerMock.push.mockReset();
  activeOrganizationMock.getStoredActiveOrganizationId.mockReset();
  activeOrganizationMock.setActiveOrganizationId.mockReset();
  mockSidebarDefaults();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('Sidebar notifications', () => {
  it('프로필 드롭다운에 알림 item을 표시하고 overlay를 연다', async () => {
    render(<Sidebar />);

    fireEvent.click(await screen.findByText('홍길동'));
    fireEvent.click(screen.getByRole('button', { name: '알림' }));

    expect(screen.getByRole('dialog', { name: '알림' })).toBeInTheDocument();
  });

  it('SSE notifications.changed 이벤트를 받으면 알림 목록을 재조회한다', async () => {
    let listener: EventListener | null = null;
    const source = {
      addEventListener: vi.fn((_event: string, callback: EventListener) => {
        listener = callback;
      }),
      close: vi.fn(),
    };
    vi.mocked(notificationsApi.createEventSource).mockReturnValue(
      source as unknown as EventSource,
    );

    render(<Sidebar />);

    await waitFor(() =>
      expect(notificationsApi.listNotifications).toHaveBeenCalledTimes(1),
    );
    act(() => {
      listener?.(new Event('notifications.changed'));
    });

    await waitFor(() =>
      expect(notificationsApi.listNotifications).toHaveBeenCalledTimes(2),
    );
  });
});

describe('Sidebar organization switcher', () => {
  it('organization manager는 내 모듈 운영 메뉴를 볼 수 있다', async () => {
    render(<Sidebar />);

    expect(await screen.findByRole('link', { name: '내 모듈' })).toHaveAttribute(
      'href',
      '/dashboard/mymodule',
    );
  });

  it('운영 가능한 row가 없는 일반 멤버에게 내 모듈 운영 메뉴를 숨긴다', async () => {
    mockSidebarDefaults({ currentOrganization: memberOrganization });

    render(<Sidebar />);

    await screen.findByText('Beta');
    await waitFor(() => {
      expect(
        screen.queryByRole('link', { name: '내 모듈' }),
      ).not.toBeInTheDocument();
    });
  });

  it('운영 가능한 row가 있는 일반 멤버에게 내 모듈 운영 메뉴를 표시한다', async () => {
    mockSidebarDefaults({
      currentOrganization: memberOrganization,
      operationRows: [
        {
          app: {
            id: 'app-1',
            name: '작성자 모듈',
            created_at: '2026-07-10T00:00:00Z',
            updated_at: '2026-07-10T00:00:00Z',
          },
        },
      ],
    });

    render(<Sidebar />);

    expect(await screen.findByRole('link', { name: '내 모듈' })).toHaveAttribute(
      'href',
      '/dashboard/mymodule',
    );
  });

  it('현재 organization 이름과 구분 badge를 표시한다', async () => {
    render(<Sidebar />);

    expect(await screen.findByText('Acme')).toBeInTheDocument();
    expect(screen.getAllByText('내 조직').length).toBeGreaterThan(0);
  });

  it('organization이 2개 이상이면 dropdown에서 내 조직과 멤버 조직을 구분한다', async () => {
    render(<Sidebar />);

    fireEvent.click(await screen.findByRole('button', { name: '조직 전환' }));

    expect(
      screen.getByRole('menuitem', { name: 'Acme 조직 선택' }),
    ).toHaveAttribute('aria-current', 'true');
    expect(
      screen.getByRole('menuitem', { name: 'Beta 조직 선택' }),
    ).toBeInTheDocument();
    expect(screen.getAllByText('내 조직').length).toBeGreaterThan(0);
    expect(screen.getByText('멤버 조직')).toBeInTheDocument();
  });

  it('다른 organization 선택 시 active organization을 저장하고 dashboard로 이동한다', async () => {
    render(<Sidebar />);

    fireEvent.click(await screen.findByRole('button', { name: '조직 전환' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Beta 조직 선택' }));

    expect(activeOrganizationMock.setActiveOrganizationId).toHaveBeenCalledWith(
      'org-member',
    );
    expect(routerMock.push).toHaveBeenCalledWith('/dashboard');
    expect(screen.getByText('Beta')).toBeInTheDocument();
    expect(screen.getByText('멤버 조직')).toBeInTheDocument();
  });

  it('현재 organization을 다시 선택하면 저장하지 않고 dropdown만 닫는다', async () => {
    render(<Sidebar />);

    await screen.findByText('Acme');
    activeOrganizationMock.setActiveOrganizationId.mockClear();
    fireEvent.click(screen.getByRole('button', { name: '조직 전환' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Acme 조직 선택' }));

    expect(activeOrganizationMock.setActiveOrganizationId).not.toHaveBeenCalled();
    expect(routerMock.push).not.toHaveBeenCalled();
    expect(
      screen.queryByRole('menuitem', { name: 'Beta 조직 선택' }),
    ).not.toBeInTheDocument();
  });

  it('organization이 1개뿐이면 switcher dropdown을 열지 않는다', async () => {
    mockSidebarDefaults({ organizations: [managerOrganization] });

    render(<Sidebar />);

    const switcher = await screen.findByRole('button', { name: '조직 전환' });
    expect(switcher).toBeDisabled();
    fireEvent.click(switcher);
    expect(screen.queryByRole('menuitem')).not.toBeInTheDocument();
  });
});
