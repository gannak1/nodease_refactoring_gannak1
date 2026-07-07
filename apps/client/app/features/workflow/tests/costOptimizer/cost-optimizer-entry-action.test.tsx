import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { CostOptimizerEntryAction } from '../../components/costOptimizer/CostOptimizerEntryAction';

const pushMock = vi.hoisted(() => vi.fn());
const getAvailabilityMock = vi.hoisted(() => vi.fn());

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock('../../api/workflowApi', () => ({
  workflowApi: {
    getCostOptimizerAvailability: getAvailabilityMock,
  },
}));

const writableAccess = {
  can_read: true,
  can_execute: true,
  can_write: true,
  can_manage: false,
};

describe('CostOptimizerEntryAction', () => {
  beforeEach(() => {
    pushMock.mockReset();
    getAvailabilityMock.mockReset();
    getAvailabilityMock.mockResolvedValue({
      available: true,
      permission: { can_compare: true },
    });
  });

  it('최적화 버튼은 모델 라우팅 최적화 화면으로 이동한다', async () => {
    render(
      <CostOptimizerEntryAction
        workflowId="workflow-1"
        nodeId="llm-1"
        workflowAccess={writableAccess}
        label="최적화"
        destination="model-routing"
      />,
    );

    const button = await screen.findByRole('button', { name: '최적화' });
    await waitFor(() => expect(button).not.toBeDisabled());
    fireEvent.click(button);

    expect(pushMock).toHaveBeenCalledWith('/modules/workflow-1/model-routing/llm-1');
  });

  it('비교 분석 테스트 버튼은 실행 로그 기반 A/B 비교 화면으로 이동한다', async () => {
    render(
      <CostOptimizerEntryAction
        workflowId="workflow-1"
        nodeId="llm-1"
        workflowAccess={writableAccess}
        label="비교 분석 테스트"
        destination="cost-optimizer"
      />,
    );

    const button = await screen.findByRole('button', {
      name: '비교 분석 테스트',
    });
    await waitFor(() => expect(button).not.toBeDisabled());
    fireEvent.click(button);

    expect(pushMock).toHaveBeenCalledWith('/modules/workflow-1/cost-optimizer/llm-1');
  });

  it('저장하지 않은 변경이 있으면 화면 이동 대신 저장 안내를 보여준다', async () => {
    render(
      <CostOptimizerEntryAction
        workflowId="workflow-1"
        nodeId="llm-1"
        workflowAccess={writableAccess}
        hasUnsavedChanges
        label="비교 분석 테스트"
        destination="cost-optimizer"
      />,
    );

    const button = await screen.findByRole('button', {
      name: '비교 분석 테스트',
    });
    await waitFor(() => expect(button).not.toBeDisabled());
    fireEvent.click(button);

    expect(pushMock).not.toHaveBeenCalled();
    expect(
      screen.getByText('현재 노드 설정을 저장한 뒤 비교를 시작할 수 있습니다.'),
    ).toBeInTheDocument();
  });
});
