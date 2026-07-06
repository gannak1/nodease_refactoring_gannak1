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
import { publicApiClient } from '@/lib/apiClient';
import { organizationApi } from './organizationApi';

const mockedPost = vi.mocked(apiClient.post);
const mockedPublicPost = vi.mocked(publicApiClient.post);

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

describe('organizationApi.declineInvitation', () => {
  it('현재 사용자의 초대 거절 endpoint를 호출한다', async () => {
    const response = {
      id: 'membership-1',
      organization_id: 'org-1',
      user_id: 'user-1',
      membership_state: 'removed',
    };
    mockedPublicPost.mockResolvedValueOnce({ data: response });

    const result = await organizationApi.declineInvitation('org-1');

    expect(mockedPublicPost).toHaveBeenCalledWith(
      '/organizations/org-1/members/me/decline',
    );
    expect(result).toEqual(response);
  });
});
