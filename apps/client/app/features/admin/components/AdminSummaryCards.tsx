'use client';

import { useEffect, useState } from 'react';
import { DollarSign, PiggyBank } from 'lucide-react';
import { DashboardSummaryCard } from '../../dashboard/components/DashboardSurface';
import { adminApi } from '../api/adminApi';
import type { AdminOrganizationSummary } from '../types/AdminUsage';

// 비용은 표시 직전에만 USD 2자리로 반올림한다 (FR-015).
const formatCost = (value: number) => `$${value.toFixed(2)}`;

export function AdminSummaryCards() {
  const [summary, setSummary] = useState<AdminOrganizationSummary | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    adminApi
      .getOrganizationSummary()
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const budgetValue =
    summary?.budget === undefined
      ? '-'
      : summary.budget === null
        ? '예산 미설정'
        : `${Math.round(summary.budget.ratio * 100)}%`;
  const budgetDescription = summary?.budget
    ? `위험 ${summary.budget.at_risk_count} · 초과 ${summary.budget.exceeded_count} · 예산 설정 ${summary.budget.budgeted_workflow_count}개`
    : '예산 관리 기능 확정 후 위험/초과 비율을 제공합니다';

  return (
    <div className="grid gap-3 md:grid-cols-2">
      <DashboardSummaryCard
        label="이번 달 LLM 비용"
        value={
          summary ? formatCost(summary.total_cost) : failed ? '-' : '집계 중'
        }
        icon={DollarSign}
        description={
          summary
            ? `${summary.month} · USD · KST 달력 월 기준`
            : failed
              ? '요약을 불러오지 못했습니다'
              : undefined
        }
      />
      <DashboardSummaryCard
        label="예산 위험 workflow"
        value={budgetValue}
        icon={PiggyBank}
        description={budgetDescription}
      />
    </div>
  );
}
