import type { CostOptimizerBaselineRow } from '@/app/features/workflow/types/Api';
import type { AppNode, LLMNodeData } from '@/app/features/workflow/types/Nodes';

export type KnowledgeBaseSelection = { id: string; name: string };

export type CandidateDraft = {
  model_id: string;
  fallback_model_id: string;
  task_type: string;
  system_prompt: string;
  user_prompt: string;
  assistant_prompt: string;
  max_tokens: number;
  temperature: number;
  top_p: number;
  presence_penalty: number;
  frequency_penalty: number;
  stop: string[];
  output_format: 'text' | 'json';
  knowledgeBases: KnowledgeBaseSelection[];
  topK: number;
  scoreThreshold: number;
};

export type BaselineNodeOptions = Partial<LLMNodeData> & {
  task_type?: string;
  output_format?: { type?: 'text' | 'json' } | 'text' | 'json';
};

export type SettingsTab = 'basic' | 'advanced' | 'knowledge';

export const findTargetNode = (
  draft: unknown,
  nodeId: string,
): AppNode | null => {
  const candidate = draft as {
    nodes?: AppNode[];
    graph?: { nodes?: AppNode[] };
  };
  const nodes = candidate.nodes || candidate.graph?.nodes || [];
  return nodes.find((node) => node.id === nodeId) || null;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

export const candidateFromOptions = (
  options: BaselineNodeOptions | null | undefined,
): CandidateDraft => {
  const data = options || {};
  const params = data.parameters || {};
  const outputFormat =
    typeof data.output_format === 'string'
      ? data.output_format
      : data.output_format?.type;

  return {
    model_id: data.model_id || '',
    fallback_model_id: data.fallback_model_id || '',
    task_type: data.task_type || 'generate',
    system_prompt: data.system_prompt || '',
    user_prompt: data.user_prompt || '',
    assistant_prompt: data.assistant_prompt || '',
    max_tokens:
      typeof params.max_tokens === 'number' ? params.max_tokens : 4096,
    temperature:
      typeof params.temperature === 'number' ? params.temperature : 0.7,
    top_p: typeof params.top_p === 'number' ? params.top_p : 1,
    presence_penalty:
      typeof params.presence_penalty === 'number'
        ? params.presence_penalty
        : 0,
    frequency_penalty:
      typeof params.frequency_penalty === 'number'
        ? params.frequency_penalty
        : 0,
    stop: Array.isArray(params.stop)
      ? params.stop.filter((item): item is string => typeof item === 'string')
      : [],
    output_format: outputFormat === 'json' ? 'json' : 'text',
    knowledgeBases: data.knowledgeBases || [],
    topK: typeof data.topK === 'number' ? data.topK : 3,
    scoreThreshold:
      typeof data.scoreThreshold === 'number' ? data.scoreThreshold : 0.5,
  };
};

export const candidateFromNode = (node: AppNode | null): CandidateDraft =>
  candidateFromOptions((node?.data || {}) as BaselineNodeOptions);

export const baselineOptionsOf = (
  baseline: CostOptimizerBaselineRow | null,
): BaselineNodeOptions | null =>
  isRecord(baseline?.node_options)
    ? (baseline.node_options as BaselineNodeOptions)
    : null;

export const llmDataFromCandidate = (
  candidate: CandidateDraft,
  title = 'B candidate',
): LLMNodeData => ({
  title,
  provider: '',
  model_id: candidate.model_id,
  fallback_model_id: candidate.fallback_model_id,
  system_prompt: candidate.system_prompt,
  user_prompt: candidate.user_prompt,
  assistant_prompt: candidate.assistant_prompt,
  referenced_variables: [],
  parameters: {
    max_tokens: candidate.max_tokens,
    temperature: candidate.temperature,
    top_p: candidate.top_p,
    presence_penalty: candidate.presence_penalty,
    frequency_penalty: candidate.frequency_penalty,
    stop: candidate.stop,
  },
  knowledgeBases: candidate.knowledgeBases,
  topK: candidate.topK,
  scoreThreshold: candidate.scoreThreshold,
});
