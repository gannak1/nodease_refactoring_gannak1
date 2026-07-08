import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AgentBuilderPanel } from './AgentBuilderPanel';
import { useWorkflowStore } from '../../store/useWorkflowStore';
import { agentBuilderApi } from '../../api/agentBuilderApi';
import { workflowApi } from '../../api/workflowApi';
import type { Edge, Node } from '../../types/Workflow';

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
    syncDraftWorkflow: vi.fn(),
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

const setPreviewState = (nodes: Node[], edges: Edge[] = []) => {
  useWorkflowStore.setState({
    agentBuilderPreview: {
      draftId: 'draft-new',
      previewGraph: {
        nodes,
        edges,
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
    vi.mocked(workflowApi.syncDraftWorkflow).mockResolvedValue({});
    vi.mocked(agentBuilderApi.cancelDraft).mockResolvedValue({
      apply_id: 'apply-cancel',
      outcome: 'canceled',
      block_reason: 'USER_CANCELED',
      stale_state: 'not_checked',
      permission_recheck_outcome: 'not_checked',
      validation_state: 'not_checked',
      audit_recorded: true,
      layout_optimization_applied: false,
      notices: [
        '도안 생성 미리보기를 닫았습니다. 실제 workflow graph는 변경되지 않았습니다.',
      ],
    });
  });

  it('Agent Builder 패널을 최소화했다가 다시 펼친다', () => {
    render(
      <AgentBuilderPanel
        workflowId="workflow-1"
        appId="app-1"
        nodes={[]}
        edges={[]}
        hasUnsavedChanges={false}
      />,
    );

    fireEvent.click(screen.getByLabelText('Agent Builder 열기'));
    expect(screen.getByText('Agent Builder')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Agent Builder 최소화'));
    expect(screen.queryByText('Agent Builder')).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Agent Builder 펼치기'));
    expect(screen.getByText('Agent Builder')).toBeInTheDocument();
  });

  it('loads the saved graph when Agent Builder creates a new workflow', async () => {
    const oldNodes = [node('old-node')];
    const newNodes = [
      node('new-input'),
      node('new-llm', 'llmNode'),
      node('new-answer', 'answerNode'),
    ];
    const newEdges: Edge[] = [
      { id: 'edge-input-llm', source: 'new-input', target: 'new-llm' },
      { id: 'edge-llm-answer', source: 'new-llm', target: 'new-answer' },
    ];

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
    setPreviewState(newNodes, newEdges);

    vi.mocked(agentBuilderApi.applyDraft).mockResolvedValue({
      apply_id: 'apply-1',
      outcome: 'saved',
      saved_workflow_id: 'workflow-new',
      latest_graph_hash: 'new-hash',
      stale_state: 'not_stale',
      permission_recheck_outcome: 'allowed',
      validation_state: 'valid',
      audit_recorded: true,
      layout_optimization_applied: true,
      notices: [],
    });
    vi.mocked(workflowApi.getDraftWorkflow).mockResolvedValue({
      nodes: newNodes,
      edges: newEdges,
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
    expect(workflowApi.syncDraftWorkflow).toHaveBeenCalledWith(
      'workflow-new',
      expect.objectContaining({
        nodes: expect.arrayContaining([
          expect.objectContaining({
            id: 'new-llm',
            position: expect.objectContaining({ x: expect.any(Number) }),
          }),
        ]),
        edges: newEdges,
        envVariables: [],
        runtimeVariables: [],
      }),
    );

    const syncedGraph =
      vi.mocked(workflowApi.syncDraftWorkflow).mock.calls[0]?.[1];
    expect(syncedGraph).toBeDefined();
    if (!syncedGraph) {
      throw new Error('Expected optimized graph to be synced');
    }
    const syncedXPositions = syncedGraph.nodes.map((item) => item.position.x);
    expect(syncedXPositions[0]).toBe(0);
    expect(syncedXPositions[1]).toBeGreaterThan(syncedXPositions[0]);
    expect(syncedXPositions[2]).toBeGreaterThan(syncedXPositions[1]);

    const state = useWorkflowStore.getState();
    expect(state.activeWorkflowId).toBe('workflow-new');
    expect(state.nodes.map((item) => item.id)).toEqual([
      'new-input',
      'new-llm',
      'new-answer',
    ]);
    expect(state.nodes.map((item) => item.position.x)).toEqual(syncedXPositions);
    expect(
      state.workflows.find((workflow) => workflow.id === 'workflow-new')?.nodes.map(
        (item) => item.position.x,
      ),
    ).toEqual(syncedXPositions);
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
      clarification_options: [],
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
      clarification_options: [],
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

  it('Knowledge Base clarification 후보를 선택 가능한 정보로 표시한다', async () => {
    vi.mocked(agentBuilderApi.createSession).mockResolvedValue({
      session_id: 'session-kb-options',
      workflow_id: 'workflow-old',
      app_id: 'app-1',
      status: 'active',
      messages: [],
      pending_request: null,
      draft_preview: null,
    });
    vi.mocked(agentBuilderApi.sendMessage).mockResolvedValue({
      request_id: 'request-kb-options',
      status: 'clarification_required',
      structured_request: null,
      clarification_questions: ['사용할 Knowledge Base를 선택해주세요.'],
      clarification_options: [
        {
          candidate_id: 'safe-rec-1',
          label: '휴가 정책',
          confidence: 'high',
          score: 0.7,
          reason_category: 'topic_keyword_match',
        },
        {
          candidate_id: 'safe-rec-2',
          label: '인사 정책',
          confidence: 'high',
          score: 0.66,
          reason_category: 'metadata_match',
        },
      ],
      draft_preview: null,
      validation_result: null,
      preview_prompt: null,
      warnings: ['Knowledge Base 후보가 비슷해 자동 선택하지 않았습니다.'],
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
      target: { value: '휴가 정책을 찾아서 요약해줘' },
    });
    fireEvent.keyDown(screen.getByRole('textbox'), {
      key: 'Enter',
      code: 'Enter',
    });

    expect(await screen.findByText('휴가 정책')).toBeTruthy();
    expect(screen.getByText('인사 정책')).toBeTruthy();
    expect(screen.getByText(/점수 0.70/)).toBeTruthy();
    expect(screen.getByText(/점수 0.66/)).toBeTruthy();
  });

  it('Knowledge Base 후보를 선택한 뒤 safe handle로 도안 생성을 요청한다', async () => {
    vi.mocked(agentBuilderApi.createSession).mockResolvedValue({
      session_id: 'session-kb-confirm',
      workflow_id: 'workflow-old',
      app_id: 'app-1',
      status: 'active',
      messages: [],
      pending_request: null,
      draft_preview: null,
    });
    vi.mocked(agentBuilderApi.sendMessage)
      .mockResolvedValueOnce({
        request_id: 'request-kb-clarify',
        status: 'clarification_required',
        structured_request: null,
        clarification_questions: ['사용할 Knowledge Base를 선택해주세요.'],
        clarification_options: [
          {
            candidate_id: 'safe-rec-1',
            resolution_id: 'resolve-kb-1',
            requirement_id: 'kr-1',
            label: '휴가 정책',
            confidence: 'high',
            score: 0.7,
            reason_category: 'topic_keyword_match',
          },
        ],
        draft_preview: null,
        validation_result: null,
        preview_prompt: null,
        warnings: [],
      })
      .mockResolvedValueOnce({
        request_id: 'request-kb-draft',
        status: 'draft_ready',
        structured_request: null,
        clarification_questions: [],
        clarification_options: [],
        draft_preview: null,
        validation_result: { valid: true, issues: [] },
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
      target: { value: 'Find the policy knowledge base and summarize it' },
    });
    fireEvent.keyDown(screen.getByRole('textbox'), {
      key: 'Enter',
      code: 'Enter',
    });

    fireEvent.click(await screen.findByRole('button', { name: /휴가 정책/ }));
    fireEvent.click(screen.getByLabelText('Agent Builder 요청 보내기'));

    await waitFor(() => {
      expect(agentBuilderApi.sendMessage).toHaveBeenLastCalledWith(
        'session-kb-confirm',
        expect.objectContaining({
          message: 'Find the policy knowledge base and summarize it',
          selectedKnowledgeCandidate: {
            candidate_id: 'safe-rec-1',
            resolution_id: 'resolve-kb-1',
            requirement_id: 'kr-1',
          },
        }),
      );
    });
  });

  it('Knowledge Base 없이 생성 선택도 safe handle로 도안 생성을 요청한다', async () => {
    vi.mocked(agentBuilderApi.createSession).mockResolvedValue({
      session_id: 'session-kb-none',
      workflow_id: 'workflow-old',
      app_id: 'app-1',
      status: 'active',
      messages: [],
      pending_request: null,
      draft_preview: null,
    });
    vi.mocked(agentBuilderApi.sendMessage)
      .mockResolvedValueOnce({
        request_id: 'request-kb-none-clarify',
        status: 'clarification_required',
        structured_request: null,
        clarification_questions: ['사용할 Knowledge Base를 선택해주세요.'],
        clarification_options: [
          {
            type: 'no_knowledge_base',
            candidate_id: '__agent_builder_no_kb__',
            resolution_id: 'resolve-kb-1',
            requirement_id: 'kr-1',
            label: 'Knowledge Base 없이 생성',
            safe_label: 'Knowledge Base 없이 생성',
            confidence: 'user_choice',
            score: null,
            reason_category: 'user_selected_no_kb',
            threshold_result: 'user_selected',
            runtime_availability: 'not_applicable',
          },
        ],
        draft_preview: null,
        validation_result: null,
        preview_prompt: null,
        warnings: [],
      })
      .mockResolvedValueOnce({
        request_id: 'request-kb-none-draft',
        status: 'draft_ready',
        structured_request: null,
        clarification_questions: [],
        clarification_options: [],
        draft_preview: null,
        validation_result: { valid: true, issues: [] },
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
      target: { value: 'Find the policy knowledge base and summarize it' },
    });
    fireEvent.keyDown(screen.getByRole('textbox'), {
      key: 'Enter',
      code: 'Enter',
    });

    fireEvent.click(
      await screen.findByRole('button', { name: /Knowledge Base 없이 생성/ }),
    );
    fireEvent.click(screen.getByLabelText('Agent Builder 요청 보내기'));

    await waitFor(() => {
      expect(agentBuilderApi.sendMessage).toHaveBeenLastCalledWith(
        'session-kb-none',
        expect.objectContaining({
          message: 'Find the policy knowledge base and summarize it',
          selectedKnowledgeCandidate: {
            candidate_id: '__agent_builder_no_kb__',
            resolution_id: 'resolve-kb-1',
            requirement_id: 'kr-1',
          },
        }),
      );
    });
  });

  it('session restore는 redacted 사용자 메시지와 assistant 응답을 함께 복원한다', async () => {
    window.localStorage.setItem(
      'agent-builder:workflow-old:app-1',
      'session-restore',
    );
    vi.mocked(agentBuilderApi.getSession).mockResolvedValue({
      session_id: 'session-restore',
      workflow_id: 'workflow-old',
      app_id: 'app-1',
      status: 'active',
      messages: [
        {
          kind: 'user',
          request_id: 'request-restore',
          content: '휴가 정책을 찾아서 요약해줘',
          redacted: true,
        },
        {
          kind: 'assistant',
          request_id: 'request-restore',
          response: {
            request_id: 'request-restore',
            status: 'clarification_required',
            structured_request: null,
            clarification_questions: ['사용할 Knowledge Base를 선택해주세요.'],
            clarification_options: [],
            draft_preview: null,
            validation_result: null,
            preview_prompt: null,
            warnings: [],
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

    expect(await screen.findByText('휴가 정책을 찾아서 요약해줘')).toBeTruthy();
    expect(screen.getByText('사용할 Knowledge Base를 선택해주세요.')).toBeTruthy();
  });

  it('validation을 통과하지 못한 draft에는 도안 생성 미리보기 버튼을 노출하지 않는다', async () => {
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
          clarification_options: [],
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
    expect(
      screen.queryByRole('button', { name: '도안 생성 미리보기' }),
    ).toBeNull();
  });

  it('도안 생성 미리보기 중에는 버튼을 비활성화하고 취소 후 같은 도안을 다시 열 수 있다', async () => {
    window.localStorage.setItem(
      'agent-builder:workflow-old:app-1',
      'session-reopen',
    );
    vi.mocked(agentBuilderApi.getSession).mockResolvedValue({
      session_id: 'session-reopen',
      workflow_id: 'workflow-old',
      app_id: 'app-1',
      status: 'active',
      messages: [
        {
          request_id: 'request-reopen',
          status: 'draft_ready',
          clarification_questions: [],
          clarification_options: [],
          warnings: [],
          draft_preview: {
            draft_id: 'draft-reopen',
            preview_graph: {
              nodes: [node('preview-node')],
              edges: [],
              viewport: { x: 0, y: 0, zoom: 1 },
            },
            base_graph_hash: 'base-hash',
            draft_mode: 'new_workflow',
            node_detail_previews: [],
            validation_result: { valid: true, issues: [] },
            safety_notices: [],
          },
        },
      ],
      pending_request: null,
      draft_preview: null,
    });
    vi.mocked(agentBuilderApi.recordPreviewOpened).mockResolvedValue(undefined);

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

    const previewButton = await screen.findByRole('button', {
      name: '도안 생성 미리보기',
    });
    fireEvent.click(previewButton);

    await waitFor(() => {
      expect(agentBuilderApi.recordPreviewOpened).toHaveBeenCalledTimes(1);
    });
    expect(
      screen.getByRole('button', { name: '도안 생성 미리보기' }),
    ).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: '취소' }));

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: '도안 생성 미리보기' }),
      ).not.toBeDisabled();
    });
    expect(agentBuilderApi.cancelDraft).toHaveBeenCalledWith('draft-reopen');

    fireEvent.click(
      screen.getByRole('button', { name: '도안 생성 미리보기' }),
    );

    await waitFor(() => {
      expect(agentBuilderApi.recordPreviewOpened).toHaveBeenCalledTimes(2);
    });
  });

  it('session top-level draft_preview만 있어도 도안 생성 미리보기를 복구한다', async () => {
    window.localStorage.setItem(
      'agent-builder:workflow-old:app-1',
      'session-top-level-draft',
    );
    vi.mocked(agentBuilderApi.getSession).mockResolvedValue({
      session_id: 'session-top-level-draft',
      workflow_id: 'workflow-old',
      app_id: 'app-1',
      status: 'active',
      messages: [],
      pending_request: null,
      draft_preview: {
        draft_id: 'draft-top-level',
        preview_graph: {
          nodes: [node('preview-node')],
          edges: [],
          viewport: { x: 0, y: 0, zoom: 1 },
        },
        base_graph_hash: 'base-hash',
        draft_mode: 'new_workflow',
        node_detail_previews: [],
        validation_result: { valid: true, issues: [] },
        safety_notices: [],
      },
    });
    vi.mocked(agentBuilderApi.recordPreviewOpened).mockResolvedValue(undefined);

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

    const previewButton = await screen.findByRole('button', {
      name: '도안 생성 미리보기',
    });
    fireEvent.click(previewButton);

    await waitFor(() => {
      expect(agentBuilderApi.recordPreviewOpened).toHaveBeenCalledWith(
        'draft-top-level',
      );
    });
  });

  it('Preview Mode 중 새 요청을 보내면 이전 preview를 종료한다', async () => {
    vi.mocked(agentBuilderApi.createSession).mockResolvedValue({
      session_id: 'session-preview-supersede',
      workflow_id: 'workflow-old',
      app_id: 'app-1',
      status: 'active',
      messages: [],
      pending_request: null,
      draft_preview: null,
    });
    vi.mocked(agentBuilderApi.sendMessage).mockResolvedValue({
      request_id: 'request-next',
      status: 'draft_ready',
      structured_request: null,
      clarification_questions: [],
      clarification_options: [],
      draft_preview: null,
      validation_result: { valid: true, issues: [] },
      preview_prompt: null,
      warnings: [],
    });
    useWorkflowStore.setState({
      agentBuilderPreview: {
        draftId: 'draft-current',
        previewGraph: { nodes: [node('preview-node')], edges: [] },
        nodeDetailPreviews: [],
        validationResult: { valid: true, issues: [] },
        baseGraphHash: 'base-hash',
        draftMode: 'new_workflow',
      },
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
      target: { value: '새 도안을 만들어줘' },
    });
    fireEvent.keyDown(screen.getByRole('textbox'), {
      key: 'Enter',
      code: 'Enter',
    });

    await waitFor(() => {
      expect(agentBuilderApi.sendMessage).toHaveBeenCalled();
    });
    expect(useWorkflowStore.getState().agentBuilderPreview).toBeNull();
  });
});
