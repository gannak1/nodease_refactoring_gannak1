import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import MyModulePage from '@/app/dashboard/mymodule/page';

const routerMock = vi.hoisted(() => ({ push: vi.fn() }));
const sharedModalState = vi.hoisted(() => ({
  props: null as null | {
    workflowId: string;
    workflowName?: string;
    llmNodes: Array<{ id: string; candidateDraft?: unknown }>;
  },
}));

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
    getDraftWorkflow: vi.fn(),
    getCostOptimizerParameterRecommendations: vi.fn(),
  },
}));

vi.mock(
  '@/app/features/workflow/components/costOptimizer/OptimizationRecommendationModal',
  () => ({
    OptimizationRecommendationModal: (props: {
      workflowId: string;
      workflowName?: string;
      llmNodes: Array<{ id: string; candidateDraft?: unknown }>;
    }) => {
      sharedModalState.props = props;
      return <div data-testid="shared-optimization-recommendation-modal" />;
    },
  }),
);

const { moduleOperationsApi } = await import(
  '@/app/features/app/api/moduleOperationsApi'
);
const { apiClient } = await import('@/lib/apiClient');
const { workflowApi } = await import('@/app/features/workflow/api/workflowApi');

describe('FR-013 내 모듈 추천 모달 연결', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sharedModalState.props = null;
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
    vi.mocked(workflowApi.getDraftWorkflow).mockResolvedValue({
      graph: {
        nodes: [
          {
            id: 'llm-triage',
            type: 'llmNode',
            data: {
              title: '티켓 처리 판단',
              model_id: 'gpt-4.1',
              parameters: { max_tokens: 1200, temperature: 0.2 },
            },
          },
        ],
      },
    } as never);
    vi.mocked(
      workflowApi.getCostOptimizerParameterRecommendations,
    ).mockResolvedValue({
      recommendations: [],
      warnings: [],
    } as never);
  });

  afterEach(() => {
    cleanup();
  });

  it('예산 위험 workflow의 최적화 권장은 공유 inline 검증 모달에 현재 LLM 설정을 전달한다', async () => {
    render(<MyModulePage />);

    fireEvent.click(await screen.findByRole('button', { name: '최적화 권장' }));

    await waitFor(() => {
      expect(
        screen.getByTestId('shared-optimization-recommendation-modal'),
      ).toBeInTheDocument();
    });

    expect(sharedModalState.props).toMatchObject({
      workflowId: 'workflow-1',
      workflowName: '예산 위험 티켓 처리',
      llmNodes: [
        {
          id: 'llm-triage',
          candidateDraft: expect.objectContaining({
            model_id: 'gpt-4.1',
            max_tokens: 1200,
          }),
        },
      ],
    });
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

    const usage = (await screen.findAllByText('81%')).at(-1);
    expect(usage).toBeDefined();
    expect(usage.parentElement).toHaveTextContent('정상');
    expect(usage.parentElement).not.toHaveTextContent('위험');
    expect(
      screen.queryByRole('button', { name: '최적화 권장' }),
    ).not.toBeInTheDocument();
  });
});
