import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AgentBuilderPanel } from './AgentBuilderPanel';
import { useWorkflowStore } from '../../store/useWorkflowStore';
import { agentBuilderApi } from '../../api/agentBuilderApi';
import { workflowApi } from '../../api/workflowApi';
import type { Edge, Node } from '../../types/Workflow';

const routerPush = vi.fn();
const setViewport = vi.fn();
const fitView = vi.fn();

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
      fitView,
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
    getModelOptions: vi.fn(),
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
    window.sessionStorage.clear();
    useWorkflowStore.setState(initialState, true);
    vi.mocked(workflowApi.syncDraftWorkflow).mockResolvedValue({});
    vi.mocked(agentBuilderApi.getModelOptions).mockResolvedValue([
      {
        provider_name: 'openai',
        unavailable_reason: null,
        options: [
          {
            model: {
              id: 'model-openai',
              model_id_for_api_call: 'gpt-5.5-pro',
              name: 'GPT-5.5 Pro',
              provider_name: 'openai',
            },
            credential: {
              id: 'credential-openai',
              credential_name: 'OpenAI Main',
            },
            relation_priority: 0,
          },
        ],
      },
      {
        provider_name: 'anthropic',
        unavailable_reason: null,
        options: [
          {
            model: {
              id: 'model-anthropic',
              model_id_for_api_call: 'claude-sonnet-5',
              name: 'Claude Sonnet 5',
              provider_name: 'anthropic',
            },
            credential: {
              id: 'credential-anthropic',
              credential_name: 'Anthropic Main',
            },
            relation_priority: 0,
          },
        ],
      },
      { provider_name: 'google', unavailable_reason: 'no_authorized_model', options: [] },
      { provider_name: 'llamaparse', unavailable_reason: 'chat_model_not_supported', options: [] },
    ]);
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

  it('Agent Builder 패널을 최소화했다가 다시 펼친다', async () => {
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
    await screen.findByRole('button', {
      name: /Agent Builder 모델: GPT-5.5 Pro/,
    });
    expect(screen.getByText('Agent Builder')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Agent Builder 최소화'));
    expect(screen.queryByText('Agent Builder')).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Agent Builder 펼치기'));
    expect(screen.getByText('Agent Builder')).toBeInTheDocument();
  });

  it('credential 허용 모델을 provider 순서로 표시하고 선택 모델을 요청에 포함한다', async () => {
    vi.mocked(agentBuilderApi.createSession).mockResolvedValue({
      session_id: 'session-model',
      status: 'active',
      messages: [],
    });
    vi.mocked(agentBuilderApi.sendMessage).mockResolvedValue({
      request_id: 'request-model',
      status: 'unsupported',
      clarification_questions: [],
      clarification_options: [],
      warnings: [],
    });

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
    await screen.findByRole('button', { name: /Agent Builder 모델: GPT-5.5 Pro/ });
    fireEvent.click(
      screen.getByRole('button', { name: /Agent Builder 모델: GPT-5.5 Pro/ }),
    );

    expect(
      screen.getAllByTestId('agent-builder-model-provider').map((item) => item.textContent),
    ).toEqual(['openai', 'anthropic', 'google', 'llamaparse']);
    fireEvent.click(screen.getByRole('button', { name: /Claude Sonnet 5/ }));

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: '입력과 응답 노드를 만들어줘' },
    });
    fireEvent.click(screen.getByLabelText('Agent Builder 요청 보내기'));

    await waitFor(() => {
      expect(agentBuilderApi.sendMessage).toHaveBeenCalledWith(
        'session-model',
        expect.objectContaining({
          intentModelSelection: {
            credentialId: 'credential-anthropic',
            modelId: 'model-anthropic',
          },
        }),
      );
    });
  });

  it('사용 가능한 intent model이 없으면 hidden fallback 없이 요청을 차단한다', async () => {
    vi.mocked(agentBuilderApi.getModelOptions).mockResolvedValue([
      { provider_name: 'openai', unavailable_reason: 'no_authorized_model', options: [] },
      { provider_name: 'anthropic', unavailable_reason: 'no_authorized_model', options: [] },
      { provider_name: 'google', unavailable_reason: 'no_authorized_model', options: [] },
      {
        provider_name: 'llamaparse',
        unavailable_reason: 'chat_model_not_supported',
        options: [],
      },
    ]);

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
    await screen.findByRole('button', {
      name: /Agent Builder 모델: 선택 필요/,
    });
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: '입력과 응답 노드를 만들어줘' },
    });
    fireEvent.click(screen.getByLabelText('Agent Builder 요청 보내기'));

    await waitFor(() => {
      expect(agentBuilderApi.getModelOptions).toHaveBeenCalled();
    });
    expect(agentBuilderApi.createSession).not.toHaveBeenCalled();
    expect(agentBuilderApi.sendMessage).not.toHaveBeenCalled();
  });

  it('loads the saved graph when Agent Builder creates a new workflow', async () => {
    const oldNodes = [node('old-node')];
    const newNodes = [
      node('new-input'),
      node('new-llm', 'llmNode'),
      node('new-answer', 'answerNode'),
    ];
    const savedNodes = [
      { ...node('new-input'), position: { x: 0, y: 0 } },
      { ...node('new-llm', 'llmNode'), position: { x: 360, y: 0 } },
      { ...node('new-answer', 'answerNode'), position: { x: 720, y: 0 } },
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
      nodes: savedNodes,
      edges: newEdges,
      viewport: { x: 10, y: 10, zoom: 1 },
      features: { nextNodeDisplayNumber: 2 },
    });
    vi.mocked(workflowApi.getWorkflow).mockResolvedValue({
      app_id: 'app-1',
    });
    window.localStorage.setItem(
      'agent-builder:workflow:workflow-old',
      'session-new-workflow',
    );
    vi.mocked(agentBuilderApi.getSession).mockResolvedValue({
      session_id: 'session-new-workflow',
      workflow_id: 'workflow-old',
      app_id: 'app-1',
      status: 'active',
      messages: [
        {
          kind: 'user',
          request_id: 'request-new-workflow',
          content: 'Create a new workflow and keep this conversation',
          redacted: true,
        },
      ],
      pending_request: null,
      draft_preview: null,
    });

    const { rerender, unmount } = render(
      <AgentBuilderPanel
        workflowId="workflow-old"
        appId="app-1"
        nodes={oldNodes}
        edges={[]}
        hasUnsavedChanges={false}
      />,
    );

    fireEvent.click(screen.getByLabelText('Agent Builder 열기'));
    await screen.findByText('Create a new workflow and keep this conversation');
    fireEvent.click(screen.getByRole('button', { name: '적용 및 저장' }));

    await waitFor(() => {
      expect(routerPush).toHaveBeenCalledWith('/modules/workflow-new');
    });

    expect(agentBuilderApi.applyDraft).toHaveBeenCalledWith('draft-new', {
      clientPreviewGraphHash: expect.any(String),
      clientLatestGraphHash: expect.any(String),
    });
    expect(workflowApi.syncDraftWorkflow).not.toHaveBeenCalled();
    expect(
      window.localStorage.getItem('agent-builder:workflow:workflow-new'),
    ).toBe('session-new-workflow');
    expect(
      window.localStorage.getItem('agent-builder:workflow:workflow-old'),
    ).toBeNull();
    expect(
      window.sessionStorage.getItem('agent-builder:reopen:workflow-new'),
    ).not.toBeNull();

    const state = useWorkflowStore.getState();
    expect(state.activeWorkflowId).toBe('workflow-new');
    expect(state.nodes.map((item) => item.id)).toEqual([
      'new-input',
      'new-llm',
      'new-answer',
    ]);
    expect(state.nodes.map((item) => item.position)).toEqual(
      savedNodes.map((item) => item.position),
    );
    expect(
      state.workflows.find((workflow) => workflow.id === 'workflow-new')?.nodes.map(
        (item) => item.position,
      ),
    ).toEqual(savedNodes.map((item) => item.position));
    await waitFor(() => {
      expect(fitView).toHaveBeenCalledWith({
        padding: 0.2,
        duration: 300,
        maxZoom: 1,
      });
    });

    rerender(
      <AgentBuilderPanel
        workflowId="workflow-new"
        appId="app-1"
        nodes={savedNodes}
        edges={newEdges}
        hasUnsavedChanges={false}
      />,
    );
    expect(
      window.sessionStorage.getItem('agent-builder:reopen:workflow-new'),
    ).not.toBeNull();

    unmount();
    render(
      <AgentBuilderPanel
        workflowId="workflow-new"
        appId="app-1"
        nodes={savedNodes}
        edges={newEdges}
        hasUnsavedChanges={false}
      />,
    );

    await screen.findByText('Create a new workflow and keep this conversation');
    expect(
      window.sessionStorage.getItem('agent-builder:reopen:workflow-new'),
    ).toBeNull();
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

  it('workflow가 없는 app scope가 바뀌면 기존 preview 상태를 제거한다', async () => {
    const oldNodes = [node('old-node')];
    setPreviewState(oldNodes);

    const { rerender } = render(
      <AgentBuilderPanel
        workflowId=""
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
        workflowId=""
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
        selectedKnowledgeCandidate: undefined,
        selectedKnowledgeCandidates: undefined,
        intentModelSelection: {
          credentialId: 'credential-openai',
          modelId: 'model-openai',
        },
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

  it('같은 workflow의 app metadata가 채워져도 열린 패널과 대화를 유지한다', async () => {
    vi.mocked(agentBuilderApi.createSession).mockResolvedValue({
      session_id: 'session-app-hydration',
      workflow_id: 'workflow-old',
      app_id: 'app-1',
      status: 'active',
      messages: [],
      pending_request: null,
      draft_preview: null,
    });
    vi.mocked(agentBuilderApi.sendMessage).mockResolvedValue({
      request_id: 'request-app-hydration',
      status: 'clarification_required',
      structured_request: null,
      clarification_questions: ['추가 정보를 알려주세요.'],
      clarification_options: [],
      draft_preview: null,
      validation_result: null,
      preview_prompt: null,
      warnings: [],
    });

    const { rerender } = render(
      <AgentBuilderPanel
        workflowId="workflow-old"
        appId={null}
        nodes={[]}
        edges={[]}
        hasUnsavedChanges={false}
      />,
    );

    fireEvent.click(screen.getByLabelText('Agent Builder 열기'));
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'Keep this conversation after save' },
    });
    fireEvent.keyDown(screen.getByRole('textbox'), {
      key: 'Enter',
      code: 'Enter',
    });

    await screen.findByText('Keep this conversation after save');
    rerender(
      <AgentBuilderPanel
        workflowId="workflow-old"
        appId="app-1"
        nodes={[]}
        edges={[]}
        hasUnsavedChanges={false}
      />,
    );

    expect(screen.getByText('Keep this conversation after save')).toBeTruthy();
    expect(screen.getByRole('textbox')).toBeTruthy();
  });

  it('workflow target clarification에서 node를 선택해 같은 수정 요청을 재전송한다', async () => {
    vi.mocked(agentBuilderApi.createSession).mockResolvedValue({
      session_id: 'session-target',
      workflow_id: 'workflow-old',
      app_id: 'app-1',
      status: 'active',
      messages: [],
      pending_request: null,
      draft_preview: null,
    });
    vi.mocked(agentBuilderApi.sendMessage)
      .mockResolvedValueOnce({
        request_id: 'request-target-clarification',
        status: 'clarification_required',
        structured_request: null,
        clarification_questions: ['수정 대상 node를 선택해주세요.'],
        clarification_options: [
          {
            type: 'workflow_node',
            node_id: 'github-read-1',
            node_type: 'githubNode',
            label: 'GitHub PR 조회 1',
          },
          {
            type: 'workflow_node',
            node_id: 'github-read-2',
            node_type: 'githubNode',
            label: 'GitHub PR 조회 2',
          },
        ],
        draft_preview: null,
        validation_result: {
          valid: false,
          issues: [
            {
              code: 'WORKFLOW_TARGET_UNRESOLVED',
              message: '기존 workflow 수정 대상을 확인해야 합니다.',
            },
          ],
        },
        preview_prompt: null,
        warnings: [],
      })
      .mockResolvedValueOnce({
        request_id: 'request-target-resolved',
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
      target: { value: 'github 노드 뒤에 LLM 노드를 추가해줘' },
    });
    fireEvent.keyDown(screen.getByRole('textbox'), {
      key: 'Enter',
      code: 'Enter',
    });

    const targetButton = await screen.findByRole('button', {
      name: /GitHub PR 조회 2/,
    });
    expect(screen.queryByTestId('agent-builder-kb-candidate-list')).toBeNull();
    fireEvent.click(targetButton);

    await waitFor(() => {
      expect(agentBuilderApi.sendMessage).toHaveBeenLastCalledWith(
        'session-target',
        expect.objectContaining({
          message: 'github 노드 뒤에 LLM 노드를 추가해줘',
          selectedNodeId: 'github-read-2',
          selectedKnowledgeCandidate: undefined,
          selectedKnowledgeCandidates: undefined,
        }),
      );
    });
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
        {
          candidate_id: 'safe-rec-3',
          label: '총무 정책',
          confidence: 'medium',
          score: 0.58,
          reason_category: 'metadata_match',
        },
        {
          type: 'no_knowledge_base',
          candidate_id: '__agent_builder_no_kb__',
          label: 'Knowledge Base 없이 생성',
          confidence: 'user_choice',
          score: null,
          reason_category: 'user_selected_no_kb',
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
    expect(screen.getByText('총무 정책')).toBeTruthy();
    expect(screen.queryByText('Knowledge Base 없이 생성')).toBeNull();
    expect(screen.getByText(/점수 0.70/)).toBeTruthy();
    expect(screen.getByText(/점수 0.66/)).toBeTruthy();
    const candidateList = screen.getByTestId('agent-builder-kb-candidate-list');
    expect(candidateList.className).toContain('max-h-[13.5rem]');
    expect(candidateList.className).toContain('overflow-y-auto');
  });

  it('새 요청과 응답이 추가되면 대화 영역을 맨 아래로 스크롤한다', async () => {
    vi.mocked(agentBuilderApi.createSession).mockResolvedValue({
      session_id: 'session-scroll',
      workflow_id: 'workflow-old',
      app_id: 'app-1',
      status: 'active',
      messages: [],
      pending_request: null,
      draft_preview: null,
    });
    vi.mocked(agentBuilderApi.sendMessage).mockResolvedValue({
      request_id: 'request-scroll',
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
    const conversation = screen.getByTestId('agent-builder-conversation');
    Object.defineProperty(conversation, 'scrollHeight', {
      configurable: true,
      value: 480,
    });

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: '새 workflow를 만들어줘' },
    });
    fireEvent.keyDown(screen.getByRole('textbox'), {
      key: 'Enter',
      code: 'Enter',
    });

    await waitFor(() => {
      expect(agentBuilderApi.sendMessage).toHaveBeenCalled();
      expect(conversation.scrollTop).toBe(480);
    });
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
          selectedKnowledgeCandidates: [
            {
              candidate_id: 'safe-rec-1',
              resolution_id: 'resolve-kb-1',
              requirement_id: 'kr-1',
            },
          ],
        }),
      );
    });
  });

  it('KB 선택으로 도안을 만든 뒤에는 빈 입력으로 같은 요청을 다시 제출할 수 없다', async () => {
    vi.mocked(agentBuilderApi.createSession).mockResolvedValue({
      session_id: 'session-kb-no-repeat',
      workflow_id: 'workflow-old',
      app_id: 'app-1',
      status: 'active',
      messages: [],
      pending_request: null,
      draft_preview: null,
    });
    vi.mocked(agentBuilderApi.sendMessage)
      .mockResolvedValueOnce({
        request_id: 'request-kb-no-repeat-clarify',
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
        request_id: 'request-kb-no-repeat-draft',
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
      target: { value: '휴가 정책을 찾아서 요약해줘' },
    });
    fireEvent.keyDown(screen.getByRole('textbox'), {
      key: 'Enter',
      code: 'Enter',
    });

    fireEvent.click(await screen.findByRole('button', { name: /휴가 정책/ }));
    fireEvent.click(screen.getByLabelText('Agent Builder 요청 보내기'));

    await waitFor(() => {
      expect(agentBuilderApi.sendMessage).toHaveBeenCalledTimes(2);
    });
    expect(
      screen.getByLabelText('Agent Builder 요청 보내기'),
    ).toBeDisabled();
  });

  it('Knowledge Base 후보를 여러 개 선택해 도안 생성을 요청한다', async () => {
    vi.mocked(agentBuilderApi.createSession).mockResolvedValue({
      session_id: 'session-kb-multi',
      workflow_id: 'workflow-old',
      app_id: 'app-1',
      status: 'active',
      messages: [],
      pending_request: null,
      draft_preview: null,
    });
    vi.mocked(agentBuilderApi.sendMessage)
      .mockResolvedValueOnce({
        request_id: 'request-kb-multi-clarify',
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
          {
            candidate_id: 'safe-rec-2',
            resolution_id: 'resolve-kb-1',
            requirement_id: 'kr-1',
            label: '인사 정책',
            confidence: 'high',
            score: 0.66,
            reason_category: 'metadata_match',
          },
        ],
        draft_preview: null,
        validation_result: null,
        preview_prompt: null,
        warnings: [],
      })
      .mockResolvedValueOnce({
        request_id: 'request-kb-multi-draft',
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
    fireEvent.click(screen.getByRole('button', { name: /인사 정책/ }));
    fireEvent.click(screen.getByLabelText('Agent Builder 요청 보내기'));

    await waitFor(() => {
      expect(agentBuilderApi.sendMessage).toHaveBeenLastCalledWith(
        'session-kb-multi',
        expect.objectContaining({
          message: 'Find the policy knowledge base and summarize it',
          selectedKnowledgeCandidate: undefined,
          selectedKnowledgeCandidates: [
            {
              candidate_id: 'safe-rec-1',
              resolution_id: 'resolve-kb-1',
              requirement_id: 'kr-1',
            },
            {
              candidate_id: 'safe-rec-2',
              resolution_id: 'resolve-kb-1',
              requirement_id: 'kr-1',
            },
          ],
        }),
      );
    });
  });

  it('Knowledge Base 후보를 선택하지 않으면 빈 선택으로 도안 생성을 요청한다', async () => {
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
            type: 'knowledge_base',
            candidate_id: 'safe-rec-1',
            resolution_id: 'resolve-kb-1',
            requirement_id: 'kr-1',
            label: '휴가 정책',
            safe_label: '휴가 정책',
            confidence: 'high',
            score: 0.7,
            reason_category: 'topic_keyword_match',
            threshold_result: 'clarification_required',
            runtime_availability: 'available',
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

    expect(await screen.findByRole('button', { name: /휴가 정책/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Knowledge Base 없이 생성/ })).toBeNull();
    fireEvent.click(screen.getByLabelText('Agent Builder 요청 보내기'));

    await waitFor(() => {
      expect(agentBuilderApi.sendMessage).toHaveBeenLastCalledWith(
        'session-kb-none',
        expect.objectContaining({
          message: 'Find the policy knowledge base and summarize it',
          selectedKnowledgeCandidate: undefined,
          selectedKnowledgeCandidates: [],
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
        safety_notices: [
          '초안 생성 중에는 외부 시스템을 호출하지 않습니다.',
        ],
        configuration_issues: [
          {
            node_id: 'github-read',
            node_type: 'githubNode',
            node_label: 'GitHub PR 조회',
            capability: 'github_pr_read',
            missing_parameters: [
              { key: 'credential', label: 'GitHub credential' },
              { key: 'repo_owner', label: 'Repository owner' },
              { key: 'repo_name', label: 'Repository name' },
              { key: 'pr_number', label: 'PR 번호' },
            ],
          },
          {
            node_id: 'github-comment',
            node_type: 'githubNode',
            node_label: 'GitHub PR 댓글 등록',
            capability: 'github_pr_comment',
            missing_parameters: [
              { key: 'credential', label: 'GitHub credential' },
              { key: 'repo_owner', label: 'Repository owner' },
              { key: 'repo_name', label: 'Repository name' },
              { key: 'pr_number', label: 'PR 번호' },
            ],
          },
        ],
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
    expect(screen.getByText('GitHub PR 조회')).toBeInTheDocument();
    expect(screen.getByText('GitHub PR 댓글 등록')).toBeInTheDocument();
    expect(screen.getAllByText('필요한 파라미터')).toHaveLength(2);
    expect(screen.getAllByText('GitHub credential')).toHaveLength(2);
    expect(screen.getAllByText('Repository owner')).toHaveLength(2);
    expect(screen.getAllByText('PR 번호')).toHaveLength(2);
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

  it('저장되지 않은 변경이 있으면 적용 및 저장을 호출하지 않는다', async () => {
    setPreviewState([node('preview-node')]);

    render(
      <AgentBuilderPanel
        workflowId="workflow-old"
        appId="app-1"
        nodes={[node('actual-node')]}
        edges={[]}
        hasUnsavedChanges
      />,
    );

    fireEvent.click(screen.getByLabelText('Agent Builder 열기'));
    await screen.findByRole('button', {
      name: /Agent Builder 모델: GPT-5.5 Pro/,
    });

    expect(
      screen.getByText(
        '저장되지 않은 변경이 있어 초안 생성, 도안 생성 미리보기, 적용 및 저장이 차단됩니다.',
      ),
    ).toBeTruthy();
    expect(
      screen.getByRole('button', { name: '적용 및 저장' }),
    ).toBeDisabled();
    expect(agentBuilderApi.applyDraft).not.toHaveBeenCalled();
    expect(useWorkflowStore.getState().agentBuilderPreview?.draftId).toBe(
      'draft-new',
    );
  });

  it('backend가 적용을 차단하면 안내를 표시하고 preview graph를 유지한다', async () => {
    setPreviewState([node('preview-node')]);
    vi.mocked(agentBuilderApi.applyDraft).mockResolvedValue({
      apply_id: 'apply-blocked',
      outcome: 'blocked',
      block_reason: 'DRAFT_STALE',
      stale_state: 'stale',
      permission_recheck_outcome: 'allowed',
      validation_state: 'valid',
      audit_recorded: true,
      layout_optimization_applied: false,
      notices: ['workflow가 변경되어 도안을 다시 생성해야 합니다.'],
    });

    render(
      <AgentBuilderPanel
        workflowId="workflow-old"
        appId="app-1"
        nodes={[node('actual-node')]}
        edges={[]}
        hasUnsavedChanges={false}
      />,
    );

    fireEvent.click(screen.getByLabelText('Agent Builder 열기'));
    fireEvent.click(screen.getByRole('button', { name: '적용 및 저장' }));

    expect(
      await screen.findByText('workflow가 변경되어 도안을 다시 생성해야 합니다.'),
    ).toBeTruthy();
    expect(workflowApi.getDraftWorkflow).not.toHaveBeenCalled();
    expect(useWorkflowStore.getState().agentBuilderPreview?.draftId).toBe(
      'draft-new',
    );
  });

  it('backend 저장이 실패하면 실패 안내를 표시하고 preview graph를 유지한다', async () => {
    setPreviewState([node('preview-node')]);
    vi.mocked(agentBuilderApi.applyDraft).mockResolvedValue({
      apply_id: 'apply-failed',
      outcome: 'failed',
      failure_reason: 'SAVE_FAILED',
      stale_state: 'not_stale',
      permission_recheck_outcome: 'allowed',
      validation_state: 'valid',
      audit_recorded: false,
      layout_optimization_applied: false,
      notices: ['초안 저장에 실패했습니다. 다시 시도해주세요.'],
    });

    render(
      <AgentBuilderPanel
        workflowId="workflow-old"
        appId="app-1"
        nodes={[node('actual-node')]}
        edges={[]}
        hasUnsavedChanges={false}
      />,
    );

    fireEvent.click(screen.getByLabelText('Agent Builder 열기'));
    fireEvent.click(screen.getByRole('button', { name: '적용 및 저장' }));

    expect(
      await screen.findByText('초안 저장에 실패했습니다. 다시 시도해주세요.'),
    ).toBeTruthy();
    expect(workflowApi.getDraftWorkflow).not.toHaveBeenCalled();
    expect(useWorkflowStore.getState().agentBuilderPreview?.draftId).toBe(
      'draft-new',
    );
  });
});
