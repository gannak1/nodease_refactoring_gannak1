import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { LLMNodeData } from '../../../../types/Nodes';
import { getUpstreamNodes } from '../../../../utils/getUpstreamNodes';
import { UnregisteredVariablesAlert } from '../../../ui/UnregisteredVariablesAlert';
import { ValidationAlert } from '../../../ui/ValidationAlert';
import { useWorkflowStore } from '@/app/features/workflow/store/useWorkflowStore';
import {
  ingestWorkflowDraftCASResult,
  resolveWorkflowDraftCASExpectation,
} from '@/app/features/workflow/utils/workflowDraftCAS';
import { CollapsibleSection } from '../../ui/CollapsibleSection';
import {
  HelpCircle,
  BookOpen,
  MousePointerClick,
  Wand2,
  FileJson,
  RefreshCw,
} from 'lucide-react';
import { PromptWizardModal } from '../../../modals/PromptWizardModal';
import { ModelSelectDropdown } from './ModelSelectDropdown';
import { LLMParameterSidePanel } from './LLMParameterSidePanel';
import { resolveWorkflowWizardOrganizationId } from '@/app/features/workflow/utils/resolveWorkflowWizardOrganizationId';
import {
  DraggedOutputVariable,
  getDroppedOutputReferenceName,
  getTokenLabelMap,
  upsertNamedSelector,
} from '@/app/features/workflow/utils/nodeVariablePorts';
import { isWorkflowChatModelOption } from '@/app/features/workflow/utils/llmModelFilters';
import { VariableTokenEditor } from '../../ui/VariableTokenEditor';
import { PropertyVisibilityToggle } from '../../ui/PropertyVisibilityToggle';
import { CostOptimizerEntryAction } from '../../../costOptimizer/CostOptimizerEntryAction';
import { OptimizationRecommendationModal } from '../../../costOptimizer/OptimizationRecommendationModal';
import { candidateFromOptions } from '../../../costOptimizer/costOptimizerPlaygroundModel';
import { workflowApi } from '@/app/features/workflow/api/workflowApi';
import type { ModelRoutingPolicyResponse } from '@/app/features/workflow/types/Api';

// LLMModelResponse와 일치하는 백엔드 응답 타입
type ModelOption = {
  id: string; // UUID
  model_id_for_api_call: string; // "gpt-4o"
  name: string;
  type: string;
  provider_name?: string;
  is_active: boolean;
};

const TOKEN_PATTERN = /{{\s*([^}]+?)\s*}}/g;
const MODEL_ROUTING_REFRESH_MIN = 5;
const MODEL_ROUTING_REFRESH_MAX = 100;
const MODEL_ROUTING_REFRESH_STEP = 5;
const MODEL_ROUTING_REFRESH_RECOMMEND = [20, 50] as const;
const MODEL_ROUTING_VALIDATION_BUDGET_MIN = 0.5;
const MODEL_ROUTING_VALIDATION_BUDGET_MAX = 10;
const MODEL_ROUTING_VALIDATION_BUDGET_STEP = 0.5;
const MODEL_ROUTING_COHORT_MIN = 1;
const MODEL_ROUTING_COHORT_MAX = 12;
const MODEL_ROUTING_COHORT_RECOMMEND = [3, 6] as const;

const extractTokenNames = (value: string) => {
  const names = new Set<string>();
  TOKEN_PATTERN.lastIndex = 0;

  let match: RegExpExecArray | null;
  while ((match = TOKEN_PATTERN.exec(value)) !== null) {
    const name = match[1].trim();
    if (name) names.add(name);
  }

  return names;
};

const selectorForOutput = (output: DraggedOutputVariable) => [
  output.sourceNodeId,
  output.outputId || output.key,
];

interface LLMNodePanelProps {
  nodeId: string;
  data: LLMNodeData;
  onOpenKnowledgeBaseSettings?: () => void;
}

type PromptHelpId = 'fallback' | 'system' | 'user' | 'assistant';
type OutputFormatType = 'text' | 'json';
type JsonSchemaFieldType = 'string' | 'number' | 'boolean' | 'object' | 'array';
type JsonSchemaField = {
  key: string;
  type: JsonSchemaFieldType;
  required: boolean;
};

const schemaFieldTypes: Array<{ value: JsonSchemaFieldType; label: string }> = [
  { value: 'string', label: 'string' },
  { value: 'number', label: 'number' },
  { value: 'boolean', label: 'boolean' },
  { value: 'object', label: 'object' },
  { value: 'array', label: 'array' },
];

const jsonSchemaFieldTypes = new Set<JsonSchemaFieldType>(
  schemaFieldTypes.map((fieldType) => fieldType.value),
);

const outputFormatTypeOf = (
  outputFormat: LLMNodeData['output_format'],
): OutputFormatType => (outputFormat?.type === 'json' ? 'json' : 'text');

const schemaFieldsFromOutputFormat = (
  outputFormat: LLMNodeData['output_format'],
): JsonSchemaField[] => {
  const schema = outputFormat?.schema;
  if (!schema || typeof schema !== 'object' || Array.isArray(schema)) return [];

  const properties = schema.properties;
  if (!properties || typeof properties !== 'object' || Array.isArray(properties)) {
    return [];
  }

  const required = Array.isArray(schema.required)
    ? schema.required.filter((field): field is string => typeof field === 'string')
    : [];

  return Object.entries(properties).map(([key, propertySchema]) => {
    const type =
      propertySchema &&
      typeof propertySchema === 'object' &&
      !Array.isArray(propertySchema)
        ? propertySchema.type
        : null;
    return {
      key,
      type:
        typeof type === 'string' &&
        jsonSchemaFieldTypes.has(type as JsonSchemaFieldType)
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

const outputFormatSignatureOf = (outputFormat: LLMNodeData['output_format']) =>
  JSON.stringify(outputFormat ?? null);

const applyRecommendationPatchesToNodeData = (
  data: LLMNodeData,
  patches: Record<string, unknown>[],
): Partial<LLMNodeData> => {
  const nextData: Record<string, unknown> = {};
  let nextParameters: Record<string, unknown> | null = null;

  const ensureParameters = () => {
    if (!nextParameters) {
      nextParameters = {
        ...(typeof data.parameters === 'object' && data.parameters
          ? data.parameters
          : {}),
      };
    }
    return nextParameters;
  };

  patches.forEach((patch) => {
    const parameters = patch.parameters;
    if (
      parameters &&
      typeof parameters === 'object' &&
      !Array.isArray(parameters)
    ) {
      const currentParameters = ensureParameters();
      Object.entries(parameters).forEach(([key, value]) => {
        if (value === null) {
          delete currentParameters[key];
        } else {
          currentParameters[key] = value;
        }
      });
    }

    const knowledge = patch.knowledge;
    if (knowledge && typeof knowledge === 'object' && !Array.isArray(knowledge)) {
      const knowledgePatch = knowledge as Record<string, unknown>;
      if (Array.isArray(knowledgePatch.knowledge_base_ids)) {
        nextData.knowledgeBases = knowledgePatch.knowledge_base_ids
          .filter((id): id is string => typeof id === 'string' && id.length > 0)
          .map((id) => ({ id, name: '' }));
      }
      if ('top_k' in knowledgePatch) nextData.topK = knowledgePatch.top_k;
      if ('score_threshold' in knowledgePatch) {
        nextData.scoreThreshold = knowledgePatch.score_threshold;
      }
      if ('dedupe_retrieved_context' in knowledgePatch) {
        nextData.dedupeRetrievedContext =
          knowledgePatch.dedupe_retrieved_context;
      }
      if ('retrieved_context_max_chars' in knowledgePatch) {
        nextData.retrievedContextMaxChars =
          knowledgePatch.retrieved_context_max_chars;
      }
      if ('retrieved_context_compression' in knowledgePatch) {
        nextData.retrievedContextCompression =
          knowledgePatch.retrieved_context_compression;
      }
      if ('answer_grounding_check' in knowledgePatch) {
        nextData.answerGroundingCheck = knowledgePatch.answer_grounding_check;
      }
    }
  });

  if (nextParameters) {
    nextData.parameters = nextParameters;
  }

  return nextData as Partial<LLMNodeData>;
};

const HelpPopover = ({
  id,
  activeHelp,
  onToggle,
  children,
  widthClassName = 'w-48',
}: {
  id: PromptHelpId;
  activeHelp: PromptHelpId | null;
  onToggle: (id: PromptHelpId) => void;
  children: React.ReactNode;
  widthClassName?: string;
}) => {
  const isOpen = activeHelp === id;

  return (
    <div className="relative inline-block ml-1">
      <button
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          onToggle(id);
        }}
        className="nodrag flex h-4 w-4 items-center justify-center rounded-full text-gray-400 transition-colors hover:text-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500/40"
        aria-label="도움말 보기"
        aria-expanded={isOpen}
      >
        <HelpCircle className="w-3 h-3" />
      </button>
      {isOpen && (
        <div
          className={`absolute left-0 top-5 z-50 rounded-lg border border-gray-200 bg-white p-2 text-[11px] text-gray-600 shadow-lg ${widthClassName}`}
          onClick={(event) => event.stopPropagation()}
        >
          {children}
          <div className="absolute -top-1 left-2 h-2 w-2 rotate-45 border-l border-t border-gray-200 bg-white" />
        </div>
      )}
    </div>
  );
};

// 노드 실행 필수 요건 체크
// 1. 시스템 프롬프트 또는 사용자 프롬프트 중 하나 이상 입력되어야 함
// 2. 모델이 선택되어야 함

const groupModelsByProvider = (models: ModelOption[]) => {
  const sorted = [...models].sort((a, b) => a.name.localeCompare(b.name));
  const grouped = sorted.reduce(
    (acc, model) => {
      const provider = model.provider_name || 'Unknown';
      if (!acc[provider]) acc[provider] = [];
      acc[provider].push(model);
      return acc;
    },
    {} as Record<string, ModelOption[]>,
  );

  return Object.entries(grouped)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([provider, providerModels]) => ({
      provider,
      models: providerModels,
    }));
};

export function LLMNodePanel({
  nodeId,
  data,
  onOpenKnowledgeBaseSettings,
}: LLMNodePanelProps) {
  const fullscreenNodeSettingsSection = useWorkflowStore(
    (state) => state.fullscreenNodeSettingsSection,
  );
  const openSettingsTab = useCallback(() => {
    window.open('/dashboard/settings', '_blank', 'noopener,noreferrer');
  }, []);
  const {
    updateNodeData,
    nodes,
    edges,
    activeWorkflowId,
    workflowAccess,
    hasUnsavedChanges,
  } = useWorkflowStore();
  const wizardOrganizationId = resolveWorkflowWizardOrganizationId(
    workflowAccess,
    activeWorkflowId,
  );
  const pendingPromptReferencesRef = useRef<
    LLMNodeData['referenced_variables']
  >([]);
  const lastSyncedOutputFormatRef = useRef(
    outputFormatSignatureOf(data.output_format),
  );
  const lastSyncedOutputFormatNodeRef = useRef(nodeId);

  const [activeHelp, setActiveHelp] = useState<PromptHelpId | null>(null);
  const [activeSettingsTab, setActiveSettingsTab] = useState<
    'basic' | 'advanced'
  >('basic');

  useEffect(() => {
    if (fullscreenNodeSettingsSection !== 'routing') return;
    setActiveSettingsTab('basic');
    const animationFrame = window.requestAnimationFrame(() => {
      document
        .querySelector<HTMLElement>(
          `[data-agent-builder-node-settings-section="routing"][data-node-id="${nodeId}"]`,
        )
        ?.scrollIntoView({ block: 'start', behavior: 'smooth' });
    });
    return () => window.cancelAnimationFrame(animationFrame);
  }, [fullscreenNodeSettingsSection, nodeId]);
  const [isOptimizationModalOpen, setIsOptimizationModalOpen] = useState(false);
  const [appliedRecommendationIds, setAppliedRecommendationIds] = useState<
    string[]
  >([]);
  const [draftJsonSchemaFields, setDraftJsonSchemaFields] = useState<
    JsonSchemaField[]
  >(() => schemaFieldsFromOutputFormat(data.output_format));
  const [persistedRoutingPolicy, setPersistedRoutingPolicy] =
    useState<ModelRoutingPolicyResponse | null>(null);
  const [routingPolicyError, setRoutingPolicyError] = useState<string | null>(null);
  const [isRoutingPolicyRefreshing, setIsRoutingPolicyRefreshing] =
    useState(false);
  const [routingValidationBudgetUsd, setRoutingValidationBudgetUsd] = useState(
    () => {
      const value = Number(data.model_routing_policy?.validation_budget_usd);
      return Number.isFinite(value)
        ? Math.min(
            MODEL_ROUTING_VALIDATION_BUDGET_MAX,
            Math.max(MODEL_ROUTING_VALIDATION_BUDGET_MIN, value),
          )
        : 3;
    },
  );
  const [routingMaxCohorts, setRoutingMaxCohorts] = useState(() => {
    const value = Number(data.model_routing_policy?.max_cohorts);
    return Number.isFinite(value)
      ? Math.min(
          MODEL_ROUTING_COHORT_MAX,
          Math.max(MODEL_ROUTING_COHORT_MIN, value),
        )
      : 6;
  });
  const [isManualCohortFormOpen, setIsManualCohortFormOpen] = useState(false);
  const [editingManualCohortId, setEditingManualCohortId] = useState<string | null>(
    null,
  );
  const [convertingAutoCohortId, setConvertingAutoCohortId] = useState<string | null>(
    null,
  );
  const [manualCohort, setManualCohort] = useState({
    label: '',
    key: '',
    representativeQuery: '',
    additionalExamples: [] as string[],
    fixed: false,
    safetyProtected: false,
  });
  const manualCohortExampleCount = new Set(
    [
      manualCohort.representativeQuery.trim(),
      ...manualCohort.additionalExamples.map((example) => example.trim()),
    ].filter(Boolean),
  ).size;
  const manualCohortRequiredExampleCount = manualCohort.safetyProtected ? 5 : 3;
  const manualCohortHasEnoughExamples =
    manualCohortExampleCount >= manualCohortRequiredExampleCount;
  const [isCohortWizardRunning, setIsCohortWizardRunning] = useState(false);
  const [isManualCohortCreating, setIsManualCohortCreating] = useState(false);

  // 모델 상태 로드
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);

  // 프롬프트 마법사 상태
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardField, setWizardField] = useState<
    'system' | 'user' | 'assistant'
  >('system');

  // 마법사 열기 핸들러
  const openWizard = (field: 'system' | 'user' | 'assistant') => {
    setWizardField(field);
    setWizardOpen(true);
  };

  const toggleHelp = useCallback((id: PromptHelpId) => {
    setActiveHelp((current) => (current === id ? null : id));
  }, []);

  const applyRecommendationPatches = useCallback(
    (patches: Record<string, unknown>[]) => {
      const nextData = applyRecommendationPatchesToNodeData(data, patches);
      if (Object.keys(nextData).length === 0) return;
      updateNodeData(nodeId, nextData);
    },
    [data, nodeId, updateNodeData],
  );

  // 마법사에서 적용된 프롬프트 처리
  const handleApplyImproved = (improvedPrompt: string) => {
    const fieldMap = {
      system: 'system_prompt',
      user: 'user_prompt',
      assistant: 'assistant_prompt',
    } as const;
    handleFieldChange(fieldMap[wizardField], improvedPrompt);
  };

  const chatModelOptions = useMemo(
    () => modelOptions.filter(isWorkflowChatModelOption),
    [modelOptions],
  );
  const groupedModelOptions = useMemo(
    () => groupModelsByProvider(chatModelOptions),
    [chatModelOptions],
  );
  const selectedModel = useMemo(
    () =>
      modelOptions.find(
        (model) => model.model_id_for_api_call === data.model_id,
      ),
    [modelOptions, data.model_id],
  );
  const fallbackCandidates = useMemo(
    () =>
      chatModelOptions.filter(
        (model) => model.model_id_for_api_call !== data.model_id,
      ),
    [chatModelOptions, data.model_id],
  );
  const groupedFallbackOptions = useMemo(() => {
    const groups = groupModelsByProvider(fallbackCandidates);
    if (!data.model_id) return groups;
    const selectedProvider = (
      selectedModel?.provider_name || 'Unknown'
    ).toLowerCase();
    return [...groups].sort((a, b) => {
      const aIsSelected = a.provider.toLowerCase() === selectedProvider;
      const bIsSelected = b.provider.toLowerCase() === selectedProvider;
      if (aIsSelected !== bIsSelected) {
        return aIsSelected ? 1 : -1;
      }
      return a.provider.localeCompare(b.provider);
    });
  }, [fallbackCandidates, data.model_id, selectedModel]);
  const fallbackDisabled = !data.model_id?.trim();
  const routingPolicySummary = useMemo(() => {
    const policy = persistedRoutingPolicy;
    const legacyPolicy = data.model_routing_policy;
    const activePolicy = policy?.active_policy ?? legacyPolicy?.active_policy;
    const runsSinceLastRefresh =
      policy?.refresh?.eligible_runs_since_last_refresh ??
      legacyPolicy?.refresh?.runs_since_last_refresh ??
      0;
    const refreshEveryRuns =
      legacyPolicy?.refresh?.refresh_every_runs ??
      policy?.refresh?.refresh_every_runs ??
      20;
    const status =
      policy?.status ||
      legacyPolicy?.status ||
      (activePolicy ? 'active' : data.auto_model_routing ? 'collecting' : 'off');

    return {
      status,
      policyVersion:
        policy?.policy_version || legacyPolicy?.policy_version || '정책 없음',
      reasonCode: activePolicy
        ? '입력군 규칙과 맞지 않으면 기본 정책을 사용합니다.'
        : '정책 대기 중',
      runsSinceLastRefresh,
      refreshEveryRuns,
      lastUpdate: policy?.last_update ?? null,
    };
  }, [
    data.auto_model_routing,
    data.model_routing_policy,
    persistedRoutingPolicy,
  ]);
  const adaptiveRoutingSummary = useMemo(
    () =>
      persistedRoutingPolicy?.adaptive ?? {
        validation_budget_usd: routingValidationBudgetUsd,
        max_cohorts: routingMaxCohorts,
        active_cohort_count: 0,
        budget_month: null,
        spent_usd: 0,
        reserved_usd: 0,
        remaining_usd: routingValidationBudgetUsd,
        cohorts: [],
        latest_batch: null,
      },
    [persistedRoutingPolicy?.adaptive, routingMaxCohorts, routingValidationBudgetUsd],
  );
  const upstreamNodes = useMemo(
    () => getUpstreamNodes(nodeId, nodes, edges),
    [nodeId, nodes, edges],
  );
  const tokenLabels = useMemo(
    () => getTokenLabelMap(data.referenced_variables, upstreamNodes),
    [data.referenced_variables, upstreamNodes],
  );
  const outputFormatType = outputFormatTypeOf(data.output_format);
  const outputFormatSignature = useMemo(
    () => outputFormatSignatureOf(data.output_format),
    [data.output_format],
  );

  useEffect(() => {
    const nodeChanged = lastSyncedOutputFormatNodeRef.current !== nodeId;
    const outputFormatChanged =
      lastSyncedOutputFormatRef.current !== outputFormatSignature;

    if (nodeChanged || outputFormatChanged) {
      setDraftJsonSchemaFields(schemaFieldsFromOutputFormat(data.output_format));
      lastSyncedOutputFormatRef.current = outputFormatSignature;
      lastSyncedOutputFormatNodeRef.current = nodeId;
    }
  }, [data.output_format, nodeId, outputFormatSignature]);

  const validationErrors = useMemo(() => {
    const allPrompts =
      (data.system_prompt || '') +
      (data.user_prompt || '') +
      (data.assistant_prompt || '');
    const registeredNames = new Set(Object.keys(tokenLabels));
    const errors: string[] = [];

    // 정규식: 닫는 중괄호 } 를 제외한 모든 문자 1개 이상 (공백, 한글 포함)
    const regex = /{{\s*([^}]+?)\s*}}/g;
    let match;
    while ((match = regex.exec(allPrompts)) !== null) {
      const varName = match[1].trim();
      // varName이 비어있지 않고, 등록된 이름에 없으면 에러
      if (varName && !registeredNames.has(varName)) {
        errors.push(varName);
      }
    }
    return Array.from(new Set(errors));
  }, [
    data.system_prompt,
    data.user_prompt,
    data.assistant_prompt,
    tokenLabels,
  ]);

  const allPromptsEmpty = useMemo(() => {
    return (
      !data.system_prompt?.trim() &&
      !data.user_prompt?.trim() &&
      !data.assistant_prompt?.trim()
    );
  }, [data.system_prompt, data.user_prompt, data.assistant_prompt]);

  // 핸들러
  const handleUpdateData = useCallback(
    (key: keyof LLMNodeData, value: unknown) => {
      updateNodeData(nodeId, { [key]: value });
    },
    [nodeId, updateNodeData],
  );
  const updateOutputFormat = useCallback(
    (format: OutputFormatType) => {
      const nextOutputFormat =
        format === 'json'
          ? {
              type: 'json' as const,
              schema: outputSchemaFromFields(draftJsonSchemaFields),
            }
          : { type: 'text' as const };
      lastSyncedOutputFormatRef.current = outputFormatSignatureOf(nextOutputFormat);
      lastSyncedOutputFormatNodeRef.current = nodeId;
      updateNodeData(nodeId, {
        output_format: nextOutputFormat,
      });
    },
    [draftJsonSchemaFields, nodeId, updateNodeData],
  );
  const updateJsonSchemaFields = useCallback(
    (fields: JsonSchemaField[]) => {
      setDraftJsonSchemaFields(fields);
      const nextOutputFormat = {
        type: 'json' as const,
        schema: outputSchemaFromFields(fields),
      };
      lastSyncedOutputFormatRef.current =
        outputFormatSignatureOf(nextOutputFormat);
      lastSyncedOutputFormatNodeRef.current = nodeId;
      updateNodeData(nodeId, {
        output_format: nextOutputFormat,
      });
    },
    [nodeId, updateNodeData],
  );
  const addJsonSchemaField = useCallback(() => {
    updateJsonSchemaFields([
      ...draftJsonSchemaFields,
      { key: '', type: 'string', required: false },
    ]);
  }, [draftJsonSchemaFields, updateJsonSchemaFields]);
  const updateJsonSchemaField = useCallback(
    (index: number, updates: Partial<JsonSchemaField>) => {
      updateJsonSchemaFields(
        draftJsonSchemaFields.map((field, fieldIndex) =>
          fieldIndex === index ? { ...field, ...updates } : field,
        ),
      );
    },
    [draftJsonSchemaFields, updateJsonSchemaFields],
  );
  const removeJsonSchemaField = useCallback(
    (index: number) => {
      updateJsonSchemaFields(
        draftJsonSchemaFields.filter((_, fieldIndex) => fieldIndex !== index),
      );
    },
    [draftJsonSchemaFields, updateJsonSchemaFields],
  );
  const handleRoutingRefreshEveryRunsChange = useCallback(
    (value: number) => {
      const refreshEveryRuns = Math.min(
        MODEL_ROUTING_REFRESH_MAX,
        Math.max(MODEL_ROUTING_REFRESH_MIN, value),
      );
      updateNodeData(nodeId, {
        model_routing_policy: {
          ...(data.model_routing_policy || {}),
          refresh: {
            ...(data.model_routing_policy?.refresh || {}),
            refresh_every_runs: refreshEveryRuns,
          },
        },
      });
    },
    [data.model_routing_policy, nodeId, updateNodeData],
  );

  const loadRoutingPolicy = useCallback(async () => {
    if (!activeWorkflowId) return;
    try {
      const policy = await workflowApi.getModelRoutingPolicy(
        activeWorkflowId,
        nodeId,
      );
      setPersistedRoutingPolicy(policy);
      if (policy.adaptive) {
        setRoutingValidationBudgetUsd(policy.adaptive.validation_budget_usd);
        setRoutingMaxCohorts(policy.adaptive.max_cohorts);
      }
      setRoutingPolicyError(null);
    } catch {
      setPersistedRoutingPolicy(null);
      setRoutingPolicyError('정책 상태를 불러오지 못했습니다.');
    }
  }, [activeWorkflowId, nodeId]);

  const syncRoutingPolicy = useCallback(
    async (
      enabled: boolean,
      refreshEveryRuns: number,
      validationBudgetUsd: number,
      maxCohorts: number,
      defaultModelId: string = data.model_id || '',
      fallbackModelId: string | null = data.fallback_model_id || null,
    ) => {
      if (!activeWorkflowId) return;
      try {
        const expectation = await resolveWorkflowDraftCASExpectation(
          activeWorkflowId,
        );
        const policy = await workflowApi.patchModelRoutingPolicy(
          activeWorkflowId,
          nodeId,
          {
            enabled,
            refresh_every_runs: refreshEveryRuns,
            validation_budget_usd: validationBudgetUsd,
            max_cohorts: maxCohorts,
            default_model_id: defaultModelId,
            fallback_model_id: fallbackModelId,
            ...expectation,
          },
        );
        ingestWorkflowDraftCASResult(activeWorkflowId, policy);
        setPersistedRoutingPolicy(policy);
        setRoutingPolicyError(null);
      } catch {
        setRoutingPolicyError('정책 설정을 저장하지 못했습니다.');
      }
    },
    [activeWorkflowId, data.fallback_model_id, data.model_id, nodeId],
  );

  const handleAutoModelRoutingChange = useCallback(
    (enabled: boolean) => {
      handleUpdateData('auto_model_routing', enabled);
      void syncRoutingPolicy(
        enabled,
        routingPolicySummary.refreshEveryRuns,
        routingValidationBudgetUsd,
        routingMaxCohorts,
      );
    },
    [
      handleUpdateData,
      routingPolicySummary.refreshEveryRuns,
      routingValidationBudgetUsd,
      routingMaxCohorts,
      syncRoutingPolicy,
    ],
  );

  const handleRoutingRefreshEveryRunsCommit = useCallback(() => {
    void syncRoutingPolicy(
      Boolean(data.auto_model_routing),
      routingPolicySummary.refreshEveryRuns,
      routingValidationBudgetUsd,
      routingMaxCohorts,
    );
  }, [
    data.auto_model_routing,
    routingPolicySummary.refreshEveryRuns,
    routingValidationBudgetUsd,
    routingMaxCohorts,
    syncRoutingPolicy,
  ]);

  const handleRoutingValidationBudgetChange = useCallback(
    (value: number) => {
      const nextBudget = Math.min(
        MODEL_ROUTING_VALIDATION_BUDGET_MAX,
        Math.max(MODEL_ROUTING_VALIDATION_BUDGET_MIN, value),
      );
      setRoutingValidationBudgetUsd(nextBudget);
      updateNodeData(nodeId, {
        model_routing_policy: {
          ...(data.model_routing_policy || {}),
          validation_budget_usd: nextBudget,
        },
      });
    },
    [data.model_routing_policy, nodeId, updateNodeData],
  );

  const handleRoutingValidationBudgetCommit = useCallback(() => {
    void syncRoutingPolicy(
      Boolean(data.auto_model_routing),
      routingPolicySummary.refreshEveryRuns,
      routingValidationBudgetUsd,
      routingMaxCohorts,
    );
  }, [
    data.auto_model_routing,
    routingPolicySummary.refreshEveryRuns,
    routingValidationBudgetUsd,
    routingMaxCohorts,
    syncRoutingPolicy,
  ]);

  const handleRoutingMaxCohortsChange = useCallback(
    (value: number) => {
      const nextMaximum = Math.min(
        MODEL_ROUTING_COHORT_MAX,
        Math.max(MODEL_ROUTING_COHORT_MIN, value),
      );
      setRoutingMaxCohorts(nextMaximum);
      updateNodeData(nodeId, {
        model_routing_policy: {
          ...(data.model_routing_policy || {}),
          max_cohorts: nextMaximum,
        },
      });
    },
    [data.model_routing_policy, nodeId, updateNodeData],
  );

  const handleRoutingMaxCohortsCommit = useCallback(() => {
    void syncRoutingPolicy(
      Boolean(data.auto_model_routing),
      routingPolicySummary.refreshEveryRuns,
      routingValidationBudgetUsd,
      routingMaxCohorts,
    );
  }, [
    data.auto_model_routing,
    routingMaxCohorts,
    routingPolicySummary.refreshEveryRuns,
    routingValidationBudgetUsd,
    syncRoutingPolicy,
  ]);

  const handleManualCohortWizard = useCallback(async () => {
    const representativeQuery = manualCohort.representativeQuery.trim();
    if (!activeWorkflowId || !representativeQuery || isCohortWizardRunning) return;
    try {
      setIsCohortWizardRunning(true);
      const suggestion = await workflowApi.suggestModelRoutingCohort(
        activeWorkflowId,
        nodeId,
        { representative_query: representativeQuery },
      );
      setManualCohort({
        label: suggestion.label,
        key: suggestion.key,
        representativeQuery: suggestion.representative_query,
        additionalExamples: (suggestion.representative_examples || []).filter(
          (example) => example !== suggestion.representative_query,
        ),
        fixed: manualCohort.fixed,
        safetyProtected: suggestion.safety_protected,
      });
      setRoutingPolicyError(null);
    } catch {
      setRoutingPolicyError(
        '입력군 초안을 만들지 못했습니다. 대표 문의를 직접 작성해 등록할 수 있습니다.',
      );
    } finally {
      setIsCohortWizardRunning(false);
    }
  }, [
    activeWorkflowId,
    isCohortWizardRunning,
    manualCohort.fixed,
    manualCohort.representativeQuery,
    nodeId,
  ]);

  const handleManualCohortCreate = useCallback(async () => {
    if (
      !activeWorkflowId ||
      !manualCohort.label.trim() ||
      !manualCohort.key.trim() ||
      !manualCohort.representativeQuery.trim() ||
      !manualCohortHasEnoughExamples ||
      isManualCohortCreating
    ) {
      return;
    }
    try {
      setIsManualCohortCreating(true);
      const request = {
        label: manualCohort.label.trim(),
        key: manualCohort.key.trim(),
        representative_query: manualCohort.representativeQuery.trim(),
        representative_examples: [
          manualCohort.representativeQuery.trim(),
          ...manualCohort.additionalExamples,
        ],
        fixed: manualCohort.fixed,
        safety_protected: manualCohort.safetyProtected,
      };
      if (convertingAutoCohortId) {
        await workflowApi.convertModelRoutingCohortToManual(
          activeWorkflowId,
          nodeId,
          convertingAutoCohortId,
          request,
        );
      } else if (editingManualCohortId) {
        await workflowApi.updateModelRoutingCohort(
          activeWorkflowId,
          nodeId,
          editingManualCohortId,
          request,
        );
      } else {
        await workflowApi.createModelRoutingCohort(activeWorkflowId, nodeId, request);
      }
      setManualCohort({
        label: '',
        key: '',
        representativeQuery: '',
        additionalExamples: [],
        fixed: false,
        safetyProtected: false,
      });
      setEditingManualCohortId(null);
      setConvertingAutoCohortId(null);
      setIsManualCohortFormOpen(false);
      await loadRoutingPolicy();
      setRoutingPolicyError(null);
    } catch {
      setRoutingPolicyError(
        '입력군을 저장하지 못했습니다. 입력값, 중복 영문 키, 최대 개수를 확인해 주세요.',
      );
    } finally {
      setIsManualCohortCreating(false);
    }
  }, [
    activeWorkflowId,
    convertingAutoCohortId,
    editingManualCohortId,
    isManualCohortCreating,
    loadRoutingPolicy,
    manualCohort,
    manualCohortHasEnoughExamples,
    nodeId,
  ]);

  const openManualCohortForm = useCallback(() => {
    setEditingManualCohortId(null);
    setConvertingAutoCohortId(null);
    setManualCohort({
      label: '',
      key: '',
      representativeQuery: '',
      additionalExamples: [],
      fixed: false,
      safetyProtected: false,
    });
    setIsManualCohortFormOpen(true);
  }, []);

  const handleManualCohortEdit = useCallback(
    (cohort: {
      id: string;
      label: string;
      key: string;
      representative_query: string | null;
      representative_examples?: string[];
      required: boolean;
      safety_protected: boolean;
    }) => {
      setEditingManualCohortId(cohort.id);
      setConvertingAutoCohortId(null);
      setManualCohort({
        label: cohort.label,
        key: cohort.key,
        representativeQuery: cohort.representative_query || '',
        additionalExamples: (cohort.representative_examples || []).filter(
          (example) => example !== cohort.representative_query,
        ),
        fixed: cohort.required,
        safetyProtected: cohort.safety_protected,
      });
      setIsManualCohortFormOpen(true);
    },
    [],
  );

  const handleAutoCohortConvert = useCallback(
    (cohort: {
      id: string;
      label: string;
      key: string;
      representative_query: string | null;
      representative_examples?: string[];
      safety_protected: boolean;
    }) => {
      setEditingManualCohortId(null);
      setConvertingAutoCohortId(cohort.id);
      setManualCohort({
        label: cohort.label,
        key: cohort.key,
        representativeQuery: cohort.representative_query || '',
        additionalExamples: (cohort.representative_examples || []).filter(
          (example) => example !== cohort.representative_query,
        ),
        fixed: false,
        safetyProtected: cohort.safety_protected,
      });
      setIsManualCohortFormOpen(true);
      setRoutingPolicyError(null);
    },
    [],
  );

  const handleManualCohortDelete = useCallback(
    async (cohort: { id: string; label: string }) => {
      if (!activeWorkflowId) return;
      const shouldDelete = window.confirm(
        `'${cohort.label}' 입력군을 삭제할까요? 이후 요청은 전체 기본 정책으로 처리됩니다.`,
      );
      if (!shouldDelete) return;
      try {
        await workflowApi.deleteModelRoutingCohort(
          activeWorkflowId,
          nodeId,
          cohort.id,
        );
        await loadRoutingPolicy();
        setRoutingPolicyError(null);
      } catch {
        setRoutingPolicyError('입력군을 삭제하지 못했습니다. 정책 상태를 확인해 주세요.');
      }
    },
    [activeWorkflowId, loadRoutingPolicy, nodeId],
  );

  const handleManualRoutingPolicyRefresh = useCallback(async () => {
    if (
      !activeWorkflowId ||
      !persistedRoutingPolicy?.policy_id ||
      isRoutingPolicyRefreshing
    ) {
      return;
    }
    try {
      setIsRoutingPolicyRefreshing(true);
      await workflowApi.refreshModelRoutingPolicy(activeWorkflowId, nodeId);
      await loadRoutingPolicy();
      setRoutingPolicyError(null);
    } catch {
      setRoutingPolicyError('정책 갱신을 요청하지 못했습니다.');
    } finally {
      setIsRoutingPolicyRefreshing(false);
    }
  }, [
    activeWorkflowId,
    isRoutingPolicyRefreshing,
    loadRoutingPolicy,
    nodeId,
    persistedRoutingPolicy?.policy_id,
  ]);

  // Claude 계열 여부 판별 (모델 옵션 우선, 실패 시 이름 프리픽스 판단)
  const isAnthropicModelId = useCallback(
    (modelId: string) => {
      const candidate = modelOptions.find(
        (model) => model.model_id_for_api_call === modelId,
      );
      const provider = (candidate?.provider_name || '').toLowerCase();
      if (provider) return provider.includes('anthropic');
      return modelId.toLowerCase().startsWith('claude');
    },
    [modelOptions],
  );

  // Claude 모델에서 top_p를 제거해 파라미터 충돌을 방지
  const stripTopP = (parameters?: Record<string, unknown>) => {
    if (
      !parameters ||
      !Object.prototype.hasOwnProperty.call(parameters, 'top_p')
    ) {
      return parameters;
    }
    const rest = { ...parameters };
    delete rest.top_p;
    return rest;
  };

  // 모델 변경 시 Claude면 top_p 제거, 폴백 모델 중복 선택도 정리
  const handleModelChange = useCallback(
    (nextModelId: string) => {
      const updates: Partial<LLMNodeData> = { model_id: nextModelId };
      if (data.fallback_model_id && data.fallback_model_id === nextModelId) {
        updates.fallback_model_id = '';
      }
      if (isAnthropicModelId(nextModelId)) {
        const nextParams = stripTopP(data.parameters);
        if (nextParams !== data.parameters) {
          updates.parameters = nextParams || {};
        }
      }
      updateNodeData(nodeId, updates);
    },
    [
      data.fallback_model_id,
      data.parameters,
      isAnthropicModelId,
      nodeId,
      updateNodeData,
    ],
  );

  const handleRoutingDefaultModelChange = useCallback(
    (nextModelId: string) => {
      const nextFallbackModelId =
        data.fallback_model_id === nextModelId
          ? null
          : data.fallback_model_id || null;
      handleModelChange(nextModelId);
      void syncRoutingPolicy(
        true,
        routingPolicySummary.refreshEveryRuns,
        routingValidationBudgetUsd,
        routingMaxCohorts,
        nextModelId,
        nextFallbackModelId,
      );
    },
    [
      data.fallback_model_id,
      handleModelChange,
      routingMaxCohorts,
      routingPolicySummary.refreshEveryRuns,
      routingValidationBudgetUsd,
      syncRoutingPolicy,
    ],
  );

  const handleRoutingFallbackModelChange = useCallback(
    (nextFallbackModelId: string) => {
      handleUpdateData('fallback_model_id', nextFallbackModelId);
      void syncRoutingPolicy(
        true,
        routingPolicySummary.refreshEveryRuns,
        routingValidationBudgetUsd,
        routingMaxCohorts,
        data.model_id || '',
        nextFallbackModelId || null,
      );
    },
    [
      data.model_id,
      handleUpdateData,
      routingMaxCohorts,
      routingPolicySummary.refreshEveryRuns,
      routingValidationBudgetUsd,
      syncRoutingPolicy,
    ],
  );

  // 외부 갱신/새로고침 등으로 top_p가 다시 들어오는 상황을 정리
  useEffect(() => {
    if (!data.model_id) return;
    if (!isAnthropicModelId(data.model_id)) return;
    const nextParams = stripTopP(data.parameters);
    if (nextParams !== data.parameters) {
      updateNodeData(nodeId, { parameters: nextParams || {} });
    }
  }, [
    data.model_id,
    data.parameters,
    isAnthropicModelId,
    nodeId,
    updateNodeData,
  ]);

  const handleFieldChange = useCallback(
    (field: keyof LLMNodeData, value: unknown) => {
      if (
        field === 'system_prompt' ||
        field === 'user_prompt' ||
        field === 'assistant_prompt'
      ) {
        const nextSystemPrompt =
          field === 'system_prompt'
            ? String(value || '')
            : data.system_prompt || '';
        const nextUserPrompt =
          field === 'user_prompt'
            ? String(value || '')
            : data.user_prompt || '';
        const nextAssistantPrompt =
          field === 'assistant_prompt'
            ? String(value || '')
            : data.assistant_prompt || '';
        const usedNames = new Set([
          ...extractTokenNames(nextSystemPrompt),
          ...extractTokenNames(nextUserPrompt),
          ...extractTokenNames(nextAssistantPrompt),
        ]);
        const mergedReferences = [
          ...(data.referenced_variables || []),
          ...pendingPromptReferencesRef.current,
        ];
        const pendingReferenceKeys = new Set(
          pendingPromptReferencesRef.current.map(
            (reference) =>
              `${reference.name}:${reference.value_selector?.[0] || ''}:${reference.value_selector?.[1] || ''}`,
          ),
        );
        const nextReferences = mergedReferences.filter((reference, index) => {
          if (!reference.name || !usedNames.has(reference.name)) return false;
          const referenceKey = `${reference.name}:${reference.value_selector?.[0] || ''}:${reference.value_selector?.[1] || ''}`;
          if (
            !Object.prototype.hasOwnProperty.call(
              tokenLabels,
              reference.name,
            ) &&
            !pendingReferenceKeys.has(referenceKey)
          ) {
            return false;
          }
          return (
            mergedReferences.findIndex((candidate) => {
              if (candidate.name !== reference.name) return false;
              return (
                candidate.value_selector?.[0] ===
                  reference.value_selector?.[0] &&
                candidate.value_selector?.[1] === reference.value_selector?.[1]
              );
            }) === index
          );
        });

        pendingPromptReferencesRef.current =
          pendingPromptReferencesRef.current.filter((reference) =>
            usedNames.has(reference.name),
          );
        updateNodeData(nodeId, {
          [field]: value,
          referenced_variables: nextReferences,
        });
        return;
      }

      updateNodeData(nodeId, { [field]: value });
    },
    [
      data.assistant_prompt,
      data.referenced_variables,
      data.system_prompt,
      data.user_prompt,
      nodeId,
      tokenLabels,
      updateNodeData,
    ],
  );

  const handlePromptDropOutput = useCallback(
    (output: DraggedOutputVariable) => {
      const referenceName = getDroppedOutputReferenceName(
        data.referenced_variables,
        output,
        'value_selector',
      );
      const nextReferences = upsertNamedSelector(
        data.referenced_variables,
        output,
        'value_selector',
      ) as LLMNodeData['referenced_variables'];
      pendingPromptReferencesRef.current = [
        ...pendingPromptReferencesRef.current.filter(
          (reference) => reference.name !== referenceName,
        ),
        {
          name: referenceName,
          value_selector: selectorForOutput(output),
        },
      ];
      updateNodeData(nodeId, { referenced_variables: nextReferences });
      return referenceName;
    },
    [data.referenced_variables, nodeId, updateNodeData],
  );

  // 사용자가 사용 가능한 모델 가져오기
  useEffect(() => {
    const fetchMyModels = async () => {
      try {
        setLoadingModels(true);
        const res = await fetch(`/api/v1/llm/my-models`, {
          method: 'GET',
          headers: {
            'Content-Type': 'application/json',
          },
          credentials: 'include',
        });
        if (res.ok) {
          const json = await res.json();
          setModelOptions(json);
        }
      } catch {
        setModelOptions([]);
      } finally {
        setLoadingModels(false);
      }
    };

    fetchMyModels();
  }, []);

  useEffect(() => {
    if (!data.auto_model_routing) {
      setPersistedRoutingPolicy(null);
      return;
    }
    void loadRoutingPolicy();
  }, [data.auto_model_routing, loadRoutingPolicy]);

  useEffect(() => {
    if (!activeHelp) return;

    const closeHelp = () => setActiveHelp(null);
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeHelp();
    };

    window.addEventListener('click', closeHelp);
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('click', closeHelp);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [activeHelp]);

  const routingRefreshRange = useMemo(() => {
    const totalRange = MODEL_ROUTING_REFRESH_MAX - MODEL_ROUTING_REFRESH_MIN;
    const currentPercent =
      ((routingPolicySummary.refreshEveryRuns - MODEL_ROUTING_REFRESH_MIN) /
        totalRange) *
      100;
    const recommendStart =
      ((MODEL_ROUTING_REFRESH_RECOMMEND[0] - MODEL_ROUTING_REFRESH_MIN) /
        totalRange) *
      100;
    const recommendEnd =
      ((MODEL_ROUTING_REFRESH_RECOMMEND[1] - MODEL_ROUTING_REFRESH_MIN) /
        totalRange) *
      100;

    return {
      currentPercent,
      recommendStart,
      recommendWidth: recommendEnd - recommendStart,
    };
  }, [routingPolicySummary.refreshEveryRuns]);

  return (
    <div className="relative flex flex-col gap-2">
      <div className="sticky top-0 z-10 rounded-lg border border-slate-200 bg-white p-2 shadow-sm">
        <div className="flex flex-col gap-2">
          <div className="grid grid-cols-2 gap-1">
            {[
              { id: 'basic' as const, label: '기본 설정' },
              { id: 'advanced' as const, label: '고급 설정' },
            ].map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveSettingsTab(tab.id)}
                className={`nodrag rounded-md px-3 py-2 text-xs font-bold transition-colors ${
                  activeSettingsTab === tab.id
                    ? 'bg-slate-900 text-white shadow-sm'
                    : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                }`}
                aria-pressed={activeSettingsTab === tab.id}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <CostOptimizerEntryAction
              workflowId={activeWorkflowId}
              nodeId={nodeId}
              workflowAccess={workflowAccess}
              hasUnsavedChanges={hasUnsavedChanges}
              label="최적화"
              destination="model-routing"
              title="운영 로그 기반 LLM 노드 설정 추천을 검토합니다."
              onOpen={() => setIsOptimizationModalOpen(true)}
            />
            <CostOptimizerEntryAction
              workflowId={activeWorkflowId}
              nodeId={nodeId}
              workflowAccess={workflowAccess}
              hasUnsavedChanges={hasUnsavedChanges}
              label="비교 분석 테스트"
              destination="cost-optimizer"
              title="실행 로그를 기준으로 A/B 비교 분석 테스트 화면을 엽니다."
            />
          </div>
        </div>
      </div>

      {activeSettingsTab === 'advanced' ? (
        <div className="min-h-[560px] overflow-hidden rounded-xl border border-slate-200 bg-white">
          <LLMParameterSidePanel
            embedded
            nodeId={nodeId}
            data={data}
            onClose={() => setActiveSettingsTab('basic')}
          />
        </div>
      ) : (
        <>
      <div
        data-agent-builder-node-settings-section="routing"
        data-node-id={nodeId}
        className="rounded-lg border border-slate-200 bg-slate-50 p-3"
      >

      {/* 1. 모델 선택 */}
      <CollapsibleSection title="모델" showDivider>
        <div className="flex flex-col gap-2">
          {loadingModels ? (
            <div className="text-xs text-gray-400">모델 로딩 중...</div>
          ) : modelOptions.length > 0 ? (
            <>
              <label className="flex items-start gap-2 rounded-md border border-emerald-100 bg-emerald-50 px-3 py-2">
                <input
                  type="checkbox"
                  className="nodrag mt-0.5 h-4 w-4 rounded border-emerald-300 text-emerald-600 focus:ring-emerald-500"
                  checked={Boolean(data.auto_model_routing)}
                  onChange={(event) => handleAutoModelRoutingChange(event.target.checked)}
                  aria-label="자동 모델 라우팅"
                />
                <span className="min-w-0">
                  <span className="block text-xs font-semibold text-emerald-900">
                    자동 모델 라우팅
                  </span>
                  <span className="mt-0.5 block text-[11px] leading-relaxed text-emerald-700">
                    켜면 저장된 정책으로 실행 모델을 고르고, 실행 중에는
                    judge LLM을 호출하지 않습니다.
                  </span>
                </span>
              </label>

              {data.auto_model_routing ? (
                <div className="flex flex-col rounded-md border border-slate-200 bg-white p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-xs font-semibold text-slate-800">
                        자동 라우팅 사용 중
                      </div>
                      <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
                        직접 모델 선택 대신 active policy를 기준으로 모델을
                        선택합니다.
                      </p>
                    </div>
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-600">
                      {routingPolicySummary.status}
                    </span>
                  </div>
                  <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div className="rounded border border-slate-100 bg-slate-50 p-2">
                      <label className="block text-[11px] font-semibold text-slate-600">
                        기본 모델 (규칙 미일치 시)
                      </label>
                      <ModelSelectDropdown
                        value={data.model_id || ''}
                        onChange={handleRoutingDefaultModelChange}
                        models={chatModelOptions}
                        groupedModels={groupedModelOptions}
                        placeholder="기본 모델을 선택하세요"
                      />
                    </div>
                    <div className="rounded border border-slate-100 bg-slate-50 p-2">
                      <label className="block text-[11px] font-semibold text-slate-600">
                        기본 대체 모델
                      </label>
                      <ModelSelectDropdown
                        value={data.fallback_model_id || ''}
                        onChange={handleRoutingFallbackModelChange}
                        models={fallbackCandidates}
                        groupedModels={groupedFallbackOptions}
                        disabled={fallbackDisabled}
                        placeholder={
                          fallbackDisabled
                            ? '먼저 기본 모델을 선택하세요'
                            : '기본 대체 모델을 선택하세요'
                        }
                      />
                    </div>
                  </div>
                  <dl className="mt-3 grid grid-cols-1 gap-2 text-[11px] sm:grid-cols-2">
                    <div className="rounded border border-slate-100 bg-slate-50 p-2">
                      <dt className="font-semibold text-slate-500">
                        정책 버전
                      </dt>
                      <dd className="mt-1 truncate font-semibold text-slate-900">
                        {routingPolicySummary.policyVersion}
                      </dd>
                    </div>
                    <div className="rounded border border-slate-100 bg-slate-50 p-2">
                      <dt className="font-semibold text-slate-500">
                        정책 갱신 기준
                      </dt>
                      <dd className="mt-1 font-semibold text-slate-900">
                        {routingPolicySummary.runsSinceLastRefresh}/
                        {routingPolicySummary.refreshEveryRuns}회
                      </dd>
                    </div>
                  </dl>
                  <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
                    갱신 근거: {routingPolicySummary.reasonCode}
                  </p>
                  {routingPolicySummary.lastUpdate ? (
                    <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-2.5 text-[11px]">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold text-slate-700">
                          최근 정책 점검
                        </span>
                        <span className="font-semibold text-slate-600">
                          {routingPolicySummary.lastUpdate.trigger ===
                          'auto_n_runs'
                            ? '자동 갱신'
                            : '수동 갱신'}{' '}
                          ·{' '}
                          {routingPolicySummary.lastUpdate.status === 'applied'
                            ? '반영됨'
                            : routingPolicySummary.lastUpdate.status}
                        </span>
                      </div>
                      <p className="mt-1 text-slate-500">
                        Judge:{' '}
                        {routingPolicySummary.lastUpdate.judge_model || '없음'}
                        {routingPolicySummary.lastUpdate.judge_cost !== null
                          ? ` · 비용 $${routingPolicySummary.lastUpdate.judge_cost}`
                          : ''}
                      </p>
                    </div>
                  ) : null}
                  {routingPolicyError ? (
                    <p className="mt-2 text-[11px] text-rose-600">
                      {routingPolicyError}
                    </p>
                  ) : null}
                  {!persistedRoutingPolicy?.policy_id ? (
                    <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
                      첫 배포 운영 실행이 완료된 뒤 정책을 갱신할 수 있습니다.
                    </p>
                  ) : null}
                  <button
                    type="button"
                    className="nodrag mt-3 inline-flex items-center gap-1.5 rounded-md border border-emerald-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-emerald-800 hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-60"
                    onClick={handleManualRoutingPolicyRefresh}
                    disabled={
                      isRoutingPolicyRefreshing ||
                      routingPolicySummary.status === 'refreshing' ||
                      !activeWorkflowId ||
                      !persistedRoutingPolicy?.policy_id
                    }
                  >
                    <RefreshCw
                      className={`h-3.5 w-3.5 ${isRoutingPolicyRefreshing ? 'animate-spin' : ''}`}
                    />
                    자동 정책 갱신하기
                  </button>
                  <div
                    data-testid="routing-refresh-controls"
                    className="order-2 mt-3 rounded-lg border border-emerald-100 bg-emerald-50/60 p-3"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-xs font-semibold text-emerald-900">
                          자동 정책 점검 주기
                        </div>
                        <p className="mt-0.5 text-[11px] leading-relaxed text-emerald-700">
                          배포 후 운영 실행이 이 횟수만큼 쌓이면 모델 선택
                          정책을 다시 점검합니다.
                        </p>
                      </div>
                      <span className="shrink-0 rounded bg-white px-2 py-1 text-xs font-mono font-semibold text-emerald-800 ring-1 ring-emerald-200">
                        {routingPolicySummary.refreshEveryRuns}회
                      </span>
                    </div>
                    <div className="mt-3">
                      <div className="relative h-7">
                        <div className="pointer-events-none absolute inset-x-0 top-1/2 h-2.5 -translate-y-1/2 overflow-hidden rounded-full bg-white ring-1 ring-emerald-200">
                          <div
                            className="absolute inset-y-0 bg-emerald-200"
                            style={{
                              left: `${routingRefreshRange.recommendStart}%`,
                              width: `${routingRefreshRange.recommendWidth}%`,
                            }}
                          />
                          <div
                            className="absolute inset-y-0 w-0.5 bg-emerald-600"
                            style={{
                              left: `${routingRefreshRange.currentPercent}%`,
                            }}
                          />
                        </div>
                        <input
                          type="range"
                          min={MODEL_ROUTING_REFRESH_MIN}
                          max={MODEL_ROUTING_REFRESH_MAX}
                          step={MODEL_ROUTING_REFRESH_STEP}
                          value={routingPolicySummary.refreshEveryRuns}
                          onChange={(event) =>
                            handleRoutingRefreshEveryRunsChange(
                              Number(event.target.value),
                            )
                          }
                          onMouseUp={handleRoutingRefreshEveryRunsCommit}
                          onTouchEnd={handleRoutingRefreshEveryRunsCommit}
                          onKeyUp={handleRoutingRefreshEveryRunsCommit}
                          className="nodrag absolute inset-0 h-6 w-full cursor-pointer appearance-none bg-transparent accent-emerald-600
                            [&::-moz-range-track]:bg-transparent
                            [&::-ms-track]:bg-transparent
                            [&::-webkit-slider-runnable-track]:bg-transparent"
                          aria-label="자동 정책 점검 주기"
                        />
                      </div>
                      <div className="mt-1 flex items-center justify-between text-[10px] text-emerald-700/70">
                        <span>자주 갱신</span>
                        <span className="font-semibold text-emerald-700">
                          권장: {MODEL_ROUTING_REFRESH_RECOMMEND[0]}~
                          {MODEL_ROUTING_REFRESH_RECOMMEND[1]}회
                        </span>
                        <span>보수적 갱신</span>
                      </div>
                    </div>
                  </div>
                  <div className="order-3 mt-3 rounded-lg border border-indigo-100 bg-indigo-50/60 p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-xs font-semibold text-indigo-950">
                          월간 모델 검증 한도
                        </div>
                        <p className="mt-0.5 text-[11px] leading-relaxed text-indigo-800">
                          새 모델은 입력군마다 5회 실제 Replay 검증을 통과해야
                          정책에 들어갑니다. 이 한도 안에서만 검증 비용을 사용합니다.
                        </p>
                      </div>
                      <span className="shrink-0 rounded bg-white px-2 py-1 text-xs font-mono font-semibold text-indigo-800 ring-1 ring-indigo-200">
                        ${routingValidationBudgetUsd.toFixed(1)}
                      </span>
                    </div>
                    <input
                      type="range"
                      min={MODEL_ROUTING_VALIDATION_BUDGET_MIN}
                      max={MODEL_ROUTING_VALIDATION_BUDGET_MAX}
                      step={MODEL_ROUTING_VALIDATION_BUDGET_STEP}
                      value={routingValidationBudgetUsd}
                      onChange={(event) =>
                        handleRoutingValidationBudgetChange(Number(event.target.value))
                      }
                      onMouseUp={handleRoutingValidationBudgetCommit}
                      onTouchEnd={handleRoutingValidationBudgetCommit}
                      onKeyUp={handleRoutingValidationBudgetCommit}
                      className="nodrag mt-3 h-2 w-full cursor-pointer accent-indigo-600"
                      aria-label="월간 모델 검증 한도"
                    />
                    <div className="mt-2 flex items-center justify-between text-[10px] text-indigo-700">
                      <span>최소 $0.5</span>
                      <span>
                        이번 달 사용 ${adaptiveRoutingSummary.spent_usd.toFixed(4)} · 예약 ${adaptiveRoutingSummary.reserved_usd.toFixed(4)}
                      </span>
                      <span>최대 $10</span>
                    </div>
                  </div>
                  <div className="order-4 mt-3 rounded-lg border border-cyan-100 bg-cyan-50/60 p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-xs font-semibold text-cyan-950">
                          입력군 최대 개수
                        </div>
                        <p className="mt-0.5 text-[11px] leading-relaxed text-cyan-800">
                          현재 자주 쓰이는 입력군만 이 개수 안에서 검증하고 라우팅합니다.
                          휴면 입력군은 새 입력군 자리를 차지하지 않습니다.
                        </p>
                      </div>
                      <span className="shrink-0 rounded bg-white px-2 py-1 text-xs font-mono font-semibold text-cyan-800 ring-1 ring-cyan-200">
                        {routingMaxCohorts}개
                      </span>
                    </div>
                    <input
                      type="range"
                      min={MODEL_ROUTING_COHORT_MIN}
                      max={MODEL_ROUTING_COHORT_MAX}
                      step={1}
                      value={routingMaxCohorts}
                      onChange={(event) =>
                        handleRoutingMaxCohortsChange(Number(event.target.value))
                      }
                      onMouseUp={handleRoutingMaxCohortsCommit}
                      onTouchEnd={handleRoutingMaxCohortsCommit}
                      onKeyUp={handleRoutingMaxCohortsCommit}
                      className="nodrag mt-3 h-2 w-full cursor-pointer accent-cyan-600"
                      aria-label="입력군 최대 개수"
                    />
                    <div className="mt-2 flex items-center justify-between text-[10px] text-cyan-800">
                      <span>최소 {MODEL_ROUTING_COHORT_MIN}개</span>
                      <span>
                        권장: {MODEL_ROUTING_COHORT_RECOMMEND[0]}~
                        {MODEL_ROUTING_COHORT_RECOMMEND[1]}개
                      </span>
                      <span>최대 {MODEL_ROUTING_COHORT_MAX}개</span>
                    </div>
                  </div>
                  <div
                    data-testid="routing-cohort-management"
                    className="order-1 mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-xs font-semibold text-slate-900">
                          입력군 관리
                        </div>
                        <p className="mt-0.5 text-[11px] leading-relaxed text-slate-500">
                          운영 입력은 원문을 저장하지 않고 특징 벡터와 해시로만 묶습니다.
                          검증된 입력군만 다른 모델 규칙을 사용할 수 있습니다.
                        </p>
                      </div>
                      <span className="rounded bg-white px-2 py-1 text-[11px] font-semibold text-slate-700 ring-1 ring-slate-200">
                        {adaptiveRoutingSummary.active_cohort_count}/
                        {adaptiveRoutingSummary.max_cohorts}
                      </span>
                    </div>
                    {adaptiveRoutingSummary.cohorts.length === 0 ? (
                      <div className="mt-3 rounded border border-dashed border-slate-200 bg-white px-3 py-2 text-[11px] text-slate-500">
                        <p>
                          입력군이 없어 현재 모든 요청은 기본 모델로 처리합니다. 서로 다른 운영 입력이 두 점검 구간에서 충분히 쌓이면 입력군을 자동으로 발견합니다.
                        </p>
                        <button
                          type="button"
                          className="nodrag mt-2 font-semibold text-slate-700 underline underline-offset-2 hover:text-slate-950 disabled:cursor-not-allowed disabled:opacity-60"
                          onClick={openManualCohortForm}
                        >
                          대표 문의로 입력군 만들기
                        </button>
                      </div>
                    ) : (
                      <ul className="mt-3 space-y-2">
                        {adaptiveRoutingSummary.cohorts.slice(0, 6).map((cohort) => (
                          <li
                            key={cohort.id}
                            className="flex items-start justify-between gap-3 rounded border border-slate-200 bg-white px-2.5 py-2 text-[11px]"
                          >
                            <div className="min-w-0">
                              <div className="flex items-center gap-2">
                                <span className="truncate font-semibold text-slate-800">
                                {cohort.label}
                                </span>
                                <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
                                  {cohort.source === 'manual' ? '사용자 등록' : '자동 발견'}
                                </span>
                              </div>
                              <p className="mt-1 whitespace-pre-wrap break-words leading-relaxed text-slate-600">
                                대표 문의:{' '}
                                {cohort.representative_query || '대표 문의를 준비 중입니다.'}
                              </p>
                              {(cohort.representative_examples?.length || 0) > 1 ? (
                                <p className="mt-1 text-slate-500">
                                  매칭 예문 {cohort.representative_examples?.length}개
                                </p>
                              ) : null}
                              <p className="mt-1 text-slate-500">
                                {cohort.key} · {cohort.source === 'manual' ? '직접 등록' : '자동 발견'} ·{' '}
                                {cohort.observation_count}회
                              </p>
                            </div>
                            <div className="shrink-0 text-right">
                              <span className="block font-semibold text-slate-700">
                                {cohort.status === 'draft' ? '초안' : cohort.status}
                              </span>
                              <span className="block text-slate-500">
                                기본 모델: {cohort.validated_model_id || '검증 대기'}
                              </span>
                              <span className="block text-slate-500">
                                {cohort.required ? '고정됨' : '자동 관리'}
                              </span>
                              <div className="mt-2 flex justify-end gap-1.5">
                                {cohort.source === 'manual' ? (
                                  <button
                                    type="button"
                                    className="nodrag rounded border border-slate-300 bg-white px-2 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-100"
                                    onClick={() => handleManualCohortEdit(cohort)}
                                    aria-label={`${cohort.label} 수정`}
                                  >
                                    수정
                                  </button>
                                ) : (
                                  <button
                                    type="button"
                                    className="nodrag rounded border border-violet-300 bg-violet-50 px-2 py-1 text-[11px] font-semibold text-violet-800 hover:bg-violet-100"
                                    onClick={() => handleAutoCohortConvert(cohort)}
                                    aria-label={`${cohort.label} 사용자 입력군으로 전환`}
                                  >
                                    사용자 입력군으로 전환
                                  </button>
                                )}
                                {!cohort.safety_protected ? (
                                  <button
                                    type="button"
                                    className="nodrag rounded border border-rose-200 bg-white px-2 py-1 text-[11px] font-semibold text-rose-700 hover:bg-rose-50"
                                    onClick={() => handleManualCohortDelete(cohort)}
                                    aria-label={`${cohort.label} 입력군 삭제`}
                                  >
                                    삭제
                                  </button>
                                ) : null}
                              </div>
                            </div>
                          </li>
                        ))}
                      </ul>
                    )}
                    {adaptiveRoutingSummary.latest_batch ? (
                      <p className="mt-3 text-[11px] text-slate-500">
                        최근 검증 배치: {adaptiveRoutingSummary.latest_batch.completed_items}/
                        {adaptiveRoutingSummary.latest_batch.total_items}회 완료 ·{' '}
                        {adaptiveRoutingSummary.latest_batch.status}
                      </p>
                    ) : null}
                    <div className="mt-3 border-t border-slate-200 pt-3">
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-xs font-semibold text-slate-800">
                          입력군 초안
                        </div>
                        <button
                          type="button"
                          className="nodrag rounded border border-slate-300 bg-white px-2 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
                          onClick={() => {
                            if (isManualCohortFormOpen) {
                              setIsManualCohortFormOpen(false);
                              setEditingManualCohortId(null);
                              setConvertingAutoCohortId(null);
                            } else {
                              openManualCohortForm();
                            }
                          }}
                        >
                          {isManualCohortFormOpen ? '닫기' : '직접 입력군 추가'}
                        </button>
                      </div>
                      {!persistedRoutingPolicy?.policy_id ? (
                        <p className="mt-2 text-[11px] text-slate-500">
                          지금 저장한 입력군은 workflow 초안에 보관되고, 첫 배포 운영 실행에서 실제 라우팅 입력군으로 준비됩니다.
                        </p>
                      ) : null}
                      {isManualCohortFormOpen ? (
                        <div className="mt-3 space-y-2 rounded border border-slate-200 bg-white p-3">
                          <p className="text-[11px] font-semibold text-slate-800">
                            {editingManualCohortId || convertingAutoCohortId
                              ? '사용자 입력군 수정'
                              : '사용자 입력군 등록'}
                          </p>
                          {editingManualCohortId || convertingAutoCohortId ? (
                            <p className="rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-[11px] leading-relaxed text-amber-800">
                              대표 문의를 바꾸면 기존 모델 검증 결과는 다시 확인해야 합니다. 이 입력군은 검증 대기 상태로 전환됩니다.
                            </p>
                          ) : null}
                          <label className="block text-[11px] font-medium text-slate-700">
                            대표 문의
                            <textarea
                              aria-label="대표 문의"
                              value={manualCohort.representativeQuery}
                              onChange={(event) =>
                                setManualCohort((current) => ({
                                  ...current,
                                  representativeQuery: event.target.value,
                                }))
                              }
                              className="nodrag mt-1 min-h-20 w-full resize-y rounded border border-slate-300 px-2 py-1.5 text-xs text-slate-800"
                              placeholder="예: 결제가 완료됐는데 서비스 이용이 되지 않습니다."
                            />
                            <span className="mt-1 block text-[10px] font-normal leading-relaxed text-slate-500">
                              대표 문의는 입력군 설정으로 저장됩니다. 실제 고객 정보, 비밀값, API 키는 넣지 마세요.
                            </span>
                          </label>
                          <label className="flex items-start gap-2 rounded border border-slate-200 bg-slate-50 px-2.5 py-2 text-[11px] text-slate-700">
                            <input
                              type="checkbox"
                              className="nodrag mt-0.5 h-3.5 w-3.5"
                              checked={manualCohort.fixed}
                              onChange={(event) =>
                                setManualCohort((current) => ({
                                  ...current,
                                  fixed: event.target.checked,
                                }))
                              }
                            />
                            <span>
                              <span className="block font-semibold">입력군 고정</span>
                              <span className="mt-0.5 block text-slate-500">
                                고정하면 입력량이 줄어도 자동 휴면 또는 종료 처리하지 않습니다.
                              </span>
                            </span>
                          </label>
                          <label className="flex items-start gap-2 rounded border border-rose-200 bg-rose-50 px-2.5 py-2 text-[11px] text-rose-900">
                            <input
                              type="checkbox"
                              className="nodrag mt-0.5 h-3.5 w-3.5"
                              checked={manualCohort.safetyProtected}
                              onChange={(event) =>
                                setManualCohort((current) => ({
                                  ...current,
                                  safetyProtected: event.target.checked,
                                }))
                              }
                            />
                            <span>
                              <span className="block font-semibold">고위험 입력군</span>
                              <span className="mt-0.5 block text-rose-700">
                                보안, 개인정보, 법무, SLA, 금전 보상처럼 오답 영향이 큰 문의입니다. 예문 5개와 강화된 품질 검증을 요구합니다.
                              </span>
                            </span>
                          </label>
                          <button
                            type="button"
                            className="nodrag inline-flex items-center gap-1 rounded border border-violet-300 bg-violet-50 px-2 py-1.5 text-[11px] font-semibold text-violet-800 hover:bg-violet-100 disabled:cursor-not-allowed disabled:opacity-60"
                            onClick={handleManualCohortWizard}
                            disabled={
                              !manualCohort.representativeQuery.trim() ||
                              isCohortWizardRunning
                            }
                          >
                            <Wand2 className="h-3.5 w-3.5" />
                            {isCohortWizardRunning ? '초안 만드는 중' : '입력군 마법사'}
                          </button>
                          {manualCohort.additionalExamples.length > 0 ? (
                            <div className="rounded border border-violet-100 bg-violet-50/50 p-2.5">
                              <div className="text-[11px] font-semibold text-violet-950">
                                자동 생성 예문
                              </div>
                              <p className="mt-0.5 text-[10px] leading-relaxed text-violet-700">
                                실제 문의는 대표 문의와 아래 예문을 함께 비교합니다. 맞지 않는 예문은 삭제하세요.
                              </p>
                              <ul className="mt-2 space-y-1.5">
                                {manualCohort.additionalExamples.map((example, index) => (
                                  <li
                                    key={`${example}-${index}`}
                                    className="flex items-start justify-between gap-2 rounded border border-violet-100 bg-white px-2 py-1.5 text-[11px] text-slate-700"
                                  >
                                    <span className="min-w-0 whitespace-pre-wrap break-words">
                                      {example}
                                    </span>
                                    <button
                                      type="button"
                                      className="nodrag shrink-0 font-semibold text-rose-600 hover:text-rose-800"
                                      aria-label={`자동 생성 예문 ${index + 1} 삭제`}
                                      onClick={() =>
                                        setManualCohort((current) => ({
                                          ...current,
                                          additionalExamples: current.additionalExamples.filter(
                                            (_, itemIndex) => itemIndex !== index,
                                          ),
                                        }))
                                      }
                                    >
                                      삭제
                                    </button>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          ) : null}
                          <p
                            className={`rounded border px-2 py-1.5 text-[11px] ${
                              manualCohortHasEnoughExamples
                                ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                                : 'border-amber-200 bg-amber-50 text-amber-800'
                            }`}
                          >
                            {manualCohortHasEnoughExamples
                              ? `대표 예문 ${manualCohortExampleCount}개가 준비됐습니다.`
                              : `대표 예문이 최소 ${manualCohortRequiredExampleCount}개 필요합니다.`}
                          </p>
                          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                            <label className="block text-[11px] font-medium text-slate-700">
                              입력군 이름
                              <input
                                aria-label="입력군 이름"
                                value={manualCohort.label}
                                onChange={(event) =>
                                  setManualCohort((current) => ({
                                    ...current,
                                    label: event.target.value,
                                  }))
                                }
                                className="nodrag mt-1 h-8 w-full rounded border border-slate-300 px-2 text-xs text-slate-800"
                                placeholder="예: 결제 오류 문의"
                              />
                            </label>
                            <label className="block text-[11px] font-medium text-slate-700">
                              영문 키
                              <input
                                aria-label="영문 키"
                                value={manualCohort.key}
                                onChange={(event) =>
                                  setManualCohort((current) => ({
                                    ...current,
                                    key: event.target.value,
                                  }))
                                }
                                className="nodrag mt-1 h-8 w-full rounded border border-slate-300 px-2 font-mono text-xs text-slate-800"
                                placeholder="billing_issue"
                              />
                            </label>
                          </div>
                          <div className="flex justify-end">
                            <button
                              type="button"
                              className="nodrag rounded bg-slate-900 px-2.5 py-1.5 text-[11px] font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"
                              onClick={handleManualCohortCreate}
                              disabled={
                                !manualCohort.label.trim() ||
                                 !manualCohort.key.trim() ||
                                 !manualCohort.representativeQuery.trim() ||
                                 !manualCohortHasEnoughExamples ||
                                 isManualCohortCreating
                              }
                            >
                              {isManualCohortCreating
                                ? editingManualCohortId || convertingAutoCohortId
                                  ? '수정 중'
                                  : '등록 중'
                                : editingManualCohortId || convertingAutoCohortId
                                  ? '입력군 수정'
                                  : '입력군 추가'}
                            </button>
                          </div>
                        </div>
                      ) : null}
                    </div>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex items-center">
                    <label className="text-xs font-semibold text-gray-700">
                      기본 모델
                    </label>
                    <PropertyVisibilityToggle
                      nodeId={nodeId}
                      propertyKey="model_id"
                    />
                  </div>
                  <ModelSelectDropdown
                    value={data.model_id || ''}
                    onChange={handleModelChange}
                    models={chatModelOptions}
                    groupedModels={groupedModelOptions}
                    placeholder="모델을 선택하세요"
                  />
                  <div className="mt-3 flex flex-col gap-2">
                    <div className="flex items-center gap-1">
                      <label className="text-xs font-semibold text-gray-700">
                        대체 모델
                      </label>
                      <HelpPopover
                        id="fallback"
                        activeHelp={activeHelp}
                        onToggle={toggleHelp}
                        widthClassName="w-60"
                      >
                        기본 모델 호출이 실패하거나 타임아웃될 때 대신 사용할
                        모델입니다.
                      </HelpPopover>
                    </div>
                    <div className="relative group">
                      <ModelSelectDropdown
                        value={data.fallback_model_id || ''}
                        onChange={(val) =>
                          handleUpdateData('fallback_model_id', val)
                        }
                        models={fallbackCandidates}
                        groupedModels={groupedFallbackOptions}
                        disabled={fallbackDisabled}
                        placeholder={
                          fallbackDisabled
                            ? '먼저 모델을 선택하세요'
                            : '대체 모델을 선택하세요'
                        }
                      />
                      {fallbackDisabled && (
                        <div className="pointer-events-none absolute left-0 top-full z-10 mt-1 w-56 rounded border border-gray-200 bg-white p-2 text-[11px] text-gray-600 shadow-lg opacity-0 transition-opacity group-hover:opacity-100">
                          먼저 기본 모델을 설정해주세요.
                        </div>
                      )}
                    </div>
                    <p className="text-xs text-gray-500">
                      대체 모델은 다른 Provider 사용을 권장합니다.
                      <br />
                      다른 Provider를 추가하려면 아래에서 API Key를
                      등록하세요.
                    </p>
                  </div>
                </>
              )}

              {!data.auto_model_routing && (
                <button
                  onClick={openSettingsTab}
                  className="mt-2 text-left text-xs text-blue-600 hover:text-blue-800 hover:underline"
                >
                  Provider API Key 등록하기
                </button>
              )}
            </>
          ) : (
            <div className="flex flex-col gap-2 p-3 bg-gray-50 rounded border border-gray-200 items-center justify-center text-center">
              <span className="text-xs text-gray-500">
                사용 가능한 모델이 없습니다.
              </span>
              <button
                onClick={openSettingsTab}
                className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium rounded transition-colors"
              >
                Provider 설정하러 가기 →
              </button>
            </div>
          )}
        </div>
      </CollapsibleSection>

      <CollapsibleSection title="출력 형식">
        <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-bold text-gray-900">
            <FileJson className="h-4 w-4 text-gray-600" />
            출력 형식
          </div>
          <div className="inline-flex rounded-md border border-gray-200 bg-white p-1">
            {(['text', 'json'] as const).map((format) => (
              <button
                key={format}
                type="button"
                onClick={() => updateOutputFormat(format)}
                className={`rounded px-3 py-1.5 text-xs font-bold transition-colors ${
                  outputFormatType === format
                    ? 'bg-emerald-600 text-white'
                    : 'text-gray-600 hover:bg-gray-50'
                }`}
              >
                {format === 'json' ? 'JSON' : 'TEXT'}
              </button>
            ))}
          </div>

          {outputFormatType === 'json' ? (
            <div className="mt-3 grid gap-3 rounded-md border border-dashed border-gray-300 bg-white p-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-xs font-bold text-gray-700">
                    JSON schema
                  </div>
                  <div className="text-[11px] text-gray-500">
                    flat key-type 행으로 출력 계약을 정의합니다.
                  </div>
                </div>
                <button
                  type="button"
                  onClick={addJsonSchemaField}
                  className="rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs font-bold text-gray-700 hover:bg-gray-50"
                >
                  스키마 필드 추가
                </button>
              </div>

              {draftJsonSchemaFields.length === 0 ? (
                <div className="rounded-md bg-gray-50 px-3 py-2 text-xs text-gray-500">
                  정의된 필드가 없습니다.
                </div>
              ) : (
                <div className="grid gap-2">
                  {draftJsonSchemaFields.map((field, index) => (
                    <div
                      key={`json-schema-field-${index}`}
                      className="grid grid-cols-[minmax(120px,1fr)_minmax(110px,140px)_auto_auto] items-center gap-2 rounded-md border border-gray-200 bg-white p-2"
                    >
                      <label className="grid gap-1 text-[11px] font-semibold text-gray-500">
                        <span>필드명</span>
                        <input
                          value={field.key}
                          onChange={(event) =>
                            updateJsonSchemaField(index, {
                              key: event.target.value,
                            })
                          }
                          className="min-w-0 rounded-md border border-gray-200 px-2 py-1.5 text-xs text-gray-800 outline-none focus:border-emerald-400"
                          placeholder="예: summary"
                        />
                      </label>
                      <label className="grid gap-1 text-[11px] font-semibold text-gray-500">
                        <span>타입</span>
                        <select
                          value={field.type}
                          onChange={(event) =>
                            updateJsonSchemaField(index, {
                              type: event.target.value as JsonSchemaFieldType,
                            })
                          }
                          className="min-w-0 rounded-md border border-gray-200 px-2 py-1.5 text-xs text-gray-800 outline-none focus:border-emerald-400"
                        >
                          {schemaFieldTypes.map((fieldType) => (
                            <option key={fieldType.value} value={fieldType.value}>
                              {fieldType.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label className="flex items-center gap-1 pt-5 text-xs font-semibold text-gray-600">
                        <input
                          type="checkbox"
                          checked={field.required}
                          onChange={(event) =>
                            updateJsonSchemaField(index, {
                              required: event.target.checked,
                            })
                          }
                        />
                        필수
                      </label>
                      <button
                        type="button"
                        onClick={() => removeJsonSchemaField(index)}
                        className="mt-5 rounded-md px-2 py-1 text-xs font-bold text-red-500 hover:bg-red-50"
                      >
                        삭제
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : null}
        </div>
      </CollapsibleSection>

      {/* 2.5 Knowledge 선택 버튼 */}
      <div className="my-2 group">
        <button
          type="button"
          onClick={() => {
            if (onOpenKnowledgeBaseSettings) {
              onOpenKnowledgeBaseSettings();
              return;
            }
            // 부모 컴포넌트에서 사이드 패널 열기
            const event = new CustomEvent('openLLMReferencePanel', {
              detail: { nodeId },
            });
            window.dispatchEvent(event);
          }}
          className={`relative w-full py-4 px-5 rounded-xl border-2 border-dashed transition-all duration-300 flex items-center gap-4 active:scale-[0.98] ${
            (data.knowledgeBases?.length ?? 0) > 0 ||
            (data.knowledgeCollections?.length ?? 0) > 0
              ? 'border-indigo-400 bg-indigo-50/80 text-indigo-800 shadow-sm hover:shadow-md hover:bg-indigo-50 hover:border-indigo-500'
              : 'border-gray-300 bg-gray-50/50 text-gray-600 hover:border-indigo-400 hover:bg-indigo-50/30 hover:text-indigo-700 hover:shadow-sm'
          }`}
        >
          {/* 호버 시 배경 일러스트 효과 */}
          <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/40 to-transparent translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-1000 pointer-events-none" />

          {/* 왼쪽 아이콘 (책) */}
          <div
            className={`p-2 rounded-lg transition-colors duration-300 ${
              (data.knowledgeBases?.length ?? 0) > 0 ||
              (data.knowledgeCollections?.length ?? 0) > 0
                ? 'bg-indigo-200 text-indigo-700'
                : 'bg-gray-200 text-gray-500 group-hover:bg-indigo-100 group-hover:text-indigo-600'
            }`}
          >
            <BookOpen className="w-5 h-5" />
          </div>

          {/* 텍스트 내용 */}
          <div className="flex flex-col items-start flex-1 gap-0.5">
            <span className="font-bold text-sm tracking-tight">
              Knowledge 설정
            </span>
            <span
              className={`text-xs transition-colors duration-300 ${
                (data.knowledgeBases?.length ?? 0) > 0 ||
                (data.knowledgeCollections?.length ?? 0) > 0
                  ? 'text-indigo-600 font-medium'
                  : 'text-gray-400 group-hover:text-indigo-500'
              }`}
            >
              {(data.knowledgeBases?.length ?? 0) > 0 ||
              (data.knowledgeCollections?.length ?? 0) > 0
                ? `고정 KB ${data.knowledgeBases?.length ?? 0}개 · Collection ${
                    data.knowledgeCollections?.length ?? 0
                  }개`
                : 'LLM에 지식을 연결하세요'}
            </span>
          </div>

          {/* 오른쪽 아이콘 (클릭 동작) */}
          <div className="transform transition-all duration-300 group-hover:scale-110 group-hover:rotate-[-6deg] text-gray-300 group-hover:text-indigo-500">
            <MousePointerClick className="w-6 h-6" />
          </div>
        </button>
      </div>

      {/* 3. 프롬프트 */}
      <CollapsibleSection title="프롬프트">
        <div className="flex flex-col gap-3 relative">
          {/* 프롬프트 설명 */}
          <p className="text-xs text-gray-500 mb-1">
            LLM에 전달할 메시지를 작성하세요. 최소 1개 이상 입력이 필요합니다.
          </p>

          {allPromptsEmpty && (
            <ValidationAlert message="⚠️ 최소 1개의 프롬프트를 입력해야 실행할 수 있습니다." />
          )}

          <div>
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center">
                <label className="text-xs font-semibold text-gray-700">
                  시스템 프롬프트
                </label>
                <PropertyVisibilityToggle
                  nodeId={nodeId}
                  propertyKey="system_prompt"
                />
                <HelpPopover
                  id="system"
                  activeHelp={activeHelp}
                  onToggle={toggleHelp}
                >
                  AI의 역할, 성격, 행동 규칙을 정의합니다. 모든 대화에 일관되게
                  적용됩니다.
                </HelpPopover>
              </div>
              <div className="group/wizard relative">
                <button
                  type="button"
                  onClick={() => openWizard('system')}
                  disabled={modelOptions.length === 0}
                  className="flex items-center gap-1 px-1.5 py-0.5 text-blue-500 hover:text-blue-700 hover:bg-blue-50 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed text-[10px]"
                >
                  <Wand2 className="w-3 h-3" />
                  <span>프롬프트 마법사</span>
                </button>
                <div className="absolute z-50 hidden group-hover/wizard:block w-32 p-2 text-[11px] text-gray-600 bg-white border border-gray-200 rounded-lg shadow-lg right-0 top-7">
                  AI가 프롬프트를 개선해드려요
                  <div className="absolute -top-1 right-2 w-2 h-2 bg-white border-l border-t border-gray-200 rotate-45" />
                </div>
              </div>
            </div>
            <VariableTokenEditor
              className="min-h-24"
              ariaLabel="시스템 프롬프트"
              placeholder="예: 너는 친절하고 전문적인 고객 상담 AI입니다. 항상 존댓말을 사용하고, 정확하고 간결하게 답변해주세요."
              value={data.system_prompt || ''}
              onChange={(value) => handleFieldChange('system_prompt', value)}
              onDropOutput={handlePromptDropOutput}
              tokenLabels={tokenLabels}
            />
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center">
                <label className="text-xs font-semibold text-gray-700">
                  사용자 프롬프트
                </label>
                <PropertyVisibilityToggle
                  nodeId={nodeId}
                  propertyKey="user_prompt"
                />
                <HelpPopover
                  id="user"
                  activeHelp={activeHelp}
                  onToggle={toggleHelp}
                >
                  사용자가 AI에게 보내는 질문이나 요청입니다. 좌측 입력 패널에서
                  변수를 클릭해 동적 값을 삽입할 수 있습니다.
                </HelpPopover>
              </div>
              <div className="group/wizard relative">
                <button
                  type="button"
                  onClick={() => openWizard('user')}
                  disabled={modelOptions.length === 0}
                  className="flex items-center gap-1 px-1.5 py-0.5 text-blue-500 hover:text-blue-700 hover:bg-blue-50 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed text-[10px]"
                >
                  <Wand2 className="w-3 h-3" />
                  <span>프롬프트 마법사</span>
                </button>
                <div className="absolute z-50 hidden group-hover/wizard:block w-32 p-2 text-[11px] text-gray-600 bg-white border border-gray-200 rounded-lg shadow-lg right-0 top-7">
                  AI가 프롬프트를 개선해드려요
                  <div className="absolute -top-1 right-2 w-2 h-2 bg-white border-l border-t border-gray-200 rotate-45" />
                </div>
              </div>
            </div>
            <VariableTokenEditor
              className="min-h-32"
              ariaLabel="사용자 프롬프트"
              placeholder={`예: 다음 내용을 한국어로 3줄 요약해줘:\n\n여기에 입력 변수를 넣으려면 좌측 입력 패널의 변수를 클릭하세요.`}
              value={data.user_prompt || ''}
              onChange={(value) => handleFieldChange('user_prompt', value)}
              onDropOutput={handlePromptDropOutput}
              tokenLabels={tokenLabels}
            />
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center">
                <label className="text-xs font-semibold text-gray-700">
                  어시스턴트 프롬프트
                </label>
                <PropertyVisibilityToggle
                  nodeId={nodeId}
                  propertyKey="assistant_prompt"
                />
                <HelpPopover
                  id="assistant"
                  activeHelp={activeHelp}
                  onToggle={toggleHelp}
                >
                  AI 응답의 시작 부분을 미리 지정합니다. 특정 형식이나 톤으로
                  응답을 유도할 때 유용합니다.
                </HelpPopover>
              </div>
              <div className="group/wizard relative">
                <button
                  type="button"
                  onClick={() => openWizard('assistant')}
                  disabled={modelOptions.length === 0}
                  className="flex items-center gap-1 px-1.5 py-0.5 text-blue-500 hover:text-blue-700 hover:bg-blue-50 rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed text-[10px]"
                >
                  <Wand2 className="w-3 h-3" />
                  <span>프롬프트 마법사</span>
                </button>
                <div className="absolute z-50 hidden group-hover/wizard:block w-32 p-2 text-[11px] text-gray-600 bg-white border border-gray-200 rounded-lg shadow-lg right-0 top-7">
                  AI가 프롬프트를 개선해드려요
                  <div className="absolute -top-1 right-2 w-2 h-2 bg-white border-l border-t border-gray-200 rotate-45" />
                </div>
              </div>
            </div>
            <VariableTokenEditor
              className="min-h-24"
              ariaLabel="어시스턴트 프롬프트"
              placeholder="예: 분석 결과를 다음과 같이 정리하겠습니다:"
              value={data.assistant_prompt || ''}
              onChange={(value) => handleFieldChange('assistant_prompt', value)}
              onDropOutput={handlePromptDropOutput}
              tokenLabels={tokenLabels}
            />
          </div>

          {validationErrors.length > 0 && (
            <UnregisteredVariablesAlert variables={validationErrors} />
          )}
        </div>
      </CollapsibleSection>

        </>
      )}

      {isOptimizationModalOpen ? (
        <OptimizationRecommendationModal
          workflowId={activeWorkflowId}
          workflowName="현재 workflow"
          llmNodes={[
            {
              id: nodeId,
              title: String(data.title || 'LLM 노드'),
              candidateDraft: candidateFromOptions(data),
            },
          ]}
          initialNodeId={nodeId}
          appliedIds={appliedRecommendationIds}
          onClose={() => setIsOptimizationModalOpen(false)}
          onMarkForReview={setAppliedRecommendationIds}
          onApplyPatches={applyRecommendationPatches}
        />
      ) : null}

      {/* 프롬프트 마법사 모달 */}
      <PromptWizardModal
        isOpen={wizardOpen}
        onClose={() => setWizardOpen(false)}
        promptType={wizardField}
        organizationId={wizardOrganizationId}
        originalPrompt={
          wizardField === 'system'
            ? data.system_prompt || ''
            : wizardField === 'user'
              ? data.user_prompt || ''
              : data.assistant_prompt || ''
        }
        onApply={handleApplyImproved}
      />
    </div>
  );
}
