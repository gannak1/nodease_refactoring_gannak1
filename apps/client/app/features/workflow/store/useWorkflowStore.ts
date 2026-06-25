import { App, AppIcon } from '../../app/api/appApi';
import {
  Connection,
  Edge,
  EdgeChange,
  NodeChange,
  addEdge,
  applyNodeChanges,
  applyEdgeChanges,
  OnNodesChange,
  OnEdgesChange,
  OnConnect,
} from '@xyflow/react';
import {
  Features,
  EnvVariable,
  RuntimeVariable,
  Node,
} from '../types/Workflow';
import { DeploymentResponse } from '../types/Deployment';

import { create } from 'zustand';
import { DEFAULT_NODES } from '../constants';
import { workflowApi } from '../api/workflowApi';

export interface Workflow {
  id: string;
  appId: string;
  nodes: Node[];
  edges: Edge[];
  viewport?: {
    x: number;
    y: number;
    zoom: number;
  };
}

type WorkflowState = {
  // === Editor UI 상태 (editorStore에서 유래) ===
  workflows: Workflow[];
  activeWorkflowId: string;

  projectName: string;
  projectIcon: AppIcon;
  projectDescription: string;
  projectApp: App | null; // Full app object for editing
  interactiveMode: 'mouse' | 'touchpad'; // 입력 모드 (마우스/터치패드)
  isFullscreen: boolean;

  // === 설정 패널 상태 ===
  isSettingsOpen: boolean;
  toggleSettings: () => void;

  // === 버전 기록 상태 ===
  isVersionHistoryOpen: boolean;
  previewingVersion: DeploymentResponse | null;
  lastDeployedAt: Date | null; // 배포 완료 시점 (리스트 갱신 트리거)

  // === 테스트 패널 상태 ===
  isTestPanelOpen: boolean;
  toggleTestPanel: () => void;

  // === 그래프 데이터 (ReactFlow) ===
  nodes: Node[];
  edges: Edge[];

  // === 추가 필드 (API 동기화용) ===
  features: Features; // 워크플로우 기능 설정
  envVariables: EnvVariable[]; // 환경 변수
  runtimeVariables: RuntimeVariable[]; // 런타임 변수

  // === ReactFlow 액션 ===
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: OnConnect;
  setNodes: (nodes: Node[]) => void;
  setEdges: (edges: Edge[]) => void;
  undo: () => void;
  redo: () => void;
  copySelectedNodes: () => void;
  pasteCopiedNodes: () => void;
  duplicateSelectedNodes: () => void;
  hasSelectedElements: () => boolean;
  deleteSelectedElements: () => void;
  clearSelection: () => void;

  // === Inner Node Selection (for Loop/Workflow nodes) ===
  selectedInnerNode: { parentNodeId: string; nodeId: string } | null;
  setSelectedInnerNode: (parentNodeId: string, nodeId: string) => void;
  clearInnerNodeSelection: () => void;
  updateInnerNodeData: (
    parentNodeId: string,
    nodeId: string,
    newData: Record<string, unknown>,
  ) => void;

  // === Editor UI 액션 ===
  toggleVersionHistory: () => void;
  previewVersion: (version: DeploymentResponse) => void;
  exitPreview: () => void;
  restoreVersion: (version: DeploymentResponse) => Promise<void>;
  notifyDeploymentComplete: () => void; // 배포 완료 알림

  // === Remote Execution Trigger ===
  runTrigger: number;
  triggerWorkflowRun: () => void;

  // === Editor UI 액션 ===

  setProjectInfo: (name: string, icon: AppIcon, description?: string) => void;
  setProjectApp: (app: App) => void;
  setInteractiveMode: (mode: 'mouse' | 'touchpad') => void;
  toggleFullscreen: () => void;
  addWorkflow: (
    workflow: Omit<Workflow, 'id'>,
    appId: string,
  ) => Promise<string>;
  loadWorkflowsByApp: (appId: string) => Promise<void>;
  setActiveWorkflow: (id: string) => void;
  setActiveWorkflowIdSafe: (id: string) => void;
  deleteWorkflow: (id: string) => void;
  updateWorkflowViewport: (
    id: string,
    viewport: { x: number; y: number; zoom: number },
  ) => void;

  // === 시작노드 검증 핼퍼 ===
  getStartNodeType: () =>
    | 'startNode'
    | 'webhookTrigger'
    | 'scheduleTrigger'
    | null;
  getStartNodeCount: () => number;
  canPublish: () => boolean;

  // === API 동기화 액션 ===
  setFeatures: (features: Features) => void;
  setEnvVariables: (vars: EnvVariable[]) => void;
  setRuntimeVariables: (vars: RuntimeVariable[]) => void;
  updateNodeData: (nodeId: string, newData: Record<string, unknown>) => void;
  setWorkflowData: (
    data: {
      nodes: Node[];
      edges: Edge[];
      viewport: { x: number; y: number; zoom: number };
      features?: Features;
      envVariables?: EnvVariable[];
      runtimeVariables?: RuntimeVariable[];
    },
    workflowId?: string,
  ) => void;
};

type GraphSnapshot = {
  nodes: Node[];
  edges: Edge[];
};

const HISTORY_LIMIT = 50;
const PASTE_OFFSET = 40;

const cloneGraph = (nodes: Node[], edges: Edge[]): GraphSnapshot => ({
  nodes: structuredClone(nodes),
  edges: structuredClone(edges),
});

const syncActiveWorkflow = (
  workflows: Workflow[],
  activeWorkflowId: string,
  nodes: Node[],
  edges: Edge[],
) =>
  workflows.map((workflow) =>
    workflow.id === activeWorkflowId ? { ...workflow, nodes, edges } : workflow,
  );

const shouldRecordEdgeChanges = (changes: EdgeChange[]) =>
  changes.some((change) => change.type !== 'select');

const isDraggingPositionChange = (change: NodeChange) =>
  change.type === 'position' && 'dragging' in change && change.dragging === true;

const shouldRecordCompletedNodeChanges = (changes: NodeChange[]) =>
  changes.some(
    (change) => change.type !== 'select' && !isDraggingPositionChange(change),
  );

const REFERENCE_FIELD_KEYS = new Set([
  'value_selector',
  'variable_selector',
  'source_selector',
  'target_selector',
]);

const remapSelectorValue = (
  value: unknown,
  idMap: Map<string, string>,
): unknown => {
  if (typeof value === 'string') {
    return idMap.get(value) || value;
  }
  if (Array.isArray(value)) {
    return value.map((item, index) =>
      index === 0 ? remapSelectorValue(item, idMap) : item,
    );
  }
  return value;
};

const remapCodeInputSource = (source: string, idMap: Map<string, string>) => {
  const separatorIndex = source.indexOf('.');
  if (separatorIndex <= 0) return source;

  const nodeId = source.slice(0, separatorIndex);
  const remappedNodeId = idMap.get(nodeId);
  if (!remappedNodeId) return source;

  return `${remappedNodeId}${source.slice(separatorIndex)}`;
};

const remapInputsArray = (
  inputs: unknown[],
  idMap: Map<string, string>,
): unknown[] =>
  inputs.map((input) => {
    if (!input || typeof input !== 'object') {
      return remapCopiedNodeReferences(input, idMap);
    }

    return Object.fromEntries(
      Object.entries(input).map(([key, item]) => [
        key,
        key === 'source' && typeof item === 'string'
          ? remapCodeInputSource(item, idMap)
          : remapCopiedNodeReferences(item, idMap),
      ]),
    );
  });

const remapCopiedNodeReferences = (
  value: unknown,
  idMap: Map<string, string>,
): unknown => {
  if (typeof value === 'string') {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((item) =>
      remapCopiedNodeReferences(item, idMap),
    );
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        REFERENCE_FIELD_KEYS.has(key)
          ? remapSelectorValue(item, idMap)
          : key === 'inputs' && Array.isArray(item)
            ? remapInputsArray(item, idMap)
          : remapCopiedNodeReferences(item, idMap),
      ]),
    );
  }
  return value;
};

const preparePastedNodeData = (
  data: Node['data'],
  idMap: Map<string, string>,
): Node['data'] => {
  const remappedData = remapCopiedNodeReferences(data, idMap) as Node['data'] & {
    displayNumber?: unknown;
  };
  delete remappedData.displayNumber;
  return remappedData;
};

const getInternalEdges = (edges: Edge[], nodeIds: Set<string>) =>
  edges.filter(
    (edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target),
  );

const buildDuplicatedGraphElements = (
  sourceNodes: Node[],
  sourceEdges: Edge[],
) => {
  const idMap = new Map<string, string>();
  const timestamp = Date.now();
  sourceNodes.forEach((node, index) => {
    idMap.set(node.id, `${node.id}-copy-${timestamp}-${index}`);
  });

  const duplicatedNodes = sourceNodes.map((node) => {
    const newId = idMap.get(node.id);
    return {
      ...structuredClone(node),
      id: newId || `${node.id}-copy-${timestamp}`,
      data: preparePastedNodeData(node.data, idMap),
      selected: true,
      position: {
        x: node.position.x + PASTE_OFFSET,
        y: node.position.y + PASTE_OFFSET,
      },
    } as Node;
  });

  const duplicatedEdges = sourceEdges
    .map((edge, index) => {
      const source = idMap.get(edge.source);
      const target = idMap.get(edge.target);
      if (!source || !target) return null;
      return {
        ...structuredClone(edge),
        id: `${edge.id}-copy-${timestamp}-${index}`,
        source,
        target,
        selected: false,
      } as Edge;
    })
    .filter((edge): edge is Edge => edge !== null);

  return { duplicatedNodes, duplicatedEdges };
};

type InternalWorkflowState = WorkflowState & {
  undoStack: GraphSnapshot[];
  redoStack: GraphSnapshot[];
  copiedNodes: Node[];
  copiedEdges: Edge[];
  pendingDragStartSnapshot: GraphSnapshot | null;
};

// Initial data
const initialNodes: Node[] = DEFAULT_NODES;
const initialEdges: Edge[] = [];

const initialWorkflows: Workflow[] = [
  {
    id: 'default',
    appId: '',
    nodes: initialNodes,
    edges: initialEdges,
    viewport: { x: 0, y: 0, zoom: 1 },
  },
];

export const useWorkflowStore = create<InternalWorkflowState>((set, get) => ({
  // === Editor UI 상태 ===
  workflows: initialWorkflows,
  activeWorkflowId: initialWorkflows[0]?.id || '',
  projectName: '',
  projectIcon: { type: 'emoji', content: '�', background_color: '#3b82f6' },
  projectDescription: '',
  projectApp: null,
  interactiveMode: 'mouse',
  isFullscreen: false,

  // === 설정 패널 상태 (초기값) ===
  isSettingsOpen: false,

  // === 버전 기록 상태 ===
  isVersionHistoryOpen: false,
  previewingVersion: null,
  lastDeployedAt: null,

  // === 테스트 패널 상태 ===
  isTestPanelOpen: false,

  runTrigger: 0,
  triggerWorkflowRun: () =>
    set((state) => ({ runTrigger: state.runTrigger + 1 })),

  // === 그래프 데이터 ===
  nodes: initialNodes,
  edges: initialEdges,
  undoStack: [],
  redoStack: [],
  copiedNodes: [],
  copiedEdges: [],
  pendingDragStartSnapshot: null,
  features: {},
  envVariables: [],
  runtimeVariables: [],

  // === Inner Node Selection ===
  selectedInnerNode: null,

  // === ReactFlow 액션 ===
  setNodes: (nodes) => {
    const { nodes: currentNodes, edges, workflows, activeWorkflowId } = get();
    const updatedWorkflows = syncActiveWorkflow(
      workflows,
      activeWorkflowId,
      nodes,
      edges,
    );
    set((state) => ({
      nodes,
      workflows: updatedWorkflows,
      undoStack: [
        ...state.undoStack.slice(-(HISTORY_LIMIT - 1)),
        cloneGraph(currentNodes, edges),
      ],
      redoStack: [],
    }));
  },

  setEdges: (edges) => {
    const { nodes, edges: currentEdges, workflows, activeWorkflowId } = get();
    const updatedWorkflows = syncActiveWorkflow(
      workflows,
      activeWorkflowId,
      nodes,
      edges,
    );
    set((state) => ({
      edges,
      workflows: updatedWorkflows,
      undoStack: [
        ...state.undoStack.slice(-(HISTORY_LIMIT - 1)),
        cloneGraph(nodes, currentEdges),
      ],
      redoStack: [],
    }));
  },

  onNodesChange: (changes: NodeChange[]) => {
    const currentNodes = get().nodes || [];
    const currentEdges = get().edges || [];
    const pendingDragStartSnapshot = get().pendingDragStartSnapshot;
    // DB에 deletable:false로 저장된 노드도 삭제 가능하도록 속성 제거
    // TODO: 데이터 마이그레이션 후 제거 필요
    const deletableNodes = currentNodes.map((node) => {
      const rest = { ...node } as Node & { deletable?: unknown };
      delete rest.deletable;
      return rest;
    });
    const newNodes = applyNodeChanges(changes, deletableNodes);
    const { workflows, activeWorkflowId } = get();
    const updatedWorkflows = syncActiveWorkflow(
      workflows,
      activeWorkflowId,
      newNodes as Node[],
      currentEdges,
    );
    const isDragging = changes.some(isDraggingPositionChange);
    const shouldRecord = shouldRecordCompletedNodeChanges(changes);
    const historySnapshot = pendingDragStartSnapshot
      ? pendingDragStartSnapshot
      : cloneGraph(currentNodes, currentEdges);

    set((state) => ({
      nodes: newNodes as Node[],
      workflows: updatedWorkflows,
      pendingDragStartSnapshot: isDragging
        ? state.pendingDragStartSnapshot || cloneGraph(currentNodes, currentEdges)
        : null,
      ...(shouldRecord
        ? {
            undoStack: [
              ...state.undoStack.slice(-(HISTORY_LIMIT - 1)),
              historySnapshot,
            ],
            redoStack: [],
          }
        : {}),
    }));
  },

  onEdgesChange: (changes: EdgeChange[]) => {
    const currentEdges = get().edges || [];
    const currentNodes = get().nodes || [];
    const newEdges = applyEdgeChanges(changes, currentEdges);
    const { workflows, activeWorkflowId } = get();
    const updatedWorkflows = syncActiveWorkflow(
      workflows,
      activeWorkflowId,
      currentNodes,
      newEdges,
    );
    set((state) => ({
      edges: newEdges,
      workflows: updatedWorkflows,
      ...(shouldRecordEdgeChanges(changes)
        ? {
            undoStack: [
              ...state.undoStack.slice(-(HISTORY_LIMIT - 1)),
              cloneGraph(currentNodes, currentEdges),
            ],
            redoStack: [],
          }
        : {}),
    }));
  },

  onConnect: (connection: Connection) => {
    const currentEdges = get().edges || [];
    const currentNodes = get().nodes || [];
    const newEdges = addEdge(connection, currentEdges);
    const { workflows, activeWorkflowId } = get();
    const updatedWorkflows = syncActiveWorkflow(
      workflows,
      activeWorkflowId,
      currentNodes,
      newEdges,
    );
    set((state) => ({
      edges: newEdges,
      workflows: updatedWorkflows,
      undoStack: [
        ...state.undoStack.slice(-(HISTORY_LIMIT - 1)),
        cloneGraph(currentNodes, currentEdges),
      ],
      redoStack: [],
    }));
  },

  undo: () => {
    const { undoStack, nodes, edges, activeWorkflowId } = get();
    const previous = undoStack[undoStack.length - 1];
    if (!previous) return;

    const current = cloneGraph(nodes, edges);
    set((state) => ({
      nodes: previous.nodes,
      edges: previous.edges,
      workflows: syncActiveWorkflow(
        state.workflows,
        activeWorkflowId,
        previous.nodes,
        previous.edges,
      ),
      undoStack: undoStack.slice(0, -1),
      redoStack: [
        ...state.redoStack.slice(-(HISTORY_LIMIT - 1)),
        current,
      ],
      pendingDragStartSnapshot: null,
    }));
  },

  redo: () => {
    const { redoStack, nodes, edges, activeWorkflowId } = get();
    const next = redoStack[redoStack.length - 1];
    if (!next) return;

    const current = cloneGraph(nodes, edges);
    set((state) => ({
      nodes: next.nodes,
      edges: next.edges,
      workflows: syncActiveWorkflow(
        state.workflows,
        activeWorkflowId,
        next.nodes,
        next.edges,
      ),
      undoStack: [
        ...state.undoStack.slice(-(HISTORY_LIMIT - 1)),
        current,
      ],
      redoStack: redoStack.slice(0, -1),
      pendingDragStartSnapshot: null,
    }));
  },

  copySelectedNodes: () => {
    const { nodes, edges } = get();
    const selectedNodes = nodes.filter((node) => node.selected);
    const selectedNodeIds = new Set(selectedNodes.map((node) => node.id));
    const selectedEdges = getInternalEdges(edges, selectedNodeIds);

    set({
      copiedNodes: structuredClone(selectedNodes),
      copiedEdges: structuredClone(selectedEdges),
    });
  },

  pasteCopiedNodes: () => {
    const { copiedNodes, copiedEdges, nodes, edges, activeWorkflowId } = get();
    if (copiedNodes.length === 0) return;

    const { duplicatedNodes, duplicatedEdges } = buildDuplicatedGraphElements(
      copiedNodes,
      copiedEdges,
    );

    const nextNodes = [
      ...nodes.map((node) => ({ ...node, selected: false }) as Node),
      ...duplicatedNodes,
    ];
    const nextEdges = [
      ...edges.map((edge) => ({ ...edge, selected: false })),
      ...duplicatedEdges,
    ];

    set((state) => ({
      nodes: nextNodes,
      edges: nextEdges,
      workflows: syncActiveWorkflow(
        state.workflows,
        activeWorkflowId,
        nextNodes,
        nextEdges,
      ),
      undoStack: [
        ...state.undoStack.slice(-(HISTORY_LIMIT - 1)),
        cloneGraph(nodes, edges),
      ],
      redoStack: [],
    }));
  },

  duplicateSelectedNodes: () => {
    const { nodes, edges, activeWorkflowId } = get();
    const selectedNodes = nodes.filter((node) => node.selected);
    if (selectedNodes.length === 0) return;

    const selectedNodeIds = new Set(selectedNodes.map((node) => node.id));
    const selectedEdges = getInternalEdges(edges, selectedNodeIds);
    const { duplicatedNodes, duplicatedEdges } = buildDuplicatedGraphElements(
      selectedNodes,
      selectedEdges,
    );

    const nextNodes = [
      ...nodes.map((node) => ({ ...node, selected: false }) as Node),
      ...duplicatedNodes,
    ];
    const nextEdges = [
      ...edges.map((edge) => ({ ...edge, selected: false })),
      ...duplicatedEdges,
    ];

    set((state) => ({
      nodes: nextNodes,
      edges: nextEdges,
      workflows: syncActiveWorkflow(
        state.workflows,
        activeWorkflowId,
        nextNodes,
        nextEdges,
      ),
      undoStack: [
        ...state.undoStack.slice(-(HISTORY_LIMIT - 1)),
        cloneGraph(nodes, edges),
      ],
      redoStack: [],
    }));
  },

  hasSelectedElements: () => {
    const { nodes, edges } = get();
    return (
      nodes.some((node) => node.selected) ||
      edges.some((edge) => edge.selected)
    );
  },

  deleteSelectedElements: () => {
    const { nodes, edges, activeWorkflowId } = get();
    const selectedNodeIds = new Set(
      nodes.filter((node) => node.selected).map((node) => node.id),
    );
    const selectedEdgeIds = new Set(
      edges.filter((edge) => edge.selected).map((edge) => edge.id),
    );

    if (selectedNodeIds.size === 0 && selectedEdgeIds.size === 0) return;

    const nextNodes = nodes.filter((node) => !selectedNodeIds.has(node.id));
    const nextEdges = edges.filter(
      (edge) =>
        !selectedEdgeIds.has(edge.id) &&
        !selectedNodeIds.has(edge.source) &&
        !selectedNodeIds.has(edge.target),
    );

    set((state) => ({
      nodes: nextNodes,
      edges: nextEdges,
      workflows: syncActiveWorkflow(
        state.workflows,
        activeWorkflowId,
        nextNodes,
        nextEdges,
      ),
      undoStack: [
        ...state.undoStack.slice(-(HISTORY_LIMIT - 1)),
        cloneGraph(nodes, edges),
      ],
      redoStack: [],
    }));
  },

  clearSelection: () => {
    const { nodes, edges, workflows, activeWorkflowId } = get();
    const nextNodes = nodes.map((node) =>
      node.selected ? ({ ...node, selected: false } as Node) : node,
    );
    const nextEdges = edges.map((edge) =>
      edge.selected ? { ...edge, selected: false } : edge,
    );

    set({
      nodes: nextNodes,
      edges: nextEdges,
      workflows: syncActiveWorkflow(
        workflows,
        activeWorkflowId,
        nextNodes,
        nextEdges,
      ),
    });
  },

  setProjectInfo: (name, icon, description = '') =>
    set({
      projectName: name,
      projectIcon: icon,
      projectDescription: description,
    }),

  setProjectApp: (app) =>
    set({
      projectApp: app,
      projectName: app.name,
      projectIcon: app.icon,
      projectDescription: app.description || '',
    }),

  setInteractiveMode: (mode) => set({ interactiveMode: mode }),

  toggleFullscreen: () =>
    set((state) => ({ isFullscreen: !state.isFullscreen })),

  // === 버전 기록 액션 ===
  toggleSettings: () =>
    set((state) => ({
      isSettingsOpen: !state.isSettingsOpen,
      isVersionHistoryOpen: false,
      isTestPanelOpen: false,
    })),

  toggleVersionHistory: () =>
    set((state) => ({
      isVersionHistoryOpen: !state.isVersionHistoryOpen,
      isSettingsOpen: false,
      isTestPanelOpen: false,
    })),

  toggleTestPanel: () =>
    set((state) => ({
      isTestPanelOpen: !state.isTestPanelOpen,
      isSettingsOpen: false,
      isVersionHistoryOpen: false,
    })),

  previewVersion: (version) => {
    // 현재 스냅샷을 노드/엣지에 적용 (미리보기)
    const snapshot = version.graph_snapshot;
    set({
      previewingVersion: version,
      nodes: snapshot.nodes || [],
      edges: snapshot.edges || [],
    });
  },

  exitPreview: () => {
    // 미리보기 종료 시 현재 드래프트 상태로 복구
    // activeWorkflowId에 해당하는 데이터를 다시 로드
    const { workflows, activeWorkflowId } = get();
    const currentWorkflow = workflows.find((w) => w.id === activeWorkflowId);

    if (currentWorkflow) {
      set({
        previewingVersion: null,
        nodes: currentWorkflow.nodes,
        edges: currentWorkflow.edges,
      });
    } else {
      set({ previewingVersion: null });
    }
  },

  notifyDeploymentComplete: () => set({ lastDeployedAt: new Date() }),

  restoreVersion: async (version) => {
    const state = get();
    const { activeWorkflowId } = state;

    try {
      // 1. 스냅샷 데이터로 현재 드래프트 업데이트 API 호출
      const snapshot = version.graph_snapshot;
      await workflowApi.syncDraftWorkflow(activeWorkflowId, {
        nodes: snapshot.nodes || [],
        edges: snapshot.edges || [],
        viewport: { x: 0, y: 0, zoom: 1 }, // 뷰포트는 초기화하거나 스냅샷에서 가져옴
      });

      // 2. Store, local state 업데이트
      const { workflows } = get();
      const updatedWorkflows = workflows.map((w) =>
        w.id === activeWorkflowId
          ? { ...w, nodes: snapshot.nodes || [], edges: snapshot.edges || [] }
          : w,
      );

      set({
        workflows: updatedWorkflows,
        nodes: snapshot.nodes || [],
        edges: snapshot.edges || [],
        previewingVersion: null, // 미리보기 종료
      });
    } catch (error) {
      console.error('Failed to restore version:', error);
      throw error;
    }
  },

  addWorkflow: async (workflow, appId) => {
    try {
      // Backend API 호출
      const created = await workflowApi.createWorkflow({
        app_id: appId,
      });

      // Store에 추가
      const newWorkflow: Workflow = {
        id: created.id,
        appId: created.app_id,
        nodes: [],
        edges: [],
        viewport: { x: 0, y: 0, zoom: 1 },
      };

      set((state) => ({
        workflows: [...state.workflows, newWorkflow],
      }));

      return created.id;
    } catch (error) {
      console.error('Failed to create workflow:', error);
      throw error;
    }
  },

  loadWorkflowsByApp: async (appId: string) => {
    try {
      const workflows = await workflowApi.listWorkflowsByApp(appId);
      const currentWorkflows = get().workflows;

      // Backend 워크플로우를 프론트엔드 포맷으로 변환
      const formattedWorkflows: Workflow[] = workflows.map((w) => {
        const existing = currentWorkflows.find((cw) => cw.id === w.id);
        return {
          id: w.id,
          appId: w.app_id,
          nodes: existing?.nodes?.length ? existing.nodes : [],
          edges: existing?.edges?.length ? existing.edges : [],
          viewport: existing?.viewport || { x: 0, y: 0, zoom: 1 },
        };
      });

      set({ workflows: formattedWorkflows });
    } catch (error) {
      console.error('Failed to load workflows:', error);
      throw error;
    }
  },

  setActiveWorkflow: (id) => {
    const workflow = get().workflows.find((w) => w.id === id);
    if (workflow) {
      set({
        activeWorkflowId: id,
        nodes: workflow.nodes,
        edges: workflow.edges,
        undoStack: [],
        redoStack: [],
      });
    }
  },

  // **안전한 활성 워크플로우 ID 설정**
  // 기존 setActiveWorkflow와 달리, 노드나 엣지 데이터를 덮어쓰지 않고 ID만 변경합니다.
  // 새로고침 시 데이터가 로드되기 전에 빈 상태로 초기화되는 것을 방지하기 위해 사용합니다.
  setActiveWorkflowIdSafe: (id: string) => {
    set({ activeWorkflowId: id, undoStack: [], redoStack: [] });
  },

  deleteWorkflow: (id) => {
    const { workflows, activeWorkflowId } = get();
    const filteredWorkflows = workflows.filter((w) => w.id !== id);

    if (id === activeWorkflowId && filteredWorkflows.length > 0) {
      const newActive = filteredWorkflows[0];
      set({
        workflows: filteredWorkflows,
        activeWorkflowId: newActive.id,
        nodes: newActive.nodes,
        edges: newActive.edges,
      });
    } else {
      set({ workflows: filteredWorkflows });
    }
  },

  updateWorkflowViewport: (id, viewport) => {
    const { workflows } = get();
    const updatedWorkflows = workflows.map((w) =>
      w.id === id ? { ...w, viewport } : w,
    );
    set({ workflows: updatedWorkflows });
  },

  // === 시작노드 검증 핼퍼 ===
  getStartNodeType: () => {
    const nodes = get().nodes;
    const startNode = nodes.find(
      (n) =>
        n.type === 'startNode' ||
        n.type === 'webhookTrigger' ||
        n.type === 'scheduleTrigger',
    );
    return startNode
      ? (startNode.type as 'startNode' | 'webhookTrigger' | 'scheduleTrigger')
      : null;
  },

  getStartNodeCount: () => {
    const nodes = get().nodes;
    return nodes.filter(
      (n) =>
        n.type === 'startNode' ||
        n.type === 'webhookTrigger' ||
        n.type === 'scheduleTrigger',
    ).length;
  },

  canPublish: () => {
    const count = get().getStartNodeCount();
    return count === 1;
  },

  // === API 동기화 액션 ===
  setFeatures: (features) => set({ features }),
  setEnvVariables: (envVariables) => set({ envVariables }),
  setRuntimeVariables: (runtimeVariables) => set({ runtimeVariables }),

  updateNodeData: (nodeId, newData) => {
    set({
      nodes: get().nodes.map((node) => {
        if (node.id === nodeId) {
          return {
            ...node,
            data: { ...node.data, ...newData },
          } as Node;
        }
        return node;
      }),
    });
  },

  // === Inner Node Selection Methods ===
  setSelectedInnerNode: (parentNodeId, nodeId) =>
    set({ selectedInnerNode: { parentNodeId, nodeId } }),

  clearInnerNodeSelection: () => set({ selectedInnerNode: null }),

  updateInnerNodeData: (parentNodeId, nodeId, newData) => {
    set({
      nodes: get().nodes.map((node) => {
        if (node.id === parentNodeId) {
          // Find and update the inner node within subGraph
          const subGraph = (node.data as any).subGraph;
          if (subGraph && subGraph.nodes) {
            const updatedSubNodes = subGraph.nodes.map((subNode: any) =>
              subNode.id === nodeId
                ? { ...subNode, data: { ...subNode.data, ...newData } }
                : subNode,
            );
            return {
              ...node,
              data: {
                ...node.data,
                subGraph: { ...subGraph, nodes: updatedSubNodes },
              },
            } as Node;
          }
        }
        return node;
      }),
    });
  },

  setWorkflowData: (data: any, workflowId?: string) => {
    set({
      nodes: data.nodes || [],
      edges: data.edges || [],
      features: data.features || {},
      envVariables: data.envVariables || [],
      runtimeVariables: data.runtimeVariables || [],
      undoStack: [],
      redoStack: [],
    });

    const { activeWorkflowId, workflows } = get();
    const targetId = workflowId || activeWorkflowId;

    if (targetId) {
      const exists = workflows.some((w) => w.id === targetId);
      let updatedWorkflows;

      if (exists) {
        updatedWorkflows = workflows.map((w) =>
          w.id === targetId
            ? {
                ...w,
                nodes: data.nodes || [],
                edges: data.edges || [],
                ...(data.viewport ? { viewport: data.viewport } : {}),
              }
            : w,
        );
      } else {
        updatedWorkflows = [
          ...workflows,
          {
            id: targetId,
            appId: '',
            nodes: data.nodes || [],
            edges: data.edges || [],
            viewport: data.viewport || { x: 0, y: 0, zoom: 1 },
          },
        ];
      }
      set({ workflows: updatedWorkflows });
    }
  },
}));
