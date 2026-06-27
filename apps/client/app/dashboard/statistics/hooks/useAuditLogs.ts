import { useCallback, useEffect, useRef, useState } from 'react';
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

const localDateBoundaryToIso = (dateString: string, dayOffset = 0) => {
  const [year, month, day] = dateString.split('-').map(Number);
  return new Date(year, month - 1, day + dayOffset).toISOString();
};

export function useAuditLogs() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<AuditFilters>(defaultFilters);
  const requestSeqRef = useRef(0);

  const loadLogs = useCallback(async () => {
    const requestSeq = ++requestSeqRef.current;

    try {
      setLoading(true);
      setError(null);
      const params: Record<string, string | number> = {
        page: 1,
        limit: AUDIT_LOG_LIMIT,
      };
      if (filters.status !== 'all') params.status = filters.status;
      if (filters.startDate) {
        params.startAt = localDateBoundaryToIso(filters.startDate);
      }
      if (filters.endDate) {
        params.endAt = localDateBoundaryToIso(filters.endDate, 1);
      }

      const response = await apiClient.get<AuditLogListResponse>(
        '/users/me/audit-logs',
        { params },
      );
      if (requestSeq !== requestSeqRef.current) return;

      setLogs(response.data.items);
      setTotal(response.data.total);
    } catch {
      if (requestSeq !== requestSeqRef.current) return;

      setLogs([]);
      setTotal(0);
      setError('감사 로그를 불러오지 못했습니다.');
    } finally {
      if (requestSeq === requestSeqRef.current) {
        setLoading(false);
      }
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
