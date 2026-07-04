import { apiClient } from '@/lib/apiClient';
import type {
  AuditLogDetailResponse,
  AuditLogListResponse,
  AuditLogSearchFilters,
} from '../types/AdminAudit';
import type {
  PermissionRequestItem,
  PermissionRequestListResponse,
  PermissionRequestStatus,
} from '../types/AdminPermissionRequest';

export type AuditLogListParams = AuditLogSearchFilters & {
  page?: number;
  limit?: number;
};

const compactParams = (params: Record<string, unknown>) =>
  Object.fromEntries(
    Object.entries(params).filter(
      ([, value]) => value !== undefined && value !== null && value !== '',
    ),
  );

export const adminApi = {
  listAuditLogs: async (
    params: AuditLogListParams = {},
  ): Promise<AuditLogListResponse> => {
    const response = await apiClient.get('/admin/audit-logs', {
      params: compactParams(params),
    });
    return response.data;
  },

  getAuditLogDetail: async (
    auditLogId: string,
  ): Promise<AuditLogDetailResponse> => {
    const response = await apiClient.get(`/admin/audit-logs/${auditLogId}`);
    return response.data;
  },

  listPermissionRequests: async (params: {
    status?: PermissionRequestStatus;
    page?: number;
    limit?: number;
  } = {}): Promise<PermissionRequestListResponse> => {
    const response = await apiClient.get('/admin/permission-requests', {
      params: compactParams(params),
    });
    return response.data;
  },

  approvePermissionRequest: async (
    requestId: string,
  ): Promise<PermissionRequestItem> => {
    const response = await apiClient.post(
      `/admin/permission-requests/${requestId}/approve`,
    );
    return response.data;
  },

  rejectPermissionRequest: async (
    requestId: string,
  ): Promise<PermissionRequestItem> => {
    const response = await apiClient.post(
      `/admin/permission-requests/${requestId}/reject`,
    );
    return response.data;
  },
};
