import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AgentBuilderPanel } from './AgentBuilderPanel';
import { useWorkflowStore } from '../../store/useWorkflowStore';
import { agentBuilderApi } from '../../api/agentBuilderApi';
import { workflowApi } from '../../api/workflowApi';
import type { Node } from '../../types/Workflow';

const routerPush = vi.fn();
const setViewport = vi.fn();

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: routerPush }),
}));

vi.mock('@xyflow/react', async () => {
  const actual = await vi.importActual<typeof import('@xyflow/react')>(
    '@xyflow/react',
  );
  return {
    ...actual,
    useReactFlow: () => ({
      getViewport: () => ({ x: 0, y: 0, zoom: 1 }),
      setViewport,
    }),
  };
});

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock('../../api/agentBuilderApi', () => ({
  agentBuilderApi: {
    createSession: vi.fn(),
    getSession: vi.fn(),
    sendMessage: vi.fn(),
    cancelRequest: vi.fn(),
    recordPreviewOpened: vi.fn(),
    applyDraft: vi.fn(),
    cancelDraft: vi.fn(),
  },
}));

vi.mock('../../api/workflowApi', () => ({
  workflowApi: {
    getDraftWorkflow: vi.fn(),
    getWorkflow: vi.fn(),
  },
}));

const initialState = useWorkflowStore.getState();

const node = (id: string, type = 'startNode'): Node =>
  ({
    id,
    type,
    position: { x: 0, y: 0 },
    data: { title: id, triggerType: 'manual', variables: [] },
  }) as Node;

const setPreviewState = (nodes: Node[]) => {
  useWorkflowStore.setState({
    agentBuilderPreview: {
      draftId: 'draft-new',
      previewGraph: {
        nodes,
        edges: [],
        viewport: { x: 10, y: 10, zoom: 1 },
      },
      nodeDetailPreviews: [],
      validationResult: { valid: true, issues: [] },
      baseGraphHash: 'base-hash',
      draftMode: 'new_workflow',
    },
  });
};

describe('AgentBuilderPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    useWorkflowStore.setState(initialState, true);
  });

  it('새 workflow 저장 직후 현재 editor graph를 새 graph로 덮어쓰지 않는다', async () => {
    const oldNodes = [node('old-node')];
    const newNodes = [node('new-node')];

    useWorkflowStore.setState({
      activeWorkflowId: 'workflow-old',
      workflows: [
        {
          id: 'workflow-old',
          appId: 'app-1',
          nodes: oldNodes,
          edges: [],
          features: { nextNodeDisplayNumber: 2 },
          viewport: { x: 0, y: 0, zoom: 1 },
        },
      ],
      nodes: oldNodes,
      edges: [],
      features: { nextNodeDisplayNumber: 2 },
      hasUnsavedChanges: false,
    });
    setPreviewState(newNodes);

    vi.mocked(agentBuilderApi.applyDraft).mockResolvedValue({
      apply_id: 'apply-1',
      outcome: 'saved',
      saved_workflow_id: 'workflow-new',
      latest_graph_hash: 'new-hash',
      stale_state: 'not_stale',
      permission_recheck_outcome: 'allowed',
      validation_state: 'valid',
      audit_recorded: true,
      notices: [],
    });
    vi.mocked(workflowApi.getDraftWorkflow).mockResolvedValue({
      nodes: newNodes,
      edges: [],
      viewport: { x: 10, y: 10, zoom: 1 },
      features: { nextNodeDisplayNumber: 2 },
    });
    vi.mocked(workflowApi.getWorkflow).mockResolvedValue({
      app_id: 'app-1',
    });

    render(
      <AgentBuilderPanel
        workflowId="workflow-old"
        appId="app-1"
        nodes={oldNodes}
        edges={[]}
        hasUnsavedChanges={false}
      />,
    );

    fireEvent.click(screen.getByLabelText('Agent Builder 열기'));
    fireEvent.click(screen.getByRole('button', { name: '적용 및 저장' }));

    await waitFor(() => {
      expect(routerPush).toHaveBeenCalledWith('/modules/workflow-new');
    });

    expect(agentBuilderApi.applyDraft).toHaveBeenCalledWith('draft-new', {
      clientPreviewGraphHash: expect.any(String),
      clientLatestGraphHash: expect.any(String),
    });

    const state = useWorkflowStore.getState();
    expect(state.activeWorkflowId).toBe('workflow-old');
    expect(state.nodes[0].id).toBe('old-node');
    expect(
      state.workflows.find((workflow) => workflow.id === 'workflow-new')?.nodes[0]
        .id,
    ).toBe('new-node');
  });

  it('workflow scope가 바뀌면 기존 preview 상태를 제거한다', async () => {
    const oldNodes = [node('old-node')];
    setPreviewState(oldNodes);

    const { rerender } = render(
      <AgentBuilderPanel
        workflowId="workflow-old"
        appId="app-1"
        nodes={oldNodes}
        edges={[]}
        hasUnsavedChanges={false}
      />,
    );

    expect(useWorkflowStore.getState().agentBuilderPreview?.draftId).toBe(
      'draft-new',
    );

    rerender(
      <AgentBuilderPanel
        workflowId="workflow-next"
        appId="app-1"
        nodes={oldNodes}
        edges={[]}
        hasUnsavedChanges={false}
      />,
    );

    await waitFor(() => {
      expect(useWorkflowStore.getState().agentBuilderPreview).toBeNull();
    });
  });

  it('app scope가 바뀌면 기존 preview 상태를 제거한다', async () => {
    const oldNodes = [node('old-node')];
    setPreviewState(oldNodes);

    const { rerender } = render(
      <AgentBuilderPanel
        workflowId="workflow-old"
        appId="app-1"
        nodes={oldNodes}
        edges={[]}
        hasUnsavedChanges={false}
      />,
    );

    expect(useWorkflowStore.getState().agentBuilderPreview?.draftId).toBe(
      'draft-new',
    );

    rerender(
      <AgentBuilderPanel
        workflowId="workflow-old"
        appId="app-2"
        nodes={oldNodes}
        edges={[]}
        hasUnsavedChanges={false}
      />,
    );

    await waitFor(() => {
      expect(useWorkflowStore.getState().agentBuilderPreview).toBeNull();
    });
  });

  it('입력창에서 Enter를 누르면 Agent Builder 요청을 보낸다', async () => {
    vi.mocked(agentBuilderApi.createSession).mockResolvedValue({
      session_id: 'session-enter',
      workflow_id: 'workflow-old',
      app_id: 'app-1',
      status: 'active',
      messages: [],
      pending_request: null,
      draft_preview: null,
    });
    vi.mocked(agentBuilderApi.sendMessage).mockResolvedValue({
      request_id: 'request-enter',
      status: 'clarification_required',
      structured_request: null,
      clarification_questions: ['추가 정보를 알려주세요.'],
      draft_preview: null,
      validation_result: null,
      preview_prompt: null,
      warnings: [],
    });

    render(
      <AgentBuilderPanel
        workflowId="workflow-old"
        appId="app-1"
        nodes={[]}
        edges={[]}
        hasUnsavedChanges={false}
      />,
    );

    fireEvent.click(screen.getByLabelText('Agent Builder 열기'));
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'LLM 가동' },
    });
    fireEvent.keyDown(screen.getByRole('textbox'), {
      key: 'Enter',
      code: 'Enter',
    });

    await waitFor(() => {
      expect(agentBuilderApi.sendMessage).toHaveBeenCalledWith('session-enter', {
        message: 'LLM 가동',
        workflowId: 'workflow-old',
        appId: 'app-1',
        selectedNodeId: undefined,
        selectedEdgeId: undefined,
      });
    });
  });

  it('전송한 사용자 입력을 대화 영역에 남긴다', async () => {
    vi.mocked(agentBuilderApi.createSession).mockResolvedValue({
      session_id: 'session-user-message',
      workflow_id: 'workflow-old',
      app_id: 'app-1',
      status: 'active',
      messages: [],
      pending_request: null,
      draft_preview: null,
    });
    vi.mocked(agentBuilderApi.sendMessage).mockResolvedValue({
      request_id: 'request-user-message',
      status: 'clarification_required',
      structured_request: null,
      clarification_questions: ['추가 정보를 알려주세요.'],
      draft_preview: null,
      validation_result: null,
      preview_prompt: null,
      warnings: [],
    });

    render(
      <AgentBuilderPanel
        workflowId="workflow-old"
        appId="app-1"
        nodes={[]}
        edges={[]}
        hasUnsavedChanges={false}
      />,
    );

    fireEvent.click(screen.getByLabelText('Agent Builder 열기'));
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'Summarize input and send to Slack' },
    });
    fireEvent.keyDown(screen.getByRole('textbox'), {
      key: 'Enter',
      code: 'Enter',
    });

    await waitFor(() => {
      expect(agentBuilderApi.sendMessage).toHaveBeenCalled();
    });
    expect(screen.getByText('Summarize input and send to Slack')).toBeTruthy();
  });

  it('validation을 통과하지 못한 draft에는 도안 보기 버튼을 노출하지 않는다', async () => {
    window.localStorage.setItem(
      'agent-builder:workflow-old:app-1',
      'session-1',
    );
    vi.mocked(agentBuilderApi.getSession).mockResolvedValue({
      session_id: 'session-1',
      workflow_id: 'workflow-old',
      app_id: 'app-1',
      status: 'active',
      messages: [
        {
          request_id: 'request-1',
          status: 'validation_failed',
          clarification_questions: [],
          warnings: [],
          draft_preview: {
            draft_id: 'draft-invalid',
            preview_graph: { nodes: [], edges: [] },
            draft_mode: 'modify_workflow',
            node_detail_previews: [],
            validation_result: {
              valid: false,
              issues: [
                {
                  code: 'DRAFT_VALIDATION_FAILED',
                  message: '도안 검증에 실패했습니다.',
                },
              ],
            },
            safety_notices: [],
          },
        },
      ],
      pending_request: null,
      draft_preview: null,
    });

    render(
      <AgentBuilderPanel
        workflowId="workflow-old"
        appId="app-1"
        nodes={[]}
        edges={[]}
        hasUnsavedChanges={false}
      />,
    );

    fireEvent.click(screen.getByLabelText('Agent Builder 열기'));

    await waitFor(() => {
      expect(agentBuilderApi.getSession).toHaveBeenCalledWith('session-1');
    });
    expect(screen.queryByRole('button', { name: '도안 보기' })).toBeNull();
  });
});
