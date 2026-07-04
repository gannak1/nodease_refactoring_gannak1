import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    get: vi.fn(),
  },
}));

import { apiClient } from '@/lib/apiClient';
import { adminApi } from './adminApi';

const mockedGet = vi.mocked(apiClient.get);

afterEach(() => {
  vi.clearAllMocks();
});

describe('adminApi.listAuditLogs', () => {
  it('빈 필터 값은 query에서 제외하고 조회한다', async () => {
    mockedGet.mockResolvedValueOnce({ data: { total: 0, items: [] } });

    const result = await adminApi.listAuditLogs({
      page: 2,
      limit: 20,
      action: 'workflow.deploy',
      actorId: undefined,
      targetType: '',
    });

    expect(mockedGet).toHaveBeenCalledWith('/admin/audit-logs', {
      params: { page: 2, limit: 20, action: 'workflow.deploy' },
    });
    expect(result).toEqual({ total: 0, items: [] });
  });
});

describe('adminApi.getAuditLogDetail', () => {
  it('audit log id로 상세를 조회한다', async () => {
    const detail = {
      id: 'log-1',
      action: 'workflow.deploy',
      audit_metadata: { request_id: 'req-1' },
    };
    mockedGet.mockResolvedValueOnce({ data: detail });

    const result = await adminApi.getAuditLogDetail('log-1');

    expect(mockedGet).toHaveBeenCalledWith('/admin/audit-logs/log-1');
    expect(result).toEqual(detail);
  });
});
