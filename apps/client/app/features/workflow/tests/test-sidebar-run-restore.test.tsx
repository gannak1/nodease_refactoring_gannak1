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
});
