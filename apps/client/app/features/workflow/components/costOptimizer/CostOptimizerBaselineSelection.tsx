'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  ArrowLeft,
  Clock3,
  GitCommitHorizontal,
  ListFilter,
  Sparkles,
} from 'lucide-react';
import { workflowApi } from '../../api/workflowApi';
import type {
  CostOptimizerBaselineListParams,
  CostOptimizerBaselineRow,
} from '../../types/Api';

interface CostOptimizerBaselineSelectionProps {
  workflowId: string;
  nodeId: string;
  onBaselineSelected: (baseline: CostOptimizerBaselineRow) => void;
  onClose: () => void;
}

const DEFAULT_LIMIT = 20;

const unavailableMessage =
  '입력 기록이 보관 기간 만료 또는 보안 정책으로 인해 이 실행 로그로는 A/B 테스트를 시작할 수 없습니다.';

const noBaselineMessage =
  '비교할 실행 로그가 없습니다. 먼저 테스트 실행을 완료해 주세요.';

const compactPreview = (value: string) => {
  if (!value) return '';
  const normalized = value.replace(/\s+/g, ' ').trim();
  return normalized.length > 140 ? `${normalized.slice(0, 140)}...` : normalized;
};

const parsePreview = (value: string): unknown => {
  const trimmed = value.trim();
  if (!trimmed || (!trimmed.startsWith('{') && !trimmed.startsWith('['))) {
    return value;
  }
  try {
    return JSON.parse(trimmed);
  } catch {
    return value;
  }
};

const collectPreviewParts = (
  value: unknown,
  prefix = '',
  parts: string[] = [],
): string[] => {
  if (parts.length >= 4) return parts;
  if (value === null || value === undefined) return parts;

  if (typeof value !== 'object') {
    const label = prefix.split('.').pop() || prefix;
    const text = String(value).replace(/\s+/g, ' ').trim();
    if (text) parts.push(label ? `${label}: ${text}` : text);
    return parts;
  }

  if (Array.isArray(value)) {
    value.slice(0, 3).forEach((item, index) => {
      collectPreviewParts(item, `${prefix}[${index}]`, parts);
    });
    return parts;
  }

  Object.entries(value as Record<string, unknown>)
    .slice(0, 8)
    .forEach(([key, item]) => {
      const nextPrefix = prefix ? `${prefix}.${key}` : key;
      collectPreviewParts(item, nextPrefix, parts);
    });
  return parts;
};

const readablePreview = (value: string) => {
  if (!value) return '';
  const parts = collectPreviewParts(parsePreview(value));
  return compactPreview(parts.length > 0 ? parts.join(' · ') : value);
};

const formatCost = (cost: number) => {
  if (!Number.isFinite(cost)) return '-';
  return `$${cost.toFixed(6).replace(/0+$/, '').replace(/\.$/, '')}`;
};

const formatLatency = (latencyMs: number) => {
  if (!Number.isFinite(latencyMs)) return '-';
  if (latencyMs < 1000) return `${latencyMs}ms`;
  return `${(latencyMs / 1000).toFixed(1)}s`;
};

const formatRunTime = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
};

export function CostOptimizerBaselineSelection({
  workflowId,
  nodeId,
  onBaselineSelected,
  onClose,
}: CostOptimizerBaselineSelectionProps) {
  const [mode, setMode] = useState<'initial' | 'picker'>('initial');
  const [rows, setRows] = useState<CostOptimizerBaselineRow[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [q, setQ] = useState('');
  const [model, setModel] = useState('');
  const [compareAvailable, setCompareAvailable] = useState('');
  const [sort, setSort] = useState('started_at_desc');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const listParams = useMemo<CostOptimizerBaselineListParams>(
    () => ({
      q: q || undefined,
      model: model || undefined,
      date_from: dateFrom ? `${dateFrom}T00:00:00` : undefined,
      date_to: dateTo ? `${dateTo}T23:59:59` : undefined,
      compare_available:
        compareAvailable === '' ? undefined : compareAvailable === 'true',
      sort,
      limit: DEFAULT_LIMIT,
      offset: 0,
    }),
    [compareAvailable, dateFrom, dateTo, model, q, sort],
  );

  const loadRows = useCallback(async () => {
    setIsLoading(true);
    setMessage(null);
    try {
      const response = await workflowApi.listCostOptimizerBaselines(
        workflowId,
        nodeId,
        listParams,
      );
      setRows(response.items);
    } finally {
      setIsLoading(false);
    }
  }, [listParams, nodeId, workflowId]);

  useEffect(() => {
    if (mode === 'picker') {
      void loadRows();
    }
  }, [loadRows, mode]);

  const handleLatest = async () => {
    setMode('picker');
    setIsLoading(true);
    setMessage(null);
    try {
      const response = await workflowApi.getCostOptimizerLatestBaseline(
        workflowId,
        nodeId,
      );
      onBaselineSelected(response.baseline);
    } catch {
      setMessage(noBaselineMessage);
    } finally {
      setIsLoading(false);
    }
  };

  const handleRowSelect = (row: CostOptimizerBaselineRow) => {
    if (!row.compare_available) {
      setMessage(unavailableMessage);
      return;
    }
    onBaselineSelected(row);
  };

  const resetToInitial = () => {
    setMode('initial');
    setMessage(null);
    setRows([]);
  };

  return (
    <section aria-label="비용 최적화 baseline 선택" className="space-y-4">
      <div>
        <h3 className="text-sm font-bold text-slate-950">
          A/B 테스트 기준 선택
        </h3>
        <p className="mt-1 text-xs leading-relaxed text-slate-500">
          같은 입력으로 비교할 A 기준 실행 로그를 선택합니다.
        </p>
      </div>

      {mode === 'initial' ? (
        <div className="flex flex-col gap-3">
          <button
            type="button"
            className="group w-full rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-left transition-colors hover:border-emerald-300 hover:bg-emerald-100"
            onClick={handleLatest}
          >
            <span className="flex items-center gap-2 text-sm font-bold text-emerald-800">
              <Sparkles className="h-4 w-4" />
              최신 실행 로그로 비교하기
            </span>
            <span className="mt-1 block text-xs leading-relaxed text-emerald-700">
              가장 최근의 비교 가능한 성공 로그를 바로 기준으로 사용합니다.
            </span>
          </button>
          <button
            type="button"
            className="group w-full rounded-lg border border-slate-200 bg-white p-4 text-left transition-colors hover:border-slate-300 hover:bg-slate-50"
            onClick={() => setMode('picker')}
          >
            <span className="flex items-center gap-2 text-sm font-bold text-slate-900">
              <ListFilter className="h-4 w-4" />
              이전 실행 로그 선택해서 비교하기
            </span>
            <span className="mt-1 block text-xs leading-relaxed text-slate-500">
              과거 로그를 검색하고 비용, 토큰, 결과를 확인한 뒤 선택합니다.
            </span>
          </button>
          <button
            type="button"
            className="w-full rounded-md px-3 py-2 text-left text-xs font-semibold text-slate-500 hover:bg-slate-50"
            onClick={onClose}
          >
            닫기
          </button>
        </div>
      ) : (
        <button
          type="button"
          className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs font-semibold text-slate-500 hover:bg-slate-50"
          onClick={resetToInitial}
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          나가기
        </button>
      )}

      {message ? (
        <p
          role="status"
          className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800"
        >
          {message}
        </p>
      ) : null}
      {isLoading ? (
        <p className="text-xs text-gray-500">실행 로그를 불러오는 중입니다.</p>
      ) : null}

      {mode === 'picker' ? (
        <div className="space-y-3">
          <div className="grid gap-2">
            <input
              aria-label="baseline 검색"
              className="w-full rounded-md border border-slate-200 px-3 py-2 text-xs outline-none focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100"
              type="search"
              value={q}
              onChange={(event) => setQ(event.target.value)}
              placeholder="입력 또는 출력 검색"
            />
            <label className="grid gap-1 text-[11px] font-semibold text-slate-500">
              <span>모델</span>
              <select
                className="rounded-md border border-slate-200 px-2 py-2 text-xs font-medium text-slate-700"
                value={model}
                onChange={(event) => setModel(event.target.value)}
              >
                <option value="">전체 모델</option>
                <option value="gpt-4.1-mini">GPT mini</option>
              </select>
            </label>
            <label className="grid gap-1 text-[11px] font-semibold text-slate-500">
              <span>비교 가능 여부</span>
              <select
                className="rounded-md border border-slate-200 px-2 py-2 text-xs font-medium text-slate-700"
                value={compareAvailable}
                onChange={(event) => setCompareAvailable(event.target.value)}
              >
                <option value="">전체</option>
                <option value="true">비교 가능</option>
                <option value="false">비교 불가</option>
              </select>
            </label>
            <label className="grid gap-1 text-[11px] font-semibold text-slate-500">
              <span>정렬</span>
              <select
                className="rounded-md border border-slate-200 px-2 py-2 text-xs font-medium text-slate-700"
                value={sort}
                onChange={(event) => setSort(event.target.value)}
              >
                <option value="started_at_desc">최신순</option>
                <option value="cost_desc">비용 높은순</option>
                <option value="cost_asc">비용 낮은순</option>
                <option value="tokens_desc">토큰 많은순</option>
                <option value="latency_desc">실행 시간 긴순</option>
              </select>
            </label>
            <div className="grid grid-cols-2 gap-2">
              <label className="grid gap-1 text-[11px] font-semibold text-slate-500">
                <span>시작일</span>
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(event) => setDateFrom(event.target.value)}
                  className="rounded-md border border-slate-200 px-2 py-2 text-xs font-medium text-slate-700"
                />
              </label>
              <label className="grid gap-1 text-[11px] font-semibold text-slate-500">
                <span>종료일</span>
                <input
                  type="date"
                  value={dateTo}
                  onChange={(event) => setDateTo(event.target.value)}
                  className="rounded-md border border-slate-200 px-2 py-2 text-xs font-medium text-slate-700"
                />
              </label>
            </div>
          </div>

          <div className="grid gap-2">
            {rows.map((row) => (
              <button
                key={row.baseline_id}
                type="button"
                className="block w-full rounded-lg border border-slate-200 bg-white p-3 text-left shadow-sm transition-colors hover:border-emerald-200 hover:bg-emerald-50/40"
                onClick={() => handleRowSelect(row)}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-bold text-slate-950">
                      {row.compare_available ? row.model : '모델 확인 불가'}
                    </div>
                    <div className="mt-1 flex items-center gap-1 text-[11px] text-slate-500">
                      <Clock3 className="h-3 w-3" />
                      {formatRunTime(row.run_started_at) || '실행 시간 없음'}
                    </div>
                  </div>
                  <span
                    className={
                      row.compare_available
                        ? 'shrink-0 rounded-full bg-emerald-50 px-2 py-1 text-[11px] font-bold text-emerald-700'
                        : 'shrink-0 rounded-full bg-amber-50 px-2 py-1 text-[11px] font-bold text-amber-700'
                    }
                  >
                    {row.compare_available
                      ? row.downstream_compatibility?.label || '검증 가능'
                      : '비교 불가'}
                  </span>
                </div>

                <div className="mt-3 flex flex-wrap gap-1.5 text-[11px] font-semibold text-slate-600">
                  <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-1">
                    <Activity className="h-3 w-3" />
                    Run {row.workflow_run_status}
                  </span>
                  <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-1">
                    <GitCommitHorizontal className="h-3 w-3" />
                    Node {row.node_status}
                  </span>
                  <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-1">
                    Trace {row.trace_available || row.has_trace ? '있음' : '없음'}
                  </span>
                </div>

                <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
                  <div className="rounded-md bg-slate-50 px-2 py-1">
                    <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                      Tokens
                    </div>
                    <div className="font-semibold text-slate-700">
                      {row.compare_available ? row.total_tokens : '-'}
                    </div>
                  </div>
                  <div className="rounded-md bg-slate-50 px-2 py-1">
                    <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                      Time
                    </div>
                    <div className="font-semibold text-slate-700">
                      {row.compare_available
                        ? formatLatency(row.latency_ms)
                        : '-'}
                    </div>
                  </div>
                  <div className="rounded-md bg-slate-50 px-2 py-1">
                    <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                      Cost
                    </div>
                    <div className="font-semibold text-slate-700">
                      {row.compare_available ? formatCost(row.cost) : '-'}
                    </div>
                  </div>
                </div>

                <div className="mt-3 space-y-2">
                  <div className="rounded-md border border-slate-100 bg-slate-50 px-3 py-2">
                    <div className="mb-1 text-[10px] font-bold uppercase tracking-wide text-slate-400">
                      입력
                    </div>
                    <p className="break-words text-xs leading-relaxed text-slate-700">
                      {readablePreview(row.input_preview) || '입력 미보관'}
                    </p>
                  </div>
                  <div className="rounded-md border border-slate-100 bg-white px-3 py-2">
                    <div className="mb-1 text-[10px] font-bold uppercase tracking-wide text-slate-400">
                      출력
                    </div>
                    <p className="break-words text-xs leading-relaxed text-slate-700">
                      {readablePreview(row.output_preview) || '출력 미보관'}
                    </p>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
