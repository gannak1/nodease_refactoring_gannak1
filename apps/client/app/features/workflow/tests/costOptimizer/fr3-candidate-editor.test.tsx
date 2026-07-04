import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { NodeSettingsComparisonPanel } from '../../components/costOptimizer/NodeSettingsComparisonPanel';
import type { CandidateDraft } from '../../components/costOptimizer/costOptimizerPlaygroundModel';

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

const baseDraft: CandidateDraft = {
  model_id: '',
  fallback_model_id: '',
  task_type: 'generate',
  system_prompt: '시스템 프롬프트',
  user_prompt: '사용자 프롬프트',
  assistant_prompt: '',
  max_tokens: 1024,
  temperature: 0.3,
  top_p: 1,
  presence_penalty: 0,
  frequency_penalty: 0,
  stop: [],
  output_format: 'text',
  knowledgeBases: [],
  topK: 3,
  scoreThreshold: 0.5,
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
});
