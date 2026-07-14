import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { DeploymentFlowModal } from './DeploymentFlowModal';

afterEach(cleanup);

describe('DeploymentFlowModal', () => {
  it('sends the selected automatic optimization settings when deploying', async () => {
    const onDeploy = vi.fn().mockResolvedValue({ success: true, version: 1 });

    render(
      <DeploymentFlowModal
        isOpen
        onClose={vi.fn()}
        deploymentType="api"
        llmNodes={[{ id: 'llm-1', title: '티켓 분류' }]}
        onDeploy={onDeploy}
      />,
    );

    expect(screen.getByText('REST API 배포')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: '다음' }));

    expect(screen.getByText('운영 비용 자동 최적화')).toBeVisible();
    fireEvent.click(
      screen.getByRole('switch', { name: '운영 비용 자동 최적화 사용' }),
    );
    fireEvent.change(screen.getByRole('slider', { name: '자동 점검 주기' }), {
      target: { value: '80' },
    });
    fireEvent.change(screen.getByRole('slider', { name: '월간 검증 예산' }), {
      target: { value: '4.5' },
    });
    fireEvent.click(screen.getByRole('button', { name: '배포하기' }));

    await waitFor(() =>
      expect(onDeploy).toHaveBeenCalledWith('', {
        enabled: true,
        node_ids: ['llm-1'],
        check_every_runs: 80,
        monthly_validation_budget_usd: 4.5,
      }),
    );
  });
});
