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

describe('AdminSummaryCards', () => {
  it('이번 달 비용을 USD 2자리로 표시하고 budget null은 예산 미설정으로 표시한다', async () => {
    mockedSummary.mockResolvedValue({
      month: '2026-07',
      total_cost: 123.456789,
      budget: null,
    });

    render(<AdminSummaryCards />);

    expect(await screen.findByText('$123.46')).toHaveClass('mt-2', 'text-2xl');
    expect(screen.getByText(/2026-07/)).toHaveClass('mt-2', 'text-sm');
    expect(screen.getByText('예산 미설정')).toBeInTheDocument();
  });

  it('요약 조회 실패 시 오류 상태를 표시한다', async () => {
    mockedSummary.mockRejectedValue(new Error('boom'));

    render(<AdminSummaryCards />);

    expect(
      await screen.findAllByText('요약을 불러오지 못했습니다'),
    ).toHaveLength(2);
  });
});
