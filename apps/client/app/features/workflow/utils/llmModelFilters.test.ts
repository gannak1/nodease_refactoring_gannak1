import { describe, expect, it } from 'vitest';

import { isWorkflowChatModelOption } from './llmModelFilters';

const model = (overrides: Partial<Parameters<typeof isWorkflowChatModelOption>[0]>) => ({
  model_id_for_api_call: 'gpt-4.1',
  name: 'gpt-4.1',
  type: 'chat',
  provider_name: 'OpenAI',
  is_active: true,
  ...overrides,
});

describe('isWorkflowChatModelOption', () => {
  it('workflow LLM alias 모델은 provider와 무관하게 허용한다', () => {
    expect(
      isWorkflowChatModelOption(
        model({
          model_id_for_api_call: 'o1-pro',
          name: 'o1-pro',
        }),
      ),
    ).toBe(true);
    expect(
      isWorkflowChatModelOption(
        model({
          model_id_for_api_call: 'claude-sonnet-4-5',
          name: 'Claude Sonnet 4.5',
          provider_name: 'Anthropic',
        }),
      ),
    ).toBe(true);
    expect(
      isWorkflowChatModelOption(
        model({
          model_id_for_api_call: 'models/gemini-3-pro',
          name: 'Gemini 3 Pro',
          provider_name: 'Google',
        }),
      ),
    ).toBe(true);
  });

  it('날짜 suffix 모델은 alias 중심 노출 정책에 따라 숨긴다', () => {
    expect(
      isWorkflowChatModelOption(
        model({
          model_id_for_api_call: 'gpt-5.2-pro-2025-12-11',
          name: 'gpt-5.2-pro-2025-12-11',
        }),
      ),
    ).toBe(false);
    expect(
      isWorkflowChatModelOption(
        model({
          model_id_for_api_call: 'claude-3-5-sonnet-20241022',
          name: 'claude-3-5-sonnet-20241022',
          provider_name: 'Anthropic',
        }),
      ),
    ).toBe(false);
  });

  it('workflow LLM 노드에 맞지 않는 모델 용도는 숨긴다', () => {
    for (const id of [
      'text-embedding-3-small',
      'gpt-image-1',
      'gpt-audio',
      'gpt-realtime',
      'whisper-1',
      'tts-1',
      'omni-moderation-latest',
      'gpt-4o-transcribe',
      'sora-2',
      'gpt-4o-search-preview',
    ]) {
      expect(
        isWorkflowChatModelOption(
          model({
            model_id_for_api_call: id,
            name: id,
          }),
        ),
      ).toBe(false);
    }
  });
});
