import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react';
import { useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ExecutionComparisonPanel } from '../components/editor/ExecutionComparisonPanel';
import { TestSidebar } from '../components/editor/TestSidebar';

const mocks = vi.hoisted(() => ({
  getWorkflowRuns: vi.fn(),
  getWorkflowRun: vi.fn(),
  getWorkflowRunLlmTraces: vi.fn(),
}));

vi.mock('../api/workflowApi', () => ({
  workflowApi: mocks,
}));

vi.mock('@xyflow/react', () => ({
  useReactFlow: () => ({
    setCenter: vi.fn(),
    getViewport: vi.fn(() => ({ x: 0, y: 0, zoom: 1 })),
  }),
}));

vi.mock('../store/useWorkflowStore', () => {
  const state = {
    isTestPanelOpen: true,
    toggleTestPanel: vi.fn(),
    openTestPanel: vi.fn(),
    nodes: [
      {
        id: 'llm-triage',
        type: 'llmNode',
        position: { x: 0, y: 0 },
        data: { title: '문의 분류', observability: { status: 'success' } },
      },
    ],
    activeWorkflowId: 'workflow-1',
    setNodes: vi.fn(),
    updateNodeData: vi.fn(),
    workflowAccess: { can_execute: true },
    edges: [],
    features: {},
    envVariables: [],
    runtimeVariables: [],
    testExecutionStatus: 'success',
    testExecutionRunId: 'current-run',
    testSelectedNodeId: null,
    testExecutionStartedAt: 1_000,
    testExecutionFinishedAt: 2_000,
    testExecutionResult: { answer: '현재 답변' },
    testNodeResults: [],
    testExecutionError: null,
    currentExecutingNodeId: null,
    isTestUploading: false,
    beginTestExecution: vi.fn(),
    setTestUploading: vi.fn(),
    setCurrentExecutingNode: vi.fn(),
    setTestExecutionRunId: vi.fn(),
    selectTestExecutionNode: vi.fn(),
    addTestNodeResult: vi.fn(),
    finishTestExecution: vi.fn(),
    failTestExecution: vi.fn(),
    restoreTestExecution: vi.fn(),
    resetTestExecution: vi.fn(),
  };
  const useWorkflowStore = Object.assign(
    vi.fn(() => state),
    {
      getState: vi.fn(() => state),
    },
  );
  return { useWorkflowStore };
});

const runSummary = (id: string, startedAt: string) => ({
  id,
  workflow_id: 'workflow-1',
  user_id: 'user-1',
  status: 'success',
  trigger_mode: 'manual',
  started_at: startedAt,
  finished_at: startedAt,
  duration: 2,
  total_tokens: 120,
  total_cost: 0.0012,
});

const runDetail = (
  id: string,
  model: string,
  input: string,
  output: string,
) => {
  const isBaseline = id === 'baseline-run';

  return {
    ...runSummary(
      id,
      isBaseline ? '2026-07-13T01:00:00Z' : '2026-07-14T01:00:00Z',
    ),
    duration: isBaseline ? 2 : 1,
    total_tokens: isBaseline ? 120 : 60,
    total_cost: isBaseline ? 0.0012 : 0.0006,
    inputs: { message: input },
    outputs: { answer: output },
    node_runs: [
    {
      id: `${id}-node-run`,
      node_id: 'llm-triage',
      node_type: 'llmNode',
      status: 'success',
      inputs: { message: input },
      outputs: {
        text: output,
        model,
        usage: { total_tokens: id === 'baseline-run' ? 120 : 80 },
        cost: id === 'baseline-run' ? 0.0012 : 0.0006,
      },
      trace_metadata: {
        selected_model: model,
        matched_rule_id: id === 'baseline-run' ? 'high-risk' : 'general',
        policy_version: id === 'baseline-run' ? 'policy-v1' : 'policy-v2',
        policy_source: 'active_deployment',
        included_in_policy_learning: false,
        judge_called: false,
      },
      started_at: '2026-07-14T01:00:00Z',
      finished_at: '2026-07-14T01:00:02Z',
      duration: id === 'baseline-run' ? 2 : 1,
    },
    ],
  };
};

function ComparisonHarness() {
  const [baselineRunId, setBaselineRunId] = useState<string | null>(null);
  const [currentRunId, setCurrentRunId] = useState('current-run');

  return (
    <>
      <button type="button" onClick={() => setCurrentRunId('current-run-2')}>
        새 현재 실행
      </button>
      <ExecutionComparisonPanel
        workflowId="workflow-1"
        nodes={
          [
            {
              id: 'llm-triage',
              type: 'llmNode',
              position: { x: 0, y: 0 },
              data: { title: '문의 분류' },
            },
          ] as never
        }
        baselineRunId={baselineRunId}
        currentRunId={currentRunId}
        onBaselineRunIdChange={setBaselineRunId}
      />
    </>
  );
}

function NonLlmComparisonHarness() {
  const [baselineRunId, setBaselineRunId] = useState<string | null>(null);

  return (
    <ExecutionComparisonPanel
      workflowId="workflow-1"
      nodes={
        [
          {
            id: 'webhook-start',
            type: 'webhookTrigger',
            position: { x: 0, y: 0 },
            data: { title: '고객 티켓 수신' },
          },
        ] as never
      }
      baselineRunId={baselineRunId}
      currentRunId="current-run"
      onBaselineRunIdChange={setBaselineRunId}
    />
  );
}

function RunningComparisonHarness() {
  const [baselineRunId, setBaselineRunId] = useState<string | null>(null);
  const [currentExecutionStatus, setCurrentExecutionStatus] = useState('running');

  return (
    <>
      <button
        type="button"
        onClick={() => setCurrentExecutionStatus('success')}
      >
        현재 실행 완료
      </button>
      <ExecutionComparisonPanel
        workflowId="workflow-1"
        nodes={
          [
            {
              id: 'llm-triage',
              type: 'llmNode',
              position: { x: 0, y: 0 },
              data: { title: '문의 분류' },
            },
          ] as never
        }
        baselineRunId={baselineRunId}
        currentRunId="current-run"
        currentExecutionStatus={currentExecutionStatus}
        onBaselineRunIdChange={setBaselineRunId}
      />
    </>
  );
}

function LiveExecutionComparisonHarness() {
  const [baselineRunId, setBaselineRunId] = useState<string | null>(null);
  const [nodes, setNodes] = useState([
    {
      id: 'llm-triage',
      type: 'llmNode',
      position: { x: 0, y: 0 },
      data: { title: '문의 분류', status: 'idle' },
    },
  ]);

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setNodes((currentNodes) =>
            currentNodes.map((node) => ({
              ...node,
              data: { ...node.data, status: 'running' },
            })),
          );
        }}
      >
        실시간 상태 갱신
      </button>
      <ExecutionComparisonPanel
        workflowId="workflow-1"
        nodes={nodes as never}
        baselineRunId={baselineRunId}
        currentRunId="current-run"
        onBaselineRunIdChange={setBaselineRunId}
      />
    </>
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('TestSidebar execution comparison', () => {
  it('워크플로우 화면을 벗어나지 않고 TestSidebar를 실행 비교 모드로 전환한다', async () => {
    mocks.getWorkflowRuns.mockResolvedValue({ total: 0, items: [] });

    render(<TestSidebar />);
    fireEvent.click(screen.getByRole('button', { name: '실행 비교' }));

    expect(await screen.findByText('기준 실행 선택')).toBeVisible();
    expect(screen.getByTestId('test-execution-sidebar')).toBeVisible();
    expect(screen.queryByText('노드별 실행 결과')).not.toBeInTheDocument();
  });

  it('단일 결과로 전환해도 이전 실행 비교 분석을 유지한다', async () => {
    mocks.getWorkflowRuns.mockResolvedValue({
      total: 1,
      items: [runSummary('baseline-run', '2026-07-13T01:00:00Z')],
    });
    mocks.getWorkflowRun.mockImplementation(
      (_workflowId: string, runId: string) =>
        Promise.resolve(
          runId === 'baseline-run'
            ? runDetail('baseline-run', 'gpt-4.1', '기존 문의', '기존 답변')
            : runDetail(
                'current-run',
                'gpt-4.1-mini',
                '현재 문의',
                '현재 답변',
              ),
        ),
    );
    mocks.getWorkflowRunLlmTraces.mockResolvedValue({
      total: 0,
      limit: 100,
      offset: 0,
      items: [],
    });

    render(<TestSidebar />);
    fireEvent.click(screen.getByRole('button', { name: '실행 비교' }));
    fireEvent.click(
      await screen.findByRole('button', { name: '기준으로 고정' }),
    );
    expect(
      await screen.findByRole('button', {
        name: '문의 분류 노드 상세 비교하기',
      }),
    ).toBeVisible();
    fireEvent.click(
      screen.getByRole('button', {
        name: '문의 분류 노드 상세 비교하기',
      }),
    );
    expect(
      screen.getByRole('heading', { name: '문의 분류 상세 비교' }),
    ).toBeVisible();
    expect(mocks.getWorkflowRun).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole('button', { name: '단일 결과' }));
    fireEvent.click(screen.getByRole('button', { name: '실행 비교' }));

    expect(
      screen.getByRole('heading', { name: '문의 분류 상세 비교' }),
    ).toBeVisible();
    expect(mocks.getWorkflowRun).toHaveBeenCalledTimes(2);
  });

  it('최신 실행을 자동 선택하지 않고 사용자가 기준 실행을 명시적으로 고정한다', async () => {
    mocks.getWorkflowRuns.mockResolvedValue({
      total: 2,
      items: [
        runSummary('current-run', '2026-07-14T01:00:00Z'),
        runSummary('baseline-run', '2026-07-13T01:00:00Z'),
      ],
    });
    mocks.getWorkflowRun.mockImplementation(
      (_workflowId: string, runId: string) =>
        Promise.resolve(
          runId === 'baseline-run'
            ? runDetail('baseline-run', 'gpt-4.1', '기존 문의', '기존 답변')
            : runDetail(
                'current-run',
                'gpt-4.1-mini',
                '현재 문의',
                '현재 답변',
              ),
        ),
    );
    mocks.getWorkflowRunLlmTraces.mockResolvedValue({
      total: 0,
      limit: 100,
      offset: 0,
      items: [],
    });

    render(<ComparisonHarness />);

    expect(await screen.findByText('기준 실행 선택')).toBeVisible();
    expect(mocks.getWorkflowRun).not.toHaveBeenCalled();

    const pinButtons = screen.getAllByRole('button', { name: '기준으로 고정' });
    fireEvent.click(pinButtons[1]);

    await waitFor(() => {
      expect(mocks.getWorkflowRun).toHaveBeenCalledWith(
        'workflow-1',
        'baseline-run',
      );
      expect(mocks.getWorkflowRun).toHaveBeenCalledWith(
        'workflow-1',
        'current-run',
      );
    });
    expect(screen.getByText('기준 실행 고정됨')).toBeVisible();
  });

  it('노드별 비교 목록에서 노드 이름과 유형을 함께 표시한다', async () => {
    mocks.getWorkflowRuns.mockResolvedValue({
      total: 1,
      items: [runSummary('baseline-run', '2026-07-13T01:00:00Z')],
    });
    mocks.getWorkflowRun.mockImplementation(
      (_workflowId: string, runId: string) =>
        Promise.resolve(
          runId === 'baseline-run'
            ? runDetail('baseline-run', 'gpt-4.1', '기존 문의', '기존 답변')
            : runDetail('current-run', 'gpt-4.1-mini', '현재 문의', '현재 답변'),
        ),
    );
    mocks.getWorkflowRunLlmTraces.mockResolvedValue({
      total: 0,
      limit: 100,
      offset: 0,
      items: [],
    });

    render(<ComparisonHarness />);
    fireEvent.click(
      await screen.findByRole('button', { name: '기준으로 고정' }),
    );

    expect(await screen.findByText('문의 분류')).toBeVisible();
    expect(screen.getByText('LLM')).toBeVisible();
  });

  it('전체 실행 비교에서 수치 지표는 세로로 쌓은 가로 막대로, 상태는 별도 배지로 표시한다', async () => {
    mocks.getWorkflowRuns.mockResolvedValue({
      total: 1,
      items: [runSummary('baseline-run', '2026-07-13T01:00:00Z')],
    });
    mocks.getWorkflowRun.mockImplementation(
      (_workflowId: string, runId: string) =>
        Promise.resolve(
          runId === 'baseline-run'
            ? runDetail('baseline-run', 'gpt-4.1', '기존 문의', '기존 답변')
            : runDetail(
                'current-run',
                'gpt-4.1-mini',
                '현재 문의',
                '현재 답변',
              ),
        ),
    );
    mocks.getWorkflowRunLlmTraces.mockResolvedValue({
      total: 0,
      limit: 100,
      offset: 0,
      items: [],
    });

    render(<ComparisonHarness />);
    fireEvent.click(
      await screen.findByRole('button', { name: '기준으로 고정' }),
    );

    expect(
      await screen.findByRole('heading', { name: '전체 실행 비교' }),
    ).toBeVisible();
    expect(screen.getByTestId('overall-execution-metrics')).toHaveClass(
      'flex-col',
    );
    expect(screen.getByTestId('overall-execution-metric-cost')).toHaveTextContent(
      '50.0% 감소',
    );
    expect(
      screen.getByTestId('overall-execution-metric-cost-baseline-bar'),
    ).toHaveStyle({ width: '100%' });
    expect(
      screen.getByTestId('overall-execution-metric-cost-current-bar'),
    ).toHaveStyle({ width: '50%' });
    expect(screen.getByTestId('overall-execution-metric-duration')).toBeVisible();
    expect(screen.getByTestId('overall-execution-metric-tokens')).toBeVisible();
    expect(screen.getByText('기준 실행: 성공')).toBeVisible();
    expect(screen.getByText('현재 실행: 성공')).toBeVisible();
  });

  it('현재 실행 중에는 비교 조회 오류 대신 완료 대기 안내를 표시한다', async () => {
    mocks.getWorkflowRuns.mockResolvedValue({
      total: 1,
      items: [runSummary('baseline-run', '2026-07-13T01:00:00Z')],
    });
    mocks.getWorkflowRun.mockImplementation(
      (_workflowId: string, runId: string) =>
        Promise.resolve(
          runId === 'baseline-run'
            ? runDetail('baseline-run', 'gpt-4.1', '기존 문의', '기존 답변')
            : runDetail(
                'current-run',
                'gpt-4.1-mini',
                '현재 문의',
                '현재 답변',
              ),
        ),
    );
    mocks.getWorkflowRunLlmTraces.mockResolvedValue({
      total: 0,
      limit: 100,
      offset: 0,
      items: [],
    });

    render(<RunningComparisonHarness />);
    fireEvent.click(
      await screen.findByRole('button', { name: '기준으로 고정' }),
    );

    expect(
      await screen.findByText('현재 실행이 완료되면 비교 결과를 준비합니다.'),
    ).toBeVisible();
    expect(
      screen.queryByText('실행 비교 데이터를 불러오지 못했습니다.'),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '현재 실행 완료' }));

    expect(
      await screen.findByRole('heading', { name: '전체 실행 비교' }),
    ).toBeVisible();
  });

  it('현재 테스트를 다시 실행해도 고정한 기준 실행을 유지한다', async () => {
    mocks.getWorkflowRuns.mockResolvedValue({
      total: 1,
      items: [runSummary('baseline-run', '2026-07-13T01:00:00Z')],
    });
    mocks.getWorkflowRun.mockImplementation(
      (_workflowId: string, runId: string) =>
        Promise.resolve(
          runId === 'baseline-run'
            ? runDetail('baseline-run', 'gpt-4.1', '기존 문의', '기존 답변')
            : runDetail(runId, 'gpt-4.1-mini', '현재 문의', '현재 답변'),
        ),
    );
    mocks.getWorkflowRunLlmTraces.mockResolvedValue({
      total: 0,
      limit: 100,
      offset: 0,
      items: [],
    });

    render(<ComparisonHarness />);
    fireEvent.click(
      await screen.findByRole('button', { name: '기준으로 고정' }),
    );
    expect(await screen.findByText('기준 실행 고정됨')).toBeVisible();

    fireEvent.click(screen.getByRole('button', { name: '새 현재 실행' }));

    await waitFor(() => {
      expect(mocks.getWorkflowRun).toHaveBeenCalledWith(
        'workflow-1',
        'current-run-2',
      );
    });
    expect(screen.getByText('기준 실행 고정됨')).toBeVisible();
    expect(
      screen.queryByRole('button', { name: '기준으로 고정' }),
    ).not.toBeInTheDocument();
  });

  it('실시간 노드 상태 갱신으로 실행 비교를 다시 로드하지 않는다', async () => {
    mocks.getWorkflowRuns.mockResolvedValue({
      total: 1,
      items: [runSummary('baseline-run', '2026-07-13T01:00:00Z')],
    });
    mocks.getWorkflowRun.mockImplementation(
      (_workflowId: string, runId: string) =>
        Promise.resolve(
          runId === 'baseline-run'
            ? runDetail('baseline-run', 'gpt-4.1', '기존 문의', '기존 답변')
            : runDetail(
                'current-run',
                'gpt-4.1-mini',
                '현재 문의',
                '현재 답변',
              ),
        ),
    );
    mocks.getWorkflowRunLlmTraces.mockResolvedValue({
      total: 0,
      limit: 100,
      offset: 0,
      items: [],
    });

    render(<LiveExecutionComparisonHarness />);
    fireEvent.click(
      await screen.findByRole('button', { name: '기준으로 고정' }),
    );
    expect(
      await screen.findByRole('button', {
        name: '문의 분류 노드 상세 비교하기',
      }),
    ).toBeVisible();
    fireEvent.click(
      screen.getByRole('button', {
        name: '문의 분류 노드 상세 비교하기',
      }),
    );
    expect(
      screen.getByRole('heading', { name: '문의 분류 상세 비교' }),
    ).toBeVisible();
    expect(mocks.getWorkflowRun).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole('button', { name: '실시간 상태 갱신' }));

    expect(mocks.getWorkflowRun).toHaveBeenCalledTimes(2);
    expect(
      screen.queryByText('현재 실행 기록을 동기화하는 중입니다.'),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole('heading', { name: '문의 분류 상세 비교' }),
    ).toBeVisible();
  });

  it('LLM trace 조회 실패를 비교 근거 누락 경고로 표시한다', async () => {
    mocks.getWorkflowRuns.mockResolvedValue({
      total: 1,
      items: [runSummary('baseline-run', '2026-07-13T01:00:00Z')],
    });
    mocks.getWorkflowRun.mockImplementation(
      (_workflowId: string, runId: string) =>
        Promise.resolve(
          runId === 'baseline-run'
            ? runDetail('baseline-run', 'gpt-4.1', '기존 문의', '기존 답변')
            : runDetail(
                'current-run',
                'gpt-4.1-mini',
                '현재 문의',
                '현재 답변',
              ),
        ),
    );
    mocks.getWorkflowRunLlmTraces.mockRejectedValue({
      response: { status: 500 },
    });

    render(<ComparisonHarness />);
    fireEvent.click(
      await screen.findByRole('button', { name: '기준으로 고정' }),
    );

    expect(
      await screen.findByText('일부 LLM trace를 불러오지 못했습니다.'),
    ).toBeVisible();
    expect(
      screen.queryByText('실행 비교 데이터를 불러오지 못했습니다.'),
    ).not.toBeInTheDocument();
  });

  it('LLM trace 404는 기록 없음으로 처리하고 장애 경고를 표시하지 않는다', async () => {
    mocks.getWorkflowRuns.mockResolvedValue({
      total: 1,
      items: [runSummary('baseline-run', '2026-07-13T01:00:00Z')],
    });
    mocks.getWorkflowRun.mockImplementation(
      (_workflowId: string, runId: string) =>
        Promise.resolve(
          runId === 'baseline-run'
            ? runDetail('baseline-run', 'gpt-4.1', '기존 문의', '기존 답변')
            : runDetail(
                'current-run',
                'gpt-4.1-mini',
                '현재 문의',
                '현재 답변',
              ),
        ),
    );
    mocks.getWorkflowRunLlmTraces.mockRejectedValue({
      response: { status: 404 },
    });

    render(<ComparisonHarness />);
    fireEvent.click(
      await screen.findByRole('button', { name: '기준으로 고정' }),
    );

    expect(
      await screen.findByRole('button', {
        name: '문의 분류 노드 상세 비교하기',
      }),
    ).toBeVisible();
    expect(
      screen.queryByText('일부 LLM trace를 불러오지 못했습니다.'),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText('LLM trace 기록 없음: 기준 실행, 현재 실행'),
    ).toBeVisible();
  });

  it('노드 목록은 상태·비용·시간·토큰만 보여주고 상세에서 입력·출력·라우팅을 비교한다', async () => {
    mocks.getWorkflowRuns.mockResolvedValue({
      total: 1,
      items: [runSummary('baseline-run', '2026-07-13T01:00:00Z')],
    });
    mocks.getWorkflowRun.mockImplementation(
      (_workflowId: string, runId: string) =>
        Promise.resolve(
          runId === 'baseline-run'
            ? runDetail('baseline-run', 'gpt-4.1', '기존 문의', '기존 답변')
            : runDetail(
                'current-run',
                'gpt-4.1-mini',
                '현재 문의',
                '현재 답변',
              ),
        ),
    );
    mocks.getWorkflowRunLlmTraces.mockResolvedValue({
      total: 0,
      limit: 100,
      offset: 0,
      items: [],
    });

    render(<ComparisonHarness />);
    fireEvent.click(
      await screen.findByRole('button', { name: '기준으로 고정' }),
    );

    expect(
      await screen.findByRole('button', {
        name: '문의 분류 노드 상세 비교하기',
      }),
    ).toBeVisible();
    expect(screen.getAllByText('상태').length).toBeGreaterThan(0);
    expect(screen.getAllByText('비용').length).toBeGreaterThan(0);
    expect(screen.getAllByText('실행 시간').length).toBeGreaterThan(0);
    expect(screen.getAllByText('토큰').length).toBeGreaterThan(0);
    expect(screen.queryByText('기존 문의')).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole('button', {
        name: '문의 분류 노드 상세 비교하기',
      }),
    );

    expect(
      screen.getByRole('heading', { name: '문의 분류 상세 비교' }),
    ).toBeVisible();
    expect(screen.getByText('입력 비교')).toBeVisible();
    expect(screen.getByText('기존 문의')).toBeVisible();
    expect(screen.getByText('현재 문의')).toBeVisible();
    expect(screen.getByText('출력 비교')).toBeVisible();
    expect(screen.getByText('기존 답변')).toBeVisible();
    expect(screen.getByText('현재 답변')).toBeVisible();
    expect(screen.getByText('모델 라우팅 비교')).toBeVisible();
    expect(screen.getAllByText('gpt-4.1').length).toBeGreaterThan(0);
    expect(screen.getAllByText('gpt-4.1-mini').length).toBeGreaterThan(0);
  });

  it('LLM 노드가 아닌 비교 카드에는 비용과 토큰을 표시하지 않는다', async () => {
    mocks.getWorkflowRuns.mockResolvedValue({
      total: 1,
      items: [runSummary('baseline-run', '2026-07-13T01:00:00Z')],
    });
    mocks.getWorkflowRun.mockImplementation(
      (_workflowId: string, runId: string) => {
        const detail =
          runId === 'baseline-run'
            ? runDetail('baseline-run', 'gpt-4.1', '기존 문의', '수신 완료')
            : runDetail('current-run', 'gpt-4.1-mini', '현재 문의', '수신 완료');

        return Promise.resolve({
          ...detail,
          node_runs: detail.node_runs.map((nodeRun) => ({
            ...nodeRun,
            node_id: 'webhook-start',
            node_type: 'webhookTrigger',
            outputs: { received: true },
          })),
        });
      },
    );
    mocks.getWorkflowRunLlmTraces.mockResolvedValue({
      total: 0,
      limit: 100,
      offset: 0,
      items: [],
    });

    render(<NonLlmComparisonHarness />);
    fireEvent.click(
      await screen.findByRole('button', { name: '기준으로 고정' }),
    );

    const nodeCard = (await screen.findByText('고객 티켓 수신')).closest(
      'article',
    );
    expect(nodeCard).not.toBeNull();
    expect(
      within(nodeCard as HTMLElement).getAllByText('상태'),
    ).toHaveLength(2);
    expect(
      within(nodeCard as HTMLElement).getAllByText('실행 시간'),
    ).toHaveLength(2);
    expect(within(nodeCard as HTMLElement).queryAllByText('비용')).toHaveLength(
      0,
    );
    expect(within(nodeCard as HTMLElement).queryAllByText('토큰')).toHaveLength(
      0,
    );
  });
});
