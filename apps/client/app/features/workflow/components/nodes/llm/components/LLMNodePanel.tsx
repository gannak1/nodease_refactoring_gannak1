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
import { workflowApi } from '@/app/features/workflow/api/workflowApi';
import type {
  ModelRoutingBootstrapPreview,
  ModelRoutingBootstrapResponse,
  ModelRoutingPolicyResponse,
} from '@/app/features/workflow/types/Api';

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

const routingProfileLabel = (profile: string) => {
  if (profile === 'short') return '짧은 입력';
  if (profile === 'long') return '긴 입력';
  return '보통 입력';
};

const routingProfileReasonLabel = (reasonCode?: string | null) => {
  if (reasonCode === 'prior_guided_utility_selected') {
    return '품질 기준을 만족한 모델 중 비용과 지연 시간이 유리한 모델';
  }
  if (reasonCode === 'prior_guided_constraints_safe_default') {
    return '필수 조건을 만족하는 다른 후보가 없어 기본 모델 유지';
  }
  return '모델 기능과 운영 통계를 기준으로 선택';
};

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
  const [routingBootstrapPreview, setRoutingBootstrapPreview] =
    useState<ModelRoutingBootstrapPreview | null>(null);
  const [routingBootstrap, setRoutingBootstrap] =
    useState<ModelRoutingBootstrapResponse | null>(null);
  const [routingTaskDescription, setRoutingTaskDescription] = useState(
    data.model_routing_task_description || '',
  );
  const [routingInitialBudgetUsd, setRoutingInitialBudgetUsd] = useState(1);
  const [isCreatingRoutingBootstrap, setIsCreatingRoutingBootstrap] =
    useState(false);

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
        ? activePolicy.strategy_id === 'bootstrap_mdeberta_difficulty_v1'
          ? '작업 지문과 안전한 표본으로 난이도를 분류해 모델을 선택합니다.'
          : '모델 사전 지식과 운영 통계로 입력 길이별 정책을 계산합니다.'
        : '정책 대기 중',
      runsSinceLastRefresh,
      refreshEveryRuns,
      lastUpdate: policy?.last_update ?? null,
      performance: policy?.performance ?? {
        total_runs: 0,
        model_count: 0,
        last_recorded_at: null,
        models: [],
      },
      changePolicy: policy?.change_policy ?? {
        mode: 'event_driven' as const,
        minimum_new_runs: 3,
        quality_change_threshold: 0.05,
        efficiency_improvement_threshold: 0.1,
      },
    };
  }, [
    data.auto_model_routing,
    data.model_routing_policy,
    persistedRoutingPolicy,
  ]);
  const priorGuidedProfiles = useMemo(
    () => persistedRoutingPolicy?.active_policy?.decision_profiles ?? [],
    [persistedRoutingPolicy?.active_policy?.decision_profiles],
  );
  const bootstrapDifficultyModels = useMemo(
    () => persistedRoutingPolicy?.active_policy?.difficulty_models ?? {},
    [persistedRoutingPolicy?.active_policy?.difficulty_models],
  );
  const isBootstrapRouting =
    data.model_routing_strategy === 'bootstrap_mdeberta_difficulty_v1' ||
    persistedRoutingPolicy?.active_policy?.strategy_id ===
      'bootstrap_mdeberta_difficulty_v1';
  const isRoutingBootstrapGenerating = routingBootstrap?.status === 'generating';
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
  const loadRoutingPolicy = useCallback(async () => {
    if (!activeWorkflowId) return;
    try {
      const policy = await workflowApi.getModelRoutingPolicy(
        activeWorkflowId,
        nodeId,
      );
      setPersistedRoutingPolicy(policy);
      setRoutingPolicyError(null);
    } catch {
      setPersistedRoutingPolicy(null);
      setRoutingPolicyError('정책 상태를 불러오지 못했습니다.');
    }
  }, [activeWorkflowId, nodeId]);

  const loadRoutingBootstrapPreview = useCallback(async () => {
    if (!activeWorkflowId) return;
    try {
      const preview = await workflowApi.getModelRoutingBootstrapPreview(
        activeWorkflowId,
        nodeId,
      );
      setRoutingBootstrapPreview(preview);
      setRoutingBootstrap(preview.bootstrap);
    } catch {
      setRoutingBootstrapPreview(null);
    }
  }, [activeWorkflowId, nodeId]);

  const syncRoutingPolicy = useCallback(
    async (
      enabled: boolean,
      refreshEveryRuns: number,
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
      // 켜는 순간에는 아직 Planner artifact가 없을 수 있다. PATCH로 빈 정책을
      // 먼저 저장하지 않고, 사용자가 작업 설명을 확인한 뒤 생성 버튼으로 한 번에
      // 저장한다. 끌 때만 즉시 runtime policy를 off로 전환한다.
      if (!enabled) {
        void syncRoutingPolicy(false, routingPolicySummary.refreshEveryRuns);
      }
    },
    [
      handleUpdateData,
      routingPolicySummary.refreshEveryRuns,
      syncRoutingPolicy,
    ],
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

  const handleCreateRoutingBootstrap = useCallback(async () => {
    if (!activeWorkflowId || isCreatingRoutingBootstrap) return;
    if (!routingTaskDescription.trim()) {
      setRoutingPolicyError('이 노드가 처리하는 작업을 한 문장 이상 설명하세요.');
      return;
    }
    if (!data.model_id) {
      setRoutingPolicyError('규칙이 맞지 않을 때 사용할 기본 모델을 선택하세요.');
      return;
    }
    try {
      setIsCreatingRoutingBootstrap(true);
      const bootstrap = await workflowApi.createModelRoutingBootstrap(
        activeWorkflowId,
        nodeId,
        {
          task_description: routingTaskDescription.trim(),
          default_model_id: data.model_id,
          fallback_model_id: data.fallback_model_id || null,
          initial_budget_usd: routingInitialBudgetUsd,
        },
      );
      setRoutingBootstrap(bootstrap);
      updateNodeData(nodeId, {
        auto_model_routing: true,
        model_routing_bootstrap_id: bootstrap.id,
        model_routing_bootstrap_fingerprint: bootstrap.task_fingerprint,
        model_routing_task_description: bootstrap.task_description,
        model_routing_strategy: 'bootstrap_mdeberta_difficulty_v1',
      });
      setRoutingPolicyError(null);
      await Promise.all([loadRoutingBootstrapPreview(), loadRoutingPolicy()]);
    } catch {
      setRoutingPolicyError('자동 선택 기준을 만들지 못했습니다. 모델 권한과 작업 설명을 확인하세요.');
    } finally {
      setIsCreatingRoutingBootstrap(false);
    }
  }, [
    activeWorkflowId,
    data.fallback_model_id,
    data.model_id,
    isCreatingRoutingBootstrap,
    loadRoutingBootstrapPreview,
    loadRoutingPolicy,
    nodeId,
    routingInitialBudgetUsd,
    routingTaskDescription,
    updateNodeData,
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
        nextModelId,
        nextFallbackModelId,
      );
    },
    [
      data.fallback_model_id,
      handleModelChange,
      routingPolicySummary.refreshEveryRuns,
      syncRoutingPolicy,
    ],
  );

  const handleRoutingFallbackModelChange = useCallback(
    (nextFallbackModelId: string) => {
      handleUpdateData('fallback_model_id', nextFallbackModelId);
      void syncRoutingPolicy(
        true,
        routingPolicySummary.refreshEveryRuns,
        data.model_id || '',
        nextFallbackModelId || null,
      );
    },
    [
      data.model_id,
      handleUpdateData,
      routingPolicySummary.refreshEveryRuns,
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
    void loadRoutingBootstrapPreview();
  }, [data.auto_model_routing, loadRoutingBootstrapPreview, loadRoutingPolicy]);

  useEffect(() => {
    if (!data.auto_model_routing || !isRoutingBootstrapGenerating) return;

    // Planner는 Worker에서 여러 LLM 호출로 예문과 규칙을 만든다. UI 요청을 오래
    // 붙잡지 않고, 생성 중인 artifact만 짧은 간격으로 다시 조회한다.
    const timer = window.setInterval(() => {
      void loadRoutingBootstrapPreview();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [
    data.auto_model_routing,
    isRoutingBootstrapGenerating,
    loadRoutingBootstrapPreview,
  ]);

  useEffect(() => {
    setRoutingTaskDescription(data.model_routing_task_description || '');
  }, [data.model_routing_task_description, nodeId]);

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
          <div>
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
                  <div className="mt-3 rounded-md border border-violet-200 bg-violet-50/50 p-3">
                    <div className="flex items-start gap-1.5">
                      <div className="text-xs font-semibold text-violet-950">
                        자동 선택 기준 만들기
                      </div>
                      <HelpPopover
                        id="system"
                        activeHelp={activeHelp}
                        onToggle={toggleHelp}
                        widthClassName="w-72"
                      >
                        이 노드의 프롬프트와 작업 설명을 기준으로 간단한 요청과 더
                        많은 추론이 필요한 요청을 구분하는 기준입니다. 기준을 만든
                        뒤에는 실행마다 평가용 LLM을 호출하지 않습니다.
                      </HelpPopover>
                    </div>
                    <p className="mt-1 text-[11px] leading-relaxed text-violet-800">
                      작업 설명과 안전하게 요약한 운영 로그를 사용해 첫 배포부터
                      사용할 난이도 분류 기준을 만듭니다.
                    </p>
                    <label className="mt-3 block text-[11px] font-semibold text-slate-700">
                      이 노드가 하는 작업
                      <textarea
                        className="nodrag mt-1 min-h-20 w-full resize-y rounded border border-slate-300 bg-white px-2 py-1.5 text-xs font-normal text-slate-800 outline-none focus:border-violet-500"
                        value={routingTaskDescription}
                        onChange={(event) => setRoutingTaskDescription(event.target.value)}
                        placeholder="예: 고객 문의를 JSON으로 분류하고, 보상·SLA·개인정보 위험은 더 신중하게 판단합니다."
                        aria-label="자동 라우팅 작업 설명"
                      />
                    </label>
                    <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                      <section
                        className="rounded border border-violet-100 bg-white px-2 py-2"
                        aria-labelledby="routing-initial-budget"
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <h4
                              id="routing-initial-budget"
                              className="text-[11px] font-semibold text-slate-700"
                            >
                              1회 초기 생성 예산
                            </h4>
                            <p className="mt-0.5 text-[10px] text-slate-500">
                              기준을 처음 만들 때만 사용합니다.
                            </p>
                          </div>
                          <output className="rounded border border-violet-200 bg-violet-50 px-2 py-1 text-xs font-semibold text-violet-800">
                            ${routingInitialBudgetUsd.toFixed(2)}
                          </output>
                        </div>
                        <input
                          type="range"
                          min="0.5"
                          max="10"
                          step="0.5"
                          value={routingInitialBudgetUsd}
                          onChange={(event) =>
                            setRoutingInitialBudgetUsd(Number(event.target.value))
                          }
                          aria-label="1회 초기 생성 예산"
                          className="nodrag mt-2 w-full accent-violet-600"
                        />
                        <div className="mt-1 flex justify-between text-[10px] text-slate-500">
                          <span>최소 $0.50</span>
                          <span className="font-semibold text-violet-700">
                            권장: $1~$3
                          </span>
                          <span>최대 $10</span>
                        </div>
                      </section>
                      <div className="rounded border border-violet-100 bg-white px-2 py-1.5 text-[11px] text-violet-900">
                        <div className="font-semibold">운영 로그 활용</div>
                        <p className="mt-1">
                          {routingBootstrapPreview
                            ? routingBootstrapPreview.history_mode === 'history'
                              ? `성공 운영 로그 ${routingBootstrapPreview.available_history_count}건으로 생성`
                              : routingBootstrapPreview.history_mode === 'hybrid'
                                ? `운영 로그 ${routingBootstrapPreview.available_history_count}건 + 생성 예시`
                                : '운영 로그가 없어 생성 예시로 시작'
                            : '운영 로그 확인 중'}
                        </p>
                      </div>
                    </div>
                    <button
                      type="button"
                      className="nodrag mt-3 inline-flex items-center gap-1.5 rounded-md bg-violet-600 px-3 py-2 text-xs font-semibold text-white hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60"
                      onClick={handleCreateRoutingBootstrap}
                      disabled={
                        isCreatingRoutingBootstrap ||
                        isRoutingBootstrapGenerating ||
                        !activeWorkflowId
                      }
                    >
                      <Wand2 className="h-3.5 w-3.5" />
                      {isCreatingRoutingBootstrap || isRoutingBootstrapGenerating
                        ? '기준 생성 중...'
                        : routingBootstrap
                          ? '자동 선택 기준 다시 만들기'
                          : '자동 선택 기준 만들기'}
                    </button>
                    {routingBootstrap ? (
                      <div className="mt-3 rounded border border-violet-100 bg-white p-2 text-[11px] text-slate-700">
                        <div className="font-semibold text-violet-900">
                          {routingBootstrap.source === 'history'
                            ? '운영 로그 기반 초기 정책'
                            : routingBootstrap.source === 'hybrid'
                              ? '운영 로그 보강 초기 정책'
                              : '새 예시 기반 초기 정책'}
                        </div>
                      <p className="mt-1">
                        {routingBootstrap.status === 'generating'
                          ? '예문과 난이도 규칙을 생성 중입니다. 완료되면 이 화면이 자동으로 갱신됩니다.'
                          : routingBootstrap.status === 'failed'
                            ? '기준 생성에 실패했습니다. 모델 권한과 작업 설명을 확인한 뒤 다시 시도하세요.'
                            : <>표본 {Number(routingBootstrap.generation_summary.history_sample_count || 0) + Number(routingBootstrap.generation_summary.synthetic_sample_count || 0)}개 · Planner 비용{' '}
                              {routingBootstrap.planner_cost_usd === null || routingBootstrap.planner_cost_usd === undefined
                                ? '기록 대기'
                                : `$${routingBootstrap.planner_cost_usd.toFixed(6)}`}</>}
                      </p>
                      </div>
                    ) : null}
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
                        운영 반영 방식
                      </dt>
                      <dd className="mt-1 font-semibold text-slate-900">
                        실행 완료마다 성적 누적
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
                          'deployment_bootstrap'
                            ? '배포 정책 생성'
                            : routingPolicySummary.lastUpdate.trigger ===
                                'score_change'
                              ? '운영 성적 변화'
                              : '직접 재평가'}{' '}
                          ·{' '}
                          {routingPolicySummary.lastUpdate.status === 'applied'
                            ? '반영됨'
                            : routingPolicySummary.lastUpdate.status}
                        </span>
                      </div>
                      <p className="mt-1 text-slate-500">
                        운영 표본 {routingPolicySummary.lastUpdate.eligible_run_count}회
                        · 제외 {routingPolicySummary.lastUpdate.excluded_run_count}회
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
                      배포할 때 첫 실행용 정책을 즉시 생성합니다. 아직 배포된 정책이
                      없어 현재 초안에서는 기본 모델을 사용합니다.
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
                    정책 다시 평가
                  </button>
                  <div
                    data-testid="routing-refresh-controls"
                    className="order-2 mt-3 rounded-lg border border-emerald-100 bg-emerald-50/60 p-3"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-xs font-semibold text-emerald-900">
                          운영 성적 자동 반영
                        </div>
                        <p className="mt-0.5 text-[11px] leading-relaxed text-emerald-700">
                          배포 실행이 끝날 때마다 모델별 품질·비용·지연 성적을
                          누적합니다. 테스트 실행은 포함하지 않습니다.
                        </p>
                      </div>
                      <span className="shrink-0 rounded bg-white px-2 py-1 text-xs font-mono font-semibold text-emerald-800 ring-1 ring-emerald-200">
                        {routingPolicySummary.performance.total_runs}회
                      </span>
                    </div>
                    <div className="mt-3 space-y-2">
                      {routingPolicySummary.performance.models.length === 0 ? (
                        <div className="rounded border border-dashed border-emerald-200 bg-white px-3 py-2 text-[11px] text-emerald-800">
                          아직 배포 운영 성적이 없습니다.
                        </div>
                      ) : (
                        routingPolicySummary.performance.models.map((model) => (
                          <div
                            key={`${model.model_id}:${model.input_profile}`}
                            className="rounded border border-emerald-100 bg-white px-3 py-2 text-[11px]"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="truncate font-semibold text-slate-800">
                                {model.model_id} ·{' '}
                                {routingProfileLabel(model.input_profile)}
                              </span>
                              <span className="shrink-0 text-slate-500">
                                {model.run_count}회
                              </span>
                            </div>
                            <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-slate-500">
                              <span>품질 {(model.quality_score * 100).toFixed(1)}%</span>
                              <span>
                                평균 비용{' '}
                                {model.avg_cost === null
                                  ? '-'
                                  : `$${model.avg_cost.toFixed(6)}`}
                              </span>
                              <span>
                                평균 지연{' '}
                                {model.avg_latency_ms === null
                                  ? '-'
                                  : `${Math.round(model.avg_latency_ms)}ms`}
                              </span>
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                    <div className="mt-3 rounded border border-emerald-200 bg-white px-3 py-2 text-[11px] text-emerald-900">
                      <div className="font-semibold">정책 교체 보호 기준</div>
                      <p className="mt-1 leading-relaxed text-emerald-700">
                        새 운영 표본 {routingPolicySummary.changePolicy.minimum_new_runs}회
                        이상 · 품질 하락 방지 · 비용·지연{' '}
                        {Math.round(
                          routingPolicySummary.changePolicy
                            .efficiency_improvement_threshold * 100,
                        )}
                        % 이상 개선일 때만 정책을 교체합니다.
                      </p>
                    </div>
                  </div>
                  {isBootstrapRouting ? (
                    <div
                      data-testid="routing-bootstrap-policy"
                      className="order-1 mt-3 rounded-lg border border-violet-200 bg-violet-50/40 p-3"
                    >
                      <div className="text-xs font-semibold text-violet-950">
                        난이도별 초기 선택 모델
                      </div>
                      <p className="mt-1 text-[11px] leading-relaxed text-violet-800">
                        실행 중에는 평가용 LLM을 호출하지 않습니다. 분류 신뢰도가 낮으면
                        위 기본 모델을 사용합니다.
                      </p>
                      {Object.keys(bootstrapDifficultyModels).length === 0 ? (
                        <div className="mt-3 rounded border border-dashed border-violet-200 bg-white px-3 py-2 text-[11px] text-violet-800">
                          기준 생성 또는 배포 후 정책이 준비되면 난이도별 모델을 표시합니다.
                        </div>
                      ) : (
                        <dl className="mt-3 space-y-2">
                          {(['economy', 'balanced', 'advanced'] as const).map((tier) => {
                            const modelId = bootstrapDifficultyModels[tier];
                            if (!modelId) return null;
                            const label =
                              tier === 'economy'
                                ? '경제형 요청'
                                : tier === 'balanced'
                                  ? '균형형 요청'
                                  : '고성능 요청';
                            return (
                              <div
                                key={tier}
                                className="flex items-center justify-between rounded border border-violet-100 bg-white px-2.5 py-2 text-[11px]"
                              >
                                <dt className="font-semibold text-slate-700">{label}</dt>
                                <dd className="font-semibold text-slate-950">{modelId}</dd>
                              </div>
                            );
                          })}
                        </dl>
                      )}
                    </div>
                  ) : (
                    <div
                      data-testid="routing-prior-guided-policy"
                      className="order-1 mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3"
                    >
                      <div className="text-xs font-semibold text-slate-900">
                        사전 지식 기반 라우팅 정책
                      </div>
                      <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
                        모델 기능, 가격, 입력 길이, 출력 형식, 지식 베이스 사용 여부와
                        운영 통계를 기준으로 실행 모델을 선택합니다.
                      </p>
                      {priorGuidedProfiles.length === 0 ? (
                        <div className="mt-3 rounded border border-dashed border-slate-200 bg-white px-3 py-2 text-[11px] text-slate-500">
                          정책 계산 대기 중입니다. 정책이 준비되기 전에는 기본 모델을
                          사용합니다.
                        </div>
                      ) : (
                        <dl className="mt-3 space-y-2">
                          {priorGuidedProfiles.map((profile) => (
                            <div
                              key={profile.profile}
                              className="rounded border border-slate-200 bg-white px-2.5 py-2 text-[11px]"
                            >
                              <div className="flex items-center justify-between gap-3">
                                <dt className="font-semibold text-slate-700">
                                  {routingProfileLabel(profile.profile)}
                                </dt>
                                <dd className="font-semibold text-slate-950">
                                  {profile.selected_model_id}
                                </dd>
                              </div>
                              <p className="mt-1 leading-relaxed text-slate-500">
                                {routingProfileReasonLabel(profile.reason_code)}
                              </p>
                              {profile.fallback_model_id ? (
                                <p className="mt-1 text-slate-500">
                                  대체 모델: {profile.fallback_model_id}
                                </p>
                              ) : null}
                            </div>
                          ))}
                        </dl>
                      )}
                    </div>
                  )}
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

        </div>
        </>
      )}

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
