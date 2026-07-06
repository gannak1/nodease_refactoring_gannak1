export type WorkflowModelOption = {
  model_id_for_api_call: string;
  name: string;
  type: string;
  provider_name?: string;
  is_active: boolean;
};

const allowedModelAliases = new Set([
  'gpt-5.5-pro',
  'gpt-5.5',
  'gpt-5.4-pro',
  'gpt-5.4',
  'gpt-5.3-chat-latest',
  'gpt-5.3-codex',
  'gpt-5.2-pro',
  'gpt-5.2-chat-latest',
  'gpt-5.2-codex',
  'gpt-5.2',
  'gpt-5.1-codex-max',
  'gpt-5.1',
  'gpt-5',
  'gpt-5-pro',
  'gpt-5-mini',
  'gpt-5-nano',
  'o1-pro',
  'o3-pro',
  'o3',
  'o1',
  'gpt-4.1',
  'gpt-4o',
  'gpt-4-turbo-preview',
  'chatgpt-4o-latest',
  'gpt-4.1-mini',
  'gpt-4o-mini',
  'o3-mini',
  'o4-mini',
  'claude-opus-4-5',
  'claude-sonnet-4-5',
  'claude-haiku-4-5',
  'claude-3-5-sonnet-latest',
  'claude-3-5-opus-latest',
  'claude-3-5-haiku-latest',
  'gemini-3-pro',
  'gemini-3-flash',
  'gemini-2.5-pro',
  'gemini-2.5-flash',
  'gemini-2.0-flash',
  'gemini-2.0-flash-lite',
  'gemini-robotics-er-1.5-preview',
  'gemma-3-27b-it',
]);

const blockedModelKeywords = [
  'embedding',
  'image',
  'audio',
  'realtime',
  'moderation',
  'tts',
  'whisper',
  'transcribe',
  'sora',
  'search',
];

const blockedModelTypes = new Set([
  'embedding',
  'image',
  'audio',
  'realtime',
  'moderation',
]);

const versionSuffixPattern = /-(?:\d{4}-\d{2}-\d{2}|\d{8})$/;

export const normalizeWorkflowModelId = (modelId: string) =>
  modelId.toLowerCase().replace(/^models\//, '');

export const isWorkflowChatModelOption = (model: WorkflowModelOption) => {
  const id = normalizeWorkflowModelId(model.model_id_for_api_call);
  const name = model.name.toLowerCase();
  const type = model.type.toLowerCase();

  if (model.is_active === false) return false;
  if (blockedModelTypes.has(type)) return false;
  if (blockedModelKeywords.some((keyword) => id.includes(keyword))) return false;
  if (blockedModelKeywords.some((keyword) => name.includes(keyword))) return false;
  if (versionSuffixPattern.test(id)) return false;

  return allowedModelAliases.has(id);
};
