import { useCallback } from 'react';
import { useReactFlow, type Edge } from '@xyflow/react';
import type { AppNode } from '../types/Nodes';
import { getNodeDefinition } from '../config/nodeRegistry';
import {
  findFirstAvailableHandle,
  createNewCaseForConnection,
} from '../utils/conditionNodeHelpers';
import { arrangeConditionNodeChildren } from '../utils/arrangeConditionNodes';
import { useWorkflowStore } from '../store/useWorkflowStore';
import type { NodeDefinition } from '../config/nodeRegistry';
import {
  WORKFLOW_NODE_GAP,
  snapCanvasPosition,
} from '../utils/workflowCanvasGeometry';

const OVERLAP_THRESHOLD_X = 90;
const OVERLAP_THRESHOLD_Y = 90;
const SOURCE_AMBIGUOUS_NODE_TYPES = new Set(['conditionNode']);
const SOURCE_BLOCKED_NODE_TYPES = new Set(['answerNode']);
const NON_WORKFLOW_NODE_TYPES = new Set(['note']);

export const getLastNodes = (nodes: AppNode[], edges: Edge[]) => {
  const workflowNodeIds = new Set(
    nodes
      .filter((node) => !NON_WORKFLOW_NODE_TYPES.has(node.type || ''))
      .map((node) => node.id),
  );
  const nodesWithOutgoingEdge = new Set(
    edges
      .filter(
        (edge) =>
          workflowNodeIds.has(edge.source) && workflowNodeIds.has(edge.target),
      )
      .map((edge) => edge.source),
  );
  return nodes.filter(
    (node) =>
      workflowNodeIds.has(node.id) && !nodesWithOutgoingEdge.has(node.id),
  );
};

export const findAddAfterTarget = (nodes: AppNode[], edges: Edge[]) => {
  const selectedNodes = nodes.filter((node) => node.selected);
  if (selectedNodes.length === 1) return selectedNodes[0];
  if (selectedNodes.length > 1) return null;

  const terminalCandidates = getLastNodes(nodes, edges);

  if (terminalCandidates.length !== 1) return null;
  const terminalNode = terminalCandidates[0];
  if (SOURCE_BLOCKED_NODE_TYPES.has(terminalNode.type || '')) return null;
  return terminalNode;
};

const canUseNodeAsAddAfterSource = (node?: AppNode | null) => {
  if (!node) return false;
  const nodeType = node.type || '';
  return (
    !SOURCE_BLOCKED_NODE_TYPES.has(nodeType) &&
    !SOURCE_AMBIGUOUS_NODE_TYPES.has(nodeType)
  );
};

const canUseDefinitionAsAddAfterTarget = (nodeDef?: NodeDefinition | null) => {
  if (!nodeDef) return false;
  return nodeDef.category !== 'trigger' && nodeDef.type !== 'workflowNode';
};

export const canAddNodeDefinitionAfterTarget = (
  nodeDef: NodeDefinition,
  nodes: AppNode[],
  edges: Edge[],
) => {
  const targetNode = findAddAfterTarget(nodes, edges);
  return (
    canUseNodeAsAddAfterSource(targetNode) &&
    canUseDefinitionAsAddAfterTarget(nodeDef)
  );
};

const getNonOverlappingPosition = (
  nodes: AppNode[],
  basePosition: { x: number; y: number },
) => {
  let nextPosition = snapCanvasPosition(basePosition);
  let attempts = 0;

  while (
    attempts < 12 &&
    nodes.some(
      (node) =>
        Math.abs(node.position.x - nextPosition.x) < OVERLAP_THRESHOLD_X &&
        Math.abs(node.position.y - nextPosition.y) < OVERLAP_THRESHOLD_Y,
    )
  ) {
    attempts += 1;
    nextPosition = snapCanvasPosition({
      x: basePosition.x,
      y: basePosition.y + WORKFLOW_NODE_GAP.addAfterY * attempts,
    });
  }

  return nextPosition;
};

interface UseNodeCreationProps {
  edges: Edge[];
  setEdges: (edges: Edge[]) => void;
  previewState: {
    nearestNode: AppNode | null;
    isRight: boolean;
    draggedNodePosition: { x: number; y: number } | null;
  };
  resetPreview: () => void;
  setSearchModalContext: (context: {
    isOpen: boolean;
    position?: { x: number; y: number };
  }) => void;
}

export function useNodeCreation({
  edges,
  setEdges,
  previewState,
  resetPreview,
  setSearchModalContext,
}: UseNodeCreationProps) {
  const { screenToFlowPosition } = useReactFlow();
  const addNode = useWorkflowStore((state) => state.addNode);
  const addNodeWithEdge = useWorkflowStore((state) => state.addNodeWithEdge);
  const nodes = useWorkflowStore((state) => state.nodes) as AppNode[];

  // Handle node drop from library
  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();

      const nodeDefId = event.dataTransfer.getData('application/reactflow');
      if (!nodeDefId) return;

      const nodeDef = getNodeDefinition(nodeDefId);
      if (!nodeDef) return;

      // Use preview position if available, otherwise use mouse position
      const position =
        previewState.draggedNodePosition ||
        screenToFlowPosition({
          x: event.clientX,
          y: event.clientY,
        });

      // 워크플로우 노드(모듈)인 경우, 바로 추가하지 않고 검색 모달을 엽니다.
      if (nodeDef.type === 'workflowNode') {
        setSearchModalContext({ isOpen: true, position });
        return;
      }

      const baseNode = {
        id: `${nodeDef.id}-${Date.now()}`,
        type: nodeDef.type,
        data: nodeDef.defaultData(),
        position,
      } as unknown as AppNode;

      // Auto-connect if there's a nearest node
      let sourceHandle: string | undefined;
      let updatedConditionNode: AppNode | null = null;

      if (previewState.nearestNode) {
        // For condition nodes, use priority-based auto-connect
        if (
          previewState.isRight &&
          previewState.nearestNode.type === 'conditionNode'
        ) {
          const conditionNode = previewState.nearestNode;

          // Find first available handle in priority order
          let targetHandle = findFirstAvailableHandle(conditionNode, edges);

          // If all handles are connected, create new case
          if (targetHandle === null) {
            const result = createNewCaseForConnection(conditionNode);
            targetHandle = result.caseId;
            updatedConditionNode = result.updatedNode;
          }

          sourceHandle = targetHandle;
        }
      }

      const newNode = addNode(baseNode, (currentNodes, numberedNode) => {
        const filteredNodes = currentNodes.filter((n) => n.id !== 'GHOST');
        let nodesToSet: AppNode[];

        if (updatedConditionNode) {
          const updatedNodes = filteredNodes.map((node) =>
            node.id === updatedConditionNode!.id ? updatedConditionNode! : node,
          );
          nodesToSet = [...updatedNodes, numberedNode];
        } else {
          nodesToSet = [...filteredNodes, numberedNode];
        }

        if (
          previewState.nearestNode &&
          previewState.nearestNode.type === 'conditionNode'
        ) {
          const tempEdges = [
            ...edges,
            {
              id: `temp-${Date.now()}`,
              source: previewState.isRight
                ? previewState.nearestNode.id
                : numberedNode.id,
              target: previewState.isRight
                ? numberedNode.id
                : previewState.nearestNode.id,
              sourceHandle: sourceHandle || undefined,
            },
          ];

          nodesToSet = arrangeConditionNodeChildren(
            updatedConditionNode || previewState.nearestNode,
            nodesToSet,
            tempEdges as Edge[],
          );
        }

        return nodesToSet;
      });

      // Create edge if there's a nearest node
      if (previewState.nearestNode) {
        const newEdge = {
          id: `e-${Date.now()}`,
          source: previewState.isRight
            ? previewState.nearestNode.id
            : newNode.id,
          target: previewState.isRight
            ? newNode.id
            : previewState.nearestNode.id,
          sourceHandle: sourceHandle || undefined,
          type: 'puzzle',
        };

        setEdges([...edges, newEdge]);
      }

      // Clean up preview
      resetPreview();
    },
    [
      screenToFlowPosition,
      resetPreview,
      previewState,
      setEdges,
      edges,
      setSearchModalContext,
      addNode,
    ],
  );

  // Add node from library (center of screen)
  const handleAddNodeFromLibrary = useCallback(
    (nodeDefId: string) => {
      const nodeDef = getNodeDefinition(nodeDefId);
      if (!nodeDef) return;

      const centerPos = screenToFlowPosition({
        x: window.innerWidth / 2,
        y: window.innerHeight / 2,
      });

      const baseNode = {
        id: `${nodeDef.id}-${Date.now()}`,
        type: nodeDef.type,
        data: nodeDef.defaultData(),
        position: centerPos,
      } as unknown as AppNode;
      addNode(baseNode);
    },
    [screenToFlowPosition, addNode],
  );

  const handleAddNodeAfterSelected = useCallback(
    (nodeDefId: string) => {
      const nodeDef = getNodeDefinition(nodeDefId);
      const targetNode = findAddAfterTarget(nodes, edges);
      if (
        !nodeDef ||
        !canUseNodeAsAddAfterSource(targetNode) ||
        !canUseDefinitionAsAddAfterTarget(nodeDef)
      ) {
        return;
      }

      const position = getNonOverlappingPosition(nodes, {
        x: targetNode!.position.x + WORKFLOW_NODE_GAP.addAfterX,
        y: targetNode!.position.y,
      });
      const baseNode = {
        id: `${nodeDef.id}-${Date.now()}`,
        type: nodeDef.type,
        data: nodeDef.defaultData(),
        position,
      } as unknown as AppNode;

      addNodeWithEdge(
        baseNode,
        {
          id: `e-${targetNode!.id}-${nodeDef.id}-${Date.now()}`,
          source: targetNode!.id,
          type: 'puzzle',
        },
        (currentNodes, numberedNode) => [
          ...currentNodes.map((node) => ({
            ...node,
            selected: false,
          })),
          {
            ...numberedNode,
            selected: true,
          },
        ],
      );
    },
    [addNodeWithEdge, edges, nodes],
  );

  return {
    onDrop,
    handleAddNodeFromLibrary,
    handleAddNodeAfterSelected,
  };
}
