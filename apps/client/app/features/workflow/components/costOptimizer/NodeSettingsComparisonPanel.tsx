'use client';

import { useState } from 'react';
import { FileJson, Wand2 } from 'lucide-react';

import { PromptWizardModal } from '@/app/features/workflow/components/modals/PromptWizardModal';
import { LLMParameterSidePanel } from '@/app/features/workflow/components/nodes/llm/components/LLMParameterSidePanel';
import { LLMReferenceSidePanel } from '@/app/features/workflow/components/nodes/llm/components/LLMReferenceSidePanel';
import type { LLMNodeData } from '@/app/features/workflow/types/Nodes';
import {
  llmDataFromCandidate,
  type CandidateDraft,
  type SettingsTab,
} from './costOptimizerPlaygroundModel';

const taskTypes = [
  { value: 'classify', label: '분류' },
  { value: 'extract', label: '추출' },
  { value: 'summarize', label: '요약' },
  { value: 'generate', label: '생성' },
  { value: 'reason', label: '추론' },
];

type CandidateChangeHandler = <K extends keyof CandidateDraft>(
  key: K,
  value: CandidateDraft[K],
) => void;

type PromptField = 'system' | 'user' | 'assistant';

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

export function NodeSettingsComparisonPanel({
  title,
  nodeId,
  tab,
  onTabChange,
  draft,
  readOnly = false,
  onChange = noopCandidateChange,
  onNodeDataChange,
}: {
  title: string;
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

  const openWizard = (field: PromptField) => {
    if (readOnly) return;
    setWizardField(field);
    setIsWizardOpen(true);
  };

  const applyWizardPrompt = (improvedPrompt: string) => {
    onChange(promptFieldToDraftKey[wizardField], improvedPrompt);
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
      <textarea
        value={value}
        onChange={(event) =>
          onChange(promptFieldToDraftKey[field], event.target.value)
        }
        readOnly={readOnly}
        placeholder={placeholder}
        className={`${minHeightClassName} rounded-md border border-slate-200 px-3 py-2 text-sm outline-none focus:border-emerald-400 read-only:bg-slate-50`}
      />
    </label>
  );

  const wizardPromptKey = promptFieldToDraftKey[wizardField];

  return (
    <>
      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
        <div className="px-3 pt-3">
          <div className="mb-2 text-xs font-bold text-slate-700">{title}</div>
        </div>
        <SettingsTabSwitch value={tab} onChange={onTabChange} />
        <div className="grid gap-5 p-5">
          {tab === 'basic' ? (
            <>
              <div className="grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-3">
                <label className="grid min-w-0 gap-1 text-xs font-semibold text-slate-600">
                  <span>기본 모델</span>
                  <input
                    value={draft.model_id}
                    onChange={(event) =>
                      onChange('model_id', event.target.value)
                    }
                    readOnly={readOnly}
                    className="min-w-0 rounded-md border border-slate-200 px-3 py-2 text-sm outline-none focus:border-emerald-400 read-only:bg-slate-50"
                    placeholder="gpt-4.1-mini"
                  />
                </label>
                <label className="grid min-w-0 gap-1 text-xs font-semibold text-slate-600">
                  <span>대체 모델</span>
                  <input
                    value={draft.fallback_model_id}
                    onChange={(event) =>
                      onChange('fallback_model_id', event.target.value)
                    }
                    readOnly={readOnly}
                    className="min-w-0 rounded-md border border-slate-200 px-3 py-2 text-sm outline-none focus:border-emerald-400 read-only:bg-slate-50"
                    placeholder="선택 없음"
                  />
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
                    {taskTypes.map((taskType) => (
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
                  <div className="mt-3 rounded-md border border-dashed border-slate-300 bg-white p-3 text-xs text-slate-500">
                    JSON schema key-type 편집 UI는 compare API와 함께
                    연결됩니다.
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
