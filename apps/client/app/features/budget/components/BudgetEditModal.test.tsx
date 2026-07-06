// BudgetEditModal(FR-051 관리자 예산 설정/수정 UI) 계약 테스트 — TDD red phase.
// docs/features/budget-management/component_spec.md:
// 초기값 로드(404 → 신규 폼), 0 이하 입력 차단, 저장 성공 시 refetch 콜백,
// 403/422 오류 표시.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('../api/budgetApi', () => ({
  budgetApi: {
    getWorkflowBudget: vi.fn(),
    upsertWorkflowBudget: vi.fn(),
  },
}));

import { budgetApi } from '../api/budgetApi';
import { BudgetEditModal } from './BudgetEditModal';

const mockedGet = vi.mocked(budgetApi.getWorkflowBudget);
const mockedUpsert = vi.mocked(budgetApi.upsertWorkflowBudget);

const axiosError = (status: number, data?: unknown) =>
  Object.assign(new Error(`HTTP ${status}`), {
    isAxiosError: true,
    response: { status, data },
  });

const existingBudget = {
  workflow_id: 'wf-1',
  workflow_name: '비싼 워크플로우',
  monthly_budget_usd: 100,
  is_enabled: true,
  current_month_cost: 92.345678,
  usage_ratio: 0.923457,
  status: 'at_risk' as const,
};

afterEach(() => {
  vi.resetAllMocks();
});

const renderModal = (
  overrides: Partial<{ onClose: () => void; onSaved: () => void }> = {},
) =>
  render(
    <BudgetEditModal
      workflowId="wf-1"
      workflowName="비싼 워크플로우"
      onClose={overrides.onClose ?? vi.fn()}
      onSaved={overrides.onSaved ?? vi.fn()}
    />,
  );

describe('BudgetEditModal 초기값', () => {
  it('기존 예산이 있으면 금액과 활성 상태를 채운다', async () => {
    mockedGet.mockResolvedValueOnce(existingBudget);

    renderModal();

    const input = await screen.findByLabelText('월 예산(USD)');
    await waitFor(() => expect(input).toHaveValue(100));
    expect(screen.getByRole('checkbox')).toBeChecked();
  });

  it('404(예산 미설정)면 빈 신규 폼을 보여준다', async () => {
    mockedGet.mockRejectedValueOnce(axiosError(404));

    renderModal();

    const input = await screen.findByLabelText('월 예산(USD)');
    expect(input).toHaveValue(null);
    expect(screen.getByRole('checkbox')).toBeChecked(); // 신규는 활성 기본
    expect(
      screen.queryByText('예산을 불러오지 못했습니다'),
    ).not.toBeInTheDocument();
  });
});

describe('BudgetEditModal 검증/저장', () => {
  it('0 이하 금액은 제출을 막고 서버를 호출하지 않는다', async () => {
    mockedGet.mockRejectedValueOnce(axiosError(404));
    renderModal();

    const input = await screen.findByLabelText('월 예산(USD)');
    fireEvent.change(input, { target: { value: '0' } });
    fireEvent.click(screen.getByRole('button', { name: '저장' }));

    expect(
      await screen.findByText('0보다 큰 금액을 입력해주세요'),
    ).toBeInTheDocument();
    expect(mockedUpsert).not.toHaveBeenCalled();
  });

  it('저장 성공 시 금액/활성 여부를 보내고 onSaved를 호출한다', async () => {
    mockedGet.mockResolvedValueOnce(existingBudget);
    mockedUpsert.mockResolvedValueOnce({
      ...existingBudget,
      monthly_budget_usd: 250,
    });
    const onSaved = vi.fn();
    renderModal({ onSaved });

    const input = await screen.findByLabelText('월 예산(USD)');
    await waitFor(() => expect(input).toHaveValue(100));
    fireEvent.change(input, { target: { value: '250' } });
    fireEvent.click(screen.getByRole('button', { name: '저장' }));

    await waitFor(() =>
      expect(mockedUpsert).toHaveBeenCalledWith('wf-1', {
        monthly_budget_usd: 250,
        is_enabled: true,
      }),
    );
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it('403이면 권한 안내를 표시하고 onSaved를 호출하지 않는다', async () => {
    mockedGet.mockRejectedValueOnce(axiosError(404));
    mockedUpsert.mockRejectedValueOnce(axiosError(403));
    const onSaved = vi.fn();
    renderModal({ onSaved });

    const input = await screen.findByLabelText('월 예산(USD)');
    fireEvent.change(input, { target: { value: '100' } });
    fireEvent.click(screen.getByRole('button', { name: '저장' }));

    expect(
      await screen.findByText('예산을 관리할 권한이 없습니다'),
    ).toBeInTheDocument();
    expect(onSaved).not.toHaveBeenCalled();
  });

  it('그 외 실패(422 등)는 저장 실패 안내를 표시한다', async () => {
    mockedGet.mockRejectedValueOnce(axiosError(404));
    mockedUpsert.mockRejectedValueOnce(axiosError(422));
    renderModal();

    const input = await screen.findByLabelText('월 예산(USD)');
    fireEvent.change(input, { target: { value: '100' } });
    fireEvent.click(screen.getByRole('button', { name: '저장' }));

    expect(
      await screen.findByText('예산 저장에 실패했습니다'),
    ).toBeInTheDocument();
  });
});
