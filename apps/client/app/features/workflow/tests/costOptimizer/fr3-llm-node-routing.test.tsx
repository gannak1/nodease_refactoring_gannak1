import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { NodeInlinePanel } from '../../components/nodes/NodeInlinePanel';
import { useWorkflowStore } from '../../store/useWorkflowStore';
import type { AppNode, LLMNodeData } from '../../types/Nodes';

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
  workflowApi: {
    getCostOptimizerAvailability: vi.fn().mockResolvedValue({
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
    }),
  },
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
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

  it('모델 선택을 보여주고 작업 유형 입력은 숨긴다', async () => {
    const node = useWorkflowStore.getState().nodes[0] as AppNode;

    render(<NodeInlinePanel node={node} />);

    expect(await screen.findByText('기본 모델')).toBeInTheDocument();
    expect(screen.getByText('대체 모델')).toBeInTheDocument();
    expect(screen.queryByLabelText('작업 유형')).not.toBeInTheDocument();
  });

  it('운영 로그 기반 모델 라우팅 최적화 진입 버튼을 보여준다', async () => {
    const node = useWorkflowStore.getState().nodes[0] as AppNode;

    render(<NodeInlinePanel node={node} />);

    expect(
      await screen.findByRole('button', { name: /모델 라우팅 최적화/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/배포 후 운영 로그를 기준으로 추천 모델/),
    ).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: /자동 라우팅/ })).toBeNull();
    expect(screen.queryByLabelText('작업 유형')).not.toBeInTheDocument();
  });
});
