import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
  },
}));

import { apiClient } from '@/lib/apiClient';
import { externalActionCredentialApi } from './externalActionCredentialApi';

const credential = {
  id: 'credential-1',
  organization_id: 'organization-1',
  credential_name: '운영 Slack',
  provider: 'slack_api' as const,
  revision: 1,
  status: 'active' as const,
  created_at: '2026-07-19T00:00:00Z',
  updated_at: '2026-07-19T00:00:00Z',
  revoked_at: null,
};

describe('externalActionCredentialApi', () => {
  beforeEach(() => {
    vi.mocked(apiClient.get).mockReset();
    vi.mocked(apiClient.post).mockReset();
    vi.mocked(apiClient.patch).mockReset();
  });

  it('credential을 등록한다', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: credential });

    await expect(
      externalActionCredentialApi.create({
        credential_name: '운영 Slack',
        provider: 'slack_api',
        secret: 'test-only-placeholder',
      }),
    ).resolves.toEqual(credential);
    expect(apiClient.post).toHaveBeenCalledWith(
      '/external-action-credentials/credentials',
      {
        credential_name: '운영 Slack',
        provider: 'slack_api',
        secret: 'test-only-placeholder',
      },
    );
  });

  it('expected revision으로 이름 또는 secret을 교체한다', async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({
      data: { ...credential, revision: 2 },
    });

    await externalActionCredentialApi.update('credential-1', {
      expected_revision: 1,
      credential_name: '교체된 Slack',
      secret: 'replacement-placeholder',
    });

    expect(apiClient.patch).toHaveBeenCalledWith(
      '/external-action-credentials/credentials/credential-1',
      {
        expected_revision: 1,
        credential_name: '교체된 Slack',
        secret: 'replacement-placeholder',
      },
    );
  });

  it('expected revision으로 credential을 폐기한다', async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      data: { ...credential, revision: 2, status: 'revoked' },
    });

    await externalActionCredentialApi.revoke('credential-1', 1);

    expect(apiClient.post).toHaveBeenCalledWith(
      '/external-action-credentials/credentials/credential-1/revoke',
      { expected_revision: 1 },
    );
  });
});
