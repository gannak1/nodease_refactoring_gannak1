import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { NodeInlinePanel } from '../../components/nodes/NodeInlinePanel';
import { useWorkflowStore } from '../../store/useWorkflowStore';
import type { AppNode, LLMNodeData } from '../../types/Nodes';

const workflowApiMock = vi.hoisted(() => ({
  getCostOptimizerAvailability: vi.fn(),
  getModelRoutingPolicy: vi.fn(),
  patchModelRoutingPolicy: vi.fn(),
  refreshModelRoutingPolicy: vi.fn(),
}));

vi.mock('../../components/nodes/llm/components/ModelSelectDropdown', () => ({
  ModelSelectDropdown: ({
    value,
    onChange,
    disabled,
    placeholder,
  }: {
    value: string;
    onChange: (value: string) => void;
    disabled?: boolean;
    placeholder?: string;
  }) => (
    <select
      aria-label={placeholder || '모델 선택'}
      disabled={disabled}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="">모델 없음</option>
      <option value="gpt-4.1">GPT-4.1</option>
      <option value="gpt-4.1-mini">GPT-4.1 mini</option>
    </select>
  ),
}));

vi.mock('../../components/modals/PromptWizardModal', () => ({
  PromptWizardModal: () => null,
}));

vi.mock('../../components/nodes/ui/VariableTokenEditor', () => ({
  VariableTokenEditor: ({
    ariaLabel,
    value,
    onChange,
  }: {
    ariaLabel: string;
    value: string;
    onChange: (value: string) => void;
  }) => (
    <textarea
      aria-label={ariaLabel}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  ),
}));

vi.mock('../../components/nodes/ui/PropertyVisibilityToggle', () => ({
  PropertyVisibilityToggle: () => null,
}));

vi.mock('../../api/workflowApi', () => ({
  workflowApi: workflowApiMock,
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const initialState = useWorkflowStore.getState();

const createLlmNode = (data: Partial<LLMNodeData> = {}): AppNode =>
  ({
    id: 'llm-1',
    type: 'llmNode',
    position: { x: 0, y: 0 },
    data: {
      title: '비용 비교 대상',
      provider: 'openai',
      model_id: 'gpt-4.1',
      fallback_model_id: '',
      task_type: 'generate',
      system_prompt: '너는 고객 응대 담당자다.',
      user_prompt: '고객 문의를 처리해줘.',
      assistant_prompt: '',
      referenced_variables: [],
      parameters: { max_tokens: 800, temperature: 0.2 },
      knowledgeBases: [],
      ...data,
    },
  }) as AppNode;

describe('FR-003 LLM node model routing optimization entry', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    workflowApiMock.getCostOptimizerAvailability.mockResolvedValue({
      available: true,
      reason: null,
      workflow_id: 'workflow-1',
      node_id: 'llm-1',
      node_type: 'llmNode',
      permission: {
        can_compare: true,
        can_apply: true,
        required_auth_state: 'builder',
      },
    });
    workflowApiMock.getModelRoutingPolicy.mockResolvedValue({
      enabled: true,
      status: 'active',
      policy_id: 'policy-persisted',
      policy_version: 'router-policy-v5',
      active_policy: {
        strategy: 'prior_guided_adaptive',
        strategy_id: 'prior_guided_adaptive_v1',
        default_model_id: 'gpt-4.1-mini',
        fallback_model_id: 'gpt-4.1',
        rules: [],
        decision_profiles: [
          {
            profile: 'short',
            selected_model_id: 'gpt-4.1-mini',
            fallback_model_id: 'gpt-4.1',
            reason_code: 'prior_guided_utility_selected',
          },
          {
            profile: 'medium',
            selected_model_id: 'gpt-4.1',
            fallback_model_id: 'gpt-4.1-mini',
            reason_code: 'prior_guided_constraints_safe_default',
          },
        ],
      },
      pending_policy: null,
      refresh: {
        refresh_every_runs: 20,
        eligible_runs_since_last_refresh: 2,
        next_refresh_after_runs: 18,
        last_refresh_result: 'applied',
        last_refresh_at: null,
      },
      graph_hash: 'b'.repeat(64),
      updated_at: '2026-07-14T00:00:01Z',
      last_update: {
        id: 'update-1',
        trigger: 'auto_n_runs',
        status: 'applied',
        eligible_run_count: 20,
        excluded_run_count: 2,
        judge_provider: 'openai',
        judge_model: 'gpt-4.1-mini',
        judge_usage_log_id: 'usage-1',
        prompt_version: 'model-routing-policy-judge-v1',
        new_policy_version: 'router-policy-v5',
        judge_cost: 0.0012,
        created_at: '2026-07-10T00:00:00+00:00',
      },
    });
    workflowApiMock.patchModelRoutingPolicy.mockResolvedValue({
      enabled: true,
      status: 'collecting',
      policy_id: null,
      policy_version: null,
      active_policy: null,
      pending_policy: null,
      refresh: {
        refresh_every_runs: 20,
        eligible_runs_since_last_refresh: 0,
        next_refresh_after_runs: 20,
        last_refresh_result: null,
        last_refresh_at: null,
      },
      graph_hash: 'b'.repeat(64),
      updated_at: '2026-07-14T00:00:01Z',
    });
    workflowApiMock.refreshModelRoutingPolicy.mockResolvedValue({
      policy_id: 'policy-persisted',
      status: 'refreshing',
      trigger: 'manual_refresh',
      scheduled: true,
    });
    global.fetch = vi.fn(async () => ({
      ok: true,
      json: async () => [
        {
          id: 'model-1',
          model_id_for_api_call: 'gpt-4.1',
          name: 'GPT-4.1',
          type: 'chat',
          provider_name: 'openai',
          is_active: true,
        },
        {
          id: 'model-2',
          model_id_for_api_call: 'gpt-4.1-mini',
          name: 'GPT-4.1 mini',
          type: 'chat',
          provider_name: 'openai',
          is_active: true,
        },
      ],
    })) as unknown as typeof fetch;
    const node = createLlmNode();
    useWorkflowStore.setState(
      {
        ...initialState,
        nodes: [node],
        activeWorkflowId: 'workflow-1',
        canonicalDraftMetadata: {
          'workflow-1': {
            workflowId: 'workflow-1',
            graphHash: 'a'.repeat(64),
            updatedAt: '2026-07-14T00:00:00Z',
          },
        },
        workflowAccess: {
          workflow_id: 'workflow-1',
          organization_id: 'org-1',
          auth_state: 'builder',
          can_read: true,
          can_write: true,
          can_execute: true,
          can_deploy: true,
          can_manage: true,
          sources: [],
        },
      },
      true,
    );
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it('자동 모델 라우팅이 꺼져 있으면 직접 모델 선택을 보여주고 작업 유형 입력은 숨긴다', async () => {
    const node = useWorkflowStore.getState().nodes[0] as AppNode;

    render(<NodeInlinePanel node={node} />);

    expect(
      await screen.findByRole('checkbox', { name: /자동 모델 라우팅/ }),
    ).not.toBeChecked();
    expect(await screen.findByText('기본 모델')).toBeInTheDocument();
    expect(screen.getByText('대체 모델')).toBeInTheDocument();
    expect(screen.queryByLabelText('작업 유형')).not.toBeInTheDocument();
  });

  it('자동 모델 라우팅이 켜져 있으면 사전 지식 기반 정책만 보여준다', async () => {
    const node = createLlmNode({ auto_model_routing: true });

    render(<NodeInlinePanel node={node} />);

    expect(
      await screen.findByRole('checkbox', { name: /자동 모델 라우팅/ }),
    ).toBeChecked();
    expect(screen.getByText('자동 라우팅 사용 중')).toBeInTheDocument();
    expect(await screen.findByText('router-policy-v5')).toBeInTheDocument();
    expect(
      screen.getByTestId('routing-prior-guided-policy'),
    ).toBeInTheDocument();
    expect(screen.getByText('짧은 입력')).toBeInTheDocument();
    expect(screen.getByText('보통 입력')).toBeInTheDocument();
    expect(screen.queryByText('입력군 관리')).not.toBeInTheDocument();
    expect(screen.queryByText('월간 모델 검증 한도')).not.toBeInTheDocument();

    fireEvent.change(
      screen.getByRole('combobox', { name: '기본 모델을 선택하세요' }),
      { target: { value: 'gpt-4.1-mini' } },
    );
    await waitFor(() => {
      expect(workflowApiMock.patchModelRoutingPolicy).toHaveBeenCalledWith(
        'workflow-1',
        'llm-1',
        expect.objectContaining({
          enabled: true,
          default_model_id: 'gpt-4.1-mini',
          fallback_model_id: null,
          refresh_every_runs: 20,
          expected_graph_hash: 'a'.repeat(64),
          expected_updated_at: '2026-07-14T00:00:00Z',
        }),
      );
    });
    expect(
      useWorkflowStore.getState().getCanonicalDraftMetadata('workflow-1'),
    ).toEqual({
      workflowId: 'workflow-1',
      graphHash: 'b'.repeat(64),
      updatedAt: '2026-07-14T00:00:01Z',
    });
    expect(
      screen.getByText(/권장: 20~50회/),
    ).toBeInTheDocument();
  });

  it('자동 정책 점검 주기 변경에는 입력군이나 검증 예산을 전송하지 않는다', async () => {
    const node = createLlmNode({ auto_model_routing: true });
    render(<NodeInlinePanel node={node} />);

    const slider = await screen.findByRole('slider', {
      name: '자동 정책 점검 주기',
    });
    fireEvent.change(slider, { target: { value: '45' } });
    fireEvent.mouseUp(slider);

    await waitFor(() => {
      expect(workflowApiMock.patchModelRoutingPolicy).toHaveBeenCalledWith(
        'workflow-1',
        'llm-1',
        expect.objectContaining({
          enabled: true,
          refresh_every_runs: 45,
          default_model_id: 'gpt-4.1',
          fallback_model_id: null,
          expected_graph_hash: 'a'.repeat(64),
          expected_updated_at: '2026-07-14T00:00:00Z',
        }),
      );
    });
  });
  it('자동 모델 라우팅 토글 변경을 노드 데이터에 반영한다', async () => {
    const node = useWorkflowStore.getState().nodes[0] as AppNode;

    render(<NodeInlinePanel node={node} />);

    fireEvent.click(
      await screen.findByRole('checkbox', { name: /자동 모델 라우팅/ }),
    );

    expect(
      (useWorkflowStore.getState().nodes[0].data as LLMNodeData)
        .auto_model_routing,
    ).toBe(true);
    await waitFor(() => {
      expect(workflowApiMock.patchModelRoutingPolicy).toHaveBeenCalledWith(
        'workflow-1',
        'llm-1',
        expect.objectContaining({
          enabled: true,
          expected_graph_hash: 'a'.repeat(64),
          expected_updated_at: '2026-07-14T00:00:00Z',
        }),
      );
    });
  });

  it('자동 정책 갱신하기는 refresh API를 요청한다', async () => {
    const node = createLlmNode({ auto_model_routing: true });
    useWorkflowStore.setState(
      { ...useWorkflowStore.getState(), nodes: [node] },
      true,
    );
    render(<NodeInlinePanel node={node} />);

    fireEvent.click(
      await screen.findByRole('button', { name: /자동 정책 갱신하기/ }),
    );

    expect(workflowApiMock.refreshModelRoutingPolicy).toHaveBeenCalledWith(
      'workflow-1',
      'llm-1',
    );
  });

  it('첫 배포 운영 실행 전에는 정책 row가 없어 수동 갱신을 막고 이유를 안내한다', async () => {
    workflowApiMock.getModelRoutingPolicy.mockResolvedValueOnce({
      enabled: true,
      status: 'collecting',
      policy_id: null,
      policy_version: null,
      active_policy: null,
      pending_policy: null,
      refresh: {
        refresh_every_runs: 20,
        eligible_runs_since_last_refresh: 0,
        next_refresh_after_runs: 20,
        last_refresh_result: null,
        last_refresh_at: null,
      },
      last_update: null,
    });
    const node = createLlmNode({ auto_model_routing: true });
    useWorkflowStore.setState(
      { ...useWorkflowStore.getState(), nodes: [node] },
      true,
    );

    render(<NodeInlinePanel node={node} />);

    expect(
      await screen.findByText(/첫 배포 운영 실행이 완료된 뒤 정책을 갱신할 수 있습니다/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /자동 정책 갱신하기/ }),
    ).toBeDisabled();
  });

  it('최근 정책 갱신의 judge 비용과 결과를 보여준다', async () => {
    const node = createLlmNode({ auto_model_routing: true });
    useWorkflowStore.setState(
      { ...useWorkflowStore.getState(), nodes: [node] },
      true,
    );

    render(<NodeInlinePanel node={node} />);

    expect(await screen.findByText(/최근 정책 점검/)).toBeInTheDocument();
    expect(screen.getByText(/자동 갱신 · 반영됨/)).toBeInTheDocument();
    expect(screen.getByText(/Judge: gpt-4.1-mini/)).toBeInTheDocument();
    expect(screen.getByText(/비용 \$0\.0012/)).toBeInTheDocument();
  });

  it('운영 로그 기반 최적화 진입 버튼을 보여준다', async () => {
    const node = useWorkflowStore.getState().nodes[0] as AppNode;

    render(<NodeInlinePanel node={node} />);

    expect(
      await screen.findByRole('button', { name: /^최적화$/ }),
    ).toHaveAttribute(
      'title',
      '운영 로그 기반 LLM 노드 설정 추천을 검토합니다.',
    );
    expect(
      await screen.findByRole('checkbox', { name: /자동 모델 라우팅/ }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText('작업 유형')).not.toBeInTheDocument();
  });
});
