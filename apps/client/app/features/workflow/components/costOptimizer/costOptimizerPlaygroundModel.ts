import type { CostOptimizerBaselineRow } from '@/app/features/workflow/types/Api';
import type { CostOptimizerCandidateRequest } from '@/app/features/workflow/types/Api';
import type { AppNode, LLMNodeData } from '@/app/features/workflow/types/Nodes';

export type KnowledgeBaseSelection = { id: string; name: string };
export type JsonSchemaFieldType =
  | 'string'
  | 'number'
  | 'boolean'
  | 'object'
  | 'array';
export type JsonSchemaField = {
  key: string;
  type: JsonSchemaFieldType;
  required: boolean;
};

export type CandidateDraft = {
  model_id: string;
  fallback_model_id: string;
  task_type: string;
  system_prompt: string;
  user_prompt: string;
  assistant_prompt: string;
  referenced_variables: LLMNodeData['referenced_variables'];
  max_tokens: number;
  temperature: number;
  top_p: number;
  presence_penalty: number;
  frequency_penalty: number;
  stop: string[];
  output_format: 'text' | 'json';
  json_schema_fields: JsonSchemaField[];
  knowledgeBases: KnowledgeBaseSelection[];
  topK: number;
  scoreThreshold: number;
  dedupeRetrievedContext: boolean;
  retrievedContextMaxChars: number | null;
  retrievedContextCompression: 'off' | 'light' | 'strong';
  answerGroundingCheck: 'off' | 'basic' | 'strict';
};

export type BaselineNodeOptions = Partial<LLMNodeData> & {
  task_type?: string;
  output_format?:
    | { type?: 'text' | 'json'; schema?: Record<string, unknown> | null }
    | 'text'
    | 'json';
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

const jsonSchemaFieldTypes = new Set<JsonSchemaFieldType>([
  'string',
  'number',
  'boolean',
  'object',
  'array',
]);

const schemaFieldsFromOutputFormat = (
  outputFormat: BaselineNodeOptions['output_format'],
): JsonSchemaField[] => {
  if (!isRecord(outputFormat) || !isRecord(outputFormat.schema)) return [];

  const properties = outputFormat.schema.properties;
  if (!isRecord(properties)) return [];

  const required = Array.isArray(outputFormat.schema.required)
    ? outputFormat.schema.required.filter(
        (field): field is string => typeof field === 'string',
      )
    : [];

  return Object.entries(properties).map(([key, propertySchema]) => {
    const type = isRecord(propertySchema) ? propertySchema.type : null;
    return {
      key,
      type:
        typeof type === 'string' && jsonSchemaFieldTypes.has(type as JsonSchemaFieldType)
          ? (type as JsonSchemaFieldType)
          : 'string',
      required: required.includes(key),
    };
  });
};

const outputSchemaFromFields = (
  fields: JsonSchemaField[],
): Record<string, unknown> => {
  const normalizedFields = fields
    .map((field) => ({
      key: field.key.trim(),
      type: jsonSchemaFieldTypes.has(field.type) ? field.type : 'string',
      required: field.required,
    }))
    .filter((field) => field.key.length > 0);

  if (normalizedFields.length === 0) return {};

  return {
    type: 'object',
    properties: Object.fromEntries(
      normalizedFields.map((field) => [field.key, { type: field.type }]),
    ),
    required: normalizedFields
      .filter((field) => field.required)
      .map((field) => field.key),
  };
};

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
    referenced_variables: data.referenced_variables || [],
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
    json_schema_fields: schemaFieldsFromOutputFormat(data.output_format),
    knowledgeBases: data.knowledgeBases || [],
    topK: typeof data.topK === 'number' ? data.topK : 3,
    scoreThreshold:
      typeof data.scoreThreshold === 'number' ? data.scoreThreshold : 0.5,
    dedupeRetrievedContext: data.dedupeRetrievedContext ?? false,
    retrievedContextMaxChars:
      typeof data.retrievedContextMaxChars === 'number'
        ? data.retrievedContextMaxChars
        : null,
    retrievedContextCompression:
      data.retrievedContextCompression === 'light' ||
      data.retrievedContextCompression === 'strong'
        ? data.retrievedContextCompression
        : 'off',
    answerGroundingCheck:
      data.answerGroundingCheck === 'basic' ||
      data.answerGroundingCheck === 'strict'
        ? data.answerGroundingCheck
        : 'off',
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
  task_type: candidate.task_type,
  system_prompt: candidate.system_prompt,
  user_prompt: candidate.user_prompt,
  assistant_prompt: candidate.assistant_prompt,
  referenced_variables: candidate.referenced_variables,
  parameters: {
    max_tokens: candidate.max_tokens,
    temperature: candidate.temperature,
    top_p: candidate.top_p,
    presence_penalty: candidate.presence_penalty,
    frequency_penalty: candidate.frequency_penalty,
    stop: candidate.stop,
  },
  output_format: {
    type: candidate.output_format,
    schema:
      candidate.output_format === 'json'
        ? outputSchemaFromFields(candidate.json_schema_fields)
        : undefined,
  },
  knowledgeBases: candidate.knowledgeBases,
  topK: candidate.topK,
  scoreThreshold: candidate.scoreThreshold,
  dedupeRetrievedContext: candidate.dedupeRetrievedContext,
  retrievedContextMaxChars: candidate.retrievedContextMaxChars ?? undefined,
  retrievedContextCompression: candidate.retrievedContextCompression,
  answerGroundingCheck: candidate.answerGroundingCheck,
});

export const compareRequestCandidateFromDraft = (
  candidate: CandidateDraft,
  label = 'B',
): CostOptimizerCandidateRequest => ({
  label,
  model_id: candidate.model_id,
  fallback_model_id: candidate.fallback_model_id || null,
  task_type: candidate.task_type,
  system_prompt: candidate.system_prompt,
  user_prompt: candidate.user_prompt,
  assistant_prompt: candidate.assistant_prompt,
  referenced_variables: candidate.referenced_variables,
  parameters: {
    max_tokens: candidate.max_tokens,
    temperature: candidate.temperature,
    top_p: candidate.top_p,
    presence_penalty: candidate.presence_penalty,
    frequency_penalty: candidate.frequency_penalty,
    stop: candidate.stop,
  },
  output_format: {
    type: candidate.output_format,
    schema:
      candidate.output_format === 'json'
        ? outputSchemaFromFields(candidate.json_schema_fields)
        : undefined,
  },
  knowledge: {
    knowledge_base_ids: candidate.knowledgeBases.map((knowledgeBase) =>
      knowledgeBase.id,
    ),
    top_k: candidate.topK,
    score_threshold: candidate.scoreThreshold,
    dedupe_retrieved_context: candidate.dedupeRetrievedContext,
    retrieved_context_max_chars: candidate.retrievedContextMaxChars,
    retrieved_context_compression: candidate.retrievedContextCompression,
    answer_grounding_check: candidate.answerGroundingCheck,
  },
});
