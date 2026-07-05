'use client';

import { useEffect, useMemo, useState } from 'react';
import { FileJson, Wand2 } from 'lucide-react';

import { PromptWizardModal } from '@/app/features/workflow/components/modals/PromptWizardModal';
import { LLMParameterSidePanel } from '@/app/features/workflow/components/nodes/llm/components/LLMParameterSidePanel';
import { LLMReferenceSidePanel } from '@/app/features/workflow/components/nodes/llm/components/LLMReferenceSidePanel';
import { ModelSelectDropdown } from '@/app/features/workflow/components/nodes/llm/components/ModelSelectDropdown';
import { VariableTokenEditor } from '@/app/features/workflow/components/nodes/ui/VariableTokenEditor';
import type { LLMNodeData } from '@/app/features/workflow/types/Nodes';
import type { DraggedOutputVariable } from '@/app/features/workflow/utils/nodeVariablePorts';
import {
  getDroppedOutputReferenceName,
  upsertNamedSelector,
} from '@/app/features/workflow/utils/nodeVariablePorts';
import { LLM_TASK_TYPES } from '@/app/features/workflow/utils/llmTaskTypes';
import {
  llmDataFromCandidate,
  type CandidateDraft,
  type JsonSchemaField,
  type JsonSchemaFieldType,
  type SettingsTab,
} from './costOptimizerPlaygroundModel';

const schemaFieldTypes: Array<{ value: JsonSchemaFieldType; label: string }> = [
  { value: 'string', label: 'string' },
  { value: 'number', label: 'number' },
  { value: 'boolean', label: 'boolean' },
  { value: 'object', label: 'object' },
  { value: 'array', label: 'array' },
];

type CandidateChangeHandler = <K extends keyof CandidateDraft>(
  key: K,
  value: CandidateDraft[K],
) => void;

type PromptField = 'system' | 'user' | 'assistant';

type ModelOption = {
  id: string;
  model_id_for_api_call: string;
  name: string;
  type: string;
  provider_name?: string;
  is_active: boolean;
};

const promptFieldToDraftKey = {
  system: 'system_prompt',
  user: 'user_prompt',
  assistant: 'assistant_prompt',
} as const satisfies Record<PromptField, keyof CandidateDraft>;

const SettingsTabSwitch = ({
  value,
  onChange,
}: {
  value: SettingsTab;
  onChange: (tab: SettingsTab) => void;
}) => (
  <div className="flex min-h-11 items-end gap-0 overflow-x-auto border-b border-slate-200 bg-slate-100 px-2 pt-2">
    {(
      [
        ['basic', '기본 설정'],
        ['advanced', '고급 설정'],
        ['knowledge', '지식 베이스'],
      ] as const
    ).map(([tab, label]) => (
      <button
        key={tab}
        type="button"
        onClick={() => onChange(tab)}
        className={`flex h-9 min-w-0 max-w-36 items-center rounded-t-md border border-b-0 px-3 text-left text-xs font-semibold transition-colors ${
          value === tab
            ? 'border-slate-200 bg-white text-slate-950'
            : 'border-transparent text-slate-500 hover:bg-slate-50 hover:text-slate-800'
        }`}
      >
        {label}
      </button>
    ))}
  </div>
);

const noopCandidateChange: CandidateChangeHandler = (key, value) => {
  void key;
  void value;
};

const isChatModelOption = (model: ModelOption) => {
  const id = model.model_id_for_api_call.toLowerCase();
  const name = model.name.toLowerCase();

  if (model.is_active === false) return false;
  if (model.type === 'embedding') return false;
  if (id.includes('embedding')) return false;
  if (name.includes('embedding') || name.includes('임베딩')) return false;

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

export function NodeSettingsComparisonPanel({
  title,
  hideTitle = false,
  nodeId,
  tab,
  onTabChange,
  draft,
  readOnly = false,
  onChange = noopCandidateChange,
  onNodeDataChange,
}: {
  title: string;
  hideTitle?: boolean;
  nodeId: string;
  tab: SettingsTab;
  onTabChange: (tab: SettingsTab) => void;
  draft: CandidateDraft;
  readOnly?: boolean;
  onChange?: CandidateChangeHandler;
  onNodeDataChange?: (updates: Partial<LLMNodeData>) => void;
}) {
  const [wizardField, setWizardField] = useState<PromptField>('system');
  const [isWizardOpen, setIsWizardOpen] = useState(false);
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);

  useEffect(() => {
    if (readOnly) return;

    const fetchMyModels = async () => {
      try {
        setLoadingModels(true);
        const response = await fetch('/api/v1/llm/my-models', {
          method: 'GET',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
        });

        if (response.ok) {
          setModelOptions(await response.json());
        } else {
          setModelOptions([]);
        }
      } catch {
        setModelOptions([]);
      } finally {
        setLoadingModels(false);
      }
    };

    fetchMyModels();
  }, [readOnly]);

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
        (model) => model.model_id_for_api_call === draft.model_id,
      ),
    [modelOptions, draft.model_id],
  );
  const fallbackCandidates = useMemo(
    () =>
      chatModelOptions.filter(
        (model) => model.model_id_for_api_call !== draft.model_id,
      ),
    [chatModelOptions, draft.model_id],
  );
  const groupedFallbackOptions = useMemo(() => {
    const groups = groupModelsByProvider(fallbackCandidates);
    if (!draft.model_id) return groups;

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
  }, [fallbackCandidates, draft.model_id, selectedModel]);
  const fallbackDisabled = !draft.model_id?.trim();

  const openWizard = (field: PromptField) => {
    if (readOnly) return;
    setWizardField(field);
    setIsWizardOpen(true);
  };

  const applyWizardPrompt = (improvedPrompt: string) => {
    onChange(promptFieldToDraftKey[wizardField], improvedPrompt);
  };
  const handlePromptDropOutput = (output: DraggedOutputVariable) => {
    const referenceName = getDroppedOutputReferenceName(
      draft.referenced_variables,
      output,
      'value_selector',
    );
    onChange(
      'referenced_variables',
      upsertNamedSelector(
        draft.referenced_variables,
        output,
        'value_selector',
      ) as CandidateDraft['referenced_variables'],
    );
    return referenceName;
  };

  const renderPromptField = ({
    field,
    label,
    value,
    minHeightClassName,
    placeholder,
  }: {
    field: PromptField;
    label: string;
    value: string;
    minHeightClassName: string;
    placeholder: string;
  }) => (
    <label className="grid gap-1 text-xs font-semibold text-slate-600">
      <span className="flex items-center justify-between gap-2">
        <span>{label}</span>
        {!readOnly ? (
          <span className="group/wizard relative">
            <button
              type="button"
              onClick={() => openWizard(field)}
              className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-blue-500 transition-colors hover:bg-blue-50 hover:text-blue-700"
            >
              <Wand2 className="h-3 w-3" />
              <span>프롬프트 마법사</span>
            </button>
            <span className="absolute right-0 top-7 z-50 hidden w-32 rounded-lg border border-gray-200 bg-white p-2 text-[11px] font-normal text-gray-600 shadow-lg group-hover/wizard:block">
              AI가 프롬프트를 개선해드려요
              <span className="absolute -top-1 right-2 h-2 w-2 rotate-45 border-l border-t border-gray-200 bg-white" />
            </span>
          </span>
        ) : null}
      </span>
      {readOnly ? (
        <textarea
          value={value}
          readOnly
          placeholder={placeholder}
          className={`${minHeightClassName} rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none`}
        />
      ) : (
        <VariableTokenEditor
          value={value}
          onChange={(nextValue) =>
            onChange(promptFieldToDraftKey[field], nextValue)
          }
          onDropOutput={handlePromptDropOutput}
          placeholder={placeholder}
          ariaLabel={label}
          className={minHeightClassName}
        />
      )}
    </label>
  );

  const wizardPromptKey = promptFieldToDraftKey[wizardField];
  const handleModelChange = (modelId: string) => {
    onChange('model_id', modelId);
    if (draft.fallback_model_id === modelId) {
      onChange('fallback_model_id', '');
    }
  };
  const updateSchemaFields = (fields: JsonSchemaField[]) => {
    onChange('json_schema_fields', fields);
  };
  const addSchemaField = () => {
    updateSchemaFields([
      ...draft.json_schema_fields,
      { key: '', type: 'string', required: false },
    ]);
  };
  const updateSchemaField = (
    index: number,
    updates: Partial<JsonSchemaField>,
  ) => {
    updateSchemaFields(
      draft.json_schema_fields.map((field, fieldIndex) =>
        fieldIndex === index ? { ...field, ...updates } : field,
      ),
    );
  };
  const removeSchemaField = (index: number) => {
    updateSchemaFields(
      draft.json_schema_fields.filter((_, fieldIndex) => fieldIndex !== index),
    );
  };

  return (
    <>
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        {!hideTitle ? (
          <div className="px-3 pt-3">
            <div className="mb-2 text-xs font-bold text-slate-700">
              {title}
            </div>
          </div>
        ) : null}
        <SettingsTabSwitch value={tab} onChange={onTabChange} />
        <div className="grid gap-5 p-5">
          {tab === 'basic' ? (
            <>
              <div className="grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-3">
                <label className="grid min-w-0 gap-1 text-xs font-semibold text-slate-600">
                  <span>기본 모델</span>
                  {readOnly ? (
                    <input
                      value={draft.model_id}
                      readOnly
                      className="min-w-0 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none"
                      placeholder="모델 없음"
                    />
                  ) : loadingModels ? (
                    <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-400">
                      모델 로딩 중...
                    </div>
                  ) : (
                    <ModelSelectDropdown
                      value={draft.model_id || ''}
                      onChange={handleModelChange}
                      models={chatModelOptions}
                      groupedModels={groupedModelOptions}
                      placeholder="모델을 선택하세요"
                    />
                  )}
                </label>
                <label className="grid min-w-0 gap-1 text-xs font-semibold text-slate-600">
                  <span>대체 모델</span>
                  {readOnly ? (
                    <input
                      value={draft.fallback_model_id}
                      readOnly
                      className="min-w-0 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none"
                      placeholder="선택 없음"
                    />
                  ) : loadingModels ? (
                    <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-400">
                      모델 로딩 중...
                    </div>
                  ) : (
                    <ModelSelectDropdown
                      value={draft.fallback_model_id || ''}
                      onChange={(value) => onChange('fallback_model_id', value)}
                      models={fallbackCandidates}
                      groupedModels={groupedFallbackOptions}
                      disabled={fallbackDisabled}
                      placeholder={
                        fallbackDisabled
                          ? '먼저 모델을 선택하세요'
                          : '대체 모델을 선택하세요'
                      }
                    />
                  )}
                </label>
                <label className="grid min-w-0 gap-1 text-xs font-semibold text-slate-600">
                  <span>Task type</span>
                  <select
                    value={draft.task_type}
                    onChange={(event) =>
                      onChange('task_type', event.target.value)
                    }
                    disabled={readOnly}
                    className="min-w-0 rounded-md border border-slate-200 px-3 py-2 text-sm outline-none focus:border-emerald-400 disabled:bg-slate-50"
                  >
                    {LLM_TASK_TYPES.map((taskType) => (
                      <option key={taskType.value} value={taskType.value}>
                        {taskType.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                <div className="mb-3 flex items-center gap-2 text-sm font-bold">
                  <FileJson className="h-4 w-4 text-slate-600" />
                  출력 형식
                </div>
                <div className="inline-flex rounded-md border border-slate-200 bg-white p-1">
                  {(['text', 'json'] as const).map((format) => (
                    <button
                      key={format}
                      type="button"
                      onClick={() => {
                        if (!readOnly) onChange('output_format', format);
                      }}
                      disabled={readOnly}
                      className={`rounded px-3 py-1.5 text-xs font-bold disabled:cursor-default ${
                        draft.output_format === format
                          ? 'bg-emerald-600 text-white'
                          : 'text-slate-600 hover:bg-slate-50'
                      }`}
                    >
                      {format.toUpperCase()}
                    </button>
                  ))}
                </div>
                {draft.output_format === 'json' ? (
                  <div className="mt-3 grid gap-3 rounded-md border border-dashed border-slate-300 bg-white p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-xs font-bold text-slate-700">
                          JSON schema
                        </div>
                        <div className="text-[11px] text-slate-500">
                          flat key-type 행으로 출력 계약을 정의합니다.
                        </div>
                      </div>
                      {!readOnly ? (
                        <button
                          type="button"
                          onClick={addSchemaField}
                          className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-bold text-slate-700 hover:bg-slate-50"
                        >
                          스키마 필드 추가
                        </button>
                      ) : null}
                    </div>
                    {draft.json_schema_fields.length === 0 ? (
                      <div className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500">
                        정의된 필드가 없습니다.
                      </div>
                    ) : (
                      <div className="grid gap-2">
                        {draft.json_schema_fields.map((field, index) => (
                          <div
                            key={`${field.key}-${index}`}
                            className="grid grid-cols-[minmax(120px,1fr)_minmax(110px,140px)_auto_auto] items-center gap-2 rounded-md border border-slate-200 bg-white p-2"
                          >
                            <label className="grid gap-1 text-[11px] font-semibold text-slate-500">
                              <span>필드명</span>
                              <input
                                value={field.key}
                                onChange={(event) =>
                                  updateSchemaField(index, {
                                    key: event.target.value,
                                  })
                                }
                                readOnly={readOnly}
                                className="min-w-0 rounded-md border border-slate-200 px-2 py-1.5 text-xs text-slate-800 outline-none focus:border-emerald-400 read-only:bg-slate-50"
                                placeholder="예: summary"
                              />
                            </label>
                            <label className="grid gap-1 text-[11px] font-semibold text-slate-500">
                              <span>타입</span>
                              <select
                                value={field.type}
                                onChange={(event) =>
                                  updateSchemaField(index, {
                                    type: event.target.value as JsonSchemaFieldType,
                                  })
                                }
                                disabled={readOnly}
                                className="min-w-0 rounded-md border border-slate-200 px-2 py-1.5 text-xs text-slate-800 outline-none focus:border-emerald-400 disabled:bg-slate-50"
                              >
                                {schemaFieldTypes.map((fieldType) => (
                                  <option
                                    key={fieldType.value}
                                    value={fieldType.value}
                                  >
                                    {fieldType.label}
                                  </option>
                                ))}
                              </select>
                            </label>
                            <label className="flex items-center gap-1 pt-5 text-xs font-semibold text-slate-600">
                              <input
                                type="checkbox"
                                checked={field.required}
                                onChange={(event) =>
                                  updateSchemaField(index, {
                                    required: event.target.checked,
                                  })
                                }
                                disabled={readOnly}
                              />
                              필수
                            </label>
                            {!readOnly ? (
                              <button
                                type="button"
                                onClick={() => removeSchemaField(index)}
                                className="mt-5 rounded-md px-2 py-1 text-xs font-bold text-red-500 hover:bg-red-50"
                              >
                                삭제
                              </button>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ) : null}
              </div>

              <div className="grid gap-3">
                {renderPromptField({
                  field: 'system',
                  label: '시스템 프롬프트',
                  value: draft.system_prompt,
                  minHeightClassName: 'min-h-24',
                  placeholder:
                    '예: 너는 친절하고 전문적인 고객 상담 AI입니다.',
                })}
                {renderPromptField({
                  field: 'user',
                  label: '사용자 프롬프트',
                  value: draft.user_prompt,
                  minHeightClassName: 'min-h-32',
                  placeholder:
                    '예: 다음 내용을 한국어로 3줄 요약해줘.',
                })}
                {renderPromptField({
                  field: 'assistant',
                  label: '어시스턴트 프롬프트',
                  value: draft.assistant_prompt,
                  minHeightClassName: 'min-h-24',
                  placeholder: '예: 분석 결과를 다음과 같이 정리하겠습니다:',
                })}
              </div>
            </>
          ) : tab === 'advanced' ? (
            <div className="h-[620px] overflow-hidden rounded-lg border border-slate-200">
              <LLMParameterSidePanel
                nodeId={nodeId}
                data={llmDataFromCandidate(draft, title)}
                onClose={() => undefined}
                embedded
                readOnly={readOnly}
                onDataChange={onNodeDataChange}
              />
            </div>
          ) : (
            <div className="h-[620px] overflow-hidden rounded-lg border border-slate-200">
              <LLMReferenceSidePanel
                nodeId={nodeId}
                data={llmDataFromCandidate(draft, title)}
                onClose={() => undefined}
                embedded
                readOnly={readOnly}
                onDataChange={onNodeDataChange}
              />
            </div>
          )}
        </div>
      </div>

      {!readOnly ? (
        <PromptWizardModal
          isOpen={isWizardOpen}
          onClose={() => setIsWizardOpen(false)}
          promptType={wizardField}
          originalPrompt={String(draft[wizardPromptKey] || '')}
          onApply={applyWizardPrompt}
        />
      ) : null}
    </>
  );
}
