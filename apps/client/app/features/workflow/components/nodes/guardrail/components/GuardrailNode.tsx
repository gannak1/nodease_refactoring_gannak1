import { memo, useCallback } from 'react';
import type { MouseEvent } from 'react';
import { Node, NodeProps, Position } from '@xyflow/react';
import { ShieldCheck } from 'lucide-react';

import { BaseNode, SmartHandle } from '../../BaseNode';
import { GuardrailNodeData } from '../../../../types/Nodes';
import { useWorkflowStore } from '../../../../store/useWorkflowStore';
import { ValidationBadge } from '../../../ui/ValidationBadge';

const OPERATION_LABELS: Record<GuardrailNodeData['operation'], string> = {
  check_text: '위반 검사',
  sanitize_text: '텍스트 정제',
};

export const GuardrailNode = memo(
  ({ data, selected, id }: NodeProps<Node<GuardrailNodeData>>) => {
    const guardrails = data.guardrails || [];
    const branchEnabled =
      data.operation !== 'sanitize_text' && data.branching_enabled !== false;
    const passHandleId = data.pass_handle_id || 'pass';
    const failHandleId = data.fail_handle_id || 'fail';
    const passLabel = data.pass_label || '통과';
    const failLabel = data.fail_label || '실패';
    const numberConnection = useWorkflowStore((state) => state.numberConnection);
    const startNumberConnection = useWorkflowStore(
      (state) => state.startNumberConnection,
    );
    const hasInput =
      Boolean(data.text_to_check?.trim()) ||
      Boolean(data.input_selector && data.input_selector.length >= 2);
    const matchKeywords = data.match_keywords || [];

    const highlightedHandle =
      typeof window !== 'undefined'
        ? (window as Window & { __dragHighlightedHandle__?: string | null })
            .__dragHighlightedHandle__ || null
        : null;
    const isNumberConnectionSource =
      Boolean(numberConnection) && numberConnection?.sourceNodeId === id;

    const handleSourceNumberClick = useCallback(
      (sourceHandleId: string) => (event: MouseEvent<HTMLDivElement>) => {
        event.preventDefault();
        event.stopPropagation();
        startNumberConnection(id, sourceHandleId);
      },
      [id, startNumberConnection],
    );

    const getSourceNumberClassName = (sourceHandleId: string) =>
      isNumberConnectionSource &&
      numberConnection?.sourceHandleId === sourceHandleId
        ? 'border-blue-200 bg-blue-600 text-white ring-4 ring-blue-100'
        : undefined;

    return (
      <BaseNode
        id={id}
        data={data}
        selected={selected}
        showSourceHandle={!branchEnabled}
        icon={<ShieldCheck className="text-white" />}
        iconColor="#0f766e"
      >
        <div className="flex flex-col gap-2">
          <div className="text-sm font-semibold text-gray-800 truncate">
            {OPERATION_LABELS[data.operation] || '가드레일'}
          </div>
          <div className="text-xs text-gray-500">
            {guardrails.length > 0
              ? `${guardrails.length}개 가드레일 선택됨`
              : '선택된 가드레일 없음'}
          </div>
          {branchEnabled && (
            <>
              <div className="text-xs text-gray-500">
                키워드 분기
                {matchKeywords.length > 0
                  ? `: ${matchKeywords.join(', ')}`
                  : ': 키워드 설정 필요'}
              </div>
              <div className="mt-2 flex flex-col gap-2">
                {[
                  {
                    id: passHandleId,
                    label: passLabel,
                    className: 'text-teal-700',
                  },
                  {
                    id: failHandleId,
                    label: failLabel,
                    className: 'text-gray-600',
                  },
                ].map((branch) => {
                  const isHighlighted = highlightedHandle === branch.id;
                  return (
                    <div
                      key={branch.id}
                      className={`relative flex h-6 items-center justify-end rounded px-2 -mx-2 transition-all ${
                        isHighlighted
                          ? 'border-2 border-blue-500 bg-blue-100 shadow-lg'
                          : 'border-2 border-transparent bg-transparent'
                      }`}
                    >
                      <span
                        className={`mr-3 whitespace-nowrap text-sm font-semibold ${branch.className}`}
                      >
                        {branch.label}
                      </span>
                      <SmartHandle
                        type="source"
                        position={Position.Right}
                        id={branch.id}
                        className="!absolute !right-[-36px]"
                        style={{ top: '50%', transform: 'translateY(-50%)' }}
                        displayNumber={data.displayNumber}
                        numberClassName={getSourceNumberClassName(branch.id)}
                        onNumberClick={handleSourceNumberClick(branch.id)}
                      />
                    </div>
                  );
                })}
              </div>
            </>
          )}
          {!hasInput && <ValidationBadge message="입력 필요" />}
        </div>
      </BaseNode>
    );
  },
);

GuardrailNode.displayName = '가드레일 노드';
