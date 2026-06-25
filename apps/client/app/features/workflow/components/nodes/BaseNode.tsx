import { Handle, Position, HandleProps } from '@xyflow/react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import React, { useCallback, useEffect, useRef, useState, useMemo } from 'react';

import { cn } from '@/lib/utils';
import { getNodeDefinitionByType } from '../../config/nodeRegistry';
import { useWorkflowStore } from '../../store/useWorkflowStore';
import { AppNode, BaseNodeData } from '../../types/Nodes';
import {
  NODE_OUTPUT_DRAG_MIME,
  getNodeOutputVariables,
} from '../../utils/nodeVariablePorts';
import { NodeInlinePanel } from './NodeInlinePanel';
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
  const outputPanelRef = useRef<HTMLDivElement>(null);
  const closeOutputPanelTimerRef = useRef<number | null>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });
  const [isNodeHovered, setIsNodeHovered] = useState(false);
  const [isOutputPanelHovered, setIsOutputPanelHovered] = useState(false);
  const [isDraggingOutput, setIsDraggingOutput] = useState(false);
  const node = useWorkflowStore((state) =>
    id ? (state.nodes.find((item) => item.id === id) as AppNode | undefined) : undefined,
  );
  const updateNodeData = useWorkflowStore((state) => state.updateNodeData);
  const definition = getNodeDefinitionByType(node?.type || '');
  const detailsExpanded = Boolean(data.detailsExpanded);
  const outputVariables = useMemo(() => getNodeOutputVariables(node), [node]);

  const categoryLabels = {
    trigger: 'Trigger',
    llm: 'LLM',
    plugin: 'Plugin',
    workflow: 'Workflow',
    logic: 'Logic',
    database: 'Database',
    data: 'Data',
  } as const;
  const categoryLabel = definition
    ? categoryLabels[definition.category]
    : 'Node';
  const description = data.description || definition?.description;
  const isOutputPanelOpen =
    isNodeHovered || isOutputPanelHovered || isDraggingOutput;

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
    const handleMouseMove = (event: MouseEvent) => {
      const panelRect = outputPanelRef.current?.getBoundingClientRect();
      const nodeRect = ref.current?.getBoundingClientRect();
      if (!panelRect || !nodeRect) return;

      const isInsidePanel =
        event.clientX >= panelRect.left &&
        event.clientX <= panelRect.right &&
        event.clientY >= panelRect.top &&
        event.clientY <= panelRect.bottom;
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

      {outputVariables.length > 0 && (
        <div
          ref={outputPanelRef}
          onMouseEnter={() => {
            clearOutputPanelCloseTimer();
            setIsOutputPanelHovered(true);
          }}
          onMouseLeave={scheduleOutputPanelClose}
          className={cn(
            'nodrag absolute bottom-7 left-[calc(100%+12px)] z-40 w-56 transition-opacity duration-150',
            isOutputPanelOpen
              ? 'pointer-events-auto opacity-100'
              : 'pointer-events-none opacity-0',
          )}
        >
          <div className="rounded-lg border border-gray-200 bg-white p-2 shadow-xl">
            <div className="mb-2 px-1 text-[10px] font-semibold uppercase text-gray-400">
              Outputs
            </div>
            <div className="flex max-h-48 flex-col gap-1 overflow-y-auto">
              {outputVariables.map((output) => (
                <div
                  key={`${output.sourceNodeId}-${output.key}`}
                  draggable
                  onDragStart={(event) => {
                    clearOutputPanelCloseTimer();
                    setIsDraggingOutput(true);
                    event.dataTransfer.effectAllowed = 'copy';
                    event.dataTransfer.setData(
                      NODE_OUTPUT_DRAG_MIME,
                      JSON.stringify(output),
                    );
                  }}
                  onDragEnd={() => setIsDraggingOutput(false)}
                  className="cursor-grab rounded-md border border-gray-200 bg-gray-50 px-2 py-1.5 text-xs text-gray-700 shadow-sm active:cursor-grabbing"
                  title={`${output.label} (${output.sourceTitle}.${output.key})`}
                >
                  <div className="truncate font-semibold text-gray-800">
                    {output.label || output.key}
                  </div>
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
              {categoryLabel}
            </div>
            <h3
              className={cn(
                'text-xl font-bold text-gray-900 leading-tight mb-1',
                titleClassName,
              )}
              title={data.title}
            >
              {data.title || 'Untitled Node'}
            </h3>
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

        {detailsExpanded && node && <NodeInlinePanel node={node} />}

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
