import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { appApi } from '@/app/features/app/api/appApi';

import { AppAuthSecretControl } from './AppAuthSecretControl';

vi.mock('@/app/features/app/api/appApi', () => ({
  appApi: {
    getAuthSecretStatus: vi.fn(),
    rotateAuthSecret: vi.fn(),
  },
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const mockedAppApi = vi.mocked(appApi);
const writeClipboard = vi.fn().mockResolvedValue(undefined);

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: writeClipboard },
  });
});

afterEach(cleanup);

describe('AppAuthSecretControl', () => {
  it('issues an unconfigured secret once without browser persistence', async () => {
    const storageWrite = vi.spyOn(Storage.prototype, 'setItem');
    const onSecretAvailable = vi.fn();
    mockedAppApi.getAuthSecretStatus.mockResolvedValue({
      configured: false,
      version: 0,
      rotation_enabled: true,
      rotated_at: null,
      previous_grace_active: false,
      previous_valid_until: null,
    });
    mockedAppApi.rotateAuthSecret.mockResolvedValue({
      secret: 'one-time-secret',
      version: 1,
      rotated_at: '2026-07-17T03:00:00Z',
      previous_grace_active: false,
      previous_valid_until: null,
    });

    render(
      <AppAuthSecretControl
        appId="app-1"
        onSecretAvailable={onSecretAvailable}
      />,
    );

    fireEvent.click(await screen.findByRole('button', { name: '발급' }));
    fireEvent.click(screen.getByRole('button', { name: '발급 확인' }));

    await waitFor(() =>
      expect(mockedAppApi.rotateAuthSecret).toHaveBeenCalledWith('app-1', {
        expected_version: 0,
        revoke_previous_immediately: false,
      }),
    );
    expect(await screen.findByDisplayValue('one-time-secret')).toBeVisible();
    expect(onSecretAvailable).toHaveBeenLastCalledWith('one-time-secret');

    fireEvent.click(screen.getByRole('button', { name: '교체' }));
    expect(screen.getByDisplayValue('one-time-secret')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: '취소' }));
    expect(screen.getByDisplayValue('one-time-secret')).toBeVisible();
    expect(onSecretAvailable).toHaveBeenLastCalledWith('one-time-secret');

    mockedAppApi.rotateAuthSecret.mockRejectedValueOnce(
      new Error('version conflict'),
    );
    fireEvent.click(screen.getByRole('button', { name: '교체' }));
    fireEvent.click(screen.getByRole('button', { name: '교체 확인' }));
    await waitFor(() =>
      expect(mockedAppApi.rotateAuthSecret).toHaveBeenCalledTimes(2),
    );
    expect(screen.getByDisplayValue('one-time-secret')).toBeVisible();
    expect(onSecretAvailable).toHaveBeenLastCalledWith('one-time-secret');

    expect(storageWrite).not.toHaveBeenCalled();
    storageWrite.mockRestore();
  });

  it('supports immediate previous-secret revocation with version CAS', async () => {
    mockedAppApi.getAuthSecretStatus.mockResolvedValue({
      configured: true,
      version: 4,
      rotation_enabled: true,
      rotated_at: '2026-07-17T02:00:00Z',
      previous_grace_active: false,
      previous_valid_until: null,
    });
    mockedAppApi.rotateAuthSecret.mockResolvedValue({
      secret: 'rotated-secret',
      version: 5,
      rotated_at: '2026-07-17T03:00:00Z',
      previous_grace_active: false,
      previous_valid_until: null,
    });

    render(<AppAuthSecretControl appId="app-1" />);

    fireEvent.click(await screen.findByRole('button', { name: '교체' }));
    fireEvent.click(screen.getByLabelText('이전 secret 즉시 폐기'));
    fireEvent.click(screen.getByRole('button', { name: '교체 확인' }));

    await waitFor(() =>
      expect(mockedAppApi.rotateAuthSecret).toHaveBeenCalledWith('app-1', {
        expected_version: 4,
        revoke_previous_immediately: true,
      }),
    );
  });

  it('does not automatically retry a failed rotation', async () => {
    mockedAppApi.getAuthSecretStatus
      .mockResolvedValueOnce({
        configured: true,
        version: 2,
        rotation_enabled: true,
        rotated_at: '2026-07-17T02:00:00Z',
        previous_grace_active: false,
        previous_valid_until: null,
      })
      .mockResolvedValueOnce({
        configured: true,
        version: 3,
        rotation_enabled: true,
        rotated_at: '2026-07-17T03:00:00Z',
        previous_grace_active: false,
        previous_valid_until: null,
      });
    mockedAppApi.rotateAuthSecret.mockRejectedValue(
      new Error('version conflict'),
    );

    render(<AppAuthSecretControl appId="app-1" />);
    fireEvent.click(await screen.findByRole('button', { name: '교체' }));
    fireEvent.click(screen.getByRole('button', { name: '교체 확인' }));

    await waitFor(() =>
      expect(mockedAppApi.getAuthSecretStatus).toHaveBeenCalledTimes(2),
    );
    expect(mockedAppApi.rotateAuthSecret).toHaveBeenCalledTimes(1);
    expect(screen.queryByLabelText('새 App secret')).not.toBeInTheDocument();
  });

  it('keeps issuance unavailable while the Gateway rollout gate is disabled', async () => {
    mockedAppApi.getAuthSecretStatus.mockResolvedValue({
      configured: false,
      version: 0,
      rotation_enabled: false,
      rotated_at: null,
      previous_grace_active: false,
      previous_valid_until: null,
    });

    render(<AppAuthSecretControl appId="app-1" />);

    expect(
      await screen.findByText(
        'Gateway 전환이 완료된 후 Secret을 발급할 수 있습니다.',
      ),
    ).toBeVisible();
    expect(screen.queryByRole('button', { name: '발급' })).not.toBeInTheDocument();
    expect(mockedAppApi.rotateAuthSecret).not.toHaveBeenCalled();
  });
});
