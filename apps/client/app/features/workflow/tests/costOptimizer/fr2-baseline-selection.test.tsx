import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const workflowApiMock = vi.hoisted(() => ({
  getCostOptimizerLatestBaseline: vi.fn(),
  listCostOptimizerBaselines: vi.fn(),
}));

vi.mock('../../api/workflowApi', () => ({
  workflowApi: workflowApiMock,
}));

const comparableBaseline = {
  baseline_id: 'baseline-1',
  baseline_source: 'workflow_node_run',
  source_workflow_node_run_id: 'baseline-1',
  workflow_run_id: 'run-1',
  workflow_id: 'workflow-1',
  node_id: 'llm-triage',
  run_started_at: '2026-07-04T00:00:00Z',
  workflow_run_status: 'success',
  node_status: 'success',
  model: 'gpt-4.1-mini',
  cost: 0.0012,
  total_tokens: 420,
  latency_ms: 1800,
  input_available: true,
  output_available: true,
  usage_available: true,
  trace_available: true,
  compare_available: true,
  unavailable_reason: null,
  input_preview: 'billing escalation',
  output_preview: 'enterprise response',
  has_trace: true,
  downstream_compatibility: {
    state: 'compatible',
    label: '검증 가능',
    message: 'baseline downstream is compatible',
  },
};

const nonComparableBaseline = {
  ...comparableBaseline,
  baseline_id: 'baseline-2',
  input_available: false,
  compare_available: false,
  unavailable_reason: 'input_payload_unavailable',
  input_preview: '',
  output_preview: 'retained output',
};

const loadBaselineSelection = async () => {
  const path = '../../components/costOptimizer/CostOptimizerBaselineSelection';
  const module = await import(/* @vite-ignore */ path);
  return module.CostOptimizerBaselineSelection;
};

describe('FR-002 Cost Optimizer baseline 선택', () => {
  beforeEach(() => {
    workflowApiMock.getCostOptimizerLatestBaseline.mockResolvedValue({
      baseline: comparableBaseline,
    });
    workflowApiMock.listCostOptimizerBaselines.mockResolvedValue({
      total: 2,
      limit: 20,
      offset: 0,
      items: [comparableBaseline, nonComparableBaseline],
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('baseline 선택 화면은 최신 실행 로그와 이전 실행 로그 선택 CTA를 제공한다', async () => {
    const CostOptimizerBaselineSelection = await loadBaselineSelection();

    render(
      <CostOptimizerBaselineSelection
        workflowId="workflow-1"
        nodeId="llm-triage"
        onBaselineSelected={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(
      screen.getByRole('button', { name: /최신 실행 로그로 비교하기/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /이전 실행 로그 선택해서 비교하기/i }),
    ).toBeInTheDocument();
  });

  it('최신 실행 로그 선택은 latest baseline API를 호출하고 선택 결과를 전달한다', async () => {
    const CostOptimizerBaselineSelection = await loadBaselineSelection();
    const onBaselineSelected = vi.fn();

    render(
      <CostOptimizerBaselineSelection
        workflowId="workflow-1"
        nodeId="llm-triage"
        onBaselineSelected={onBaselineSelected}
        onClose={vi.fn()}
      />,
    );

    fireEvent.click(
      screen.getByRole('button', { name: /최신 실행 로그로 비교하기/i }),
    );

    expect(
      screen.queryByRole('button', { name: /이전 실행 로그 선택해서 비교하기/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /나가기/i }),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(workflowApiMock.getCostOptimizerLatestBaseline).toHaveBeenCalledWith(
        'workflow-1',
        'llm-triage',
      );
      expect(onBaselineSelected).toHaveBeenCalledWith(comparableBaseline);
    });
  });

  it('비교 가능한 최신 실행 로그가 없으면 최신 선택 CTA를 사용할 수 없고 안내를 표시한다', async () => {
    workflowApiMock.getCostOptimizerLatestBaseline.mockRejectedValue({
      response: { status: 400, data: { detail: 'cost_optimizer.no_baseline' } },
    });
    const CostOptimizerBaselineSelection = await loadBaselineSelection();

    render(
      <CostOptimizerBaselineSelection
        workflowId="workflow-1"
        nodeId="llm-triage"
        onBaselineSelected={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    fireEvent.click(
      screen.getByRole('button', { name: /최신 실행 로그로 비교하기/i }),
    );

    await waitFor(() => {
      expect(
        screen.getByText(/비교할 실행 로그가 없습니다/i),
      ).toBeInTheDocument();
    });
  });

  it('이전 실행 로그 picker는 baseline row의 핵심 정보를 표시한다', async () => {
    const CostOptimizerBaselineSelection = await loadBaselineSelection();

    render(
      <CostOptimizerBaselineSelection
        workflowId="workflow-1"
        nodeId="llm-triage"
        onBaselineSelected={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    fireEvent.click(
      screen.getByRole('button', { name: /이전 실행 로그 선택해서 비교하기/i }),
    );

    expect(
      screen.queryByRole('button', { name: /최신 실행 로그로 비교하기/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /나가기/i }),
    ).toBeInTheDocument();

    await waitFor(() => {
      expect(workflowApiMock.listCostOptimizerBaselines).toHaveBeenCalledWith(
        'workflow-1',
        'llm-triage',
        expect.objectContaining({ limit: 20, offset: 0 }),
      );
    });
    expect(screen.getByText('gpt-4.1-mini')).toBeInTheDocument();
    expect(screen.getByText(/420/)).toBeInTheDocument();
    expect(screen.getByText(/0.0012/)).toBeInTheDocument();
    expect(screen.getByText(/billing escalation/)).toBeInTheDocument();
    expect(screen.getByText(/enterprise response/)).toBeInTheDocument();
    expect(screen.getByText(/검증 가능/)).toBeInTheDocument();
  });

  it('비교 불가 baseline row는 표시하되 선택해도 baseline selected를 호출하지 않는다', async () => {
    const CostOptimizerBaselineSelection = await loadBaselineSelection();
    const onBaselineSelected = vi.fn();

    render(
      <CostOptimizerBaselineSelection
        workflowId="workflow-1"
        nodeId="llm-triage"
        onBaselineSelected={onBaselineSelected}
        onClose={vi.fn()}
      />,
    );

    fireEvent.click(
      screen.getByRole('button', { name: /이전 실행 로그 선택해서 비교하기/i }),
    );

    await screen.findByText(/비교 불가/);
    fireEvent.click(screen.getByText(/retained output/));

    expect(onBaselineSelected).not.toHaveBeenCalled();
    expect(
      screen.getByText(/입력 기록이 보관 기간 만료 또는 보안 정책/i),
    ).toBeInTheDocument();
  });

  it('picker 검색과 필터는 baseline list API query로 전달된다', async () => {
    const CostOptimizerBaselineSelection = await loadBaselineSelection();

    render(
      <CostOptimizerBaselineSelection
        workflowId="workflow-1"
        nodeId="llm-triage"
        onBaselineSelected={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    fireEvent.click(
      screen.getByRole('button', { name: /이전 실행 로그 선택해서 비교하기/i }),
    );
    fireEvent.change(await screen.findByRole('searchbox'), {
      target: { value: 'billing' },
    });
    fireEvent.change(screen.getByLabelText(/모델/i), {
      target: { value: 'gpt-4.1-mini' },
    });
    fireEvent.change(screen.getByLabelText(/비교 가능 여부/i), {
      target: { value: 'true' },
    });
    fireEvent.change(screen.getByLabelText(/정렬/i), {
      target: { value: 'cost_desc' },
    });

    await waitFor(() => {
      expect(workflowApiMock.listCostOptimizerBaselines).toHaveBeenLastCalledWith(
        'workflow-1',
        'llm-triage',
        expect.objectContaining({
          q: 'billing',
          model: 'gpt-4.1-mini',
          compare_available: true,
          sort: 'cost_desc',
        }),
      );
    });
  });
});
