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
  getModelRoutingBootstrapPreview: vi.fn(),
  createModelRoutingBootstrap: vi.fn(),
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
      performance: {
        total_runs: 24,
        model_count: 2,
        last_recorded_at: '2026-07-10T00:00:00+00:00',
        models: [
          {
            model_id: 'gpt-4.1-mini',
            input_profile: 'short',
            run_count: 16,
            success_rate: 1,
            schema_pass_rate: 1,
            downstream_success_rate: 1,
            fallback_rate: 0,
            avg_cost: 0.0012,
            avg_latency_ms: 850,
          },
        ],
      },
      change_policy: {
        mode: 'event_driven',
        minimum_new_runs: 3,
        quality_change_threshold: 0.05,
        efficiency_improvement_threshold: 0.1,
      },
      last_update: {
        id: 'update-1',
        trigger: 'score_change',
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
    workflowApiMock.getModelRoutingBootstrapPreview.mockResolvedValue({
      task_fingerprint: 'fingerprint-1',
      history_mode: 'synthetic',
      available_history_count: 0,
      excluded_history_count: 0,
      excluded_reason_summary: {},
      bootstrap: null,
    });
    workflowApiMock.createModelRoutingBootstrap.mockResolvedValue({
      id: 'bootstrap-1',
      status: 'ready',
      source: 'synthetic',
      task_fingerprint: 'fingerprint-1',
      task_description: '고객 문의를 JSON으로 분류합니다.',
      default_model_id: 'gpt-4.1',
      fallback_model_id: 'gpt-4.1-mini',
      initial_budget_usd: 1,
      planner_model_id: 'gpt-4.1',
      planner_cost_usd: 0.01,
      generation_summary: {
        history_sample_count: 0,
        synthetic_sample_count: 15,
      },
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
  });

  it('운영 성적과 정책 교체 기준을 보여주고 횟수 슬라이더는 숨긴다', async () => {
    const node = createLlmNode({ auto_model_routing: true });
    render(<NodeInlinePanel node={node} />);

    expect(await screen.findByText('운영 성적 자동 반영')).toBeInTheDocument();
    expect(screen.getByText('24회')).toBeInTheDocument();
    expect(screen.getByText('정책 교체 보호 기준')).toBeInTheDocument();
    expect(screen.getByText(/비용·지연 10% 이상 개선/)).toBeInTheDocument();
    expect(
      screen.queryByRole('slider', { name: '자동 정책 점검 주기' }),
    ).not.toBeInTheDocument();
  });
  it('자동 모델 라우팅 토글은 기준 생성 전에는 빈 정책을 저장하지 않는다', async () => {
    const node = useWorkflowStore.getState().nodes[0] as AppNode;

    render(<NodeInlinePanel node={node} />);

    fireEvent.click(
      await screen.findByRole('checkbox', { name: /자동 모델 라우팅/ }),
    );

    expect(
      (useWorkflowStore.getState().nodes[0].data as LLMNodeData)
        .auto_model_routing,
    ).toBe(true);
    expect(workflowApiMock.patchModelRoutingPolicy).not.toHaveBeenCalled();
  });

  it('작업 설명과 예산으로 초안 단계의 자동 선택 기준을 생성한다', async () => {
    const node = createLlmNode({ auto_model_routing: true });
    useWorkflowStore.setState(
      { ...useWorkflowStore.getState(), nodes: [node] },
      true,
    );
    render(<NodeInlinePanel node={node} />);

    fireEvent.change(await screen.findByLabelText('자동 라우팅 작업 설명'), {
      target: { value: '고객 문의를 JSON으로 분류하고 위험 문의는 신중하게 판단합니다.' },
    });
    const initialBudgetSlider = screen.getByRole('slider', {
      name: '1회 초기 생성 예산',
    });
    fireEvent.change(initialBudgetSlider, { target: { value: '2.5' } });

    expect(screen.getByText('권장: $1~$3')).toBeInTheDocument();
    expect(initialBudgetSlider).toHaveValue('2.5');

    fireEvent.click(screen.getByRole('button', { name: '자동 선택 기준 만들기' }));

    await waitFor(() => {
      expect(workflowApiMock.createModelRoutingBootstrap).toHaveBeenCalledWith(
        'workflow-1',
        'llm-1',
        expect.objectContaining({
          task_description: '고객 문의를 JSON으로 분류하고 위험 문의는 신중하게 판단합니다.',
          default_model_id: 'gpt-4.1',
          initial_budget_usd: 2.5,
        }),
      );
    });
    expect(
      (useWorkflowStore.getState().nodes[0].data as LLMNodeData)
        .model_routing_bootstrap_id,
    ).toBe('bootstrap-1');
  });

  it('bootstrap 정책은 요청별 난이도 분류기와 후보 모델을 보여준다', async () => {
    workflowApiMock.getModelRoutingPolicy.mockResolvedValueOnce({
      enabled: true,
      status: 'active',
      policy_id: 'policy-bootstrap',
      policy_version: 'bootstrap-12345678',
      active_policy: {
        strategy_id: 'bootstrap_request_complexity_v3',
        default_model_id: 'gpt-4.1-mini',
        fallback_model_id: 'gpt-4.1',
        task_complexity_profile: {
          kind: 'planner_task_complexity_v1',
          score: 78,
          tier: 'advanced',
          reasoning_depth: 4,
          instruction_complexity: 4,
          schema_precision: 5,
          context_synthesis: 3,
          grounding_requirement: 3,
          output_generation_demand: 2,
          ambiguity: 2,
          reason: '복수 조건과 엄격한 JSON 계약을 함께 만족해야 합니다.',
        },
        difficulty_models: {
          economy: 'gpt-4o-mini',
          balanced: 'gpt-4.1-mini',
          advanced: 'gpt-4.1',
        },
        rules: [],
      },
      pending_policy: null,
      refresh: {
        refresh_every_runs: 20,
        eligible_runs_since_last_refresh: 0,
        next_refresh_after_runs: 20,
        last_refresh_result: 'applied',
        last_refresh_at: null,
      },
      last_update: null,
    });
    const node = createLlmNode({
      auto_model_routing: true,
      model_routing_strategy: 'bootstrap_request_complexity_v3',
    });
    useWorkflowStore.setState(
      { ...useWorkflowStore.getState(), nodes: [node] },
      true,
    );

    render(<NodeInlinePanel node={node} />);

    expect(
      await screen.findByTestId('routing-bootstrap-policy'),
    ).toBeInTheDocument();
    expect(screen.getByText('요청 난이도 분류기')).toBeInTheDocument();
    expect(
      screen.getByText('초기 작업 계약 분석'),
    ).toBeInTheDocument();
    expect(screen.getByText('78 / 100 · 고성능형')).toBeInTheDocument();
    expect(
      screen.getByText('복수 조건과 엄격한 JSON 계약을 함께 만족해야 합니다.'),
    ).toBeInTheDocument();
    expect(screen.getByText('경제형 요청')).toBeInTheDocument();
    expect(screen.getByText('균형형 요청')).toBeInTheDocument();
    expect(screen.getByText('고성능 요청')).toBeInTheDocument();
    expect(screen.queryByTestId('routing-prior-guided-policy')).not.toBeInTheDocument();
  });

  it('정책 다시 평가는 refresh API를 요청한다', async () => {
    const node = createLlmNode({ auto_model_routing: true });
    useWorkflowStore.setState(
      { ...useWorkflowStore.getState(), nodes: [node] },
      true,
    );
    render(<NodeInlinePanel node={node} />);

    fireEvent.click(
      await screen.findByRole('button', { name: /정책 다시 평가/ }),
    );

    expect(workflowApiMock.refreshModelRoutingPolicy).toHaveBeenCalledWith(
      'workflow-1',
      'llm-1',
    );
  });

  it('배포 전 draft에는 정책이 없고 배포 시 즉시 생성된다고 안내한다', async () => {
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
      await screen.findByText(/배포할 때 첫 실행용 정책을 즉시 생성합니다/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /정책 다시 평가/ }),
    ).toBeDisabled();
  });

  it('최근 정책 평가의 운영 표본과 결과를 보여준다', async () => {
    const node = createLlmNode({ auto_model_routing: true });
    useWorkflowStore.setState(
      { ...useWorkflowStore.getState(), nodes: [node] },
      true,
    );

    render(<NodeInlinePanel node={node} />);

    expect(await screen.findByText(/최근 정책 점검/)).toBeInTheDocument();
    expect(screen.getByText(/운영 성적 변화 · 반영됨/)).toBeInTheDocument();
    expect(screen.getByText(/운영 표본 20회 · 제외 2회/)).toBeInTheDocument();
    expect(screen.queryByText(/Judge:/)).not.toBeInTheDocument();
  });

  it('비교 분석 테스트만 상단 액션으로 보여준다', async () => {
    const node = useWorkflowStore.getState().nodes[0] as AppNode;

    render(<NodeInlinePanel node={node} />);

    expect(
      await screen.findByRole('button', { name: '비교 분석 테스트' }),
    ).toHaveAttribute(
      'title',
      '실행 로그를 기준으로 A/B 비교 분석 테스트 화면을 엽니다.',
    );
    expect(screen.queryByRole('button', { name: /^최적화$/ })).not.toBeInTheDocument();
    expect(
      await screen.findByRole('checkbox', { name: /자동 모델 라우팅/ }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText('작업 유형')).not.toBeInTheDocument();
  });
});
