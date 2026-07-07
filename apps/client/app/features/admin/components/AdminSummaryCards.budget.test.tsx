// AdminSummaryCards 예산 카드 실데이터(FR-015) 계약 테스트 — TDD red phase.
// docs/features/budget-management/api_spec.md GET /admin/summary 확장:
// budget 블록(budgeted_workflow_count/at_risk_count/exceeded_count/ratio)을
// 실제 데이터로 표시한다. null은 기존 "예산 미설정" 유지(기존 테스트가 보증).
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

vi.mock('../api/adminApi', () => ({
  adminApi: {
    getOrganizationSummary: vi.fn(),
  },
}));

import { adminApi } from '../api/adminApi';
import { AdminSummaryCards } from './AdminSummaryCards';

const mockedSummary = vi.mocked(adminApi.getOrganizationSummary);

afterEach(() => {
  vi.clearAllMocks();
});

describe('AdminSummaryCards 예산 카드', () => {
  it('budget 블록이 있으면 위험/초과 비율과 건수를 표시한다', async () => {
    mockedSummary.mockResolvedValue({
      month: '2026-07',
      total_cost: 123.456789,
      budget: {
        budgeted_workflow_count: 5,
        at_risk_count: 1,
        exceeded_count: 1,
        ratio: 0.4,
      },
    });

    render(<AdminSummaryCards />);

    // 위험/초과 비율은 % 정수 표시 (표시 직전 1회 반올림)
    expect(await screen.findByText('40%')).toBeInTheDocument();
    expect(screen.getByText(/위험 1/)).toBeInTheDocument();
    expect(screen.getByText(/초과 1/)).toBeInTheDocument();
    expect(screen.getByText(/예산 설정 5개/)).toBeInTheDocument();
    expect(screen.queryByText('예산 미설정')).not.toBeInTheDocument();
  });
});
