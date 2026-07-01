import type { Connection } from '@xyflow/react';
import type { Edge, WorkflowDraftRequest } from '../types/Workflow';
import type { AppNode } from '../types/Nodes';

export type GraphValidationIssueCode =
  | 'MISSING_SOURCE_NODE'
  | 'MISSING_TARGET_NODE'
  | 'START_NODE_HAS_INCOMING_EDGE'
  | 'TRIGGER_NODE_HAS_INCOMING_EDGE'
  | 'TERMINAL_NODE_HAS_OUTGOING_EDGE'
  | 'INVALID_CONDITION_SOURCE_HANDLE'
  | 'INVALID_GUARDRAIL_SOURCE_HANDLE'
  | 'DUPLICATE_EDGE'
  | 'CYCLE_DETECTED';

export type GraphValidationIssue = {
  level: 'error' | 'warning';
  code: GraphValidationIssueCode;
  message: string;
  edgeId?: string;
  nodeId?: string;
  sourceNodeId?: string;
  targetNodeId?: string;
  sourceNodeTitle?: string;
  targetNodeTitle?: string;
};

export type GraphValidationResult = {
  ok: boolean;
  errors: GraphValidationIssue[];
  warnings: GraphValidationIssue[];
};

export type GraphSnapshot = WorkflowDraftRequest;

export type GraphCleanupResult = {
  graph: GraphSnapshot;
  removedIssues: GraphValidationIssue[];
  unresolvedIssues: GraphValidationIssue[];
};

const START_NODE_TYPES = new Set(['startNode']);
const TRIGGER_NODE_TYPES = new Set(['webhookTrigger', 'scheduleTrigger']);
const SOURCE_ONLY_NODE_TYPES = new Set([
  ...START_NODE_TYPES,
  ...TRIGGER_NODE_TYPES,
]);
const TERMINAL_NODE_TYPES = new Set(['answerNode']);

const getNodeTitle = (node?: AppNode) => {
  const title = String(node?.data?.title || '').trim();
  return title || node?.id || '알 수 없는 노드';
};

const getEdgeKey = (edge: Pick<Edge, 'source' | 'target'> & Partial<Edge>) =>
  [
    edge.source,
    edge.sourceHandle || '',
    edge.target,
    edge.targetHandle || '',
  ].join('__');

const toIssue = (
  code: GraphValidationIssueCode,
  message: string,
  edge: Edge,
  sourceNode?: AppNode,
  targetNode?: AppNode,
): GraphValidationIssue => ({
  level: 'error',
  code,
  message,
  edgeId: edge.id,
  nodeId: targetNode?.id || sourceNode?.id,
  sourceNodeId: edge.source,
  targetNodeId: edge.target,
  sourceNodeTitle: getNodeTitle(sourceNode),
  targetNodeTitle: getNodeTitle(targetNode),
});

const getConditionSourceHandles = (node: AppNode) => {
  const cases = Array.isArray(node.data?.cases) ? node.data.cases : [];
  return new Set([
    'default',
    ...cases
      .map((caseItem) =>
        typeof caseItem === 'object' && caseItem !== null
          ? String((caseItem as { id?: unknown }).id || '')
          : '',
      )
      .filter(Boolean),
  ]);
};

const getGuardrailSourceHandles = (node: AppNode) => {
  const data = node.data as Record<string, unknown>;
  return new Set([
    'source',
    String(data.pass_handle_id || 'pass'),
    String(data.fail_handle_id || 'fail'),
  ]);
};

const createsCycle = (nodes: AppNode[], edges: Edge[]) => {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const graph = new Map<string, string[]>();

  for (const node of nodes) {
    graph.set(node.id, []);
  }

  for (const edge of edges) {
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) continue;
    graph.get(edge.source)?.push(edge.target);
  }

  const visiting = new Set<string>();
  const visited = new Set<string>();

  const visit = (nodeId: string): string | null => {
    if (visiting.has(nodeId)) return nodeId;
    if (visited.has(nodeId)) return null;

    visiting.add(nodeId);
    for (const nextNodeId of graph.get(nodeId) || []) {
      const cycleNodeId = visit(nextNodeId);
      if (cycleNodeId) return cycleNodeId;
    }
    visiting.delete(nodeId);
    visited.add(nodeId);
    return null;
  };

  for (const node of nodes) {
    const cycleNodeId = visit(node.id);
    if (cycleNodeId) return cycleNodeId;
  }

  return null;
};

const getDirectEdgeIssues = (
  nodes: AppNode[],
  edges: Edge[],
  options?: { includeDuplicateWarnings?: boolean },
) => {
  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const issues: GraphValidationIssue[] = [];
  const seenEdgeKeys = new Map<string, Edge>();

  for (const edge of edges) {
    const sourceNode = nodeMap.get(edge.source);
    const targetNode = nodeMap.get(edge.target);

    if (!sourceNode) {
      issues.push(
        toIssue(
          'MISSING_SOURCE_NODE',
          '존재하지 않는 노드에서 시작하는 연결입니다.',
          edge,
          sourceNode,
          targetNode,
        ),
      );
      continue;
    }

    if (!targetNode) {
      issues.push(
        toIssue(
          'MISSING_TARGET_NODE',
          '존재하지 않는 노드로 향하는 연결입니다.',
          edge,
          sourceNode,
          targetNode,
        ),
      );
      continue;
    }

    if (START_NODE_TYPES.has(targetNode.type || '')) {
      issues.push(
        toIssue(
          'START_NODE_HAS_INCOMING_EDGE',
          '입력 노드에는 다른 노드를 연결할 수 없습니다.',
          edge,
          sourceNode,
          targetNode,
        ),
      );
    } else if (TRIGGER_NODE_TYPES.has(targetNode.type || '')) {
      issues.push(
        toIssue(
          'TRIGGER_NODE_HAS_INCOMING_EDGE',
          '트리거 노드에는 다른 노드를 연결할 수 없습니다.',
          edge,
          sourceNode,
          targetNode,
        ),
      );
    }

    if (TERMINAL_NODE_TYPES.has(sourceNode.type || '')) {
      issues.push(
        toIssue(
          'TERMINAL_NODE_HAS_OUTGOING_EDGE',
          '응답 노드에서는 다른 노드로 연결할 수 없습니다.',
          edge,
          sourceNode,
          targetNode,
        ),
      );
    }

    if (sourceNode.type === 'conditionNode') {
      const sourceHandle = edge.sourceHandle || 'default';
      if (!getConditionSourceHandles(sourceNode).has(sourceHandle)) {
        issues.push(
          toIssue(
            'INVALID_CONDITION_SOURCE_HANDLE',
            '존재하지 않는 IF/ELSE 분기에서 시작하는 연결입니다.',
            edge,
            sourceNode,
            targetNode,
          ),
        );
      }
    }

    if (sourceNode.type === 'guardrailNode') {
      const sourceHandle = edge.sourceHandle || 'source';
      if (!getGuardrailSourceHandles(sourceNode).has(sourceHandle)) {
        issues.push(
          toIssue(
            'INVALID_GUARDRAIL_SOURCE_HANDLE',
            '존재하지 않는 가드레일 분기에서 시작하는 연결입니다.',
            edge,
            sourceNode,
            targetNode,
          ),
        );
      }
    }

    if (options?.includeDuplicateWarnings) {
      const edgeKey = getEdgeKey(edge);
      const firstEdge = seenEdgeKeys.get(edgeKey);
      if (firstEdge) {
        issues.push({
          ...toIssue(
            'DUPLICATE_EDGE',
            '같은 노드 사이에 중복된 연결이 있습니다.',
            edge,
            sourceNode,
            targetNode,
          ),
          level: 'warning',
          edgeId: edge.id || firstEdge.id,
        });
      } else {
        seenEdgeKeys.set(edgeKey, edge);
      }
    }
  }

  return issues;
};

export const validateWorkflowGraph = (
  graph: Pick<GraphSnapshot, 'nodes' | 'edges'>,
): GraphValidationResult => {
  const nodes = (graph.nodes || []) as AppNode[];
  const edges = (graph.edges || []) as Edge[];
  const directIssues = getDirectEdgeIssues(nodes, edges, {
    includeDuplicateWarnings: true,
  });
  const cycleNodeId = createsCycle(nodes, edges);

  const cycleIssue: GraphValidationIssue[] = cycleNodeId
    ? [
        {
          level: 'error',
          code: 'CYCLE_DETECTED',
          message: `워크플로우에 순환 연결이 있습니다. 문제 노드: ${getNodeTitle(
            nodes.find((node) => node.id === cycleNodeId),
          )}`,
          nodeId: cycleNodeId,
        },
      ]
    : [];

  const allIssues = [...directIssues, ...cycleIssue];
  const errors = allIssues.filter((issue) => issue.level === 'error');
  const warnings = allIssues.filter((issue) => issue.level === 'warning');

  return {
    ok: errors.length === 0,
    errors,
    warnings,
  };
};

export const cleanupInvalidEdges = (
  graph: GraphSnapshot,
): GraphCleanupResult => {
  const nodes = (graph.nodes || []) as AppNode[];
  const edges = (graph.edges || []) as Edge[];
  const directIssues = getDirectEdgeIssues(nodes, edges);
  const removableEdgeIds = new Set(
    directIssues
      .filter(
        (issue) =>
          issue.code !== 'DUPLICATE_EDGE' && issue.edgeId && issue.level === 'error',
      )
      .map((issue) => issue.edgeId),
  );
  const nextEdges = edges.filter((edge) => !removableEdgeIds.has(edge.id));
  const cleanedGraph = {
    ...graph,
    nodes,
    edges: nextEdges,
  };
  const validationAfterCleanup = validateWorkflowGraph(cleanedGraph);

  return {
    graph: cleanedGraph,
    removedIssues: directIssues.filter(
      (issue) => issue.edgeId && removableEdgeIds.has(issue.edgeId),
    ),
    unresolvedIssues: validationAfterCleanup.errors,
  };
};

export const validateConnection = (
  nodes: AppNode[],
  edges: Edge[],
  connection: Connection,
): GraphValidationResult => {
  if (!connection.source || !connection.target) {
    return {
      ok: false,
      errors: [
        {
          level: 'error',
          code: 'MISSING_TARGET_NODE',
          message: '연결할 노드를 찾을 수 없습니다.',
        },
      ],
      warnings: [],
    };
  }

  const nextEdge: Edge = {
    id: `__pending__${getEdgeKey({
      source: connection.source,
      sourceHandle: connection.sourceHandle,
      target: connection.target,
      targetHandle: connection.targetHandle,
    })}`,
    source: connection.source,
    target: connection.target,
    sourceHandle: connection.sourceHandle,
    targetHandle: connection.targetHandle,
  };

  return validateWorkflowGraph({
    nodes,
    edges: [...edges, nextEdge],
  });
};

export const formatGraphIssue = (issue: GraphValidationIssue) => {
  if (issue.sourceNodeTitle && issue.targetNodeTitle) {
    return `${issue.message} (${issue.sourceNodeTitle} -> ${issue.targetNodeTitle})`;
  }
  return issue.message;
};

export const hasIncomingHandle = (node: AppNode) =>
  !SOURCE_ONLY_NODE_TYPES.has(node.type || '');
