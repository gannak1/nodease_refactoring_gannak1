import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
}));

const workflowApiMock = vi.hoisted(() => ({
  getDraftWorkflow: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'workflow-1', nodeId: 'llm-1' }),
  useRouter: () => routerMock,
}));

vi.mock('../../api/workflowApi', () => ({
  workflowApi: workflowApiMock,
}));

vi.mock('../../components/costOptimizer/CostOptimizerBaselineSelection', () => ({
  CostOptimizerBaselineSelection: ({
    onBaselineSelected,
  }: {
    onBaselineSelected: (baseline: Record<string, unknown>) => void;
  }) => (
    <button
      type="button"
      onClick={() =>
        onBaselineSelected({
          baseline_id: 'baseline-1',
          model: 'gpt-4.1',
          cost: 0.0012,
          total_tokens: 249,
          latency_ms: 1600,
          input_preview: 'baseline input',
          output_preview: 'baseline output',
          has_trace: true,
          node_options: {
            model_id: 'gpt-4.1',
            provider: 'openai',
            system_prompt: 'baseline system',
            user_prompt: 'baseline user',
            assistant_prompt: '',
            parameters: { max_tokens: 800, temperature: 0.2 },
            knowledgeBases: [],
          },
        })
      }
    >
      테스트 baseline 선택
    </button>
  ),
}));

vi.mock('../../components/costOptimizer/NodeSettingsComparisonPanel', () => ({
  NodeSettingsComparisonPanel: ({ title }: { title: string }) => (
    <section aria-label={title}>{title}</section>
  ),
}));

const loadPlaygroundPage = async () => {
  const module = await import(
    '@/app/modules/[id]/cost-optimizer/[nodeId]/page'
  );
  return module.default;
};

describe('FR-006 Cost Optimizer playground mode switch', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    global.ResizeObserver = class ResizeObserver {
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = vi.fn();
    };
    workflowApiMock.getDraftWorkflow.mockResolvedValue({
      nodes: [
        {
          id: 'llm-1',
          type: 'llmNode',
          position: { x: 0, y: 0 },
          data: {
            title: '티켓 처리 판단',
            provider: 'openai',
            model_id: 'gpt-4.1',
            system_prompt: 'system',
            user_prompt: 'user',
            assistant_prompt: '',
            referenced_variables: [],
            parameters: { max_tokens: 800, temperature: 0.2 },
            knowledgeBases: [],
          },
        },
      ],
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('기본 모드는 실험 설정이고 결과 분석 모드로 전환할 수 있다', async () => {
    const CostOptimizerPlaygroundPage = await loadPlaygroundPage();

    render(<CostOptimizerPlaygroundPage />);

    await waitFor(() => {
      expect(workflowApiMock.getDraftWorkflow).toHaveBeenCalledWith(
        'workflow-1',
      );
    });

    expect(
      screen.getByRole('button', { name: '실험 설정' }),
    ).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('B candidate')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '결과 분석' }));

    expect(
      screen.getByRole('button', { name: '결과 분석' }),
    ).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('비교 리포트')).toBeInTheDocument();
    expect(screen.getByText(/B 실행 후 결과 분석이 표시됩니다/)).toBeInTheDocument();
  });
});
