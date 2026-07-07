import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('../../organization/api/organizationApi', () => ({
  organizationApi: {
    acceptInvitation: vi.fn(),
    declineInvitation: vi.fn(),
  },
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

import { organizationApi } from '../../organization/api/organizationApi';
import { NotificationOverlay } from './NotificationOverlay';

const notification = {
  id: 'organization_invitation:membership-1',
  type: 'organization.invitation' as const,
  organization_id: 'org-1',
  organization_name: 'Acme',
  organization_auth_state: 'member' as const,
  created_at: '2026-07-06T10:00:00.000Z',
};

afterEach(() => {
  vi.clearAllMocks();
});

describe('NotificationOverlay', () => {
  it('organization 초대 알림과 수락/거절 버튼을 표시한다', () => {
    render(
      <NotificationOverlay
        notifications={[notification]}
        loading={false}
        error={null}
        onClose={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByRole('dialog', { name: '알림' })).toBeInTheDocument();
    expect(screen.getByText('Acme')).toBeInTheDocument();
    expect(screen.getByText('조직 멤버 초대')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /수락/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /거절/ })).toBeInTheDocument();
  });

  it('수락 클릭 시 accept API를 호출하고 목록을 갱신한다', async () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    vi.mocked(organizationApi.acceptInvitation).mockResolvedValue(
      {} as Awaited<ReturnType<typeof organizationApi.acceptInvitation>>,
    );

    render(
      <NotificationOverlay
        notifications={[notification]}
        loading={false}
        error={null}
        onClose={vi.fn()}
        onRefresh={onRefresh}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /수락/ }));

    await waitFor(() =>
      expect(organizationApi.acceptInvitation).toHaveBeenCalledWith('org-1'),
    );
    await waitFor(() => expect(onRefresh).toHaveBeenCalled());
  });

  it('거절 클릭 시 decline API를 호출하고 목록을 갱신한다', async () => {
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    vi.mocked(organizationApi.declineInvitation).mockResolvedValue(
      {} as Awaited<ReturnType<typeof organizationApi.declineInvitation>>,
    );

    render(
      <NotificationOverlay
        notifications={[notification]}
        loading={false}
        error={null}
        onClose={vi.fn()}
        onRefresh={onRefresh}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /거절/ }));

    await waitFor(() =>
      expect(organizationApi.declineInvitation).toHaveBeenCalledWith('org-1'),
    );
    await waitFor(() => expect(onRefresh).toHaveBeenCalled());
  });

  it('알림이 없으면 empty state를 표시한다', () => {
    render(
      <NotificationOverlay
        notifications={[]}
        loading={false}
        error={null}
        onClose={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.getByText('새 알림이 없습니다.')).toBeInTheDocument();
  });
});
