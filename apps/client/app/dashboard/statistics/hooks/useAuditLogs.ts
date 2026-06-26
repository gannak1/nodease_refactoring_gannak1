import { useCallback, useEffect, useMemo, useState } from 'react';
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
      const response = await apiClient.get<AuditLogListResponse>(
        '/users/me/audit-logs',
        { params: { page: 1, limit: AUDIT_LOG_LIMIT } },
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
  }, []);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  const filteredLogs = useMemo(() => {
    return logs.filter((log) => {
      const occurredAt = new Date(log.occurred_at).getTime();

      if (filters.status !== 'all' && log.status !== filters.status) {
        return false;
      }
      if (filters.startDate) {
        const start = new Date(`${filters.startDate}T00:00:00`).getTime();
        if (occurredAt < start) return false;
      }
      if (filters.endDate) {
        const end = new Date(`${filters.endDate}T23:59:59.999`).getTime();
        if (occurredAt > end) return false;
      }
      return true;
    });
  }, [logs, filters]);

  const resetFilters = () => setFilters(defaultFilters);

  return {
    logs: filteredLogs,
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
