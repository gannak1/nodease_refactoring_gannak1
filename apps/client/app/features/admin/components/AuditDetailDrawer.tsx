'use client';

import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { adminApi } from '../api/adminApi';
import type { AuditLogDetailResponse } from '../types/AdminAudit';
import { auditActionLabel } from '../utils/auditActionLabel';

type AuditDetailDrawerProps = {
  auditLogId: string;
  actorName?: string | null;
  onClose: () => void;
};

const FOCUSABLE_SELECTOR =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

const formatMetadataValue = (value: unknown) =>
  typeof value === 'string' ? value : JSON.stringify(value);

export function AuditDetailDrawer({
  auditLogId,
  actorName,
  onClose,
}: AuditDetailDrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [detail, setDetail] = useState<AuditLogDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setError(null);
    adminApi
      .getAuditLogDetail(auditLogId)
      .then((data) => {
        if (!cancelled) setDetail(data);
      })
      .catch(() => {
        if (!cancelled) setError('감사 로그 상세를 불러오지 못했습니다.');
      });
    return () => {
      cancelled = true;
    };
  }, [auditLogId]);

  useEffect(() => {
    panelRef.current?.focus();
  }, []);

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape') {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== 'Tab' || !panelRef.current) return;
    const focusable = panelRef.current.querySelectorAll<HTMLElement>(
      FOCUSABLE_SELECTOR,
    );
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const label = detail ? auditActionLabel(detail.action) : null;
  const metadataEntries = detail ? Object.entries(detail.audit_metadata) : [];

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        className="absolute inset-0 bg-slate-950/30"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="감사 로그 상세"
        tabIndex={-1}
        onKeyDown={handleKeyDown}
        className="relative flex h-full w-full max-w-md flex-col overflow-y-auto bg-white shadow-xl outline-none"
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <h2 className="text-sm font-semibold text-slate-950">
            감사 로그 상세
          </h2>
          <button
            onClick={onClose}
            className="rounded p-1 text-slate-500 hover:bg-slate-100"
            aria-label="닫기"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {error && (
          <p className="px-5 py-6 text-sm text-red-700">{error}</p>
        )}
        {!error && !detail && (
          <p className="px-5 py-6 text-sm text-slate-500">불러오는 중...</p>
        )}
        {detail && (
          <dl className="flex flex-col gap-4 px-5 py-5 text-sm">
            <DetailField
              label="발생 시각"
              value={
                <time dateTime={detail.occurred_at}>
                  {new Date(detail.occurred_at).toLocaleString()}
                </time>
              }
            />
            <DetailField
              label="행위자"
              value={
                actorName ||
                detail.actor_id ||
                `${detail.actor_type} (id 없음)`
              }
            />
            <DetailField
              label="Action"
              value={
                <span className="flex flex-wrap items-center gap-2">
                  <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">
                    {detail.action}
                  </code>
                  {label && <span className="text-slate-700">{label}</span>}
                </span>
              }
            />
            <DetailField
              label="대상"
              value={
                detail.target_type
                  ? `${detail.target_type}${detail.target_id ? ` · ${detail.target_id}` : ''}`
                  : '-'
              }
            />
            <DetailField
              label="상태"
              value={
                <span
                  className={`w-fit rounded-md px-2 py-0.5 text-xs font-semibold ${
                    detail.status === 'failure'
                      ? 'bg-red-50 text-red-700'
                      : 'bg-emerald-50 text-emerald-700'
                  }`}
                >
                  {detail.status}
                </span>
              }
            />
            {metadataEntries.length > 0 && (
              <div>
                <dt className="text-xs font-semibold uppercase text-slate-500">
                  Metadata
                </dt>
                <dd className="mt-2 flex flex-col gap-1 rounded-md border border-slate-200 bg-slate-50 p-3">
                  {metadataEntries.map(([key, value]) => (
                    <div key={key} className="flex gap-2 text-xs">
                      <span className="shrink-0 font-medium text-slate-500">
                        {key}
                      </span>
                      <span className="break-all text-slate-800">
                        {formatMetadataValue(value)}
                      </span>
                    </div>
                  ))}
                </dd>
              </div>
            )}
          </dl>
        )}
      </div>
    </div>
  );
}

function DetailField({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase text-slate-500">
        {label}
      </dt>
      <dd className="mt-1 text-slate-900">{value}</dd>
    </div>
  );
}
