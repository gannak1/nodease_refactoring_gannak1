import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';

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
  useRouter: () => ({ push: vi.fn() }),
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
import { notificationsApi } from '../../notifications/api/notificationsApi';
import Sidebar from './Sidebar';

const fakeEventSource = () => ({
  addEventListener: vi.fn(),
  close: vi.fn(),
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('Sidebar notifications', () => {
  it('프로필 드롭다운에 알림 item을 표시하고 overlay를 연다', async () => {
    vi.mocked(authApi.me).mockResolvedValue({
      user: { name: '홍길동', email: 'hong@example.com' },
    });
    vi.mocked(notificationsApi.listNotifications).mockResolvedValue({ items: [] });
    vi.mocked(notificationsApi.createEventSource).mockReturnValue(
      fakeEventSource() as unknown as EventSource,
    );

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
    vi.mocked(authApi.me).mockResolvedValue({
      user: { name: '홍길동', email: 'hong@example.com' },
    });
    vi.mocked(notificationsApi.listNotifications).mockResolvedValue({ items: [] });
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
