import { useCallback, useMemo } from 'react';
import { ShieldCheck } from 'lucide-react';

import { useWorkflowStore } from '@/app/features/workflow/store/useWorkflowStore';
import {
  GuardrailNodeData,
  GuardrailOperation,
  GuardrailOption,
} from '../../../../types/Nodes';
import { getUpstreamNodes } from '../../../../utils/getUpstreamNodes';
import {
  DraggedOutputVariable,
  getDroppedOutputReferenceName,
  getNodeOutputVariables,
  getTokenLabelMap,
  upsertNamedSelector,
} from '../../../../utils/nodeVariablePorts';
import { ValidationAlert } from '../../../ui/ValidationAlert';
import { RoundedSelect } from '../../../ui/RoundedSelect';
import { CollapsibleSection } from '../../ui/CollapsibleSection';
import { VariableSelectorSlot } from '../../ui/VariableSelectorSlot';
import { VariableTokenEditor } from '../../ui/VariableTokenEditor';

interface GuardrailNodePanelProps {
  nodeId: string;
  data: GuardrailNodeData;
}

const CHECK_GUARDRAILS: GuardrailOption[] = [
  'Keywords',
  'Jailbreak',
  'NSFW',
  'Personal Data (PII)',
  'Secret Keys',
  'Topical Alignment',
  'URLs',
  'Custom',
  'Custom Regex',
];

const SANITIZE_GUARDRAILS: GuardrailOption[] = [
  'PII',
  'Secret Keys',
  'URLs',
  'Custom Regex',
];

const OPERATION_OPTIONS = [
  { label: '위반 검사', value: 'check_text' },
  { label: '텍스트 정제', value: 'sanitize_text' },
];

const parseKeywordList = (value: string) =>
  value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);

export function GuardrailNodePanel({ nodeId, data }: GuardrailNodePanelProps) {
  const { updateNodeData, nodes, edges } = useWorkflowStore();

  const upstreamNodes = useMemo(
    () => getUpstreamNodes(nodeId, nodes, edges),
    [nodeId, nodes, edges],
  );

  const upstreamOutputMap = useMemo(() => {
    const outputMap = new Map<string, DraggedOutputVariable>();
    for (const upstreamNode of upstreamNodes) {
      for (const output of getNodeOutputVariables(upstreamNode)) {
        outputMap.set(`${output.sourceNodeId}:${output.key}`, output);
        if (output.outputId) {
          outputMap.set(`${output.sourceNodeId}:${output.outputId}`, output);
        }
      }
    }
    return outputMap;
  }, [upstreamNodes]);

  const selectedInput = useMemo(() => {
    const selector = data.input_selector || [];
    if (selector.length < 2) return undefined;
    return upstreamOutputMap.get(`${selector[0]}:${selector[1]}`);
  }, [data.input_selector, upstreamOutputMap]);

  const availableGuardrails =
    data.operation === 'sanitize_text' ? SANITIZE_GUARDRAILS : CHECK_GUARDRAILS;
  const selectedGuardrails = data.guardrails || [];
  const keywordText = useMemo(() => {
    const keywords = data.match_keywords || [];
    return keywords.length > 0 ? keywords.join(', ') : data.custom_keywords || '';
  }, [data.custom_keywords, data.match_keywords]);
  const tokenLabels = useMemo(
    () => getTokenLabelMap(data.referenced_variables, upstreamNodes),
    [data.referenced_variables, upstreamNodes],
  );

  const updateData = useCallback(
    (key: keyof GuardrailNodeData, value: unknown) => {
      updateNodeData(nodeId, { [key]: value });
    },
    [nodeId, updateNodeData],
  );

  const handleOperationChange = useCallback(
    (value: string | number) => {
      const operation = value as GuardrailOperation;
      const nextAllowed =
        operation === 'sanitize_text' ? SANITIZE_GUARDRAILS : CHECK_GUARDRAILS;
      const nextGuardrails = selectedGuardrails.filter((guardrail) =>
        nextAllowed.includes(guardrail),
      );

      updateNodeData(nodeId, {
        operation,
        branching_enabled:
          operation === 'sanitize_text' ? false : data.branching_enabled ?? true,
        guardrails:
          nextGuardrails.length > 0
            ? nextGuardrails
            : operation === 'sanitize_text'
              ? ['PII']
              : ['Keywords'],
      });
    },
    [data.branching_enabled, nodeId, selectedGuardrails, updateNodeData],
  );

  const toggleGuardrail = useCallback(
    (guardrail: GuardrailOption) => {
      const nextGuardrails = selectedGuardrails.includes(guardrail)
        ? selectedGuardrails.filter((item) => item !== guardrail)
        : [...selectedGuardrails, guardrail];
      updateData('guardrails', nextGuardrails);
    },
    [selectedGuardrails, updateData],
  );

  const handleTextDropOutput = useCallback(
    (output: DraggedOutputVariable) => {
      const referenceName = getDroppedOutputReferenceName(
        data.referenced_variables,
        output,
        'value_selector',
      );
      updateNodeData(nodeId, {
        referenced_variables: upsertNamedSelector(
          data.referenced_variables,
          output,
          'value_selector',
        ),
      });
      return referenceName;
    },
    [data.referenced_variables, nodeId, updateNodeData],
  );

  const handleInputSelectorChange = useCallback(
    (selector: string[], output: DraggedOutputVariable) => {
      updateNodeData(nodeId, {
        input_selector: selector,
        referenced_variables: upsertNamedSelector(
          data.referenced_variables,
          output,
          'value_selector',
        ),
      });
    },
    [data.referenced_variables, nodeId, updateNodeData],
  );

  const handleBranchingChange = useCallback(
    (checked: boolean) => {
      updateNodeData(nodeId, {
        branching_enabled: checked,
        branch_condition: data.branch_condition || 'keyword_match',
        pass_label: data.pass_label || '통과',
        fail_label: data.fail_label || '실패',
        pass_handle_id: data.pass_handle_id || 'pass',
        fail_handle_id: data.fail_handle_id || 'fail',
        guardrails:
          checked && !selectedGuardrails.includes('Keywords')
            ? [...selectedGuardrails, 'Keywords']
            : selectedGuardrails,
      });
    },
    [
      data.branch_condition,
      data.fail_handle_id,
      data.fail_label,
      data.pass_handle_id,
      data.pass_label,
      nodeId,
      selectedGuardrails,
      updateNodeData,
    ],
  );

  const handleKeywordChange = useCallback(
    (value: string) => {
      const keywords = parseKeywordList(value);
      updateNodeData(nodeId, {
        custom_keywords: value,
        match_keywords: keywords,
        guardrails: selectedGuardrails.includes('Keywords')
          ? selectedGuardrails
          : [...selectedGuardrails, 'Keywords'],
      });
    },
    [nodeId, selectedGuardrails, updateNodeData],
  );

  const inputMissing =
    !data.text_to_check?.trim() &&
    (!data.input_selector || data.input_selector.length < 2);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start gap-2 rounded-md border border-teal-100 bg-teal-50 px-3 py-2 text-xs leading-relaxed text-teal-800">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0" />
        <span>
          이 노드는 선택한 조건으로 텍스트를 검사하거나 정제합니다. 임시 분기를
          켜면 키워드 일치 여부에 따라 통과/실패 경로로 나눌 수 있습니다.
        </span>
      </div>

      <div className="flex flex-col gap-2">
        <label className="text-xs font-medium text-gray-700">작업</label>
        <RoundedSelect
          value={data.operation || 'check_text'}
          onChange={handleOperationChange}
          options={OPERATION_OPTIONS}
        />
      </div>

      <CollapsibleSection title="입력" showDivider>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-700">
              텍스트 소스
            </label>
            <VariableSelectorSlot
              label="텍스트 소스"
              value={data.input_selector}
              selectedOutput={selectedInput}
              placeholder="이전 노드의 출력을 선택하세요"
              onChange={handleInputSelectorChange}
            />
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-700">
              검사할 텍스트
            </label>
            <VariableTokenEditor
              className="min-h-20 text-sm"
              placeholder="텍스트를 입력하거나 이전 노드 변수를 삽입하세요"
              value={data.text_to_check || ''}
              onChange={(value) => updateData('text_to_check', value)}
              onDropOutput={handleTextDropOutput}
              tokenLabels={tokenLabels}
              ariaLabel="가드레일 검사 텍스트"
            />
          </div>

          {inputMissing && (
            <ValidationAlert message="텍스트 소스 또는 직접 입력값이 필요합니다." />
          )}
        </div>
      </CollapsibleSection>

      {data.operation !== 'sanitize_text' && (
        <CollapsibleSection title="시스템 메시지" showDivider>
          <textarea
            value={data.system_message || ''}
            onChange={(event) =>
              updateData('system_message', event.target.value)
            }
            placeholder="위반 검사에 사용할 시스템 메시지를 입력하세요"
            className="min-h-24 w-full resize-y rounded border border-gray-300 px-3 py-2 text-sm text-gray-800 outline-none focus:border-blue-500"
          />
        </CollapsibleSection>
      )}

      <CollapsibleSection title="가드레일" showDivider>
        <div className="flex flex-wrap gap-2">
          {availableGuardrails.map((guardrail) => {
            const isSelected = selectedGuardrails.includes(guardrail);
            return (
              <button
                key={guardrail}
                type="button"
                onClick={() => toggleGuardrail(guardrail)}
                className={`rounded-md border px-2.5 py-1.5 text-xs font-semibold transition-colors ${
                  isSelected
                    ? 'border-teal-300 bg-teal-50 text-teal-800'
                    : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300 hover:bg-gray-50'
                }`}
                aria-pressed={isSelected}
              >
                {guardrail}
              </button>
            );
          })}
        </div>
      </CollapsibleSection>

      {data.operation !== 'sanitize_text' && (
        <CollapsibleSection title="임시 분기" showDivider>
          <div className="flex flex-col gap-3">
            <label className="flex items-center gap-2 text-xs font-semibold text-gray-700">
              <input
                type="checkbox"
                checked={data.branching_enabled !== false}
                onChange={(event) =>
                  handleBranchingChange(event.target.checked)
                }
                className="h-4 w-4 rounded border-gray-300 text-teal-600 focus:ring-teal-500"
              />
              통과 / 실패 출력 사용
            </label>

            <div className="flex flex-col gap-1">
              <label className="text-xs font-medium text-gray-700">
                매칭 키워드
              </label>
              <textarea
                value={keywordText}
                onChange={(event) => handleKeywordChange(event.target.value)}
                placeholder="통과 경로로 보낼 키워드를 쉼표로 구분해 입력"
                className="min-h-16 w-full resize-y rounded border border-gray-300 px-3 py-2 text-sm text-gray-800 outline-none focus:border-blue-500"
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-gray-700">
                  통과 라벨
                </label>
                <input
                  value={data.pass_label || '통과'}
                  onChange={(event) =>
                    updateData('pass_label', event.target.value)
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm text-gray-800 outline-none focus:border-blue-500"
                />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs font-medium text-gray-700">
                  실패 라벨
                </label>
                <input
                  value={data.fail_label || '실패'}
                  onChange={(event) =>
                    updateData('fail_label', event.target.value)
                  }
                  className="w-full rounded border border-gray-300 px-3 py-2 text-sm text-gray-800 outline-none focus:border-blue-500"
                />
              </div>
            </div>
          </div>
        </CollapsibleSection>
      )}

      {selectedGuardrails.includes('Keywords') &&
        !(data.operation !== 'sanitize_text' && data.branching_enabled !== false) && (
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-700">
              키워드
            </label>
            <textarea
              value={keywordText}
              onChange={(event) => handleKeywordChange(event.target.value)}
              placeholder="차단하거나 감시할 키워드를 쉼표로 구분해 입력"
              className="min-h-16 w-full resize-y rounded border border-gray-300 px-3 py-2 text-sm text-gray-800 outline-none focus:border-blue-500"
            />
          </div>
        )}

      {selectedGuardrails.includes('Custom') && (
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-700">
            사용자 정의 가드레일
          </label>
          <textarea
            value={data.custom_prompt || ''}
            onChange={(event) => updateData('custom_prompt', event.target.value)}
            placeholder="검사할 사용자 정의 정책을 설명하세요"
            className="min-h-20 w-full resize-y rounded border border-gray-300 px-3 py-2 text-sm text-gray-800 outline-none focus:border-blue-500"
          />
        </div>
      )}

      {selectedGuardrails.includes('Custom Regex') && (
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-700">
            사용자 정의 정규식
          </label>
          <textarea
            value={data.custom_regex || ''}
            onChange={(event) => updateData('custom_regex', event.target.value)}
            placeholder="정규식 패턴"
            className="min-h-16 w-full resize-y rounded border border-gray-300 px-3 py-2 font-mono text-xs text-gray-800 outline-none focus:border-blue-500"
          />
        </div>
      )}
    </div>
  );
}
