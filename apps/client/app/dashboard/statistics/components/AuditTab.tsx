import { useAuditLogs, AuditStatus } from '../hooks/useAuditLogs';
import {
  CheckCircle2,
  Clock,
  Filter,
  RefreshCcw,
  RotateCw,
  ShieldCheck,
  XCircle,
} from 'lucide-react';

const statusLabel: Record<AuditStatus, string> = {
  success: '성공',
  failure: '실패',
};

const categoryLabel: Record<string, string> = {
  action: '사용자 행동',
  data_change: '데이터 변경',
};

export const AuditTab = () => {
  const { logs, total, limit, loading, error, filters, setFilters, resetFilters, reload } =
    useAuditLogs();

  if (loading && logs.length === 0) {
    return (
      <div className="flex h-96 items-center justify-center">
        <div className="text-gray-500">감사 로그를 불러오는 중입니다...</div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col space-y-6">
      <div className="bg-white p-4 rounded-xl border border-gray-200 shadow-sm space-y-4">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-gray-500" />
            <div className="flex rounded-lg border border-gray-200 overflow-hidden">
              {(['all', 'success', 'failure'] as const).map((status) => (
                <button
                  key={status}
                  onClick={() => setFilters({ ...filters, status })}
                  className={`px-3 py-1.5 text-sm font-medium transition-colors ${
                    filters.status === status
                      ? 'bg-gray-800 text-white'
                      : 'bg-white text-gray-500 hover:bg-gray-50'
                  }`}
                >
                  {status === 'all' ? '전체' : statusLabel[status]}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-gray-500" />
            <input
              type="date"
              value={filters.startDate}
              onChange={(event) =>
                setFilters({ ...filters, startDate: event.target.value })
              }
              className="px-2 py-1.5 border border-gray-200 rounded-lg text-sm bg-white"
            />
            <span className="text-gray-400">~</span>
            <input
              type="date"
              value={filters.endDate}
              onChange={(event) =>
                setFilters({ ...filters, endDate: event.target.value })
              }
              className="px-2 py-1.5 border border-gray-200 rounded-lg text-sm bg-white"
            />
          </div>

          <button
            onClick={resetFilters}
            className="text-xs text-gray-400 underline hover:text-gray-600 flex items-center gap-1"
          >
            <RefreshCcw className="w-3 h-3" />
            초기화
          </button>

          <button
            onClick={reload}
            className="ml-auto p-2 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50"
            title="새로고침"
          >
            <RotateCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="flex-1 bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden flex flex-col">
        <div className="flex-1 overflow-y-auto">
          {error ? (
            <div className="flex h-64 flex-col items-center justify-center text-gray-400">
              <XCircle className="w-10 h-10 mb-2 opacity-30" />
              {error}
            </div>
          ) : logs.length > 0 ? (
            logs.map((log) => (
              <div
                key={log.id}
                className="p-4 border-b border-gray-100 flex items-start gap-3"
              >
                <div className="mt-1 flex-shrink-0">
                  {log.status === 'success' ? (
                    <CheckCircle2 className="w-5 h-5 text-green-500" />
                  ) : (
                    <XCircle className="w-5 h-5 text-red-500" />
                  )}
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex items-center flex-wrap gap-2">
                    <span className="text-xs font-bold text-gray-700 bg-gray-100 px-2 py-0.5 rounded-full border border-gray-200">
                      {categoryLabel[log.category] ?? log.category}
                    </span>
                    <span className="font-medium text-gray-900">
                      {log.action}
                    </span>
                    <span className="text-xs text-gray-500">
                      {new Date(log.occurred_at).toLocaleString()}
                    </span>
                  </div>

                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-500">
                    <span className="bg-gray-50 px-2 py-1 rounded border border-gray-100">
                      상태: {statusLabel[log.status]}
                    </span>
                    {log.target_type && (
                      <span className="bg-gray-50 px-2 py-1 rounded border border-gray-100">
                        대상: {log.target_type}
                        {log.target_id ? ` / ${log.target_id}` : ''}
                      </span>
                    )}
                    {log.request_id && (
                      <span className="bg-gray-50 px-2 py-1 rounded border border-gray-100">
                        request_id: {log.request_id}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            ))
          ) : (
            <div className="flex h-64 flex-col items-center justify-center text-gray-400">
              <ShieldCheck className="w-10 h-10 mb-2 opacity-30" />
              표시할 감사 로그가 없습니다.
            </div>
          )}
        </div>

        <div className="p-4 border-t border-gray-100 text-center text-xs text-gray-400">
          최근 {limit}건 중 {logs.length}건을 표시합니다. 전체 {total}건
        </div>
      </div>
    </div>
  );
};
