import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { LLMNodeData } from '../../../../types/Nodes';
import { getUpstreamNodes } from '../../../../utils/getUpstreamNodes';
import { UnregisteredVariablesAlert } from '../../../ui/UnregisteredVariablesAlert';
import { ValidationAlert } from '../../../ui/ValidationAlert';
import { useWorkflowStore } from '@/app/features/workflow/store/useWorkflowStore';
import { CollapsibleSection } from '../../ui/CollapsibleSection';
import {
  HelpCircle,
  BookOpen,
  MousePointerClick,
  Wand2,
  SlidersHorizontal,
} from 'lucide-react';
import { PromptWizardModal } from '../../../modals/PromptWizardModal';
import { ModelSelectDropdown } from './ModelSelectDropdown';
import { LLMParameterSidePanel } from './LLMParameterSidePanel';
import {
  fetchEligibleKnowledgeBases,
  sanitizeSelectedKnowledgeBases,
  isSameKnowledgeSelection,
} from '@/app/features/workflow/utils/llmKnowledgeBaseSelection';
import { resolveWorkflowWizardOrganizationId } from '@/app/features/workflow/utils/resolveWorkflowWizardOrganizationId';
import {
  DraggedOutputVariable,
  getDroppedOutputReferenceName,
  getTokenLabelMap,
  upsertNamedSelector,
} from '@/app/features/workflow/utils/nodeVariablePorts';
import { VariableTokenEditor } from '../../ui/VariableTokenEditor';
import { PropertyVisibilityToggle } from '../../ui/PropertyVisibilityToggle';
import { CostOptimizerEntryAction } from '../../../costOptimizer/CostOptimizerEntryAction';

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
  isAdvancedSettingsOpen?: boolean;
  onOpenAdvancedSettings?: () => void;
  onOpenKnowledgeBaseSettings?: () => void;
}

type PromptHelpId = 'fallback' | 'system' | 'user' | 'assistant';

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

const isChatModelOption = (model: ModelOption) => {
  const id = model.model_id_for_api_call.toLowerCase();
  const name = model.name.toLowerCase();

  // provider_name이 있으면 사용, 없으면 model_id로 추론
  let provider = (model.provider_name || '').toLowerCase();
  if (!provider) {
    if (
      id.startsWith('gpt-') ||
      id.startsWith('o1') ||
      id.startsWith('o3') ||
      id.startsWith('o4') ||
      id.startsWith('chatgpt')
    ) {
      provider = 'openai';
    } else if (
      id.startsWith('gemini') ||
      id.startsWith('gemma') ||
      id.startsWith('models/gemini')
    ) {
      provider = 'google';
    } else if (id.startsWith('claude')) {
      provider = 'anthropic';
    } else if (id.startsWith('grok')) {
      provider = 'xai';
    } else if (id.startsWith('deepseek')) {
      provider = 'deepseek';
    }
  }

  // Embedding 모델 제외
  if (id.includes('embedding') || model.type === 'embedding') return false;
  if (name.includes('embedding') || name.includes('임베딩')) return false;

  // ========== OpenAI 화이트리스트 (16개) - 정확히 일치만 허용 ==========
  if (
    provider.includes('openai') ||
    id.startsWith('gpt-') ||
    id.startsWith('o1') ||
    id.startsWith('o3') ||
    id.startsWith('o4') ||
    id.startsWith('chatgpt')
  ) {
    const allowedOpenAI = new Set([
      'gpt-5.2', // 범용 플래그십
      'gpt-5.1', // 코딩/명령 이행 강화
      'gpt-5', // GPT-5 시리즈 시작
      'o3-pro', // 초고도 추론
      'o3', // 논리 특화
      'o1', // 추론 전용
      'gpt-4.1', // 100만 토큰 컨텍스트
      'gpt-4o', // 멀티모달 표준
      'gpt-4-turbo-preview', // 최적화된 GPT-4
      'chatgpt-4o-latest', // 동적 업데이트
      'gpt-5-mini', // 효율 모델
      'gpt-5-nano', // 초경량
      'gpt-4.1-mini', // 경량 GPT-4급
      'gpt-4o-mini', // 저렴한 멀티모달
      'o3-mini', // 실시간 추론
      'o4-mini', // 차세대 에이전트용
    ]);
    const cleanId = id.replace('models/', '');
    const isAllowed = allowedOpenAI.has(cleanId);
    if (!isAllowed) return false;
  }

  // ========== Anthropic 화이트리스트 (10개) - 정확히 일치만 허용 ==========
  if (provider.includes('anthropic') || id.startsWith('claude')) {
    const allowedAnthropic = new Set([
      'claude-opus-4-5-20251101', // 최신 최상위
      'claude-sonnet-4-5-20250929', // 에이전트/컴퓨터 제어
      'claude-haiku-4-5-20251001', // 최신 경량
      'claude-3-5-sonnet-latest', // 안정된 3.5
      'claude-3-5-opus-latest', // 깊은 분석
      'claude-3-5-haiku-latest', // 3.5 경량
      'claude-opus-4-1-20250805', // 고성능 안정화
      'claude-sonnet-4-20250514', // 2025 상반기 주력
      'claude-3-5-sonnet-20241022', // 선호도 높은 구버전
      'claude-3-opus-20240229', // 레거시 플래그십
    ]);
    const cleanId = id.replace('models/', '');
    const isAllowed = allowedAnthropic.has(cleanId);
    if (!isAllowed) return false;
  }

  // ========== Google 화이트리스트 (8개) - 정확히 일치만 허용 ==========
  if (
    provider.includes('google') ||
    id.includes('gemini') ||
    id.includes('gemma')
  ) {
    const allowedGoogle = new Set([
      'gemini-3-pro', // 2026 주력
      'gemini-3-flash', // 초고속
      'gemini-2.5-pro', // 대형 컨텍스트
      'gemini-2.5-flash', // 범용 속도형
      'gemini-2.0-flash', // 안정된 표준
      'gemini-2.0-flash-lite', // 초경량
      'gemini-robotics-er-1.5-preview', // 로보틱스 특화
      'gemma-3-27b-it', // 오픈 가중치
    ]);
    const cleanId = id.replace('models/', '');
    const isAllowed = allowedGoogle.has(cleanId);
    if (!isAllowed) return false;
  }

  return true;
};

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
  isAdvancedSettingsOpen,
  onOpenAdvancedSettings,
  onOpenKnowledgeBaseSettings,
}: LLMNodePanelProps) {
  const openSettingsTab = useCallback(() => {
    window.open('/dashboard/settings', '_blank', 'noopener,noreferrer');
  }, []);
  const { updateNodeData, nodes, edges, activeWorkflowId, workflowAccess } =
    useWorkflowStore();
  const wizardOrganizationId = resolveWorkflowWizardOrganizationId(
    workflowAccess,
    activeWorkflowId,
  );
  const pendingPromptReferencesRef = useRef<
    LLMNodeData['referenced_variables']
  >([]);

  const [activeHelp, setActiveHelp] = useState<PromptHelpId | null>(null);
  const [isParameterPanelOpen, setIsParameterPanelOpen] = useState(false);
  const isUsingExternalAdvancedPanel =
    typeof onOpenAdvancedSettings === 'function';
  const isAdvancedButtonActive = isUsingExternalAdvancedPanel
    ? Boolean(isAdvancedSettingsOpen)
    : isParameterPanelOpen;

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
    () => modelOptions.filter(isChatModelOption),
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
  const upstreamNodes = useMemo(
    () => getUpstreamNodes(nodeId, nodes, edges),
    [nodeId, nodes, edges],
  );
  const tokenLabels = useMemo(
    () => getTokenLabelMap(data.referenced_variables, upstreamNodes),
    [data.referenced_variables, upstreamNodes],
  );

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
    if (!data.knowledgeBases || data.knowledgeBases.length === 0) return;
    let active = true;
    const syncKnowledgeBases = async () => {
      try {
        const { bases } = await fetchEligibleKnowledgeBases();
        if (!active) return;
        const nextSelected = sanitizeSelectedKnowledgeBases(
          data.knowledgeBases || [],
          bases,
        );
        if (
          !isSameKnowledgeSelection(nextSelected, data.knowledgeBases || [])
        ) {
          updateNodeData(nodeId, { knowledgeBases: nextSelected });
        }
      } catch {
        // 지식 베이스 동기화 실패는 노드 편집 자체를 막지 않습니다.
      }
    };

    syncKnowledgeBases();
    return () => {
      active = false;
    };
  }, [data.knowledgeBases, nodeId, updateNodeData]);

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
      {!isUsingExternalAdvancedPanel && isParameterPanelOpen && (
        <div className="absolute right-[calc(100%+56px)] top-0 z-50">
          <LLMParameterSidePanel
            nodeId={nodeId}
            data={data}
            onClose={() => setIsParameterPanelOpen(false)}
          />
        </div>
      )}

      <div className="flex justify-end gap-2">
        <CostOptimizerEntryAction
          workflowId={activeWorkflowId}
          nodeId={nodeId}
          workflowAccess={workflowAccess}
        />
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            if (onOpenAdvancedSettings) {
              onOpenAdvancedSettings();
              return;
            }
            setIsParameterPanelOpen((current) => !current);
          }}
          className={`nodrag inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-semibold transition-colors ${
            isAdvancedButtonActive
              ? 'border-blue-200 bg-blue-50 text-blue-700'
              : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300 hover:bg-gray-50'
          }`}
          aria-expanded={isAdvancedButtonActive}
          aria-label="LLM 고급 설정 열기"
        >
          <SlidersHorizontal className="h-3.5 w-3.5" />
          고급 설정
        </button>
      </div>

      {/* 1. 모델 선택 */}
      <CollapsibleSection title="모델" showDivider>
        <div className="flex flex-col gap-2">
          <div className="flex items-center">
            <label className="text-xs font-semibold text-gray-700">
              기본 모델
            </label>
            <PropertyVisibilityToggle nodeId={nodeId} propertyKey="model_id" />
          </div>
          {loadingModels ? (
            <div className="text-xs text-gray-400">모델 로딩 중...</div>
          ) : modelOptions.length > 0 ? (
            <>
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
                  다른 Provider를 추가하려면 아래에서 API Key를 등록하세요.
                </p>
              </div>
              {/* Provider 설정 링크 */}
              <button
                onClick={openSettingsTab}
                className="mt-2 text-xs text-blue-600 hover:text-blue-800 hover:underline text-left"
              >
                Provider API Key 등록하기
              </button>
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

      {/* 2.5 지식 베이스 버튼 (지식 베이스 그룹 통합) */}
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
            (data.knowledgeBases?.length ?? 0) > 0
              ? 'border-indigo-400 bg-indigo-50/80 text-indigo-800 shadow-sm hover:shadow-md hover:bg-indigo-50 hover:border-indigo-500'
              : 'border-gray-300 bg-gray-50/50 text-gray-600 hover:border-indigo-400 hover:bg-indigo-50/30 hover:text-indigo-700 hover:shadow-sm'
          }`}
        >
          {/* 호버 시 배경 일러스트 효과 */}
          <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/40 to-transparent translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-1000 pointer-events-none" />

          {/* 왼쪽 아이콘 (책) */}
          <div
            className={`p-2 rounded-lg transition-colors duration-300 ${
              (data.knowledgeBases?.length ?? 0) > 0
                ? 'bg-indigo-200 text-indigo-700'
                : 'bg-gray-200 text-gray-500 group-hover:bg-indigo-100 group-hover:text-indigo-600'
            }`}
          >
            <BookOpen className="w-5 h-5" />
          </div>

          {/* 텍스트 내용 */}
          <div className="flex flex-col items-start flex-1 gap-0.5">
            <span className="font-bold text-sm tracking-tight">
              지식 베이스 설정
            </span>
            <span
              className={`text-xs transition-colors duration-300 ${
                (data.knowledgeBases?.length ?? 0) > 0
                  ? 'text-indigo-600 font-medium'
                  : 'text-gray-400 group-hover:text-indigo-500'
              }`}
            >
              {(data.knowledgeBases?.length ?? 0) > 0
                ? `${data.knowledgeBases!.length}개 그룹 연결됨`
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
