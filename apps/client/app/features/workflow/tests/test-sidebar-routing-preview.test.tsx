import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { TestSidebar } from '../components/editor/TestSidebar';
import { useWorkflowStore } from '../store/useWorkflowStore';

const previewModelRoutingMock = vi.hoisted(() => vi.fn());

type TestStoreNode = {
  id: string;
  type?: string;
  data?: unknown;
};

vi.mock('@xyflow/react', () => ({
  useReactFlow: () => ({
    setCenter: vi.fn(),
    getViewport: vi.fn(() => ({ zoom: 1 })),
  }),
}));

vi.mock('../api/workflowApi', () => ({
  workflowApi: {
    previewModelRouting: previewModelRoutingMock,
  },
}));

vi.mock('../store/useWorkflowStore', () => {
  const state = {
    isTestPanelOpen: true,
    toggleTestPanel: vi.fn(),
    nodes: [
      {
        id: 'start',
        type: 'startNode',
        data: {
          variables: [
            {
              id: 'question-variable',
              name: 'question',
              label: '질문',
              type: 'paragraph',
              required: false,
              placeholder: '질문을 입력하세요',
            },
          ],
        },
      },
      {
        id: 'llm-triage',
        type: 'llmNode',
        data: { auto_model_routing: true, model_id: 'gpt-4.1' },
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
    addTestNodeResult: vi.fn(),
    finishTestExecution: vi.fn(),
    failTestExecution: vi.fn(),
    resetTestExecution: vi.fn(),
  };
  const useWorkflowStore = Object.assign(vi.fn(() => state), {
    getState: vi.fn(() => state),
  });
  return { useWorkflowStore };
});

const preview = (selectedModelId: string) => ({
  deployment_version: 2,
  policy_version: 'router-policy-v4',
  decision_source: 'matched_rule' as const,
  selected_model_id: selectedModelId,
  fallback_model_id: 'gpt-4.1-mini',
  default_model_id: 'gpt-4.1',
  configured_fallback_model_id: 'gpt-4.1-mini',
  matched_cohort: { id: 'support', label: '사용 안내' },
  matched_rule_id: 'route-support',
  reason_code: 'policy_rule_matched',
  availability: 'available' as const,
  semantic_evaluation: 'not_required' as const,
  draft_matches_deployment: true,
});

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  previewModelRoutingMock.mockReset();
  const store = (
    useWorkflowStore as unknown as {
      getState: () => { nodes: TestStoreNode[] };
    }
  ).getState();
  store.nodes = [
    {
      id: 'start',
      type: 'startNode',
      data: {
        variables: [
          {
            id: 'question-variable',
            name: 'question',
            label: '질문',
            type: 'paragraph',
            required: false,
            placeholder: '질문을 입력하세요',
          },
        ],
      },
    },
    {
      id: 'llm-triage',
      type: 'llmNode',
      data: {
        title: '문의 분류',
        auto_model_routing: true,
        model_id: 'gpt-4.1',
      },
    },
  ];
});

describe('TestSidebar routing preview', () => {
  it('현재 입력을 실행 없이 preview API로 보내고, 입력을 바꾸면 다음 판단 결과로 갱신한다', async () => {
    previewModelRoutingMock
      .mockResolvedValueOnce(preview('gpt-4o-mini'))
      .mockResolvedValueOnce(preview('gpt-5.4-mini'));
    render(<TestSidebar />);

    expect(screen.getByText('라우팅 판단').closest('details')).toHaveAttribute(
      'open',
    );
    const input = await screen.findByPlaceholderText('질문을 입력하세요');
    fireEvent.change(input, { target: { value: '영수증 재발급 방법' } });
    fireEvent.click(screen.getByRole('button', { name: '라우팅 미리보기' }));

    await waitFor(() =>
      expect(previewModelRoutingMock).toHaveBeenLastCalledWith(
        'workflow-1',
        'llm-triage',
        { question: '영수증 재발급 방법' },
      ),
    );
    expect(await screen.findByText('gpt-4o-mini')).toBeVisible();

    fireEvent.change(input, { target: { value: 'SLA 위반 사고 대응' } });
    fireEvent.click(screen.getByRole('button', { name: '라우팅 미리보기' }));

    await waitFor(() =>
      expect(previewModelRoutingMock).toHaveBeenLastCalledWith(
        'workflow-1',
        'llm-triage',
        { question: 'SLA 위반 사고 대응' },
      ),
    );
    expect(await screen.findByText('gpt-5.4-mini')).toBeVisible();
  });

  it('자동 라우팅 LLM 노드가 여러 개면 사용자가 선택한 노드로 미리보기를 요청한다', async () => {
    const store = (
      useWorkflowStore as unknown as {
        getState: () => { nodes: TestStoreNode[] };
      }
    ).getState();
    store.nodes.push({
      id: 'llm-response',
      type: 'llmNode',
      data: {
        title: '응답 작성',
        auto_model_routing: true,
        model_id: 'gpt-4.1',
      },
    });
    previewModelRoutingMock.mockResolvedValueOnce(preview('gpt-5.4-mini'));

    render(<TestSidebar />);

    const input = await screen.findByPlaceholderText('질문을 입력하세요');
    fireEvent.change(input, { target: { value: '답변 작성 요청' } });
    const nodeSelect = screen.getByLabelText('미리보기 대상 LLM 노드');
    fireEvent.change(nodeSelect, { target: { value: 'llm-response' } });
    fireEvent.click(screen.getByRole('button', { name: '라우팅 미리보기' }));

    await waitFor(() =>
      expect(previewModelRoutingMock).toHaveBeenLastCalledWith(
        'workflow-1',
        'llm-response',
        { question: '답변 작성 요청' },
      ),
    );
    expect(await screen.findByText('gpt-5.4-mini')).toBeVisible();
  });

  it('draft에서 자동 라우팅을 껐더라도 배포 정책 판단은 API에 위임한다', async () => {
    const store = (
      useWorkflowStore as unknown as {
        getState: () => { nodes: TestStoreNode[] };
      }
    ).getState();
    const node = store.nodes.find((item) => item.id === 'llm-triage');
    if (!node) throw new Error('테스트 대상 LLM 노드가 없습니다.');
    (node.data as { auto_model_routing?: boolean }).auto_model_routing = false;
    previewModelRoutingMock.mockResolvedValueOnce(preview('gpt-4o-mini'));

    render(<TestSidebar />);

    const input = await screen.findByPlaceholderText('질문을 입력하세요');
    fireEvent.change(input, { target: { value: '배포 정책 확인' } });
    fireEvent.click(screen.getByRole('button', { name: '라우팅 미리보기' }));

    await waitFor(() =>
      expect(previewModelRoutingMock).toHaveBeenLastCalledWith(
        'workflow-1',
        'llm-triage',
        { question: '배포 정책 확인' },
      ),
    );
  });
});
