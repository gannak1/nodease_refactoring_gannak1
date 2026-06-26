import { DragEvent, useCallback, useMemo } from 'react';
import { useWorkflowStore } from '@/app/features/workflow/store/useWorkflowStore';
import { AnswerNodeData, AnswerNodeOutput } from '../../../../types/Nodes';
import { getUpstreamNodes } from '../../../../utils/getUpstreamNodes';
import { CollapsibleSection } from '../../ui/CollapsibleSection';
import {
  NODE_OUTPUT_DRAG_MIME,
  NodeOutputVariable,
  getNodeOutputVariables,
  parseDraggedOutput,
} from '../../../../utils/nodeVariablePorts';
import { ArrowRight, Plus, Trash2 } from 'lucide-react';

interface AnswerNodePanelProps {
  nodeId: string;
  data: AnswerNodeData;
}

const selectorFor = (output: NodeOutputVariable) => [
  output.sourceNodeId,
  output.key,
];

const selectorEquals = (selector: string[] | undefined, output: NodeOutputVariable) =>
  Array.isArray(selector) &&
  selector[0] === output.sourceNodeId &&
  (selector[1] === output.key || selector[1] === output.outputId);

const toSafeVariableName = (value: string) => {
  const normalized = value.trim().replace(/[^\w]/g, '_');
  return normalized || 'result';
};

const getUniqueVariableName = (
  outputs: AnswerNodeOutput[],
  baseValue: string,
  currentIndex?: number,
) => {
  const baseName = toSafeVariableName(baseValue);
  const usedNames = new Set(
    outputs
      .filter((_, index) => index !== currentIndex)
      .map((output) => output.variable?.trim())
      .filter(Boolean),
  );

  if (!usedNames.has(baseName)) return baseName;

  let suffix = 2;
  while (usedNames.has(`${baseName}_${suffix}`)) {
    suffix += 1;
  }
  return `${baseName}_${suffix}`;
};

export function AnswerNodePanel({ nodeId, data }: AnswerNodePanelProps) {
  const { updateNodeData, nodes, edges } = useWorkflowStore();

  const upstreamNodes = useMemo(
    () => getUpstreamNodes(nodeId, nodes, edges),
    [nodeId, nodes, edges],
  );

  const upstreamOutputMap = useMemo(() => {
    const outputMap = new Map<string, NodeOutputVariable>();
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

  const getSelectedOutput = useCallback(
    (selector: string[] | undefined) => {
      if (!Array.isArray(selector) || selector.length < 2) return undefined;
      return upstreamOutputMap.get(`${selector[0]}:${selector[1]}`);
    },
    [upstreamOutputMap],
  );

  const handleAddOutput = useCallback(() => {
    const newOutputs = [
      ...(data.outputs || []),
      { variable: '', value_selector: [] },
    ];
    updateNodeData(nodeId, { outputs: newOutputs });
  }, [data.outputs, nodeId, updateNodeData]);

  const handleUpdateOutput = useCallback(
    (index: number, key: keyof AnswerNodeOutput, value: string | string[]) => {
      const newOutputs = [...(data.outputs || [])];
      newOutputs[index] = {
        ...newOutputs[index],
        [key]: value,
      };
      updateNodeData(nodeId, { outputs: newOutputs });
    },
    [data.outputs, nodeId, updateNodeData],
  );

  const handleRemoveOutput = useCallback(
    (index: number) => {
      const newOutputs = [...(data.outputs || [])];
      newOutputs.splice(index, 1);
      updateNodeData(nodeId, { outputs: newOutputs });
    },
    [data.outputs, nodeId, updateNodeData],
  );

  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer.types.includes(NODE_OUTPUT_DRAG_MIME)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
  };

  const handleDropOutput = useCallback(
    (event: DragEvent<HTMLDivElement>, index?: number) => {
      const droppedOutput = parseDraggedOutput(event.dataTransfer);
      if (!droppedOutput) return;

      event.preventDefault();
      event.stopPropagation();

      const currentOutputs = data.outputs || [];
      const existingIndex = currentOutputs.findIndex((output, outputIndex) => {
        if (index !== undefined && outputIndex === index) return false;
        return selectorEquals(output.value_selector, droppedOutput);
      });

      const targetIndex = index ?? existingIndex;
      const nextVariable = getUniqueVariableName(
        currentOutputs,
        droppedOutput.key,
        targetIndex >= 0 ? targetIndex : undefined,
      );
      const nextOutput = {
        variable:
          targetIndex >= 0
            ? currentOutputs[targetIndex]?.variable || nextVariable
            : nextVariable,
        value_selector: selectorFor(droppedOutput),
      };

      const nextOutputs =
        targetIndex >= 0
          ? currentOutputs.map((output, outputIndex) =>
              outputIndex === targetIndex ? { ...output, ...nextOutput } : output,
            )
          : [...currentOutputs, nextOutput];

      updateNodeData(nodeId, { outputs: nextOutputs });
    },
    [data.outputs, nodeId, updateNodeData],
  );

  const outputs = data.outputs || [];

  return (
    <div className="flex flex-col gap-4">
      <CollapsibleSection title="반환값 매핑" showDivider>
        <div className="flex flex-col gap-3">
          <div className="flex items-start justify-between gap-2">
            <p className="text-xs leading-snug text-gray-500">
              이전 노드의 출력 칩을 드롭해서 최종 응답으로 내보낼 값을
              연결하세요.
            </p>
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation();
                handleAddOutput();
              }}
              className="shrink-0 rounded p-1 transition-colors hover:bg-gray-200"
              title="빈 반환값 추가"
              aria-label="빈 반환값 추가"
            >
              <Plus className="h-4 w-4 text-gray-600" />
            </button>
          </div>

          {outputs.length === 0 && (
            <div
              onDragOver={handleDragOver}
              onDrop={(event) => handleDropOutput(event)}
              className="flex min-h-14 items-center justify-center rounded-lg border border-dashed border-blue-200 bg-blue-50/60 px-3 py-3 text-xs font-medium text-blue-700 transition-colors hover:border-blue-300 hover:bg-blue-50"
            >
              출력 칩을 여기에 드롭
            </div>
          )}

          {outputs.map((output, index) => {
            const selectedOutput = getSelectedOutput(output.value_selector);
            const sourceTitle = selectedOutput?.sourceTitle;

            return (
              <div
                key={`${output.variable || 'output'}-${index}`}
                className="group flex flex-col gap-2 rounded-lg border border-gray-200 bg-white p-3 shadow-sm transition-all hover:border-gray-300 hover:shadow-md"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <div className="h-1.5 w-1.5 rounded-full bg-blue-500/50" />
                    <span className="text-[10px] font-bold tracking-wider text-gray-400">
                      반환값 {index + 1}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleRemoveOutput(index)}
                    className="flex h-5 w-5 items-center justify-center rounded bg-transparent text-gray-400 opacity-0 transition-all hover:bg-red-50 hover:text-red-500 group-hover:opacity-100"
                    title="반환값 삭제"
                    aria-label="반환값 삭제"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>

                <div className="flex items-center gap-2">
                  <div
                    onDragOver={handleDragOver}
                    onDrop={(event) => handleDropOutput(event, index)}
                    className="flex min-h-9 flex-[4] items-center rounded-md border border-dashed border-gray-200 bg-gray-50 px-2 py-1.5 transition-colors hover:border-blue-300 hover:bg-blue-50/60"
                    title="출력 칩을 드롭해서 소스를 연결하거나 교체"
                  >
                    {selectedOutput ? (
                      <div className="inline-flex max-w-full flex-col gap-0.5">
                        <span className="inline-flex max-w-full items-center rounded-md border border-blue-100 bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-800 shadow-sm">
                          <span className="truncate">
                            {selectedOutput.label || selectedOutput.key}
                          </span>
                        </span>
                        {sourceTitle && (
                          <span className="truncate px-0.5 text-[10px] text-gray-500">
                            {sourceTitle}
                          </span>
                        )}
                      </div>
                    ) : (
                      <span className="text-xs font-medium text-gray-400">
                        출력 칩 드롭
                      </span>
                    )}
                  </div>

                  <div className="flex flex-none items-center justify-center text-gray-400">
                    <div className="flex h-6 w-6 items-center justify-center rounded-full bg-gray-100">
                      <ArrowRight className="h-3 w-3 text-gray-500" />
                    </div>
                  </div>

                  <div className="flex-[3]">
                    <input
                      type="text"
                      className="w-full rounded-md border border-gray-200 px-2.5 py-1.5 text-xs font-semibold text-blue-600 placeholder:font-normal placeholder:text-gray-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500/20"
                      placeholder="반환 key"
                      value={output.variable}
                      onChange={(event) =>
                        handleUpdateOutput(index, 'variable', event.target.value)
                      }
                    />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </CollapsibleSection>
    </div>
  );
}
