import { Handle, Position, HandleProps } from '@xyflow/react';
import { Check, ChevronDown, ChevronRight, Pencil, X } from 'lucide-react';
import React, { useCallback, useEffect, useRef, useState, useMemo } from 'react';

import { cn } from '@/lib/utils';
import { getNodeDefinitionByType } from '../../config/nodeRegistry';
import { useWorkflowStore } from '../../store/useWorkflowStore';
import { AppNode, BaseNodeData } from '../../types/Nodes';
import { getUpstreamNodes } from '../../utils/getUpstreamNodes';
import {
  NODE_OUTPUT_DRAG_MIME,
  NodeOutputVariable,
  getNodeOutputVariables,
} from '../../utils/nodeVariablePorts';
import { NodeInlinePanel } from './NodeInlinePanel';
import { NodeOutputsSection } from './NodeOutputsSection';
import { VisiblePropertySummary } from './VisiblePropertySummary';

interface BaseNodeProps {
  id?: string;
  data: BaseNodeData;
  children?: React.ReactNode;

  showSourceHandle?: boolean;
  showTargetHandle?: boolean;

  className?: string;
  selected?: boolean;

  icon?: React.ReactNode;
  iconColor?: string;

  targetHandleId?: string;
  sourceHandleId?: string;
  targetHandleStyle?: React.CSSProperties;
  sourceHandleStyle?: React.CSSProperties;

  onHandlePlusClick?: (side: 'left' | 'right') => void;
  titleClassName?: string;
  showDetailsToggle?: boolean;
}

const INPUT_CHIP_COLORS = [
  'border-rose-200 bg-rose-50 text-rose-700',
  'border-blue-200 bg-blue-50 text-blue-700',
  'border-emerald-200 bg-emerald-50 text-emerald-700',
  'border-amber-200 bg-amber-50 text-amber-700',
  'border-violet-200 bg-violet-50 text-violet-700',
  'border-cyan-200 bg-cyan-50 text-cyan-700',
  'border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700',
  'border-slate-200 bg-slate-50 text-slate-700',
];

const getInputChipColor = (sourceNodeId: string) => {
  let hash = 0;
  for (let index = 0; index < sourceNodeId.length; index += 1) {
    hash = (hash * 31 + sourceNodeId.charCodeAt(index)) % INPUT_CHIP_COLORS.length;
  }
  return INPUT_CHIP_COLORS[hash];
};

const setOutputDragPreview = (
  event: React.DragEvent<HTMLElement>,
  label: string,
) => {
  const source = event.currentTarget;
  const sourceRect = source.getBoundingClientRect();
  const preview = document.createElement('div');

  preview.textContent = label;
  preview.className =
    'pointer-events-none fixed left-0 top-0 z-[9999] inline-flex items-center rounded-md border border-blue-200 bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-800 shadow-lg';
  preview.style.width = `${Math.max(sourceRect.width, 32)}px`;
  preview.style.maxWidth = '240px';
  preview.style.height = `${Math.max(sourceRect.height, 24)}px`;
  preview.style.transform = 'translate(-10000px, -10000px)';
  preview.style.whiteSpace = 'nowrap';
  preview.style.overflow = 'hidden';
  preview.style.textOverflow = 'ellipsis';

  document.body.appendChild(preview);
  event.dataTransfer.setDragImage(
    preview,
    Math.min(sourceRect.width / 2, 48),
    Math.min(sourceRect.height / 2, 16),
  );

  window.setTimeout(() => {
    preview.remove();
  }, 0);
};

const getOutputLabels = (data: BaseNodeData) =>
  data.outputLabels &&
  typeof data.outputLabels === 'object' &&
  !Array.isArray(data.outputLabels)
    ? (data.outputLabels as Record<string, string>)
    : {};

const withoutOutputLabel = (
  labels: Record<string, string>,
  outputKey: string,
) => {
  const nextLabels = { ...labels };
  delete nextLabels[outputKey];
  return nextLabels;
};

const buildOutputLabelPatch = (
  node: AppNode,
  outputKey: string,
  outputId: string | undefined,
  nextLabel: string,
) => {
  const data = node.data as BaseNodeData;
  const currentLabels = getOutputLabels(data);

  if (node.type === 'startNode' && Array.isArray(data.variables)) {
    let changed = false;
    const nextVariables = data.variables.map((variable) => {
      if (!variable || typeof variable !== 'object') return variable;

      const variableRecord = variable as Record<string, unknown>;
      const variableId = String(variableRecord.id || '').trim();
      const variableName = String(variableRecord.name || '').trim();
      const variableLabel = String(variableRecord.label || '').trim();
      const matches =
        variableName === outputKey ||
        variableId === outputId ||
        (!variableName && variableLabel === outputKey);

      if (!matches) return variable;
      changed = true;
      return { ...variableRecord, label: nextLabel };
    });

    if (changed) {
      return {
        variables: nextVariables,
        outputLabels: withoutOutputLabel(currentLabels, outputKey),
      };
    }
  }

  return {
    outputLabels: {
      ...currentLabels,
      [outputKey]: nextLabel,
    },
  };
};

export const SmartHandle: React.FC<
  HandleProps & {
    className?: string;
    displayNumber?: number;
    showPlusButton?: boolean;
  }
> = ({ className, displayNumber, showPlusButton = true, ...props }) => {
  return (
    <Handle
      {...props}
      className={cn(
        // 히트 영역은 투명하게 유지하되, 드래그하기 쉽도록 크기 확보
        '!w-8 !h-8 !bg-transparent !border-0 rounded-full z-50 flex items-center justify-center',
        className,
      )}
    >
      {typeof displayNumber === 'number' ? (
        <div className="flex h-8 min-w-8 items-center justify-center rounded-full border-2 border-white bg-gray-900 px-2 text-xs font-bold tabular-nums text-white shadow-md">
          {displayNumber}
        </div>
      ) : showPlusButton ? (
        <>
          {/* 호버 시 나타나는 플러스 버튼 */}
          <div
            className="w-6 h-6 rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex items-center justify-center bg-blue-500"
            style={{ position: 'relative' }}
          >
            {/* 플러스 아이콘 - 가로선 */}
            <div
              className="absolute bg-white pointer-events-none"
              style={{
                width: '12px',
                height: '2px',
                top: '50%',
                left: '50%',
                transform: 'translate(-50%, -50%)',
              }}
            />
            {/* 플러스 아이콘 - 세로선 */}
            <div
              className="absolute bg-white pointer-events-none"
              style={{
                width: '2px',
                height: '12px',
                top: '50%',
                left: '50%',
                transform: 'translate(-50%, -50%)',
              }}
            />
          </div>
        </>
      ) : null}
    </Handle>
  );
};

export const JigsawBackground = ({
  width,
  height,
  selected,
  status,
}: {
  width: number;
  height: number;
  selected?: boolean;
  status?: string;
}) => {
  const r = 16;

  const d = useMemo(() => {
    if (width === 0 || height === 0) return '';

    return `
      M ${r} 0
      L ${width - r} 0
      Q ${width} 0 ${width} ${r}
      L ${width} ${height - r}
      Q ${width} ${height} ${width - r} ${height}
      L ${r} ${height}
      Q 0 ${height} 0 ${height - r}
      L 0 ${r}
      Q 0 0 ${r} 0
    `;
  }, [width, height]);

  let strokeColor = '#d1d5db';
  const strokeWidth = 2;

  if (selected) {
    strokeColor = '#3b82f6'; // blue-500
  } else if (status === 'running') {
    strokeColor = '#3b82f6';
  } else if (status === 'success') {
    strokeColor = '#22c55e'; // green-500
  } else if (status === 'failure') {
    strokeColor = '#ef4444'; // red-500
  }

  return (
    <svg
      width={width}
      height={height}
      className={`absolute top-0 left-0 pointer-events-none drop-shadow-sm transition-all duration-300`}
      style={{ overflow: 'visible', zIndex: 0 }}
    >
      <path
        d={d}
        fill="white"
        stroke={strokeColor}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
};

export const BaseNode: React.FC<BaseNodeProps> = ({
  id,
  data,
  children,
  showSourceHandle = true,
  showTargetHandle = true,
  className,
  selected,
  icon,
  iconColor = '#3b82f6',
  targetHandleId = 'target',
  sourceHandleId = 'source',
  targetHandleStyle,
  sourceHandleStyle,
  titleClassName = 'truncate max-w-[260px]',
  showDetailsToggle = true,
}) => {
  const ref = useRef<HTMLDivElement>(null);
  const titleInputRef = useRef<HTMLInputElement>(null);
  const outputLabelInputRef = useRef<HTMLInputElement>(null);
  const inputPanelRef = useRef<HTMLDivElement>(null);
  const outputPanelRef = useRef<HTMLDivElement>(null);
  const closeOutputPanelTimerRef = useRef<number | null>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [isNodeHovered, setIsNodeHovered] = useState(false);
  const [isInputPanelHovered, setIsInputPanelHovered] = useState(false);
  const [isOutputPanelHovered, setIsOutputPanelHovered] = useState(false);
  const [isDraggingOutput, setIsDraggingOutput] = useState(false);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [draftTitle, setDraftTitle] = useState('');
  const [titleBeforeEdit, setTitleBeforeEdit] = useState('');
  const [editingOutputKey, setEditingOutputKey] = useState<string | null>(null);
  const [editingOutputId, setEditingOutputId] = useState<string | undefined>();
  const [draftOutputLabel, setDraftOutputLabel] = useState('');
  const [outputLabelBeforeEdit, setOutputLabelBeforeEdit] = useState('');
  const [collapsedInputSources, setCollapsedInputSources] = useState<
    Set<string>
  >(new Set());
  const node = useWorkflowStore((state) =>
    id ? (state.nodes.find((item) => item.id === id) as AppNode | undefined) : undefined,
  );
  const nodes = useWorkflowStore((state) => state.nodes);
  const edges = useWorkflowStore((state) => state.edges);
  const updateNodeData = useWorkflowStore((state) => state.updateNodeData);
  const definition = getNodeDefinitionByType(node?.type || '');
  const detailsExpanded = Boolean(data.detailsExpanded);
  const outputVariables = useMemo(() => getNodeOutputVariables(node), [node]);
  const inputVariables = useMemo(() => {
    if (!node) return [];
    return getUpstreamNodes(node.id, nodes, edges).flatMap(
      (upstreamNode) => getNodeOutputVariables(upstreamNode as AppNode),
    );
  }, [edges, node, nodes]);
  const inputVariableGroups = useMemo(() => {
    const groupMap = new Map<
      string,
      { sourceNodeId: string; sourceTitle: string; outputs: NodeOutputVariable[] }
    >();

    for (const input of inputVariables) {
      const group = groupMap.get(input.sourceNodeId);
      if (group) {
        group.outputs.push(input);
      } else {
        groupMap.set(input.sourceNodeId, {
          sourceNodeId: input.sourceNodeId,
          sourceTitle: input.sourceTitle,
          outputs: [input],
        });
      }
    }

    return Array.from(groupMap.values());
  }, [inputVariables]);

  const nodeTypeLabel = definition?.name || 'Node';
  const description = data.description || definition?.description;
  const titleText = String(data.title || 'Untitled Node');
  const isInputPanelOpen =
    inputVariables.length > 0 &&
    (isNodeHovered || isInputPanelHovered || isDraggingOutput);
  const isOutputPanelOpen =
    outputVariables.length > 0 &&
    (isNodeHovered ||
      isOutputPanelHovered ||
      isDraggingOutput ||
      editingOutputKey !== null);

  const clearOutputPanelCloseTimer = useCallback(() => {
    if (!closeOutputPanelTimerRef.current) return;
    window.clearTimeout(closeOutputPanelTimerRef.current);
    closeOutputPanelTimerRef.current = null;
  }, []);

  const scheduleOutputPanelClose = useCallback(() => {
    clearOutputPanelCloseTimer();
    closeOutputPanelTimerRef.current = window.setTimeout(() => {
      if (
        ref.current?.matches(':hover') ||
        outputPanelRef.current?.matches(':hover') ||
        isDraggingOutput
      ) {
        closeOutputPanelTimerRef.current = null;
        return;
      }
      setIsNodeHovered(false);
      setIsInputPanelHovered(false);
      setIsOutputPanelHovered(false);
      closeOutputPanelTimerRef.current = null;
    }, 350);
  }, [clearOutputPanelCloseTimer, isDraggingOutput]);

  useEffect(() => {
    if (!ref.current) return;
    if (ref.current.offsetWidth > 0 || ref.current.offsetHeight > 0) {
      setDimensions({
        width: ref.current.offsetWidth,
        height: ref.current.offsetHeight,
      });
    }

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.borderBoxSize && entry.borderBoxSize.length > 0) {
          setDimensions({
            width: entry.borderBoxSize[0].inlineSize,
            height: entry.borderBoxSize[0].blockSize,
          });
        } else {
          setDimensions({
            width: (entry.contentRect.width || 0) + 56,
            height: (entry.contentRect.height || 0) + 56,
          });
          if (ref.current) {
            setDimensions({
              width: ref.current.offsetWidth,
              height: ref.current.offsetHeight,
            });
          }
        }
      }
    });
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    return () => clearOutputPanelCloseTimer();
  }, [clearOutputPanelCloseTimer]);

  useEffect(() => {
    if (!isDraggingOutput) return;

    const keepCopyCursor = (event: DragEvent) => {
      if (!event.dataTransfer?.types.includes(NODE_OUTPUT_DRAG_MIME)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = 'copy';
    };

    const stopDragging = () => setIsDraggingOutput(false);

    window.addEventListener('dragover', keepCopyCursor);
    window.addEventListener('drop', stopDragging);
    window.addEventListener('dragend', stopDragging);
    return () => {
      window.removeEventListener('dragover', keepCopyCursor);
      window.removeEventListener('drop', stopDragging);
      window.removeEventListener('dragend', stopDragging);
    };
  }, [isDraggingOutput]);

  useEffect(() => {
    if (!isEditingTitle) return;
    titleInputRef.current?.focus();
    titleInputRef.current?.select();
  }, [isEditingTitle]);

  useEffect(() => {
    if (!editingOutputKey) return;
    outputLabelInputRef.current?.focus();
    outputLabelInputRef.current?.select();
  }, [editingOutputKey]);

  useEffect(() => {
    const handleMouseMove = (event: MouseEvent) => {
      const panelRect = outputPanelRef.current?.getBoundingClientRect();
      const inputPanelRect = inputPanelRef.current?.getBoundingClientRect();
      const nodeRect = ref.current?.getBoundingClientRect();
      if (!nodeRect) return;

      const isInsidePanel =
        panelRect &&
        event.clientX >= panelRect.left &&
        event.clientX <= panelRect.right &&
        event.clientY >= panelRect.top &&
        event.clientY <= panelRect.bottom;
      const isInsideInputPanel =
        inputPanelRect &&
        event.clientX >= inputPanelRect.left &&
        event.clientX <= inputPanelRect.right &&
        event.clientY >= inputPanelRect.top &&
        event.clientY <= inputPanelRect.bottom;
      const isInsideNode =
        event.clientX >= nodeRect.left &&
        event.clientX <= nodeRect.right &&
        event.clientY >= nodeRect.top &&
        event.clientY <= nodeRect.bottom;

      if (isInsidePanel) {
        clearOutputPanelCloseTimer();
        setIsOutputPanelHovered(true);
        return;
      }

      if (isInsideInputPanel) {
        clearOutputPanelCloseTimer();
        setIsInputPanelHovered(true);
        return;
      }

      if (isInsideNode) {
        clearOutputPanelCloseTimer();
        return;
      }

      if (isOutputPanelOpen && !isDraggingOutput) {
        scheduleOutputPanelClose();
      }
    };

    window.addEventListener('mousemove', handleMouseMove);
    return () => window.removeEventListener('mousemove', handleMouseMove);
  }, [
    clearOutputPanelCloseTimer,
    isDraggingOutput,
    isOutputPanelOpen,
    scheduleOutputPanelClose,
  ]);

  const getHandleStyle = (side: 'left' | 'right') => {
    if (side === 'left') {
      return { left: '-20px', ...targetHandleStyle };
    } else {
      return { right: '-20px', ...sourceHandleStyle };
    }
  };

  const handleDoubleClick = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!showDetailsToggle || !node) return;

    const target = event.target;
    if (
      target instanceof HTMLElement &&
      target.closest(
        'button, input, textarea, select, [contenteditable]:not([contenteditable="false"]), [draggable="true"], .nodrag',
      )
    ) {
      return;
    }

    event.stopPropagation();
    updateNodeData(node.id, { detailsExpanded: !detailsExpanded });
  };

  const startTitleEdit = useCallback(
    (event: React.MouseEvent<HTMLButtonElement>) => {
      if (!node) return;
      event.preventDefault();
      event.stopPropagation();
      setTitleBeforeEdit(titleText);
      setDraftTitle(titleText);
      setIsEditingTitle(true);
    },
    [node, titleText],
  );

  const cancelTitleEdit = useCallback(() => {
    setDraftTitle(titleBeforeEdit);
    setIsEditingTitle(false);
  }, [titleBeforeEdit]);

  const saveTitleEdit = useCallback(() => {
    if (!node) return;
    const nextTitle = draftTitle.trim();
    if (!nextTitle) {
      cancelTitleEdit();
      return;
    }
    updateNodeData(node.id, { title: nextTitle });
    setTitleBeforeEdit(nextTitle);
    setDraftTitle(nextTitle);
    setIsEditingTitle(false);
  }, [cancelTitleEdit, draftTitle, node, updateNodeData]);

  const startOutputLabelEdit = useCallback(
    (
      event: React.MouseEvent<HTMLDivElement>,
      output: NodeOutputVariable,
    ) => {
      event.preventDefault();
      event.stopPropagation();
      setEditingOutputKey(output.key);
      setEditingOutputId(output.outputId);
      setDraftOutputLabel(output.label || output.key);
      setOutputLabelBeforeEdit(output.label || output.key);
    },
    [],
  );

  const cancelOutputLabelEdit = useCallback(() => {
    setDraftOutputLabel(outputLabelBeforeEdit);
    setEditingOutputKey(null);
    setEditingOutputId(undefined);
  }, [outputLabelBeforeEdit]);

  const saveOutputLabelEdit = useCallback(() => {
    if (!node || !editingOutputKey) return;
    const nextLabel = draftOutputLabel.trim();
    if (!nextLabel) {
      cancelOutputLabelEdit();
      return;
    }

    updateNodeData(
      node.id,
      buildOutputLabelPatch(node, editingOutputKey, editingOutputId, nextLabel),
    );
    setOutputLabelBeforeEdit(nextLabel);
    setDraftOutputLabel(nextLabel);
    setEditingOutputKey(null);
    setEditingOutputId(undefined);
  }, [
    cancelOutputLabelEdit,
    draftOutputLabel,
    editingOutputKey,
    editingOutputId,
    node,
    updateNodeData,
  ]);

  const startOutputDrag = useCallback(
    (
      event: React.DragEvent<HTMLDivElement>,
      output: NodeOutputVariable,
    ) => {
      clearOutputPanelCloseTimer();
      setIsDraggingOutput(true);
      event.dataTransfer.effectAllowed = 'copy';
      event.dataTransfer.setData(NODE_OUTPUT_DRAG_MIME, JSON.stringify(output));
      setOutputDragPreview(event, output.label || output.key);
    },
    [clearOutputPanelCloseTimer],
  );

  return (
    <div
      ref={ref}
      onMouseEnter={() => {
        clearOutputPanelCloseTimer();
        setIsNodeHovered(true);
      }}
      onMouseLeave={scheduleOutputPanelClose}
      onDoubleClick={handleDoubleClick}
      className={cn(
        'relative group w-[420px] min-h-[150px] p-7 transition-all',
        className,
      )}
      style={{ isolation: 'isolate', overflow: 'visible' }}
    >
      <JigsawBackground
        width={dimensions.width}
        height={dimensions.height}
        selected={selected}
        status={data.status}
      />

      {inputVariables.length > 0 && (
        <div
          ref={inputPanelRef}
          onMouseEnter={() => {
            clearOutputPanelCloseTimer();
            setIsInputPanelHovered(true);
          }}
          onMouseLeave={scheduleOutputPanelClose}
          className={cn(
            'nodrag absolute left-[calc(100%+12px)] top-0 z-40 w-60 transition-opacity duration-150',
            isInputPanelOpen
              ? 'pointer-events-auto opacity-100'
              : 'pointer-events-none opacity-0',
          )}
        >
          <div className="rounded-xl border border-gray-200 bg-white p-3 shadow-xl">
            <div className="mb-3 flex items-center justify-between gap-3 px-0.5">
              <div className="text-xs font-bold text-gray-900">
                {inputVariables.length} Inputs
              </div>
            </div>
            <div className="flex max-h-64 flex-col gap-3 overflow-y-auto">
              {inputVariableGroups.map((group) => {
                const isCollapsed = collapsedInputSources.has(
                  group.sourceNodeId,
                );

                const chipColor = getInputChipColor(group.sourceNodeId);

                return (
                  <div key={group.sourceNodeId} className="min-w-0">
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation();
                        setCollapsedInputSources((current) => {
                          const next = new Set(current);
                          if (next.has(group.sourceNodeId)) {
                            next.delete(group.sourceNodeId);
                          } else {
                            next.add(group.sourceNodeId);
                          }
                          return next;
                        });
                      }}
                      className="mb-1 flex w-full items-center justify-between gap-2 rounded-md px-1 py-0.5 text-left text-xs font-semibold text-gray-800 hover:bg-gray-50"
                      aria-expanded={!isCollapsed}
                    >
                      <span className="min-w-0 truncate">
                        {group.sourceTitle}
                      </span>
                      <ChevronDown
                        className={cn(
                          'h-3.5 w-3.5 shrink-0 text-gray-500 transition-transform',
                          isCollapsed && '-rotate-90',
                        )}
                      />
                    </button>

                    {!isCollapsed && (
                      <div className="flex flex-wrap content-start gap-1">
                        {group.outputs.map((input) => (
                          <div
                            key={`${input.sourceNodeId}-${input.key}`}
                            draggable
                            onDragStart={(event) =>
                              startOutputDrag(event, input)
                            }
                            onDragEnd={() => setIsDraggingOutput(false)}
                            className={cn(
                              'inline-flex max-w-full cursor-grab items-center rounded-md border px-2 py-1 text-xs font-semibold shadow-sm active:cursor-grabbing',
                              chipColor,
                            )}
                            title={`${input.label} (${input.sourceTitle}.${input.key})`}
                          >
                            <span className="max-w-full truncate">
                              {input.label || input.key}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {outputVariables.length > 0 && (
        <div
          ref={outputPanelRef}
          onMouseEnter={() => {
            clearOutputPanelCloseTimer();
            setIsOutputPanelHovered(true);
          }}
          onMouseLeave={scheduleOutputPanelClose}
          className={cn(
            'nodrag absolute bottom-0 left-[calc(100%+12px)] z-40 w-56 transition-opacity duration-150',
            isOutputPanelOpen
              ? 'pointer-events-auto opacity-100'
              : 'pointer-events-none opacity-0',
          )}
        >
          <div className="rounded-lg border border-gray-200 bg-white p-2 shadow-xl">
            <div className="mb-2 px-1 text-[10px] font-semibold uppercase text-gray-400">
              Outputs
            </div>
            <div className="flex max-h-48 flex-wrap content-end gap-1 overflow-y-auto">
              {outputVariables.map((output) => (
                <div
                  key={`${output.sourceNodeId}-${output.key}`}
                  draggable={editingOutputKey !== output.key}
                  onDoubleClick={(event) => startOutputLabelEdit(event, output)}
                  onDragStart={(event) => startOutputDrag(event, output)}
                  onDragEnd={() => setIsDraggingOutput(false)}
                  className="inline-flex max-w-full cursor-grab rounded-md border border-gray-200 bg-gray-50 px-2 py-1.5 text-xs text-gray-700 shadow-sm active:cursor-grabbing"
                  title={`${output.label} (${output.sourceTitle}.${output.key}) - 더블클릭해서 표시 이름 수정`}
                >
                  {editingOutputKey === output.key ? (
                    <input
                      ref={outputLabelInputRef}
                      value={draftOutputLabel}
                      onChange={(event) =>
                        setDraftOutputLabel(event.target.value)
                      }
                      onBlur={cancelOutputLabelEdit}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                          event.preventDefault();
                          saveOutputLabelEdit();
                        }
                        if (event.key === 'Escape') {
                          event.preventDefault();
                          cancelOutputLabelEdit();
                        }
                      }}
                      onClick={(event) => event.stopPropagation()}
                      onDoubleClick={(event) => event.stopPropagation()}
                      className="w-full rounded border border-blue-300 bg-white px-1.5 py-1 text-xs font-semibold text-gray-900 outline-none ring-2 ring-blue-100"
                      aria-label="출력변수 표시 이름 수정"
                    />
                  ) : (
                    <div className="max-w-full truncate font-semibold text-gray-800">
                      {output.label || output.key}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="relative z-10">
        {showDetailsToggle && node && (
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              updateNodeData(node.id, { detailsExpanded: !detailsExpanded });
            }}
            className="nodrag absolute right-0 top-0 z-20 flex h-7 w-7 items-center justify-center rounded-md border border-gray-200 bg-white text-gray-500 shadow-sm transition-colors hover:border-gray-300 hover:bg-gray-50 hover:text-gray-800"
            title={detailsExpanded ? '상세 접기' : '상세 보기'}
            aria-label={detailsExpanded ? '상세 접기' : '상세 보기'}
          >
            {detailsExpanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </button>
        )}

        {showTargetHandle && (
          <SmartHandle
            id={targetHandleId}
            type="target"
            position={Position.Left}
            className="-ml-2"
            style={getHandleStyle('left')}
            displayNumber={data.displayNumber}
            showPlusButton={showTargetHandle}
          />
        )}

        <div className="mb-4 flex items-start gap-4 pr-8">
          {icon && (
            <div
              className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl text-white shadow-sm"
              style={{ backgroundColor: iconColor }}
            >
              {React.isValidElement(icon) &&
                React.cloneElement(icon as React.ReactElement<{ className?: string }>, {
                  className: 'w-8 h-8',
                })}
            </div>
          )}

          <div className="flex min-w-0 flex-col">
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
              {nodeTypeLabel}
            </div>
            {isEditingTitle ? (
              <div
                className="nodrag nowheel mb-1 flex min-w-0 items-center gap-1"
                onClick={(event) => event.stopPropagation()}
                onDoubleClick={(event) => event.stopPropagation()}
                onMouseDown={(event) => event.stopPropagation()}
              >
                <input
                  ref={titleInputRef}
                  value={draftTitle}
                  onChange={(event) => setDraftTitle(event.target.value)}
                  onBlur={cancelTitleEdit}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault();
                      saveTitleEdit();
                    }
                    if (event.key === 'Escape') {
                      event.preventDefault();
                      cancelTitleEdit();
                    }
                  }}
                  className="min-w-0 flex-1 rounded-md border border-blue-300 bg-white px-2 py-1 text-xl font-bold leading-tight text-gray-900 shadow-sm outline-none ring-2 ring-blue-100"
                  aria-label="노드 이름 수정"
                />
                <button
                  type="button"
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={(event) => {
                    event.stopPropagation();
                    saveTitleEdit();
                  }}
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-gray-200 bg-white text-blue-600 shadow-sm transition-colors hover:border-blue-300 hover:bg-blue-50"
                  title="이름 저장"
                  aria-label="이름 저장"
                >
                  <Check className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={(event) => {
                    event.stopPropagation();
                    cancelTitleEdit();
                  }}
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-gray-200 bg-white text-gray-500 shadow-sm transition-colors hover:border-gray-300 hover:bg-gray-50 hover:text-gray-800"
                  title="이름 수정 취소"
                  aria-label="이름 수정 취소"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            ) : (
              <div className="group/title mb-1 flex min-w-0 items-center gap-1.5">
                <h3
                  className={cn(
                    'min-w-0 text-xl font-bold text-gray-900 leading-tight',
                    titleClassName,
                  )}
                  title={titleText}
                >
                  {titleText}
                </h3>
                {node && (
                  <button
                    type="button"
                    onClick={startTitleEdit}
                    className="nodrag flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-gray-400 opacity-0 transition-all hover:bg-gray-100 hover:text-gray-800 group-hover/title:opacity-100 focus:opacity-100"
                    title="노드 이름 수정"
                    aria-label="노드 이름 수정"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            )}
            {description && (
              <p
                className="line-clamp-2 text-[13px] leading-snug text-gray-500"
                title={String(description)}
              >
                {String(description)}
              </p>
            )}
          </div>
        </div>

        <div className="min-w-0 max-w-full text-sm">{children}</div>

        {!detailsExpanded && node && <VisiblePropertySummary node={node} />}

        {detailsExpanded && node && (
          <>
            <NodeInlinePanel node={node} />
            <NodeOutputsSection
              outputs={outputVariables}
              editingOutputKey={editingOutputKey}
              draftOutputLabel={draftOutputLabel}
              onDraftOutputLabelChange={setDraftOutputLabel}
              onStartOutputLabelEdit={startOutputLabelEdit}
              onSaveOutputLabelEdit={saveOutputLabelEdit}
              onCancelOutputLabelEdit={cancelOutputLabelEdit}
              onStartOutputDrag={startOutputDrag}
              onEndOutputDrag={() => setIsDraggingOutput(false)}
              outputLabelInputRef={outputLabelInputRef}
            />
          </>
        )}

        {showSourceHandle && (
          <SmartHandle
            id={sourceHandleId}
            type="source"
            position={Position.Right}
            className="-mr-2"
            style={getHandleStyle('right')}
            displayNumber={data.displayNumber}
            showPlusButton={showSourceHandle}
          />
        )}
      </div>
    </div>
  );
};
