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
        strategy_id: 'judge_bootstrap_incremental_v1',
        default_model_id: 'gpt-4.1-mini',
        fallback_model_id: 'gpt-4.1',
        rules: [],
        judge_provider: 'openai',
        judge_model_id: 'gpt-4.1-mini',
        minimum_local_samples: 24,
        local_confidence_threshold: 0.78,
        learning: {
          mode: 'local_first',
          judged_request_count: 24,
          distinct_model_count: 2,
        },
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
      learning_summary: {
        pending_count: 2,
        accepted_count: 18,
        rejected_count: 3,
        last_outcome_reason: 'contract_passed',
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
      history_mode: 'judge_first',
      available_history_count: 0,
      excluded_history_count: 0,
      excluded_reason_summary: {},
      bootstrap: null,
    });
    workflowApiMock.createModelRoutingBootstrap.mockResolvedValue({
      id: 'bootstrap-1',
      status: 'ready',
      source: 'judge_first',
      task_fingerprint: 'fingerprint-1',
      task_description: '고객 문의를 JSON으로 분류합니다.',
      default_model_id: 'gpt-4.1',
      fallback_model_id: 'gpt-4.1-mini',
      generation_summary: {
        history_sample_count: 0,
        candidate_model_count: 2,
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

  it('자동 모델 라우팅이 켜져 있으면 Judge-first 정책만 보여준다', async () => {
    const node = createLlmNode({ auto_model_routing: true });

    render(<NodeInlinePanel node={node} />);

    expect(
      await screen.findByRole('checkbox', { name: /자동 모델 라우팅/ }),
    ).toBeChecked();
    expect(screen.getByText('자동 라우팅 사용 중')).toBeInTheDocument();
    expect(await screen.findByText('router-policy-v5')).toBeInTheDocument();
    expect(
      screen.getByTestId('routing-judge-first-policy'),
    ).toBeInTheDocument();
    expect(screen.getByText('Judge-first + 점진적 로컬 학습')).toBeInTheDocument();
    expect(screen.getByText('로컬 라우터 우선')).toBeInTheDocument();
    expect(screen.getByText('24건')).toBeInTheDocument();
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
    expect(screen.getByText('계약 확인 학습 상태')).toBeInTheDocument();
    expect(screen.getByText(/학습 반영 18건/)).toBeInTheDocument();
    expect(screen.getByText(/결과 대기 2건/)).toBeInTheDocument();
    expect(screen.getByText(/학습 제외 3건/)).toBeInTheDocument();
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

  it('작업 설명으로 초안 단계의 Judge-first 자동 선택 기준을 생성한다', async () => {
    const node = createLlmNode({ auto_model_routing: true });
    useWorkflowStore.setState(
      { ...useWorkflowStore.getState(), nodes: [node] },
      true,
    );
    render(<NodeInlinePanel node={node} />);

    fireEvent.change(await screen.findByLabelText('자동 라우팅 작업 설명'), {
      target: { value: '고객 문의를 JSON으로 분류하고 위험 문의는 신중하게 판단합니다.' },
    });
    fireEvent.click(screen.getByRole('button', { name: '자동 선택 기준 만들기' }));

    await waitFor(() => {
      expect(workflowApiMock.createModelRoutingBootstrap).toHaveBeenCalledWith(
        'workflow-1',
        'llm-1',
        expect.objectContaining({
          task_description: '고객 문의를 JSON으로 분류하고 위험 문의는 신중하게 판단합니다.',
          default_model_id: 'gpt-4.1',
        }),
      );
    });
    expect(
      (useWorkflowStore.getState().nodes[0].data as LLMNodeData)
        .model_routing_bootstrap_id,
    ).toBe('bootstrap-1');
  });

  it('bootstrap 정책은 Judge 선택 누적과 로컬 학습 상태를 보여준다', async () => {
    workflowApiMock.getModelRoutingPolicy.mockResolvedValueOnce({
      enabled: true,
      status: 'active',
      policy_id: 'policy-bootstrap',
      policy_version: 'bootstrap-12345678',
      active_policy: {
        strategy_id: 'judge_bootstrap_incremental_v1',
        default_model_id: 'gpt-4.1-mini',
        fallback_model_id: 'gpt-4.1',
        rules: [],
        judge_provider: 'openai',
        judge_model_id: 'gpt-4.1-mini',
        minimum_local_samples: 24,
        local_confidence_threshold: 0.78,
        learning: {
          mode: 'judge_first',
          judged_request_count: 0,
          distinct_model_count: 0,
        },
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
      model_routing_strategy: 'judge_bootstrap_incremental_v1',
    });
    useWorkflowStore.setState(
      { ...useWorkflowStore.getState(), nodes: [node] },
      true,
    );

    render(<NodeInlinePanel node={node} />);

    expect(
      await screen.findByTestId('routing-judge-first-policy'),
    ).toBeInTheDocument();
    expect(screen.getByText('Judge-first + 점진적 로컬 학습')).toBeInTheDocument();
    expect(screen.getAllByText('Judge 선택 학습 중')).not.toHaveLength(0);
    expect(screen.getByText('학습된 Judge 선택')).toBeInTheDocument();
    expect(screen.getByText('0건')).toBeInTheDocument();
    expect(screen.queryByText('경제형 요청')).not.toBeInTheDocument();
    expect(screen.queryByText('균형형 요청')).not.toBeInTheDocument();
    expect(screen.queryByText('고성능 요청')).not.toBeInTheDocument();
    expect(screen.queryByText('요청 복잡도 점수')).not.toBeInTheDocument();
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
