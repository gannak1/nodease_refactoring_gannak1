import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { NodeSettingsComparisonPanel } from '../../components/costOptimizer/NodeSettingsComparisonPanel';
import {
  compareRequestCandidateFromDraft,
  llmDataFromCandidate,
  type CandidateDraft,
} from '../../components/costOptimizer/costOptimizerPlaygroundModel';

vi.mock(
  '@/app/features/workflow/components/nodes/llm/components/ModelSelectDropdown',
  () => ({
    ModelSelectDropdown: ({
      value,
      onChange,
      disabled,
      placeholder,
      models,
    }: {
      value: string;
      onChange: (value: string) => void;
      disabled?: boolean;
      placeholder?: string;
      models: Array<{ model_id_for_api_call: string; name: string }>;
    }) => (
      <select
        aria-label={placeholder || '모델 선택'}
        disabled={disabled}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">모델 없음</option>
        {models.map((model) => (
          <option
            key={model.model_id_for_api_call}
            value={model.model_id_for_api_call}
          >
            {model.name}
          </option>
        ))}
      </select>
    ),
  }),
);

vi.mock('../../components/modals/PromptWizardModal', () => ({
  PromptWizardModal: () => null,
}));

vi.mock(
  '../../components/nodes/llm/components/LLMParameterSidePanel',
  () => ({
    LLMParameterSidePanel: () => null,
  }),
);

vi.mock(
  '../../components/nodes/llm/components/LLMReferenceSidePanel',
  () => ({
    LLMReferenceSidePanel: () => null,
  }),
);

vi.mock('@/app/features/workflow/components/nodes/ui/VariableTokenEditor', () => ({
  VariableTokenEditor: ({
    ariaLabel,
    value,
    onChange,
    onDropOutput,
  }: {
    ariaLabel?: string;
    value: string;
    onChange: (value: string) => void;
    onDropOutput?: (output: {
      key: string;
      label: string;
      dataType: 'string';
      sourceNodeId: string;
      sourceTitle: string;
    }) => string | void;
  }) => (
    <div>
      <textarea
        aria-label={ariaLabel}
        data-testid={`variable-token-editor-${ariaLabel}`}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      {onDropOutput ? (
        <button
          type="button"
          onClick={() => {
            const name = onDropOutput({
              key: 'message',
              label: 'message',
              dataType: 'string',
              sourceNodeId: 'start-1',
              sourceTitle: '고객 티켓 수신',
            });
            onChange(`${value}{{${name || 'message'}}}`);
          }}
        >
          {ariaLabel}에 변수 삽입
        </button>
      ) : null}
    </div>
  ),
}));

const baseDraft: CandidateDraft = {
  model_id: '',
  fallback_model_id: '',
  task_type: 'generate',
  system_prompt: '시스템 프롬프트',
  user_prompt: '사용자 프롬프트',
  assistant_prompt: '',
  referenced_variables: [],
  max_tokens: 1024,
  temperature: 0.3,
  top_p: 1,
  presence_penalty: 0,
  frequency_penalty: 0,
  stop: [],
  output_format: 'text',
  json_schema_fields: [],
  knowledgeBases: [],
  topK: 3,
  scoreThreshold: 0.5,
  dedupeRetrievedContext: false,
  retrievedContextMaxChars: null,
  retrievedContextCompression: 'off',
  answerGroundingCheck: 'off',
};

describe('FR-003 Cost Optimizer candidate editor', () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('B 후보 모델과 대체 모델은 원본 LLM 노드와 같은 선택 UI로 편집한다', async () => {
    const onChange = vi.fn();
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [
          {
            id: 'model-1',
            model_id_for_api_call: 'gpt-4.1-mini',
            name: 'GPT-4.1 mini',
            type: 'chat',
            provider_name: 'OpenAI',
            is_active: true,
          },
          {
            id: 'model-2',
            model_id_for_api_call: 'gpt-4.1',
            name: 'GPT-4.1',
            type: 'chat',
            provider_name: 'OpenAI',
            is_active: true,
          },
        ],
      }),
    );

    render(
      <NodeSettingsComparisonPanel
        title="B Candidate"
        nodeId="llm-1"
        tab="basic"
        onTabChange={vi.fn()}
        draft={baseDraft}
        onChange={onChange}
      />,
    );

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith('/api/v1/llm/my-models', {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        method: 'GET',
      }),
    );

    fireEvent.change(screen.getByLabelText('모델을 선택하세요'), {
      target: { value: 'gpt-4.1-mini' },
    });

    expect(onChange).toHaveBeenCalledWith('model_id', 'gpt-4.1-mini');
    expect(screen.getByLabelText('먼저 모델을 선택하세요')).toBeDisabled();
  });

  it('모델 후보 목록에서는 비활성 모델과 embedding 모델을 제외한다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [
          {
            id: 'model-1',
            model_id_for_api_call: 'gpt-4.1-mini',
            name: 'GPT-4.1 mini',
            type: 'chat',
            provider_name: 'OpenAI',
            is_active: true,
          },
          {
            id: 'model-2',
            model_id_for_api_call: 'text-embedding-3-small',
            name: 'Text Embedding 3 Small',
            type: 'embedding',
            provider_name: 'OpenAI',
            is_active: true,
          },
          {
            id: 'model-3',
            model_id_for_api_call: 'legacy-chat',
            name: 'Legacy Chat',
            type: 'chat',
            provider_name: 'OpenAI',
            is_active: false,
          },
        ],
      }),
    );

    render(
      <NodeSettingsComparisonPanel
        title="B Candidate"
        nodeId="llm-1"
        tab="basic"
        onTabChange={vi.fn()}
        draft={baseDraft}
        onChange={vi.fn()}
      />,
    );

    expect(
      await screen.findAllByRole('option', { name: 'GPT-4.1 mini' }),
    ).toHaveLength(2);

    expect(
      screen.queryByRole('option', { name: 'Text Embedding 3 Small' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('option', { name: 'Legacy Chat' }),
    ).not.toBeInTheDocument();
  });

  it('JSON 출력 형식에서는 flat key-type schema 행을 추가하고 required 여부를 편집한다', () => {
    const onChange = vi.fn();
    const jsonDraft = {
      ...baseDraft,
      output_format: 'json' as const,
      json_schema_fields: [],
    };

    render(
      <NodeSettingsComparisonPanel
        title="B Candidate"
        nodeId="llm-1"
        tab="basic"
        onTabChange={vi.fn()}
        draft={jsonDraft}
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '스키마 필드 추가' }));

    expect(onChange).toHaveBeenCalledWith('json_schema_fields', [
      { key: '', type: 'string', required: false },
    ]);
  });

  it('text 출력 형식에서는 JSON schema 편집 UI를 표시하지 않는다', () => {
    render(
      <NodeSettingsComparisonPanel
        title="B Candidate"
        nodeId="llm-1"
        tab="basic"
        onTabChange={vi.fn()}
        draft={{
          ...baseDraft,
          output_format: 'text',
          json_schema_fields: [
            { key: 'answer', type: 'string', required: true },
          ],
        }}
        onChange={vi.fn()}
      />,
    );

    expect(
      screen.queryByRole('button', { name: '스키마 필드 추가' }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText('JSON schema')).not.toBeInTheDocument();
  });

  it('flat schema 행은 compare request의 JSON schema로 변환된다', () => {
    const request = compareRequestCandidateFromDraft({
      ...baseDraft,
      model_id: 'gpt-4.1-mini',
      output_format: 'json',
      json_schema_fields: [
        { key: 'answer', type: 'string', required: true },
        { key: 'confidence', type: 'number', required: false },
      ],
    });

    expect(request.output_format).toEqual({
      type: 'json',
      schema: {
        type: 'object',
        properties: {
          answer: { type: 'string' },
          confidence: { type: 'number' },
        },
        required: ['answer'],
      },
    });
  });

  it('고급 파라미터는 compare request의 candidate parameters로 변환된다', () => {
    const request = compareRequestCandidateFromDraft({
      ...baseDraft,
      model_id: 'gpt-4.1-mini',
      max_tokens: 512,
      temperature: 0.4,
      top_p: 0.8,
      presence_penalty: 0.2,
      frequency_penalty: -0.1,
      stop: ['END', 'STOP'],
    });

    expect(request.parameters).toEqual({
      max_tokens: 512,
      temperature: 0.4,
      top_p: 0.8,
      presence_penalty: 0.2,
      frequency_penalty: -0.1,
      stop: ['END', 'STOP'],
    });
  });

  it('task type은 원본 LLM node data 변환에서도 보존된다', () => {
    const nodeData = llmDataFromCandidate({
      ...baseDraft,
      task_type: 'classify',
    });

    expect(nodeData.task_type).toBe('classify');
  });

  it('출력 형식과 JSON schema는 원본 LLM node data 변환에서도 보존된다', () => {
    const nodeData = llmDataFromCandidate({
      ...baseDraft,
      output_format: 'json',
      json_schema_fields: [
        { key: 'answer', type: 'string', required: true },
        { key: 'score', type: 'number', required: false },
      ],
    });

    expect(nodeData.output_format).toEqual({
      type: 'json',
      schema: {
        type: 'object',
        properties: {
          answer: { type: 'string' },
          score: { type: 'number' },
        },
        required: ['answer'],
      },
    });
  });

  it('B 후보 prompt 입력은 기존 variable token editor를 재사용한다', () => {
    const onChange = vi.fn();

    render(
      <NodeSettingsComparisonPanel
        title="B Candidate"
        nodeId="llm-1"
        tab="basic"
        onTabChange={vi.fn()}
        draft={baseDraft}
        onChange={onChange}
      />,
    );

    fireEvent.change(screen.getByTestId('variable-token-editor-사용자 프롬프트'), {
      target: { value: '티켓 내용: {{message}}' },
    });

    expect(onChange).toHaveBeenCalledWith(
      'user_prompt',
      '티켓 내용: {{message}}',
    );
  });

  it('prompt 변수 삽입은 candidate referenced_variables를 함께 갱신한다', () => {
    const onChange = vi.fn();

    render(
      <NodeSettingsComparisonPanel
        title="B Candidate"
        nodeId="llm-1"
        tab="basic"
        onTabChange={vi.fn()}
        draft={baseDraft}
        onChange={onChange}
      />,
    );

    fireEvent.click(
      screen.getByRole('button', { name: '사용자 프롬프트에 변수 삽입' }),
    );

    expect(onChange).toHaveBeenCalledWith('referenced_variables', [
      { name: 'message', value_selector: ['start-1', 'message'] },
    ]);
    expect(onChange).toHaveBeenCalledWith(
      'user_prompt',
      '사용자 프롬프트{{message}}',
    );
  });

  it('compare request는 prompt referenced_variables를 포함한다', () => {
    const request = compareRequestCandidateFromDraft({
      ...baseDraft,
      model_id: 'gpt-4.1-mini',
      user_prompt: '티켓 내용: {{message}}',
      referenced_variables: [
        { name: 'message', value_selector: ['start-1', 'message'] },
      ],
    });

    expect(request.referenced_variables).toEqual([
      { name: 'message', value_selector: ['start-1', 'message'] },
    ]);
  });
});
