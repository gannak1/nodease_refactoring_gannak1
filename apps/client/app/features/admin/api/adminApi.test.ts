import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

import { apiClient } from '@/lib/apiClient';
import { adminApi } from './adminApi';

const mockedGet = vi.mocked(apiClient.get);
const mockedPost = vi.mocked(apiClient.post);

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

describe('adminApi.listPermissionRequests', () => {
  it('status와 pagination으로 권한 신청 목록을 조회한다', async () => {
    mockedGet.mockResolvedValueOnce({ data: { total: 0, items: [] } });

    await adminApi.listPermissionRequests({
      status: 'pending',
      page: 1,
      limit: 20,
    });

    expect(mockedGet).toHaveBeenCalledWith('/admin/permission-requests', {
      params: { status: 'pending', page: 1, limit: 20 },
    });
  });
});

describe('adminApi permission request actions', () => {
  it('승인/거절 action endpoint를 호출한다', async () => {
    mockedPost.mockResolvedValue({ data: { id: 'req-1' } });

    await adminApi.approvePermissionRequest('req-1');
    await adminApi.rejectPermissionRequest('req-2');

    expect(mockedPost).toHaveBeenCalledWith(
      '/admin/permission-requests/req-1/approve',
    );
    expect(mockedPost).toHaveBeenCalledWith(
      '/admin/permission-requests/req-2/reject',
    );
  });
});

describe('adminApi.listWorkflowUsage', () => {
  it('기간 미지정 시 기간 파라미터 없이 조회한다', async () => {
    mockedGet.mockResolvedValueOnce({
      data: { total: 0, period: {}, items: [] },
    });

    await adminApi.listWorkflowUsage({ page: 1, limit: 20 });

    expect(mockedGet).toHaveBeenCalledWith('/admin/usage/workflows', {
      params: { page: 1, limit: 20 },
    });
  });
});

describe('adminApi.getOrganizationSummary', () => {
  it('조직 월간 요약을 조회한다', async () => {
    const summary = { month: '2026-07', total_cost: 1.5, budget: null };
    mockedGet.mockResolvedValueOnce({ data: summary });

    const result = await adminApi.getOrganizationSummary();

    expect(mockedGet).toHaveBeenCalledWith('/admin/summary');
    expect(result).toEqual(summary);
  });
});
