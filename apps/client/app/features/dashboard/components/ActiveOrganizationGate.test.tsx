import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ActiveOrganizationGate from './ActiveOrganizationGate';
import {
  getStoredActiveOrganizationId,
  setActiveOrganizationId,
} from '@/lib/activeOrganization';
import { publicApiClient } from '@/lib/apiClient';

vi.mock('@/lib/apiClient', () => ({
  publicApiClient: {
    get: vi.fn(),
  },
}));

vi.mock('@/lib/activeOrganization', () => ({
  getStoredActiveOrganizationId: vi.fn(),
  setActiveOrganizationId: vi.fn(),
}));

const axiosError = (status: number) =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    response: { status },
  });

describe('ActiveOrganizationGate', () => {
  beforeEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
    vi.mocked(getStoredActiveOrganizationId).mockReturnValue(null);
  });

  it('gateway startup 중 502가 나면 조직 조회를 재시도한다', async () => {
    vi.mocked(publicApiClient.get)
      .mockRejectedValueOnce(axiosError(502))
      .mockResolvedValueOnce({
        data: [{ id: 'org-1', name: 'Nodease 데모 조직', is_manager: true }],
      });

    render(
      <ActiveOrganizationGate>
        <div>Dashboard ready</div>
      </ActiveOrganizationGate>,
    );

    expect(screen.getByText('조직 확인 중')).toBeTruthy();

    await waitFor(() => {
      expect(screen.getByText('Dashboard ready')).toBeTruthy();
    });
    expect(publicApiClient.get).toHaveBeenCalledTimes(2);
    expect(setActiveOrganizationId).toHaveBeenCalledWith('org-1');
  });

  it('401 같은 비일시 오류는 재시도하지 않는다', async () => {
    vi.mocked(publicApiClient.get).mockRejectedValueOnce(axiosError(401));

    render(
      <ActiveOrganizationGate>
        <div>Dashboard ready</div>
      </ActiveOrganizationGate>,
    );

    expect(await screen.findByText('조직을 확인할 수 없습니다')).toBeTruthy();
    expect(screen.getByText('Request failed with status code 401')).toBeTruthy();
    expect(publicApiClient.get).toHaveBeenCalledTimes(1);
  });
});
