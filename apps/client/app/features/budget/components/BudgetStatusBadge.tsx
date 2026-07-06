import type { BudgetUsageStatus } from '../types';

const statusLabel: Record<BudgetUsageStatus, string> = {
  normal: '정상',
  at_risk: '위험',
  exceeded: '초과',
};

const statusTone: Record<BudgetUsageStatus, string> = {
  normal: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  at_risk: 'border-amber-200 bg-amber-50 text-amber-700',
  exceeded: 'border-red-200 bg-red-50 text-red-700',
};

export function BudgetStatusBadge({
  status,
  usageRatio,
}: {
  status: BudgetUsageStatus;
  usageRatio?: number | null;
}) {
  return (
    <span
      className={`inline-flex w-fit items-center gap-1 rounded-md border px-2 py-1 text-xs font-semibold ${statusTone[status]}`}
    >
      <span>{statusLabel[status]}</span>
      {usageRatio !== undefined && usageRatio !== null && (
        <span>{Math.round(usageRatio * 100)}%</span>
      )}
    </span>
  );
}
