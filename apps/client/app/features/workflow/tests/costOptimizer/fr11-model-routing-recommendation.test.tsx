import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type {
  CostOptimizerBaselineRow,
  CostOptimizerExperimentSummary,
} from '../../types/Api';

const workflowApiMock = vi.hoisted(() => ({
  getCostOptimizerLatestBaseline: vi.fn(),
  listCostOptimizerExperiments: vi.fn(),
}));

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
}));

vi.mock('../../api/workflowApi', () => ({
  workflowApi: workflowApiMock,
}));

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'workflow-1', nodeId: 'llm-1' }),
  useRouter: () => routerMock,
  useSearchParams: () => new URLSearchParams(),
}));

const loadModelRoutingPage = async () => {
  vi.resetModules();
  const module = await import('@/app/modules/[id]/model-routing/[nodeId]/page');
  return module.default;
};

const baseline = (
  overrides: Partial<CostOptimizerBaselineRow> = {},
): CostOptimizerBaselineRow => ({
  baseline_id: 'baseline-1',
  baseline_source: 'workflow_node_runs',
  source_workflow_node_run_id: 'node-run-1',
  workflow_run_id: 'run-1',
  workflow_id: 'workflow-1',
  node_id: 'llm-1',
  run_started_at: '2026-07-06T10:00:00.000Z',
  workflow_run_status: 'success',
  node_status: 'success',
  model: 'gpt-4.1',
  cost: 0.01,
  total_tokens: 1000,
  latency_ms: 3000,
  input_available: true,
  output_available: true,
  usage_available: true,
  trace_available: true,
  compare_available: true,
  input_preview: '문의 내용을 분류해줘',
  output_preview: 'enterprise 문의입니다',
  has_trace: true,
  ...overrides,
});

const experiment = (
  overrides: Partial<CostOptimizerExperimentSummary> = {},
): CostOptimizerExperimentSummary => ({
  experiment_id: 'experiment-1',
  workflow_id: 'workflow-1',
  node_id: 'llm-1',
  baseline_node_run_id: 'node-run-1',
  baseline_workflow_run_id: 'run-1',
  status: 'completed',
  created_at: '2026-07-06T10:05:00.000Z',
  baseline_summary: {
    baseline_id: 'baseline-1',
    model: 'gpt-4.1',
    cost: 0.01,
    total_tokens: 1000,
    latency_ms: 3000,
  },
  candidates: [
    {
      candidate_id: 'candidate-1',
      name: 'mini 검증',
      status: 'success',
      model_id: 'gpt-4.1-mini',
      total_cost: 0.002,
      total_tokens: 600,
      latency_ms: 1800,
      schema_status: 'pass',
      downstream_state: 'compatible',
      created_at: '2026-07-06T10:06:00.000Z',
    },
  ],
  ...overrides,
});

describe('FR-011 모델 라우팅 추천 화면', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    workflowApiMock.getCostOptimizerLatestBaseline.mockResolvedValue({
      baseline: baseline(),
    });
    workflowApiMock.listCostOptimizerExperiments.mockResolvedValue({
      total: 0,
      limit: 50,
      offset: 0,
      items: [],
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('전략을 선택하기 전에는 추천 모델을 단정하지 않는다', async () => {
    const ModelRoutingPage = await loadModelRoutingPage();

    render(<ModelRoutingPage />);

    expect(await screen.findByText('라우팅 전략을 선택하세요')).toBeInTheDocument();
    expect(screen.queryByText('적용 검토 가능한 추천 후보가 있습니다')).toBeNull();
    expect(
      screen.getByRole('button', { name: /비용 우선/ }),
    ).toBeInTheDocument();
  });

  it('운영 로그만 있고 대체 모델 후보 실험이 없으면 후보 검증 필요 상태로 멈춘다', async () => {
    const ModelRoutingPage = await loadModelRoutingPage();

    render(<ModelRoutingPage />);

    fireEvent.click(await screen.findByRole('button', { name: /비용 우선/ }));

    expect(await screen.findByText('후보 검증이 먼저 필요합니다')).toBeInTheDocument();
    expect(
      screen.getByText(/대체 모델이 같은 입력에서 품질을 유지하는지는 후보 실험을 실행해야/),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '후보 실험 실행' }));

    expect(routerMock.push).toHaveBeenCalledWith(
      '/modules/workflow-1/cost-optimizer/llm-1',
    );
  });

  it('성공한 저비용 후보 실험이 있으면 적용 검토 가능한 추천을 보여준다', async () => {
    workflowApiMock.listCostOptimizerExperiments.mockResolvedValue({
      total: 1,
      limit: 50,
      offset: 0,
      items: [experiment()],
    });
    const ModelRoutingPage = await loadModelRoutingPage();

    render(<ModelRoutingPage />);

    fireEvent.click(await screen.findByRole('button', { name: /비용 우선/ }));

    expect(
      await screen.findByText('적용 검토 가능한 추천 후보가 있습니다'),
    ).toBeInTheDocument();
    expect(screen.getAllByText('gpt-4.1-mini').length).toBeGreaterThan(0);
    expect(screen.getByText('80%')).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole('button', { name: 'A/B 결과에서 적용 검토' }),
    );

    expect(routerMock.push).toHaveBeenCalledWith(
      '/modules/workflow-1/cost-optimizer/llm-1',
    );
  });

  it('속도 우선 전략은 품질 gate를 통과한 후보 중 latency 개선을 우선한다', async () => {
    workflowApiMock.listCostOptimizerExperiments.mockResolvedValue({
      total: 1,
      limit: 50,
      offset: 0,
      items: [
        experiment({
          candidates: [
            {
              candidate_id: 'cheap-but-slow',
              status: 'success',
              model_id: 'gpt-4.1-mini',
              total_cost: 0.001,
              total_tokens: 500,
              latency_ms: 4500,
              schema_status: 'pass',
              downstream_state: 'compatible',
            },
            {
              candidate_id: 'fast',
              status: 'success',
              model_id: 'gpt-4o-mini',
              total_cost: 0.004,
              total_tokens: 700,
              latency_ms: 1200,
              schema_status: 'pass',
              downstream_state: 'compatible',
            },
          ],
        }),
      ],
    });
    const ModelRoutingPage = await loadModelRoutingPage();

    render(<ModelRoutingPage />);

    fireEvent.click(await screen.findByRole('button', { name: /속도 우선/ }));

    await waitFor(() => {
      expect(screen.getAllByText('gpt-4o-mini').length).toBeGreaterThan(0);
    });
    expect(screen.getByText('-1.8s')).toBeInTheDocument();
  });

  it('운영 baseline이 없으면 대체 후보를 추천하지 않고 분석 불가로 표시한다', async () => {
    workflowApiMock.getCostOptimizerLatestBaseline.mockRejectedValue(
      new Error('not found'),
    );
    const ModelRoutingPage = await loadModelRoutingPage();

    render(<ModelRoutingPage />);

    fireEvent.click(await screen.findByRole('button', { name: /자동 균형/ }));

    expect(await screen.findByText('분석할 운영 로그가 없습니다')).toBeInTheDocument();
  });
});
