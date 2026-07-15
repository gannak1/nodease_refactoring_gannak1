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
  suggestModelRoutingCohort: vi.fn(),
  createModelRoutingCohort: vi.fn(),
  updateModelRoutingCohort: vi.fn(),
  convertModelRoutingCohortToManual: vi.fn(),
  deleteModelRoutingCohort: vi.fn(),
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
        default_model_id: 'gpt-4.1-mini',
        fallback_model_id: 'gpt-4.1',
        rules: [],
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
      adaptive: {
        validation_budget_usd: 3,
        max_cohorts: 6,
        active_cohort_count: 0,
        budget_month: null,
        spent_usd: 0,
        reserved_usd: 0,
        remaining_usd: 3,
        cohorts: [],
        latest_batch: null,
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
    workflowApiMock.suggestModelRoutingCohort.mockResolvedValue({
      label: '결제 오류 문의',
      key: 'billing_issue',
      representative_query: '결제가 완료됐는데 서비스 이용이 되지 않습니다.',
    });
    workflowApiMock.createModelRoutingCohort.mockResolvedValue({
      id: 'cohort-1',
      key: 'billing_issue',
      label: '결제 오류 문의',
      source: 'manual',
      status: 'proposed',
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

  it('자동 모델 라우팅이 켜져 있으면 기본 정책 모델을 설정하고 입력군 관리를 먼저 보여준다', async () => {
    const node = createLlmNode({
      auto_model_routing: true,
      model_routing_policy: {
        status: 'active',
        policy_id: 'policy-1',
        policy_version: 'router-policy-v4',
        active_policy: {
          default_model_id: 'gpt-4.1-mini',
          fallback_model_id: 'gpt-4.1',
          rules: [
            {
              id: 'low-risk-json-triage',
              selected_model_id: 'gpt-4.1-mini',
              fallback_model_id: 'gpt-4.1',
              reason_code: 'quality_gate_passed_cost_reduction',
            },
          ],
        },
        refresh: {
          runs_since_last_refresh: 12,
          refresh_every_runs: 20,
        },
      },
    });

    render(<NodeInlinePanel node={node} />);

    expect(
      await screen.findByRole('checkbox', { name: /자동 모델 라우팅/ }),
    ).toBeChecked();
    expect(screen.getByText('자동 라우팅 사용 중')).toBeInTheDocument();
    expect(await screen.findByText('router-policy-v5')).toBeInTheDocument();
    expect(screen.getByText('기본 모델 (규칙 미일치 시)')).toBeInTheDocument();
    expect(screen.getByText('기본 대체 모델')).toBeInTheDocument();
    expect(
      screen.getByRole('combobox', { name: '기본 모델을 선택하세요' }),
    ).toHaveValue('gpt-4.1');

    expect(screen.getByTestId('routing-cohort-management')).toHaveClass('order-1');
    expect(screen.getByTestId('routing-refresh-controls')).toHaveClass('order-2');

    fireEvent.change(
      screen.getByRole('combobox', { name: '기본 모델을 선택하세요' }),
      { target: { value: 'gpt-4.1-mini' } },
    );
    await waitFor(() => {
      expect(workflowApiMock.patchModelRoutingPolicy).toHaveBeenCalledWith(
        'workflow-1',
        'llm-1',
        expect.objectContaining({ default_model_id: 'gpt-4.1-mini' }),
      );
    });
  });

  it('persisted policy가 있어도 자동 정책 점검 주기 draft와 PATCH에 슬라이더 값을 사용한다', async () => {
    const node = createLlmNode({
      auto_model_routing: true,
      model_routing_policy: {
        status: 'active',
        policy_id: 'policy-1',
        policy_version: 'router-policy-v4',
        active_policy: {
          default_model_id: 'gpt-4.1-mini',
          fallback_model_id: 'gpt-4.1',
          rules: [
            {
              id: 'low-risk-json-triage',
              selected_model_id: 'gpt-4.1-mini',
              fallback_model_id: 'gpt-4.1',
              reason_code: 'quality_gate_passed_cost_reduction',
            },
          ],
        },
        refresh: {
          runs_since_last_refresh: 12,
          refresh_every_runs: 20,
        },
      },
    });
    useWorkflowStore.setState(
      {
        ...useWorkflowStore.getState(),
        nodes: [node],
      },
      true,
    );

    const { rerender } = render(<NodeInlinePanel node={node} />);

    const slider = await screen.findByRole('slider', {
      name: /자동 정책 점검 주기/,
    });
    expect(slider).toHaveValue('20');

    fireEvent.change(slider, { target: { value: '45' } });

    rerender(
      <NodeInlinePanel node={useWorkflowStore.getState().nodes[0] as AppNode} />,
    );
    const updatedSlider = screen.getByRole('slider', {
      name: /자동 정책 점검 주기/,
    });
    fireEvent.mouseUp(updatedSlider);

    const nextData = useWorkflowStore.getState().nodes[0]
      .data as LLMNodeData;
    expect(nextData.model_routing_policy?.refresh?.refresh_every_runs).toBe(45);
    expect(updatedSlider).toHaveValue('45');
    expect(screen.getByText('2/45회')).toBeInTheDocument();
    await waitFor(() => {
      expect(workflowApiMock.patchModelRoutingPolicy).toHaveBeenCalledWith(
        'workflow-1',
        'llm-1',
        expect.objectContaining({
          enabled: true,
          refresh_every_runs: 45,
          validation_budget_usd: 3,
          max_cohorts: 6,
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

  it('월간 모델 검증 한도를 deployment snapshot과 policy PATCH에 함께 반영한다', async () => {
    const node = createLlmNode({ auto_model_routing: true });
    useWorkflowStore.setState(
      { ...useWorkflowStore.getState(), nodes: [node] },
      true,
    );

    const { rerender } = render(<NodeInlinePanel node={node} />);
    const budgetSlider = await screen.findByRole('slider', {
      name: /월간 모델 검증 한도/,
    });

    fireEvent.change(budgetSlider, { target: { value: '4.5' } });
    rerender(
      <NodeInlinePanel node={useWorkflowStore.getState().nodes[0] as AppNode} />,
    );

    const updatedBudgetSlider = screen.getByRole('slider', {
      name: /월간 모델 검증 한도/,
    });
    fireEvent.mouseUp(updatedBudgetSlider);

    expect(updatedBudgetSlider).toHaveValue('4.5');
    expect(
      (useWorkflowStore.getState().nodes[0].data as LLMNodeData)
        .model_routing_policy?.validation_budget_usd,
    ).toBe(4.5);
    await waitFor(() => {
      expect(workflowApiMock.patchModelRoutingPolicy).toHaveBeenCalledWith(
        'workflow-1',
        'llm-1',
        expect.objectContaining({ validation_budget_usd: 4.5 }),
      );
    });
  });

  it('입력군 최대 개수는 draft와 policy PATCH에 함께 저장한다', async () => {
    const node = createLlmNode({ auto_model_routing: true });
    useWorkflowStore.setState(
      { ...useWorkflowStore.getState(), nodes: [node] },
      true,
    );

    const { rerender } = render(<NodeInlinePanel node={node} />);
    const slider = await screen.findByRole('slider', {
      name: /입력군 최대 개수/,
    });

    fireEvent.change(slider, { target: { value: '8' } });
    rerender(
      <NodeInlinePanel node={useWorkflowStore.getState().nodes[0] as AppNode} />,
    );
    fireEvent.mouseUp(
      screen.getByRole('slider', { name: /입력군 최대 개수/ }),
    );

    expect(
      (useWorkflowStore.getState().nodes[0].data as LLMNodeData)
        .model_routing_policy?.max_cohorts,
    ).toBe(8);
    await waitFor(() => {
      expect(workflowApiMock.patchModelRoutingPolicy).toHaveBeenCalledWith(
        'workflow-1',
        'llm-1',
        expect.objectContaining({ max_cohorts: 8 }),
      );
    });
  });

  it('대표 문의만 입력하면 입력군 마법사가 이름과 영문 키를 채우고 직접 등록한다', async () => {
    const node = createLlmNode({ auto_model_routing: true });
    useWorkflowStore.setState(
      { ...useWorkflowStore.getState(), nodes: [node] },
      true,
    );
    render(<NodeInlinePanel node={node} />);

    fireEvent.click(
      await screen.findByRole('button', { name: /직접 입력군 추가/ }),
    );
    fireEvent.change(screen.getByLabelText('대표 문의'), {
      target: { value: '결제가 완료됐는데 서비스 이용이 되지 않습니다.' },
    });
    fireEvent.click(screen.getByRole('button', { name: /입력군 마법사/ }));

    await waitFor(() => {
      expect(workflowApiMock.suggestModelRoutingCohort).toHaveBeenCalledWith(
        'workflow-1',
        'llm-1',
        { representative_query: '결제가 완료됐는데 서비스 이용이 되지 않습니다.' },
      );
    });
    expect(screen.getByLabelText('입력군 이름')).toHaveValue('결제 오류 문의');
    expect(screen.getByLabelText('영문 키')).toHaveValue('billing_issue');

    fireEvent.click(screen.getByRole('button', { name: /^입력군 추가$/ }));
    await waitFor(() => {
      expect(workflowApiMock.createModelRoutingCohort).toHaveBeenCalledWith(
        'workflow-1',
        'llm-1',
        {
          label: '결제 오류 문의',
          key: 'billing_issue',
          representative_query: '결제가 완료됐는데 서비스 이용이 되지 않습니다.',
          fixed: false,
        },
      );
    });
  });

  it('입력군 목록에 합성 대표 문의를 표시하고 생성 방식에 맞는 관리 동작을 제공한다', async () => {
    workflowApiMock.getModelRoutingPolicy.mockResolvedValue({
      enabled: true,
      status: 'active',
      policy_id: 'policy-persisted',
      policy_version: 'router-policy-v5',
      active_policy: { default_model_id: 'gpt-4.1', rules: [] },
      pending_policy: null,
      refresh: {
        refresh_every_runs: 20,
        eligible_runs_since_last_refresh: 2,
        next_refresh_after_runs: 18,
        last_refresh_result: null,
        last_refresh_at: null,
      },
      last_update: null,
      adaptive: {
        validation_budget_usd: 3,
        max_cohorts: 6,
        active_cohort_count: 2,
        budget_month: null,
        spent_usd: 0,
        reserved_usd: 0,
        remaining_usd: 3,
        cohorts: [
          {
            id: 'manual-cohort',
            key: 'billing_support',
            label: '결제 문의',
            label_en: 'billing support',
            representative_query: '결제는 완료됐지만 청구서가 발행되지 않았습니다.',
            source: 'manual',
            status: 'proposed',
            required: false,
            safety_protected: false,
            observation_count: 1,
            review_window_count: 0,
            traffic_share: 0,
            validated_model_id: null,
          },
          {
            id: 'auto-cohort',
            key: 'account_access',
            label: '계정 접근 문의',
            label_en: 'account access',
            representative_query: null,
            source: 'auto',
            status: 'active',
            required: false,
            safety_protected: false,
            observation_count: 12,
            review_window_count: 2,
            traffic_share: 0.4,
            validated_model_id: 'gpt-4.1-mini',
          },
        ],
        latest_batch: null,
      },
    });
    const node = createLlmNode({ auto_model_routing: true });
    useWorkflowStore.setState(
      { ...useWorkflowStore.getState(), nodes: [node] },
      true,
    );

    render(<NodeInlinePanel node={node} />);
    await waitFor(() => {
      expect(workflowApiMock.getModelRoutingPolicy).toHaveBeenCalledWith(
        'workflow-1',
        'llm-1',
      );
    });
    expect(
      await screen.findByText(
        '대표 문의: 결제는 완료됐지만 청구서가 발행되지 않았습니다.',
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText('대표 문의: 대표 문의를 준비 중입니다.'),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '결제 문의 수정' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '계정 접근 문의 사용자 입력군으로 전환' }),
    ).toBeInTheDocument();
  });

  it('자동 입력군을 수동 입력군으로 전환할 때 같은 row를 수정해 중복 key를 만들지 않는다', async () => {
    workflowApiMock.getModelRoutingPolicy.mockResolvedValueOnce({
      enabled: true,
      status: 'active',
      policy_id: 'policy-persisted',
      policy_version: 'router-policy-v5',
      active_policy: { default_model_id: 'gpt-4.1', rules: [] },
      pending_policy: null,
      refresh: {
        refresh_every_runs: 20,
        eligible_runs_since_last_refresh: 2,
        next_refresh_after_runs: 18,
        last_refresh_result: null,
        last_refresh_at: null,
      },
      last_update: null,
      adaptive: {
        validation_budget_usd: 3,
        max_cohorts: 6,
        active_cohort_count: 1,
        budget_month: null,
        spent_usd: 0,
        reserved_usd: 0,
        remaining_usd: 3,
        cohorts: [
          {
            id: 'auto-cohort',
            key: 'account_access',
            label: '계정 접근 문의',
            label_en: 'account access',
            representative_query: '로그인할 수 없어 계정 접근을 도와주세요.',
            source: 'auto',
            status: 'active',
            required: false,
            safety_protected: false,
            observation_count: 12,
            review_window_count: 2,
            traffic_share: 0.4,
            validated_model_id: 'gpt-4.1-mini',
          },
        ],
        latest_batch: null,
      },
    });
    workflowApiMock.convertModelRoutingCohortToManual.mockResolvedValue({
      id: 'auto-cohort',
      key: 'account_access',
      label: '계정 접근 문의',
      source: 'manual',
      status: 'proposed',
    });
    const node = createLlmNode({ auto_model_routing: true });
    useWorkflowStore.setState(
      { ...useWorkflowStore.getState(), nodes: [node] },
      true,
    );

    render(<NodeInlinePanel node={node} />);
    fireEvent.click(
      await screen.findByRole('button', {
        name: '계정 접근 문의 사용자 입력군으로 전환',
      }),
    );
    fireEvent.click(screen.getByRole('button', { name: '입력군 수정' }));

    await waitFor(() => {
      expect(workflowApiMock.convertModelRoutingCohortToManual).toHaveBeenCalledWith(
        'workflow-1',
        'llm-1',
        'auto-cohort',
        {
          label: '계정 접근 문의',
          key: 'account_access',
          representative_query: '로그인할 수 없어 계정 접근을 도와주세요.',
          fixed: false,
        },
      );
    });
    expect(workflowApiMock.createModelRoutingCohort).not.toHaveBeenCalled();
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
    ).toBeInTheDocument();
    expect(
      screen.getByText(/배포 후 운영 로그를 기준으로 추천 모델/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('checkbox', { name: /자동 모델 라우팅/ }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText('작업 유형')).not.toBeInTheDocument();
  });
});
