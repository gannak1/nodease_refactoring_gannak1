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
    onClose,
  }: {
    onBaselineSelected: (baseline: Record<string, unknown>) => void;
    onClose: () => void;
  }) => (
    <div>
      <button
        type="button"
        onClick={() =>
          onBaselineSelected({
            baseline_id: 'baseline-1',
            model: 'gpt-4.1',
            cost: 0.0012,
            total_tokens: 249,
            latency_ms: 1600,
            input_preview:
              'baseline input '.repeat(20) + '끝까지 보여야 하는 입력 문장',
            output_preview:
              'baseline output '.repeat(20) + '끝까지 보여야 하는 출력 문장',
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
      <button type="button" onClick={onClose}>
        닫기
      </button>
    </div>
  ),
}));

vi.mock('../../components/costOptimizer/NodeSettingsComparisonPanel', () => ({
  NodeSettingsComparisonPanel: ({
    title,
    hideTitle,
  }: {
    title: string;
    hideTitle?: boolean;
  }) => <section aria-label={title}>{hideTitle ? '설정 패널' : title}</section>,
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

  it('baseline 선택 전에는 B candidate와 Inspector를 열지 않는다', async () => {
    const CostOptimizerPlaygroundPage = await loadPlaygroundPage();

    render(<CostOptimizerPlaygroundPage />);

    await waitFor(() => {
      expect(workflowApiMock.getDraftWorkflow).toHaveBeenCalledWith(
        'workflow-1',
      );
    });

    expect(screen.getByRole('button', { name: '테스트 baseline 선택' }))
      .toBeInTheDocument();
    expect(screen.queryByText('B candidate')).not.toBeInTheDocument();
    expect(screen.queryByText('Inspector')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '결과 분석' }),
    ).not.toBeInTheDocument();
  });

  it('닫기와 워크플로우로 가기는 대상 노드 상세 화면으로 이동한다', async () => {
    const CostOptimizerPlaygroundPage = await loadPlaygroundPage();

    render(<CostOptimizerPlaygroundPage />);

    await waitFor(() => {
      expect(workflowApiMock.getDraftWorkflow).toHaveBeenCalledWith(
        'workflow-1',
      );
    });

    fireEvent.click(screen.getByRole('button', { name: '닫기' }));
    expect(routerMock.push).toHaveBeenCalledWith(
      '/modules/workflow-1?node=llm-1',
    );

    fireEvent.click(
      screen.getByRole('button', { name: '워크플로우로 돌아가기' }),
    );
    expect(routerMock.push).toHaveBeenCalledWith(
      '/modules/workflow-1?node=llm-1',
    );
  });

  it('baseline 선택 후 실험 설정이 열리고 결과 분석 모드로 전환할 수 있다', async () => {
    const CostOptimizerPlaygroundPage = await loadPlaygroundPage();

    render(<CostOptimizerPlaygroundPage />);

    await waitFor(() => {
      expect(workflowApiMock.getDraftWorkflow).toHaveBeenCalledWith(
        'workflow-1',
      );
    });

    fireEvent.click(screen.getByRole('button', { name: '테스트 baseline 선택' }));

    expect(
      screen.getByRole('button', { name: '실험 설정' }),
    ).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('B candidate')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '기준 실행 정보' }))
      .toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '결과 분석' }));

    expect(
      screen.getByRole('button', { name: '결과 분석' }),
    ).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('비교 리포트')).toBeInTheDocument();
    expect(screen.getByText(/B 실행 후 결과 분석이 표시됩니다/)).toBeInTheDocument();
  });

  it('B candidate는 후보 옵션 제목 대신 테스트명을 입력한다', async () => {
    const CostOptimizerPlaygroundPage = await loadPlaygroundPage();

    render(<CostOptimizerPlaygroundPage />);

    await waitFor(() => {
      expect(workflowApiMock.getDraftWorkflow).toHaveBeenCalledWith(
        'workflow-1',
      );
    });

    fireEvent.click(screen.getByRole('button', { name: '테스트 baseline 선택' }));

    const testNameInput = screen.getByLabelText('테스트명');
    expect(testNameInput).toBeInTheDocument();
    expect(screen.queryByText('후보 옵션')).not.toBeInTheDocument();

    fireEvent.change(testNameInput, {
      target: { value: 'gpt-4.1-mini 비용 절감 테스트' },
    });

    expect(testNameInput).toHaveValue('gpt-4.1-mini 비용 절감 테스트');
  });

  it('실험 설정에서는 왼쪽에 실행 시점 옵션을, 오른쪽에 기준 실행 정보를 표시한다', async () => {
    const CostOptimizerPlaygroundPage = await loadPlaygroundPage();

    render(<CostOptimizerPlaygroundPage />);

    await waitFor(() => {
      expect(workflowApiMock.getDraftWorkflow).toHaveBeenCalledWith(
        'workflow-1',
      );
    });

    fireEvent.click(screen.getByRole('button', { name: '테스트 baseline 선택' }));

    expect(screen.getByLabelText('실행 시점 옵션')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '기준 실행 정보' }))
      .toBeInTheDocument();
    expect(screen.getByText('선택된 기준 실행')).toBeInTheDocument();
    expect(screen.getByText(/baseline input/)).toBeInTheDocument();
    expect(screen.getByText(/baseline output/)).toBeInTheDocument();
    expect(
      screen.getByText(/끝까지 보여야 하는 입력 문장/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/끝까지 보여야 하는 출력 문장/),
    ).toBeInTheDocument();
  });
});
