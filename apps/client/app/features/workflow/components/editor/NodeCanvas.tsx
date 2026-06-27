'use client';

import { Plus, StickyNote, Play, Trash2, Settings } from 'lucide-react';
import { NodeSelector } from './NodeSelector';
import { LogTab } from './tabs/LogTab';
import { MonitoringTab } from './tabs/MonitoringTab';
import NodeLibrarySidebar from './NodeLibrarySidebar';
import { ViewMode } from './EditorViewSwitcher';
import { calculateAutoLayout } from '../../utils/layoutHelpers';
import { useDeployment } from '../../hooks/useDeployment';
import { useContextMenu } from '../../hooks/useContextMenu';
import { useNodeCreation } from '../../hooks/useNodeCreation';
import { MemoryModeToggle, useMemoryMode } from './memory/MemoryModeControls';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { ClockIcon } from '@/app/features/workflow/components/nodes/icons';
import { DeploymentFlowModal } from '../deployment/DeploymentFlowModal';

import { useCallback, useMemo, useEffect, useState, useRef } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  useReactFlow,
  type Viewport,
  type NodeTypes,
} from '@xyflow/react';

import '@xyflow/react/dist/style.css';

import { useWorkflowStore } from '@/app/features/workflow/store/useWorkflowStore';
import { Node, WorkflowNodeData } from '../../types/Nodes';
import { nodeTypes as coreNodeTypes } from '../nodes';
import { PuzzleEdge } from '../nodes/edges/PuzzleEdge';
import { CustomConnectionLine } from '../nodes/edges/CustomConnectionLine';
import NotePost from './NotePost';
import BottomPanel from './BottomPanel';
import { AppSearchModal } from '../modals/AppSearchModal';
import { useKeyboardShortcut } from '../../hooks/useKeyboardShortcut';
import { useCanvasKeyboardShortcuts } from '../../hooks/useCanvasKeyboardShortcuts';
import { App } from '@/app/features/app/api/appApi';
import { workflowApi } from '@/app/features/workflow/api/workflowApi';
import { useDragConnectionPreview } from '../../hooks/useDragConnectionPreview';
import { DragConnectionOverlay } from './DragConnectionOverlay';
import { SettingsSidebar } from './SettingsSidebar';
import { VersionHistorySidebar } from './VersionHistorySidebar';
import { TestSidebar } from './TestSidebar';
import { NodeFullscreenEditor } from './NodeFullscreenEditor';
import { getSnapBackgroundGap } from '../../utils/gridSnap';

interface NodeCanvasProps {
  viewMode: ViewMode;
  onViewModeChange: (mode: ViewMode) => void;
}

const MIN_ZOOM = 0.4;
const MAX_ZOOM = 1.6;
const DEFAULT_NODE_SIZE = {
  width: 420,
  height: 150,
};

export default function NodeCanvas({
  viewMode,
  onViewModeChange,
}: NodeCanvasProps) {
  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    interactiveMode,
    workflows,
    activeWorkflowId,
    updateWorkflowViewport,
    setNodes,
    updateNodeData,
    addNode,
    isVersionHistoryOpen,
    toggleVersionHistory,
    isFullscreen,
    setEdges,
    isSettingsOpen,
    toggleSettings,
    isTestPanelOpen,
    toggleTestPanel,
    clearInnerNodeSelection,
    selectedInnerNode,
    snapGridSize,
    setSnapTemporarilyDisabled,
    numberConnection,
    updateNumberConnectionInput,
    cancelNumberConnection,
    fullscreenNodeId,
    syncNodeFullscreenFromUrl,
  } = useWorkflowStore();

  const {
    fitView,
    setViewport,
    getViewport,
    screenToFlowPosition,
    deleteElements,
  } = useReactFlow();
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [, setSelectedNodeType] = useState<string | null>(null);
  const [searchModalContext, setSearchModalContext] = useState<{
    isOpen: boolean;
    position?: { x: number; y: number };
  }>({ isOpen: false });
  const [isParamPanelOpen, setIsParamPanelOpen] = useState(false);
  const [isRefPanelOpen, setIsRefPanelOpen] = useState(false);
  const [isNodeLibraryOpen, setIsNodeLibraryOpen] = useState(true);
  const reactFlowWrapperRef = useRef<HTMLDivElement>(null);
  const hoveredNodeIdRef = useRef<string | null>(null);
  const backgroundGap = getSnapBackgroundGap(snapGridSize);
  const numberConnectionCandidates = useMemo(() => {
    if (!numberConnection) return [];
    return nodes
      .filter(
        (node) =>
          node.id !== numberConnection.sourceNodeId &&
          typeof node.data?.displayNumber === 'number',
      )
      .map((node) => ({
        node,
        displayNumber: String(node.data.displayNumber),
      }));
  }, [nodes, numberConnection]);
  const currentNumberMatches = useMemo(() => {
    if (!numberConnection?.input) return [];
    return numberConnectionCandidates.filter((candidate) =>
      candidate.displayNumber.startsWith(numberConnection.input),
    );
  }, [numberConnection?.input, numberConnectionCandidates]);

  const connectNumberTarget = useCallback(
    (targetNodeId: string) => {
      if (!numberConnection) return;
      onConnect({
        source: numberConnection.sourceNodeId,
        sourceHandle: numberConnection.sourceHandleId,
        target: targetNodeId,
        targetHandle: 'target',
      });
    },
    [numberConnection, onConnect],
  );

  // Drag connection preview
  const {
    previewState,
    onDragOver: handleDragOver,
    resetPreview,
  } = useDragConnectionPreview(nodes, edges);

  // Memory mode controls
  const router = useRouter();
  const {
    isMemoryModeEnabled,
    hasProviderKey,
    memoryModeDescription,
    toggleMemoryMode,
    appendMemoryFlag,
    modals: memoryModeModals,
  } = useMemoryMode(router, toast);

  // Publish state
  const canPublish = useWorkflowStore((state) => state.canPublish());

  useEffect(() => {
    if (!numberConnection) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement ||
        (target instanceof HTMLElement && target.isContentEditable)
      ) {
        return;
      }

      if (/^\d$/.test(event.key)) {
        event.preventDefault();
        const nextInput = `${numberConnection.input}${event.key}`;
        const matches = numberConnectionCandidates.filter((candidate) =>
          candidate.displayNumber.startsWith(nextInput),
        );
        const exactMatches = matches.filter(
          (candidate) => candidate.displayNumber === nextInput,
        );
        const prefixMatches = matches.filter(
          (candidate) => candidate.displayNumber !== nextInput,
        );

        if (exactMatches.length === 1 && prefixMatches.length === 0) {
          connectNumberTarget(exactMatches[0].node.id);
          return;
        }

        updateNumberConnectionInput(nextInput);
        return;
      }

      if (event.key === 'Backspace') {
        event.preventDefault();
        updateNumberConnectionInput(numberConnection.input.slice(0, -1));
        return;
      }

      if (event.key === 'Escape') {
        event.preventDefault();
        cancelNumberConnection();
        return;
      }

      if (event.key === 'Enter') {
        event.preventDefault();
        const exactMatches = numberConnectionCandidates.filter(
          (candidate) => candidate.displayNumber === numberConnection.input,
        );
        if (exactMatches.length === 1) {
          connectNumberTarget(exactMatches[0].node.id);
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    cancelNumberConnection,
    connectNumberTarget,
    numberConnection,
    numberConnectionCandidates,
    updateNumberConnectionInput,
  ]);

  // Deployment logic (extracted to hook)
  const {
    showDeployFlowModal,
    setShowDeployFlowModal,
    showDeployDropdown,
    setShowDeployDropdown,
    deploymentType,
    toggleDeployDropdown,
    handlePublishAsRestAPI,
    handlePublishAsWebApp,
    handlePublishAsWidget,
    handlePublishAsWorkflowNode,
    handlePublishAsSchedule,
    handlePublishAsWebhook,
    handleDeploy,
  } = useDeployment({
    nodes,
    isSettingsOpen,
    toggleSettings,
    isVersionHistoryOpen,
    toggleVersionHistory,
    isTestPanelOpen,
    toggleTestPanel,
    setSelectedNodeId,
    setSelectedNodeType,
  });

  // Start node detection for deployment options
  const startNode = useMemo(() => {
    return nodes.find(
      (n) =>
        n.type === 'startNode' ||
        n.type === 'webhookTrigger' ||
        n.type === 'scheduleTrigger',
    );
  }, [nodes]);

  // Context menu hook
  const {
    contextMenu,
    nodeContextMenu,
    edgeContextMenu,
    isContextNodeSelectorOpen,
    contextMenuPos,
    setContextMenu,
    setNodeContextMenu,
    setEdgeContextMenu,
    setIsContextNodeSelectorOpen,
    onPaneContextMenu,
    handleCloseContextMenu,
    handleAddNodeFromContext,
    handleAddMemoFromContext,
    handleTestRunFromContext,
    handleSelectNodeFromContext,
  } = useContextMenu({
    triggerWorkflowRun: useWorkflowStore.getState().triggerWorkflowRun,
    setSearchModalContext,
  });

  // Node creation hook
  const { onDrop, handleAddNodeFromLibrary } = useNodeCreation({
    edges,
    setEdges,
    previewState,
    resetPreview,
    setSearchModalContext,
  });

  // 전체화면 모드 변경 시 사이드바 자동 토글
  // 전체화면 모드 변경 시 사이드바 자동 토글
  useEffect(() => {
    if (isFullscreen || viewMode !== 'edit') {
      setIsNodeLibraryOpen(false);
    } else {
      setIsNodeLibraryOpen(true);
    }
  }, [isFullscreen, viewMode]);

  useEffect(() => {
    if (viewMode !== 'edit' || !reactFlowWrapperRef.current) {
      setSnapTemporarilyDisabled(false);
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Alt') {
        setSnapTemporarilyDisabled(true);
      }
    };
    const handleKeyUp = (event: KeyboardEvent) => {
      if (event.key === 'Alt') {
        setSnapTemporarilyDisabled(false);
      }
    };
    const handleBlur = () => setSnapTemporarilyDisabled(false);

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);
    window.addEventListener('blur', handleBlur);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
      window.removeEventListener('blur', handleBlur);
      setSnapTemporarilyDisabled(false);
    };
  }, [setSnapTemporarilyDisabled, viewMode]);

  useKeyboardShortcut(
    ['Meta', 'k'],
    () => {
      setSearchModalContext({ isOpen: true });
    },
    { preventDefault: true },
  );

  // 설정, 버전 기록, 테스트 패널이 열리면 노드 상세 패널과 배포 드롭다운 닫기
  useEffect(() => {
    if (isSettingsOpen || isVersionHistoryOpen || isTestPanelOpen) {
      setSelectedNodeId(null);
      setSelectedNodeType(null);
      setIsParamPanelOpen(false);
      setIsRefPanelOpen(false);
      setShowDeployDropdown(false);
    }
  }, [
    isSettingsOpen,
    isVersionHistoryOpen,
    isTestPanelOpen,
    setShowDeployDropdown,
  ]);

  const handleSelectApp = useCallback(
    async (app: App & { active_deployment_id?: string; version?: number }) => {
      const baseNode: Node = {
        id: `workflow-${Date.now()}`,
        type: 'workflowNode',
        position:
          searchModalContext.position ||
          screenToFlowPosition({
            x: window.innerWidth / 2,
            y: window.innerHeight / 2,
          }),
        data: {
          title: app.name,
          name: app.name,
          workflowId: app.workflow_id || '',
          appId: app.id,
          icon: app.icon?.content || '⚡️',
          description: app.description || '설명 없음',
          status: 'idle',
          version: app.version || 0,
          deployment_id: app.active_deployment_id,
          expanded: false,
          outputs: [],
        } as WorkflowNodeData,
      };
      const newNode = addNode(baseNode);
      setSearchModalContext({ isOpen: false });

      if (app.active_deployment_id) {
        try {
          const deployment = await workflowApi.getDeployment(
            app.active_deployment_id,
          );
          const outputKeys =
            deployment.output_schema?.outputs?.map(
              (o: { variable: string }) => o.variable,
            ) || [];
          updateNodeData(newNode.id, { outputs: outputKeys });
        } catch {
          // Failed to load workflow outputs
        }
      }
    },
    [
      screenToFlowPosition,
      updateNodeData,
      searchModalContext.position,
      addNode,
    ],
  );

  const nodeTypes = useMemo(
    () => ({
      ...coreNodeTypes,
      note: NotePost,
    }),
    [],
  ) as unknown as NodeTypes;

  const edgeTypes = useMemo(() => ({ puzzle: PuzzleEdge }), []);
  const defaultEdgeOptions = useMemo(
    () => ({
      type: 'puzzle',
      style: { strokeWidth: 10, stroke: '#d1d5db' },
      animated: false,
    }),
    [],
  );

  const prevActiveWorkflowId = useRef(activeWorkflowId);

  useEffect(() => {
    const activeWorkflow = workflows.find((w) => w.id === activeWorkflowId);

    if (prevActiveWorkflowId.current !== activeWorkflowId) {
      if (activeWorkflow?.viewport) {
        setViewport(activeWorkflow.viewport);
      }
      prevActiveWorkflowId.current = activeWorkflowId;
    }
  }, [activeWorkflowId, workflows, setViewport]);

  const handleMoveEnd = useCallback(
    (_event: unknown, viewport: Viewport) => {
      updateWorkflowViewport(activeWorkflowId, viewport);
    },
    [activeWorkflowId, updateWorkflowViewport],
  );

  const handleNodeMouseEnter = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      hoveredNodeIdRef.current = node.id;
    },
    [],
  );

  const handleNodeMouseLeave = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      if (hoveredNodeIdRef.current === node.id) {
        hoveredNodeIdRef.current = null;
      }
    },
    [],
  );

  const handleNodeWheelZoom = useCallback(
    (event: React.WheelEvent<HTMLDivElement>) => {
      const hoveredNodeId = hoveredNodeIdRef.current;
      if (!hoveredNodeId) return;

      const target = event.target as HTMLElement | null;
      if (
        target?.closest(
          'input, textarea, select, [contenteditable="true"], .nowheel',
        )
      ) {
        return;
      }

      const hoveredNode = nodes.find((node) => node.id === hoveredNodeId);
      if (!hoveredNode) return;

      event.preventDefault();
      event.stopPropagation();

      const viewport = getViewport();
      const measuredNode = hoveredNode as Node & {
        measured?: { width?: number; height?: number };
        width?: number;
        height?: number;
      };
      const nodeWidth =
        measuredNode.measured?.width ??
        measuredNode.width ??
        DEFAULT_NODE_SIZE.width;
      const nodeHeight =
        measuredNode.measured?.height ??
        measuredNode.height ??
        DEFAULT_NODE_SIZE.height;
      const nodeCenter = {
        x: hoveredNode.position.x + nodeWidth / 2,
        y: hoveredNode.position.y + nodeHeight / 2,
      };
      const screenCenter = {
        x: nodeCenter.x * viewport.zoom + viewport.x,
        y: nodeCenter.y * viewport.zoom + viewport.y,
      };
      const zoomFactor = Math.exp(-event.deltaY * 0.0015);
      const nextZoom = Math.min(
        MAX_ZOOM,
        Math.max(MIN_ZOOM, viewport.zoom * zoomFactor),
      );

      if (nextZoom === viewport.zoom) return;

      const nextViewport = {
        x: screenCenter.x - nodeCenter.x * nextZoom,
        y: screenCenter.y - nodeCenter.y * nextZoom,
        zoom: nextZoom,
      };

      setViewport(nextViewport, { duration: 80 });
      updateWorkflowViewport(activeWorkflowId, nextViewport);
    },
    [activeWorkflowId, getViewport, nodes, setViewport, updateWorkflowViewport],
  );

  useEffect(() => {
    if (isVersionHistoryOpen || isSettingsOpen) {
      setSelectedNodeId(null);
      setSelectedNodeType(null);
      setIsParamPanelOpen(false);
    }
  }, [isVersionHistoryOpen, isSettingsOpen]);

  const handleNodeClick = useCallback(
    (event: React.MouseEvent, node: Node) => {
      if (node.type && node.type !== 'note') {
        if (isVersionHistoryOpen) {
          toggleVersionHistory();
        }
        if (isSettingsOpen) {
          toggleSettings();
        }
        if (isTestPanelOpen) {
          toggleTestPanel();
        }

        // 메인 노드 클릭 시 내부 노드 선택 해제
        clearInnerNodeSelection();
        setSelectedNodeId(null);
        setSelectedNodeType(null);
        setIsParamPanelOpen(false);
        setIsRefPanelOpen(false);
      }
    },
    [
      isVersionHistoryOpen,
      toggleVersionHistory,
      isSettingsOpen,
      toggleSettings,
      isTestPanelOpen,
      toggleTestPanel,
      clearInnerNodeSelection,
    ],
  );

  const handleClosePanel = useCallback(() => {
    setSelectedNodeId(null);
    setSelectedNodeType(null);
    setIsParamPanelOpen(false);
    setIsRefPanelOpen(false);
  }, []);

  const closeCanvasMenus = useCallback(() => {
    if (searchModalContext.isOpen) {
      setSearchModalContext({ isOpen: false });
      return true;
    }
    if (showDeployDropdown) {
      setShowDeployDropdown(false);
      return true;
    }
    if (
      contextMenu ||
      nodeContextMenu ||
      edgeContextMenu ||
      isContextNodeSelectorOpen
    ) {
      handleCloseContextMenu();
      setIsContextNodeSelectorOpen(false);
      return true;
    }
    return false;
  }, [
    searchModalContext.isOpen,
    showDeployDropdown,
    setShowDeployDropdown,
    contextMenu,
    nodeContextMenu,
    edgeContextMenu,
    isContextNodeSelectorOpen,
    handleCloseContextMenu,
    setIsContextNodeSelectorOpen,
  ]);

  const closeCanvasPanels = useCallback(() => {
    if (isParamPanelOpen || isRefPanelOpen || selectedNodeId) {
      handleClosePanel();
      return true;
    }
    if (selectedInnerNode) {
      clearInnerNodeSelection();
      return true;
    }
    if (isSettingsOpen) {
      toggleSettings();
      return true;
    }
    if (isVersionHistoryOpen) {
      toggleVersionHistory();
      return true;
    }
    if (isTestPanelOpen) {
      toggleTestPanel();
      return true;
    }
    return false;
  }, [
    isParamPanelOpen,
    isRefPanelOpen,
    selectedNodeId,
    handleClosePanel,
    selectedInnerNode,
    clearInnerNodeSelection,
    isSettingsOpen,
    toggleSettings,
    isVersionHistoryOpen,
    toggleVersionHistory,
    isTestPanelOpen,
    toggleTestPanel,
  ]);

  const isCanvasShortcutScopeBlocked = useCallback(
    () =>
      searchModalContext.isOpen ||
      showDeployFlowModal ||
      showDeployDropdown ||
      Boolean(
        contextMenu ||
        nodeContextMenu ||
        edgeContextMenu ||
        isContextNodeSelectorOpen,
      ),
    [
      searchModalContext.isOpen,
      showDeployFlowModal,
      showDeployDropdown,
      contextMenu,
      nodeContextMenu,
      edgeContextMenu,
      isContextNodeSelectorOpen,
    ],
  );

  useCanvasKeyboardShortcuts({
    isEnabled: viewMode === 'edit',
    isShortcutScopeBlocked: isCanvasShortcutScopeBlocked,
    closeMenus: closeCanvasMenus,
    closePanels: closeCanvasPanels,
    toggleNodeLibrary: () => setIsNodeLibraryOpen((prev) => !prev),
  });

  const reactFlowConfig = useMemo(() => {
    if (interactiveMode === 'touchpad') {
      return {
        panOnDrag: [1, 2],
        panOnScroll: true,
        zoomOnScroll: false,
        zoomOnPinch: true,
        selectionOnDrag: true,
        connectionRadius: 50,
      };
    } else {
      return {
        panOnDrag: true,
        panOnScroll: false,
        zoomOnScroll: true,
        zoomOnPinch: true,
        selectionOnDrag: false,
        connectionRadius: 50,
      };
    }
  }, [interactiveMode]);

  const handleAutoLayout = useCallback(() => {
    const layoutedNodes = calculateAutoLayout(nodes, edges);
    setNodes(layoutedNodes);

    setTimeout(() => {
      fitView({ padding: 0.2, duration: 300 });
      const viewport = getViewport();
      updateWorkflowViewport(activeWorkflowId, viewport);
    }, 100);
  }, [
    nodes,
    edges,
    setNodes,
    fitView,
    getViewport,
    updateWorkflowViewport,
    activeWorkflowId,
  ]);

  const currentAppId = useMemo(() => {
    const activeWorkflow = workflows.find((w) => w.id === activeWorkflowId);
    return activeWorkflow?.appId;
  }, [workflows, activeWorkflowId]);

  // 노드 우클릭 핸들러
  const onNodeContextMenu = useCallback(
    (event: React.MouseEvent, node: Node) => {
      event.preventDefault();
      event.stopPropagation();
      setNodeContextMenu({
        x: event.clientX,
        y: event.clientY,
        nodeId: node.id,
      });
      setEdgeContextMenu(null);
      setContextMenu(null);
    },
    [],
  );

  // Edge 우클릭 핸들러
  const onEdgeContextMenu = useCallback(
    (event: React.MouseEvent, edge: { id: string }) => {
      event.preventDefault();
      event.stopPropagation();
      setEdgeContextMenu({
        x: event.clientX,
        y: event.clientY,
        edgeId: edge.id,
      });
      setNodeContextMenu(null);
      setContextMenu(null);
    },
    [],
  );

  // 노드 삭제 핸들러 (React Flow 내부 로직 사용)
  const handleDeleteNode = useCallback(() => {
    if (!nodeContextMenu) return;
    deleteElements({ nodes: [{ id: nodeContextMenu.nodeId }] });
    setNodeContextMenu(null);
  }, [nodeContextMenu, deleteElements]);

  // Edge 삭제 핸들러 (React Flow 내부 로직 사용)
  const handleDeleteEdge = useCallback(() => {
    if (!edgeContextMenu) return;
    deleteElements({ edges: [{ id: edgeContextMenu.edgeId }] });
    setEdgeContextMenu(null);
  }, [edgeContextMenu, deleteElements]);

  useEffect(() => {
    const handleClick = () => handleCloseContextMenu();
    window.addEventListener('click', handleClick);
    return () => window.removeEventListener('click', handleClick);
  }, [handleCloseContextMenu]);

  // [NEW] 탭 상태 (Deleted internal logic)
  const [initialLogRunId, setInitialLogRunId] = useState<string | null>(null);
  const searchParams = useSearchParams();
  const ndvNodeParam = searchParams.get('node');
  // const tabParam = searchParams.get('tab'); // Moved to parent
  const runIdParam = searchParams.get('runId');

  // useEffect for tabParam removed

  useEffect(() => {
    const currentNodeParam =
      typeof window !== 'undefined'
        ? new URLSearchParams(window.location.search).get('node')
        : ndvNodeParam;

    if (!currentNodeParam) {
      if (fullscreenNodeId) {
        syncNodeFullscreenFromUrl(null);
      }
      return;
    }

    const hasTargetNode = nodes.some((node) => node.id === currentNodeParam);
    if (hasTargetNode && fullscreenNodeId !== currentNodeParam) {
      syncNodeFullscreenFromUrl(currentNodeParam);
    }
  }, [fullscreenNodeId, ndvNodeParam, nodes, syncNodeFullscreenFromUrl]);

  useEffect(() => {
    const handlePopState = () => {
      const nodeId = new URLSearchParams(window.location.search).get('node');
      if (!nodeId) {
        syncNodeFullscreenFromUrl(null);
        return;
      }

      if (nodes.some((node) => node.id === nodeId)) {
        syncNodeFullscreenFromUrl(nodeId);
      }
    };

    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, [nodes, syncNodeFullscreenFromUrl]);

  useEffect(() => {
    if (runIdParam) {
      setInitialLogRunId(runIdParam);
    }
  }, [runIdParam]);

  return (
    <div className="relative flex flex-1 flex-col overflow-hidden bg-slate-50 p-3">
      {/* Main Content Area Container */}
      <div className="flex h-full flex-1 flex-col overflow-hidden rounded-lg border border-slate-200 bg-slate-100">
        {/* Tab Header Removed */}

        {/* Content Area */}
        <div className="flex-1 relative overflow-hidden">
          {/* 1. Editor Tab Content */}
          <div
            className={`w-full h-full relative flex flex-row gap-2 ${
              viewMode === 'edit' ? 'flex' : 'hidden'
            }`}
          >
            {/* Node Library Sidebar */}
            <div className="flex h-full flex-col py-3 pl-3">
              <div
                className={`z-20 flex-1 rounded-lg bg-white transition-all duration-300 ease-in-out ${
                  isNodeLibraryOpen
                    ? 'w-64 border border-slate-200 shadow-sm'
                    : 'w-0 border-none'
                }`}
              >
                <NodeLibrarySidebar
                  isOpen={isNodeLibraryOpen}
                  onToggle={() => setIsNodeLibraryOpen(!isNodeLibraryOpen)}
                  onAddNode={handleAddNodeFromLibrary}
                  onOpenAppSearch={() =>
                    setSearchModalContext({ isOpen: true })
                  }
                />
              </div>
            </div>

            {/* Editor Canvas Container */}
            <div className="flex-1 h-full relative flex flex-col overflow-hidden">
              {/* App Search Modal */}
              <AppSearchModal
                isOpen={searchModalContext.isOpen}
                onClose={() => setSearchModalContext({ isOpen: false })}
                onSelect={handleSelectApp}
                excludedAppId={currentAppId}
              />

              {/* ReactFlow 캔버스 */}
              <div
                ref={reactFlowWrapperRef}
                className="w-full h-full relative"
                onContextMenu={(e) => e.preventDefault()}
                onDragOver={handleDragOver}
                onDrop={onDrop}
                onWheelCapture={handleNodeWheelZoom}
              >
                <ReactFlow
                  nodes={nodes}
                  edges={edges}
                  onNodesChange={onNodesChange}
                  onEdgesChange={onEdgesChange}
                  onConnect={onConnect}
                  onMoveEnd={handleMoveEnd}
                  onNodeClick={handleNodeClick}
                  onNodeMouseEnter={handleNodeMouseEnter}
                  onNodeMouseLeave={handleNodeMouseLeave}
                  onPaneContextMenu={onPaneContextMenu}
                  onNodeContextMenu={onNodeContextMenu}
                  onEdgeContextMenu={onEdgeContextMenu}
                  nodeTypes={nodeTypes}
                  edgeTypes={edgeTypes}
                  defaultEdgeOptions={defaultEdgeOptions}
                  connectionLineComponent={CustomConnectionLine}
                  defaultViewport={{ x: 0, y: 0, zoom: 0.8 }}
                  minZoom={MIN_ZOOM}
                  maxZoom={MAX_ZOOM}
                  attributionPosition="bottom-right"
                  className="bg-slate-50"
                  {...reactFlowConfig}
                >
                  <Background
                    variant={BackgroundVariant.Dots}
                    gap={backgroundGap}
                    size={1}
                    color="#cbd5e1"
                  />
                </ReactFlow>

                {numberConnection && (
                  <div className="pointer-events-none absolute left-1/2 top-4 z-40 flex -translate-x-1/2 flex-col items-center gap-1">
                    <div className="rounded-lg border border-blue-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-lg">
                      <span className="text-blue-700">연결할 노드 번호</span>
                      <span className="ml-2 inline-flex min-w-8 items-center justify-center rounded-md bg-blue-50 px-2 py-0.5 font-bold tabular-nums text-blue-700">
                        {numberConnection.input || '-'}
                      </span>
                      <span className="ml-2 text-slate-400">
                        숫자 입력 · Enter 확정 · Esc 취소
                      </span>
                    </div>
                    {numberConnection.input && (
                      <div className="rounded-md border border-slate-200 bg-white/95 px-2 py-1 text-[11px] font-medium text-slate-500 shadow-sm">
                        후보 {currentNumberMatches.length}개
                      </div>
                    )}
                  </div>
                )}

                {/* Drag connection preview overlay */}
                <DragConnectionOverlay
                  nearestNode={previewState.nearestNode}
                  draggedNodePosition={previewState.draggedNodePosition}
                  isRight={previewState.isRight}
                />

                {/* Right: Action Buttons */}
                <div className="absolute top-4 right-4 flex items-center gap-2 z-30">
                  {/* Group: Memory | Settings | Version | Publish */}
                  <div className="flex h-9 items-center rounded-lg border border-slate-200 bg-white p-0.5 shadow-sm">
                    <div className="h-full flex items-center px-2">
                      <MemoryModeToggle
                        isEnabled={isMemoryModeEnabled}
                        hasProviderKey={hasProviderKey}
                        description={memoryModeDescription}
                        onToggle={toggleMemoryMode}
                      />
                    </div>
                    <div className="mx-1 h-4 w-px bg-slate-200" />
                    <button
                      onClick={toggleSettings}
                      className="flex h-full items-center gap-1.5 rounded-md px-3 text-[13px] font-semibold text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-950"
                    >
                      <Settings className="w-4 h-4" />
                      <span>설정</span>
                    </button>
                    <div className="mx-1 h-4 w-px bg-slate-200" />
                    <button
                      onClick={toggleVersionHistory}
                      className="flex h-full items-center gap-1.5 rounded-md px-3 text-[13px] font-semibold text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-950"
                    >
                      <ClockIcon className="w-4 h-4" />
                      <span>버전</span>
                    </button>
                    <div className="mx-1 h-4 w-px bg-slate-200" />
                    {/* Publish Button (Inside Group) */}
                    <div className="relative h-full">
                      <button
                        disabled={!canPublish}
                        onClick={toggleDeployDropdown}
                        className={`h-full px-3 flex items-center gap-1.5 rounded-md transition-colors text-[13px] font-medium ${
                          !canPublish
                            ? 'text-gray-400 cursor-not-allowed'
                            : 'hover:bg-slate-100 text-slate-600 hover:text-slate-950'
                        }`}
                      >
                        <span>게시하기</span>
                        <svg
                          className={`w-3.5 h-3.5 transition-transform ${
                            showDeployDropdown ? 'rotate-180' : ''
                          }`}
                          fill="none"
                          stroke="currentColor"
                          viewBox="0 0 24 24"
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M19 9l-7 7-7-7"
                          />
                        </svg>
                      </button>

                      {/* Deployment Dropdown Menu */}
                      {showDeployDropdown && canPublish && (
                        <>
                          <div
                            className="fixed inset-0 z-10"
                            onClick={() => setShowDeployDropdown(false)}
                          />
                          <div className="absolute right-0 z-20 mt-2 w-64 rounded-lg border border-slate-200 bg-white py-2 text-left shadow-lg">
                            {/* Webhook Trigger Deployment */}
                            {startNode?.type === 'webhookTrigger' && (
                              <button
                                onClick={handlePublishAsWebhook}
                                className="w-full px-4 py-3 text-left hover:bg-gray-50 transition-colors"
                              >
                                <div className="font-medium text-gray-900">
                                  웹훅으로 개시하기
                                </div>
                                <div className="text-sm text-gray-500 mt-1">
                                  URL 호출로 실행
                                </div>
                              </button>
                            )}

                            {/* Schedule Trigger Deployment */}
                            {startNode?.type === 'scheduleTrigger' && (
                              <button
                                onClick={handlePublishAsSchedule}
                                className="w-full px-4 py-3 text-left hover:bg-gray-50 transition-colors"
                              >
                                <div className="font-medium text-gray-900">
                                  알람으로 개시하기
                                </div>
                                <div className="text-sm text-gray-500 mt-1">
                                  설정된 주기에 따라 실행
                                </div>
                              </button>
                            )}

                            {/* Standard Start Node Deployment Options */}
                            {(startNode?.type === 'startNode' ||
                              !startNode) && (
                              <>
                                <button
                                  onClick={handlePublishAsRestAPI}
                                  className="w-full px-4 py-3 text-left hover:bg-gray-50 transition-colors"
                                >
                                  <div className="font-medium text-gray-900">
                                    REST API로 배포
                                  </div>
                                  <div className="text-sm text-gray-500 mt-1">
                                    내 서비스나 백엔드 서버에서 호출
                                  </div>
                                </button>
                                <div className="border-t border-gray-100 my-1" />
                                <button
                                  onClick={handlePublishAsWebApp}
                                  className="w-full px-4 py-3 text-left hover:bg-gray-50 transition-colors"
                                >
                                  <div className="font-medium text-gray-900">
                                    공개 웹페이지 생성
                                  </div>
                                  <div className="text-sm text-gray-500 mt-1">
                                    설치 없이 바로 쓸 수 있는 페이지 제공
                                  </div>
                                </button>
                                <div className="border-t border-gray-100 my-1" />
                                <button
                                  onClick={handlePublishAsWidget}
                                  className="w-full px-4 py-3 text-left hover:bg-gray-50 transition-colors"
                                >
                                  <div className="font-medium text-gray-900">
                                    사이트에 임베드
                                  </div>
                                  <div className="text-sm text-gray-500 mt-1">
                                    스크립트 코드로 내 웹사이트에 삽입
                                  </div>
                                </button>
                                <div className="border-t border-gray-100 my-1" />
                                <button
                                  onClick={handlePublishAsWorkflowNode}
                                  className="w-full px-4 py-3 text-left hover:bg-gray-50 transition-colors"
                                >
                                  <div className="font-medium text-gray-900">
                                    서브 모듈로 배포
                                  </div>
                                  <div className="text-sm text-gray-500 mt-1">
                                    다른 모듈에서 재사용
                                  </div>
                                </button>
                              </>
                            )}
                          </div>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Standalone: Test Button (Primary) */}
                  <button
                    onClick={toggleTestPanel}
                    className="flex h-9 items-center gap-1.5 rounded-lg bg-slate-950 px-4 text-[13px] font-semibold text-white shadow-sm transition-colors hover:bg-slate-800"
                  >
                    <Play className="w-3.5 h-3.5 fill-current" />
                    테스트
                  </button>
                </div>

                {/* 플로팅 하단 패널 */}
                <BottomPanel
                  onCenterNodes={handleAutoLayout}
                  isPanelOpen={false}
                  onOpenAppSearch={() =>
                    setSearchModalContext({ isOpen: true })
                  }
                />

                {/* Context Menu UI */}
                {contextMenu && (
                  <div
                    className="fixed z-50 bg-white rounded-lg shadow-xl border border-gray-200 py-1 min-w-[180px]"
                    style={{ top: contextMenu.y, left: contextMenu.x }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <button
                      onClick={handleAddNodeFromContext}
                      className="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2"
                    >
                      <Plus className="w-4 h-4 text-gray-500" />
                      노드 추가
                    </button>
                    <button
                      onClick={handleAddMemoFromContext}
                      className="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2"
                    >
                      <StickyNote className="w-4 h-4 text-gray-500" />
                      메모 추가
                    </button>
                    <div className="my-1 border-t border-gray-100" />
                    <button
                      onClick={handleTestRunFromContext}
                      className="w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2"
                    >
                      <Play className="w-4 h-4 text-gray-500" />
                      테스트 실행
                    </button>
                  </div>
                )}

                {/* 노드 우클릭 삭제 메뉴 */}
                {nodeContextMenu && (
                  <div
                    className="fixed z-50 bg-white rounded-lg shadow-xl border border-gray-200 py-1 min-w-[140px]"
                    style={{ top: nodeContextMenu.y, left: nodeContextMenu.x }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <button
                      onClick={handleDeleteNode}
                      className="w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50 flex items-center gap-2"
                    >
                      <Trash2 className="w-4 h-4" />
                      노드 삭제
                    </button>
                  </div>
                )}

                {/* Edge 우클릭 삭제 메뉴 */}
                {edgeContextMenu && (
                  <div
                    className="fixed z-50 bg-white rounded-lg shadow-xl border border-gray-200 py-1 min-w-[140px]"
                    style={{ top: edgeContextMenu.y, left: edgeContextMenu.x }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <button
                      onClick={handleDeleteEdge}
                      className="w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50 flex items-center gap-2"
                    >
                      <Trash2 className="w-4 h-4" />
                      연결선 삭제
                    </button>
                  </div>
                )}

                {/* Context Menu Node Selector Modal */}
                {isContextNodeSelectorOpen && (
                  <div
                    className="fixed z-50"
                    style={{
                      left: contextMenuPos.x,
                      top:
                        typeof window !== 'undefined' &&
                        window.innerHeight - contextMenuPos.y < 420
                          ? 'auto'
                          : contextMenuPos.y,
                      bottom:
                        typeof window !== 'undefined' &&
                        window.innerHeight - contextMenuPos.y < 420
                          ? window.innerHeight - contextMenuPos.y
                          : 'auto',
                    }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <NodeSelector onSelect={handleSelectNodeFromContext} />
                  </div>
                )}

                {/* Close Node Selector when clicking outside (overlay) */}
                {isContextNodeSelectorOpen && (
                  <div
                    className="fixed inset-0 z-40"
                    onClick={() => setIsContextNodeSelectorOpen(false)}
                  />
                )}
              </div>
            </div>
          </div>

          {/* 2. Logs Tab Content */}
          {viewMode === 'log' && (
            <LogTab
              workflowId={String(activeWorkflowId)}
              initialRunId={initialLogRunId}
            />
          )}

          {/* 3. Monitoring Tab Content */}
          {viewMode === 'monitoring' && (
            <MonitoringTab
              workflowId={String(activeWorkflowId)}
              onNavigateToLog={(runId) => {
                setInitialLogRunId(runId);
                onViewModeChange('log');
              }}
            />
          )}
        </div>
      </div>
      {/* Sidebars */}
      <SettingsSidebar />
      <VersionHistorySidebar />
      <TestSidebar appendMemoryFlag={appendMemoryFlag} />

      {/* 노드 전체화면 설정(NDV) */}
      <NodeFullscreenEditor />

      {/* Deployment Flow Modal */}
      <DeploymentFlowModal
        isOpen={showDeployFlowModal}
        onClose={() => setShowDeployFlowModal(false)}
        deploymentType={deploymentType}
        onDeploy={handleDeploy}
      />

      {/* Memory Mode Modals */}
      {memoryModeModals}
    </div>
  );
}
