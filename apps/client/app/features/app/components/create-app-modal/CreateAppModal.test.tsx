import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { AxiosError, type AxiosResponse } from 'axios';
import { afterEach, describe, expect, it, vi } from 'vitest';

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => routerMock,
}));

vi.mock('../../api/appApi', () => ({
  appApi: {
    createApp: vi.fn(),
  },
}));

vi.mock('../../../organization/api/organizationApi', () => ({
  organizationApi: {
    submitPermissionRequest: vi.fn(),
  },
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

import { toast } from 'sonner';
import { organizationApi } from '../../../organization/api/organizationApi';
import { appApi } from '../../api/appApi';
import CreateAppModal from './index';

const mockedCreateApp = vi.mocked(appApi.createApp);
const mockedSubmitPermissionRequest = vi.mocked(
  organizationApi.submitPermissionRequest,
);

const forbiddenError = () => {
  const error = new AxiosError('Forbidden');
  error.response = {
    status: 403,
    data: { error: { code: 'permission.denied' } },
  } as AxiosResponse;
  return error;
};

const conflictError = () => {
  const error = new AxiosError('Conflict');
  error.response = {
    status: 409,
    data: { detail: 'Pending permission request already exists' },
  } as AxiosResponse;
  return error;
};

afterEach(() => {
  vi.clearAllMocks();
});

describe('CreateAppModal permission request flow', () => {
  it('앱 생성 403이면 권한 신청 폼으로 전환하고 신청 API를 호출한다', async () => {
    const onSuccess = vi.fn();
    const onClose = vi.fn();
    mockedCreateApp.mockRejectedValueOnce(forbiddenError());
    mockedSubmitPermissionRequest.mockResolvedValueOnce({
      id: 'req-1',
      user: null,
      requested_permission: 'app.create',
      reason: '신규 고객 온보딩 자동화가 필요합니다.',
      status: 'pending',
      created_at: '2026-07-04T09:00:00+09:00',
      decided_by: null,
      decided_at: null,
    });

    render(<CreateAppModal onSuccess={onSuccess} onClose={onClose} />);

    fireEvent.change(screen.getByPlaceholderText('앱 이름을 입력하세요'), {
      target: { value: '온보딩' },
    });
    fireEvent.click(screen.getByRole('button', { name: '생성' }));

    expect(
      await screen.findByText(/앱 생성 권한이 없습니다/),
    ).toBeInTheDocument();
    expect(
      screen.getByDisplayValue(
        '온보딩 앱을 생성해 워크플로우를 구성해야 합니다.',
      ),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText('권한이 필요한 이유를 입력하세요'), {
      target: { value: '신규 고객 온보딩 자동화가 필요합니다.' },
    });
    fireEvent.click(screen.getByRole('button', { name: '권한 신청' }));

    await waitFor(() =>
      expect(mockedSubmitPermissionRequest).toHaveBeenCalledWith({
        reason: '신규 고객 온보딩 자동화가 필요합니다.',
      }),
    );
    expect(toast.success).toHaveBeenCalledWith('권한 신청을 보냈습니다.');
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('이미 pending 신청이 있으면 중복 신청 안내를 표시한다', async () => {
    mockedCreateApp.mockRejectedValueOnce(forbiddenError());
    mockedSubmitPermissionRequest.mockRejectedValueOnce(conflictError());

    render(<CreateAppModal onSuccess={vi.fn()} onClose={vi.fn()} />);

    fireEvent.change(screen.getByPlaceholderText('앱 이름을 입력하세요'), {
      target: { value: '리포트' },
    });
    fireEvent.click(screen.getByRole('button', { name: '생성' }));
    await screen.findByText(/앱 생성 권한이 없습니다/);

    fireEvent.click(screen.getByRole('button', { name: '권한 신청' }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        '이미 대기 중인 권한 신청이 있습니다.',
      ),
    );
  });
});
