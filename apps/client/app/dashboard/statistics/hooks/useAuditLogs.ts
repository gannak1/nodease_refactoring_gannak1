import { useCallback, useEffect, useState } from 'react';
import { apiClient } from '@/lib/apiClient';

export type AuditStatus = 'success' | 'failure';

export interface AuditLog {
  id: string;
  occurred_at: string;
  actor_id: string | null;
  actor_type: 'user' | 'admin' | 'system';
  category: 'action' | 'data_change';
  action: string;
  target_type: string | null;
  target_id: string | null;
  status: AuditStatus;
  request_id: string | null;
}

interface AuditLogListResponse {
  total: number;
  items: AuditLog[];
}

export interface AuditFilters {
  status: 'all' | AuditStatus;
  startDate: string;
  endDate: string;
}

const defaultFilters: AuditFilters = {
  status: 'all',
  startDate: '',
  endDate: '',
};
const AUDIT_LOG_LIMIT = 50;

export function useAuditLogs() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<AuditFilters>(defaultFilters);

  const loadLogs = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const params: Record<string, string | number> = {
        page: 1,
        limit: AUDIT_LOG_LIMIT,
      };
      if (filters.status !== 'all') params.status = filters.status;
      if (filters.startDate) params.startDate = filters.startDate;
      if (filters.endDate) params.endDate = filters.endDate;

      const response = await apiClient.get<AuditLogListResponse>(
        '/users/me/audit-logs',
        { params },
      );
      setLogs(response.data.items);
      setTotal(response.data.total);
    } catch {
      setLogs([]);
      setTotal(0);
      setError('감사 로그를 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  const resetFilters = () => setFilters(defaultFilters);

  return {
    logs,
    total,
    limit: AUDIT_LOG_LIMIT,
    loading,
    error,
    filters,
    setFilters,
    resetFilters,
    reload: loadLogs,
  };
}
