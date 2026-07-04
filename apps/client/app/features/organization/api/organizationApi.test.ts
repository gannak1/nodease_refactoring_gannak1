import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/activeOrganization', () => ({
  activeOrganizationHeaders: vi.fn((organizationId: string | null) =>
    organizationId ? { 'X-Organization-Id': organizationId } : {},
  ),
}));

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    delete: vi.fn(),
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
  },
  publicApiClient: {
    post: vi.fn(),
  },
}));

import { apiClient } from '@/lib/apiClient';
import { organizationApi } from './organizationApi';

const mockedPost = vi.mocked(apiClient.post);

afterEach(() => {
  vi.resetAllMocks();
});

describe('organizationApi.submitPermissionRequest', () => {
  it('App 생성 권한 신청 payload를 전송한다', async () => {
    const response = {
      id: 'req-1',
      requested_permission: 'app.create',
      reason: 'workflow 생성이 필요합니다.',
      status: 'pending',
    };
    mockedPost.mockResolvedValueOnce({ data: response });

    const result = await organizationApi.submitPermissionRequest({
      reason: 'workflow 생성이 필요합니다.',
    });

    expect(mockedPost).toHaveBeenCalledWith('/permission-requests', {
      requested_permission: 'app.create',
      reason: 'workflow 생성이 필요합니다.',
    });
    expect(result).toEqual(response);
  });
});
