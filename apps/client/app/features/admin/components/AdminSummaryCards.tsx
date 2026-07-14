'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { ArrowRight, DollarSign, PiggyBank } from 'lucide-react';
import { DashboardSummaryCard } from '../../dashboard/components/DashboardSurface';
import { adminApi } from '../api/adminApi';
import type {
  AdminBudgetSummary,
  AdminOrganizationSummary,
} from '../types/AdminUsage';

// 비용은 표시 직전에만 USD 2자리로 반올림한다 (FR-015).
const formatCost = (value: number) => `$${value.toFixed(2)}`;

type BudgetRiskCardProps = {
  budget: AdminBudgetSummary | null | undefined;
  failed: boolean;
};

function BudgetRiskCard({ budget, failed }: BudgetRiskCardProps) {
  const riskCount = budget
    ? budget.at_risk_count + budget.exceeded_count
    : null;

  return (
    <Link
      href="/dashboard/admin?tab=usage"
      aria-label="예산 위험 workflow 비용 탭에서 확인"
      className="group rounded-lg border border-slate-200 bg-white p-5 transition-colors hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-slate-500">
          예산 위험 workflow
        </p>
        <PiggyBank className="h-5 w-5 shrink-0 text-blue-600" />
      </div>

      {failed ? (
        <div className="mt-1">
          <p className="text-lg font-semibold text-slate-950">-</p>
          <p className="mt-1 text-xs text-slate-500">
            요약을 불러오지 못했습니다
          </p>
        </div>
      ) : budget === undefined ? (
        <p className="mt-1 text-lg font-semibold text-slate-950">집계 중</p>
      ) : budget === null ? (
        <div className="mt-1">
          <p className="text-lg font-semibold text-slate-950">예산 미설정</p>
          <p className="mt-1 text-xs text-slate-500">
            workflow별 월 예산을 설정해주세요
          </p>
        </div>
      ) : (
        <>
          <div className="mt-2 flex items-baseline gap-1.5">
            <p className="text-2xl font-semibold text-slate-950">
              {riskCount}개
            </p>
            <p className="text-sm font-semibold text-slate-950">위험</p>
          </div>

          <div
            className="mt-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 text-sm text-slate-700"
            aria-label="예산 위험 상태 요약"
          >
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              <span className="inline-flex items-center gap-1.5">
                <span
                  data-testid="budget-at-risk-dot"
                  aria-hidden="true"
                  className="h-2 w-2 rounded-full bg-amber-400"
                />
                예산 임박 {budget.at_risk_count}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span
                  aria-hidden="true"
                  className="h-2 w-2 rounded-full bg-red-500"
                />
                예산 초과 {budget.exceeded_count}
              </span>
            </div>
          </div>
        </>
      )}
    </Link>
  );
}

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
      <BudgetRiskCard budget={summary?.budget} failed={failed} />
    </div>
  );
}
