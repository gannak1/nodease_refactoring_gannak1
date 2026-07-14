import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import MyModulePage from '@/app/dashboard/mymodule/page';

const routerMock = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock('next/navigation', () => ({
  useRouter: () => routerMock,
}));

vi.mock('@/app/features/app/api/moduleOperationsApi', () => ({
  moduleOperationsApi: {
    listModuleOperations: vi.fn(),
  },
}));

vi.mock('@/lib/apiClient', () => ({
  apiClient: {
    get: vi.fn(),
  },
}));

vi.mock('@/app/features/workflow/api/workflowApi', () => ({
  workflowApi: {
    getDeploymentParameterOptimization: vi.fn(),
  },
}));

const { moduleOperationsApi } = await import(
  '@/app/features/app/api/moduleOperationsApi'
);
const { apiClient } = await import('@/lib/apiClient');
const { workflowApi } = await import('@/app/features/workflow/api/workflowApi');

describe('FR-014 내 모듈 자동 최적화 관리', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(moduleOperationsApi.listModuleOperations).mockResolvedValue([
      {
        app: {
          id: 'app-1',
          name: '예산 위험 티켓 처리',
          workflow_id: 'workflow-1',
          created_at: '2026-07-11T00:00:00.000Z',
          updated_at: '2026-07-11T00:00:00.000Z',
          budget_status: { status: 'at_risk', usage_ratio: 0.95 },
          operation_metrics: {
            current_month_cost: 10,
            projected_month_cost: 20,
            previous_month_cost: 8,
          },
        },
        deployment: { state: 'active', deployment_id: 'deployment-1' },
        deploymentState: 'active',
        latestRun: { state: 'success' },
        permissionStatus: 'loaded',
        permission: { can_deploy: true },
        permissionSources: [],
        dataQuality: {
          permissionSourcesUnavailable: false,
          latestRunUnavailable: false,
        },
      },
    ] as never);
    vi.mocked(apiClient.get).mockResolvedValue({
      data: { id: 'org-1', name: '데모 조직', is_manager: true },
    } as never);
    vi.mocked(
      workflowApi.getDeploymentParameterOptimization,
    ).mockResolvedValue({
      enabled: true,
      status: 'collecting',
      node_ids: ['llm-triage'],
      node_count: 1,
      collected_runs: 12,
      check_every_runs: 50,
      validation_spend_usd: 0,
      monthly_validation_budget_usd: 3,
    } as never);
  });

  afterEach(() => {
    cleanup();
  });

  it('배포된 workflow의 자동 최적화 관리는 해당 배포 설정을 불러온다', async () => {
    render(<MyModulePage />);

    fireEvent.click(await screen.findByRole('button', { name: '관리' }));

    await waitFor(() => {
      expect(workflowApi.getDeploymentParameterOptimization).toHaveBeenCalledWith(
        'deployment-1',
      );
    });

    const dialog = await screen.findByRole('dialog', {
      name: '자동 최적화 관리',
    });
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText('예산 위험 티켓 처리')).toBeInTheDocument();
    expect(routerMock.push).not.toHaveBeenCalled();
  });

  it('예산 사용률 숫자가 아닌 API status로 운영 목록의 위험 상태를 표시한다', async () => {
    vi.mocked(moduleOperationsApi.listModuleOperations).mockResolvedValueOnce([
      {
        app: {
          id: 'app-1',
          name: '서버 상태 기준 워크플로우',
          workflow_id: 'workflow-1',
          created_at: '2026-07-11T00:00:00.000Z',
          updated_at: '2026-07-11T00:00:00.000Z',
          budget_status: { status: 'normal', usage_ratio: 0.81 },
          operation_metrics: {
            current_month_cost: 10,
            projected_month_cost: 20,
            previous_month_cost: 8,
          },
        },
        deployment: { state: 'active', deployment_id: 'deployment-1' },
        deploymentState: 'active',
        latestRun: { state: 'success' },
        permissionStatus: 'loaded',
        permissionSources: [],
        dataQuality: {
          permissionSourcesUnavailable: false,
          latestRunUnavailable: false,
        },
      },
    ] as never);

    render(<MyModulePage />);

    const usage = (await screen.findAllByText('81%')).at(-1)!;
    expect(usage.parentElement).toHaveTextContent('정상');
    expect(usage.parentElement).not.toHaveTextContent('위험');
  });
});
