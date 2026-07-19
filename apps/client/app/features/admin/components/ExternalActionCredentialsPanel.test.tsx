import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock('@/app/features/workflow/api/externalActionCredentialApi', () => ({
  externalActionCredentialApi: {
    create: vi.fn(),
    update: vi.fn(),
    revoke: vi.fn(),
  },
}));

import { ExternalActionCredentialsPanel } from './ExternalActionCredentialsPanel';
import { externalActionCredentialApi } from '@/app/features/workflow/api/externalActionCredentialApi';

const activeCredential = {
  id: 'credential-1',
  credential_name: '운영 Slack',
  provider: 'slack_api' as const,
  revision: 3,
  status: 'active' as const,
};

const revokedCredential = {
  ...activeCredential,
  id: 'credential-2',
  credential_name: '폐기된 GitHub',
  provider: 'github' as const,
  status: 'revoked' as const,
};

describe('ExternalActionCredentialsPanel', () => {
  const onRefresh = vi.fn().mockResolvedValue(undefined);
  const onManagePermission = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    onRefresh.mockResolvedValue(undefined);
  });

  it('관리자가 provider, 이름과 secret으로 credential을 등록한다', async () => {
    vi.mocked(externalActionCredentialApi.create).mockResolvedValue({
      ...activeCredential,
      organization_id: 'organization-1',
      created_at: '2026-07-19T00:00:00Z',
      updated_at: '2026-07-19T00:00:00Z',
      revoked_at: null,
    });
    render(
      <ExternalActionCredentialsPanel
        credentials={[]}
        onRefresh={onRefresh}
        onManagePermission={onManagePermission}
      />,
    );

    fireEvent.click(
      screen.getByRole('button', { name: '외부 Credential 등록' }),
    );
    fireEvent.change(screen.getByLabelText('Provider'), {
      target: { value: 'slack_api' },
    });
    fireEvent.change(screen.getByLabelText('Credential 이름'), {
      target: { value: ' 운영 Slack ' },
    });
    fireEvent.change(screen.getByLabelText('Secret'), {
      target: { value: 'test-only-placeholder' },
    });
    fireEvent.click(screen.getByRole('button', { name: '등록' }));

    await waitFor(() =>
      expect(externalActionCredentialApi.create).toHaveBeenCalledWith({
        credential_name: '운영 Slack',
        provider: 'slack_api',
        secret: 'test-only-placeholder',
      }),
    );
    expect(onRefresh).toHaveBeenCalledTimes(1);
    expect(screen.queryByLabelText('Secret')).not.toBeInTheDocument();
  });

  it('mutation 성공 뒤 목록 갱신이 실패해도 secret 입력을 닫아 중복 제출을 막는다', async () => {
    vi.mocked(externalActionCredentialApi.create).mockResolvedValue({
      ...activeCredential,
      organization_id: 'organization-1',
      created_at: '2026-07-19T00:00:00Z',
      updated_at: '2026-07-19T00:00:00Z',
      revoked_at: null,
    });
    onRefresh.mockRejectedValueOnce(new Error('refresh failed'));
    render(
      <ExternalActionCredentialsPanel
        credentials={[]}
        onRefresh={onRefresh}
        onManagePermission={onManagePermission}
      />,
    );

    fireEvent.click(
      screen.getByRole('button', { name: '외부 Credential 등록' }),
    );
    fireEvent.change(screen.getByLabelText('Credential 이름'), {
      target: { value: 'GitHub 운영' },
    });
    fireEvent.change(screen.getByLabelText('Secret'), {
      target: { value: 'test-only-placeholder' },
    });
    fireEvent.click(screen.getByRole('button', { name: '등록' }));

    await waitFor(() =>
      expect(externalActionCredentialApi.create).toHaveBeenCalledTimes(1),
    );
    await waitFor(() =>
      expect(screen.queryByLabelText('Secret')).not.toBeInTheDocument(),
    );
  });

  it('기존 secret을 노출하지 않고 revision 기반으로 교체한다', async () => {
    vi.mocked(externalActionCredentialApi.update).mockResolvedValue({
      ...activeCredential,
      organization_id: 'organization-1',
      revision: 4,
      created_at: '2026-07-19T00:00:00Z',
      updated_at: '2026-07-19T00:01:00Z',
      revoked_at: null,
    });
    render(
      <ExternalActionCredentialsPanel
        credentials={[activeCredential]}
        onRefresh={onRefresh}
        onManagePermission={onManagePermission}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '운영 Slack 수정' }));
    expect(screen.getByLabelText('새 Secret (선택)')).toHaveValue('');
    fireEvent.change(screen.getByLabelText('새 Secret (선택)'), {
      target: { value: 'replacement-placeholder' },
    });
    fireEvent.click(screen.getByRole('button', { name: '저장' }));

    await waitFor(() =>
      expect(externalActionCredentialApi.update).toHaveBeenCalledWith(
        'credential-1',
        {
          expected_revision: 3,
          secret: 'replacement-placeholder',
        },
      ),
    );
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it('active credential은 폐기하고 revoked credential은 권한 회수만 제공한다', async () => {
    vi.mocked(externalActionCredentialApi.revoke).mockResolvedValue({
      ...activeCredential,
      organization_id: 'organization-1',
      revision: 4,
      status: 'revoked',
      created_at: '2026-07-19T00:00:00Z',
      updated_at: '2026-07-19T00:01:00Z',
      revoked_at: '2026-07-19T00:01:00Z',
    });
    render(
      <ExternalActionCredentialsPanel
        credentials={[activeCredential, revokedCredential]}
        onRefresh={onRefresh}
        onManagePermission={onManagePermission}
      />,
    );

    expect(
      screen.queryByRole('button', { name: '폐기된 GitHub 수정' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '폐기된 GitHub 폐기' }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '폐기된 GitHub 권한' }));
    expect(onManagePermission).toHaveBeenCalledWith('credential-2');

    fireEvent.click(screen.getByRole('button', { name: '운영 Slack 폐기' }));
    fireEvent.click(screen.getByRole('button', { name: '폐기 확인' }));

    await waitFor(() =>
      expect(externalActionCredentialApi.revoke).toHaveBeenCalledWith(
        'credential-1',
        3,
      ),
    );
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });
});
