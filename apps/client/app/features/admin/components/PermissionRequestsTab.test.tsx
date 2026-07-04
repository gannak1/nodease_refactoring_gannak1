import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { AxiosError, type AxiosResponse } from 'axios';

vi.mock('../api/adminApi', () => ({
  adminApi: {
    listPermissionRequests: vi.fn(),
    approvePermissionRequest: vi.fn(),
    rejectPermissionRequest: vi.fn(),
  },
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

import { toast } from 'sonner';
import { adminApi } from '../api/adminApi';
import { PermissionRequestsTab } from './PermissionRequestsTab';
import type { OrganizationMember } from '../../organization/types/Organization';

const mockedList = vi.mocked(adminApi.listPermissionRequests);
const mockedApprove = vi.mocked(adminApi.approvePermissionRequest);
const mockedReject = vi.mocked(adminApi.rejectPermissionRequest);

const members = [
  {
    id: 'membership-1',
    user_id: 'manager-1',
    user_name: '김관리',
    user_email: 'admin@example.com',
    state: 'active',
    organization_auth_state: 'manager',
  },
] as unknown as OrganizationMember[];

const pendingRequest = {
  id: 'req-1',
  user: { id: 'user-2', name: '박신입', email: 'newbie@example.com' },
  requested_permission: 'app.create',
  reason: '온보딩 워크플로우를 만들어야 합니다.',
  status: 'pending' as const,
  created_at: '2026-07-02T10:00:00+09:00',
  decided_by: null,
  decided_at: null,
};

const approvedRequest = {
  ...pendingRequest,
  id: 'req-2',
  status: 'approved' as const,
  decided_by: 'manager-1',
  decided_at: '2026-07-03T09:00:00+09:00',
};

const conflictError = () => {
  const error = new AxiosError('Conflict');
  error.response = { status: 409 } as AxiosResponse;
  return error;
};

afterEach(() => {
  vi.clearAllMocks();
});

describe('PermissionRequestsTab', () => {
  it('pending 신청 목록을 요청자, 권한 라벨, 사유와 함께 기본 표시한다', async () => {
    mockedList.mockResolvedValue({ total: 1, items: [pendingRequest] });

    render(<PermissionRequestsTab members={members} />);

    expect(await screen.findByText('박신입')).toBeInTheDocument();
    expect(screen.getByText('newbie@example.com')).toBeInTheDocument();
    expect(screen.getByText('워크플로우 생성/배포')).toBeInTheDocument();
    expect(
      screen.getByText('온보딩 워크플로우를 만들어야 합니다.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '승인' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '거절' })).toBeInTheDocument();
    expect(mockedList).toHaveBeenCalledWith({
      status: 'pending',
      page: 1,
      limit: 20,
    });
  });

  it('status 필터를 바꾸면 해당 상태로 1페이지부터 재조회하고 처리 정보를 표시한다', async () => {
    mockedList
      .mockResolvedValueOnce({ total: 0, items: [] })
      .mockResolvedValueOnce({ total: 1, items: [approvedRequest] });

    render(<PermissionRequestsTab members={members} />);
    await screen.findByText('대기 상태의 권한 신청이 없습니다.');

    fireEvent.change(screen.getByLabelText('상태'), {
      target: { value: 'approved' },
    });

    expect(await screen.findByText('박신입')).toBeInTheDocument();
    expect(mockedList).toHaveBeenLastCalledWith({
      status: 'approved',
      page: 1,
      limit: 20,
    });
    // 처리된 건에는 승인/거절 버튼 대신 처리자/처리 시각을 표시한다.
    expect(screen.queryByRole('button', { name: '승인' })).not.toBeInTheDocument();
    expect(screen.getByText('김관리')).toBeInTheDocument();
  });

  it('승인 흐름: 확인 다이얼로그에서 확정하면 API 호출, 성공 toast, 목록 갱신', async () => {
    mockedList.mockResolvedValue({ total: 1, items: [pendingRequest] });
    mockedApprove.mockResolvedValue({ ...pendingRequest, status: 'approved' });

    render(<PermissionRequestsTab members={members} />);

    fireEvent.click(await screen.findByRole('button', { name: '승인' }));

    const dialog = screen.getByRole('dialog', { name: '권한 신청 승인 확인' });
    expect(
      within(dialog).getByText('박신입 (newbie@example.com)'),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText('온보딩 워크플로우를 만들어야 합니다.'),
    ).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole('button', { name: '승인 확정' }));

    await waitFor(() => expect(mockedApprove).toHaveBeenCalledWith('req-1'));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith('권한 신청을 승인했습니다.'),
    );
    // 확정 후 목록을 다시 불러온다 (초기 1회 + 갱신 1회).
    await waitFor(() => expect(mockedList).toHaveBeenCalledTimes(2));
    expect(
      screen.queryByRole('dialog', { name: '권한 신청 승인 확인' }),
    ).not.toBeInTheDocument();
  });

  it('거절 흐름: 확정하면 reject API를 호출한다', async () => {
    mockedList.mockResolvedValue({ total: 1, items: [pendingRequest] });
    mockedReject.mockResolvedValue({ ...pendingRequest, status: 'rejected' });

    render(<PermissionRequestsTab members={members} />);

    fireEvent.click(await screen.findByRole('button', { name: '거절' }));
    fireEvent.click(screen.getByRole('button', { name: '거절 확정' }));

    await waitFor(() => expect(mockedReject).toHaveBeenCalledWith('req-1'));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith('권한 신청을 거절했습니다.'),
    );
  });

  it('이미 처리된 신청(409)은 안내 toast 후 목록을 갱신한다', async () => {
    mockedList.mockResolvedValue({ total: 1, items: [pendingRequest] });
    mockedApprove.mockRejectedValue(conflictError());

    render(<PermissionRequestsTab members={members} />);

    fireEvent.click(await screen.findByRole('button', { name: '승인' }));
    fireEvent.click(screen.getByRole('button', { name: '승인 확정' }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith('이미 처리된 신청입니다.'),
    );
    await waitFor(() => expect(mockedList).toHaveBeenCalledTimes(2));
  });

  it('403 응답이면 접근 권한 안내 문구를 표시한다', async () => {
    const error = new AxiosError('Forbidden');
    error.response = { status: 403 } as AxiosResponse;
    mockedList.mockRejectedValue(error);

    render(<PermissionRequestsTab members={members} />);

    expect(
      await screen.findByText(/권한 신청 관리 권한이 없습니다/),
    ).toBeInTheDocument();
  });
});
