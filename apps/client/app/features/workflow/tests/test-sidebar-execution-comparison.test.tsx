import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
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
) => ({
  ...runSummary(
    id,
    id === 'baseline-run' ? '2026-07-13T01:00:00Z' : '2026-07-14T01:00:00Z',
  ),
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
        semantic_route_label:
          id === 'baseline-run' ? '고위험 문의' : '일반 문의',
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
});

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

  it('비교 모드를 종료하면 고정한 기준 실행을 해제한다', async () => {
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
    expect(await screen.findByText('기준 실행 고정됨')).toBeVisible();

    fireEvent.click(screen.getByRole('button', { name: '단일 결과' }));
    fireEvent.click(screen.getByRole('button', { name: '실행 비교' }));

    expect(await screen.findByText('기준 실행 선택')).toBeVisible();
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
});
