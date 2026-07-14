import { cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { TestSidebar } from '../components/editor/TestSidebar';

const mocks = vi.hoisted(() => ({
  getWorkflowRun: vi.fn(),
  restoreTestExecution: vi.fn(),
}));

vi.mock('@xyflow/react', () => ({
  useReactFlow: () => ({
    setCenter: vi.fn(),
    getViewport: vi.fn(() => ({ x: 0, y: 0, zoom: 1 })),
  }),
}));

vi.mock('../api/workflowApi', () => ({
  workflowApi: { getWorkflowRun: mocks.getWorkflowRun },
}));

vi.mock('../store/useWorkflowStore', () => {
  const state = {
    isTestPanelOpen: false,
    toggleTestPanel: vi.fn(),
    nodes: [
      {
        id: 'llm-triage',
        type: 'llmNode',
        position: { x: 0, y: 0 },
        data: { title: '문의 분류' },
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
    testExecutionStatus: 'idle',
    testExecutionRunId: null,
    testSelectedNodeId: null,
    testExecutionStartedAt: null,
    testExecutionFinishedAt: null,
    testExecutionResult: null,
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
    restoreTestExecution: mocks.restoreTestExecution,
    resetTestExecution: vi.fn(),
  };
  const useWorkflowStore = Object.assign(vi.fn(() => state), {
    getState: vi.fn(() => state),
  });
  return { useWorkflowStore };
});

afterEach(() => {
  cleanup();
  mocks.getWorkflowRun.mockReset();
  mocks.restoreTestExecution.mockReset();
  window.history.replaceState({}, '', '/modules/workflow-1');
});

describe('TestSidebar saved run restore', () => {
  it('새로고침 URL의 testRun을 권한 있는 run 상세 조회로 복원한다', async () => {
    window.history.replaceState(
      {},
      '',
      '/modules/workflow-1?testRun=11111111-1111-1111-1111-111111111111&testNode=llm-triage',
    );
    mocks.getWorkflowRun.mockResolvedValue({
      id: '11111111-1111-1111-1111-111111111111',
      workflow_id: 'workflow-1',
      user_id: 'user-1',
      status: 'success',
      trigger_mode: 'manual',
      outputs: { answer: '복원됨' },
      started_at: '2026-07-14T01:00:00.000Z',
      finished_at: '2026-07-14T01:00:01.000Z',
      node_runs: [],
    });

    render(<TestSidebar />);

    await waitFor(() => {
      expect(mocks.getWorkflowRun).toHaveBeenCalledWith(
        'workflow-1',
        '11111111-1111-1111-1111-111111111111',
      );
    });
    expect(mocks.restoreTestExecution).toHaveBeenCalledWith(
      expect.objectContaining({
        runId: '11111111-1111-1111-1111-111111111111',
        status: 'success',
      }),
    );
  });

  it('실행 기록 생성 전 404를 받으면 제한된 재시도 후 복원한다', async () => {
    window.history.replaceState(
      {},
      '',
      '/modules/workflow-1?testRun=22222222-2222-2222-2222-222222222222',
    );
    mocks.getWorkflowRun
      .mockRejectedValueOnce({ response: { status: 404 } })
      .mockResolvedValueOnce({
        id: '22222222-2222-2222-2222-222222222222',
        workflow_id: 'workflow-1',
        user_id: 'user-1',
        status: 'success',
        trigger_mode: 'manual',
        outputs: { answer: '나중에 기록됨' },
        started_at: '2026-07-14T01:00:00.000Z',
        finished_at: '2026-07-14T01:00:01.000Z',
        node_runs: [],
      });

    render(<TestSidebar />);

    await waitFor(
      () => {
        expect(mocks.getWorkflowRun).toHaveBeenCalledTimes(2);
      },
      { timeout: 1_500 },
    );
    expect(mocks.restoreTestExecution).toHaveBeenCalledWith(
      expect.objectContaining({
        runId: '22222222-2222-2222-2222-222222222222',
        status: 'success',
      }),
    );
  });

  it('진행 중인 실행은 실행 중으로 표시하고 완료될 때까지 다시 조회한다', async () => {
    window.history.replaceState(
      {},
      '',
      '/modules/workflow-1?testRun=33333333-3333-3333-3333-333333333333',
    );
    mocks.getWorkflowRun
      .mockResolvedValueOnce({
        id: '33333333-3333-3333-3333-333333333333',
        workflow_id: 'workflow-1',
        user_id: 'user-1',
        status: 'running',
        trigger_mode: 'manual',
        outputs: {},
        started_at: '2026-07-14T01:00:00.000Z',
        finished_at: null,
        node_runs: [],
      })
      .mockResolvedValueOnce({
        id: '33333333-3333-3333-3333-333333333333',
        workflow_id: 'workflow-1',
        user_id: 'user-1',
        status: 'success',
        trigger_mode: 'manual',
        outputs: { answer: '완료됨' },
        started_at: '2026-07-14T01:00:00.000Z',
        finished_at: '2026-07-14T01:00:01.000Z',
        node_runs: [],
      });

    render(<TestSidebar />);

    await waitFor(() => {
      expect(mocks.restoreTestExecution).toHaveBeenNthCalledWith(
        1,
        expect.objectContaining({ status: 'running' }),
      );
    });
    await waitFor(
      () => {
        expect(mocks.getWorkflowRun).toHaveBeenCalledTimes(2);
      },
      { timeout: 1_500 },
    );
    expect(mocks.restoreTestExecution).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: 'success' }),
    );
  });
});
