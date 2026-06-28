import { describe, expect, it } from 'vitest';
import type { AppNode } from '../../types/Nodes';
import type { Edge, WorkflowDraftRequest } from '../../types/Workflow';
import {
  cleanupInvalidEdges,
  validateConnection,
  validateWorkflowGraph,
} from '../../utils/validateWorkflowGraph';

const node = (id: string, type: AppNode['type'], title: string): AppNode =>
  ({
    id,
    type,
    position: { x: 0, y: 0 },
    data: { title },
  }) as AppNode;

const draft = (nodes: AppNode[], edges: Edge[]): WorkflowDraftRequest => ({
  nodes,
  edges,
  viewport: { x: 0, y: 0, zoom: 1 },
});

describe('validateWorkflowGraph', () => {
  it('blocks edges entering a start node', () => {
    const nodes = [
      node('start', 'startNode', '입력'),
      node('template', 'templateNode', '템플릿'),
    ];
    const edges = [
      {
        id: 'bad-edge',
        source: 'template',
        sourceHandle: 'source',
        target: 'start',
        targetHandle: 'target',
      },
    ];

    const result = validateWorkflowGraph(draft(nodes, edges));

    expect(result.ok).toBe(false);
    expect(result.errors[0]).toMatchObject({
      code: 'START_NODE_HAS_INCOMING_EDGE',
      edgeId: 'bad-edge',
      sourceNodeTitle: '템플릿',
      targetNodeTitle: '입력',
    });
  });

  it('cleans edges that cannot be represented or executed', () => {
    const nodes = [
      node('start', 'startNode', '입력'),
      node('template', 'templateNode', '템플릿'),
    ];
    const graph = draft(nodes, [
      {
        id: 'bad-edge',
        source: 'template',
        sourceHandle: 'source',
        target: 'start',
        targetHandle: 'target',
      },
      {
        id: 'good-edge',
        source: 'start',
        sourceHandle: 'source',
        target: 'template',
        targetHandle: 'target',
      },
    ]);

    const result = cleanupInvalidEdges(graph);

    expect(result.removedIssues).toHaveLength(1);
    expect(result.graph.edges.map((edge) => edge.id)).toEqual(['good-edge']);
  });

  it('detects cycles before execution', () => {
    const nodes = [
      node('start', 'startNode', '입력'),
      node('template', 'templateNode', '템플릿'),
      node('llm', 'llmNode', 'LLM'),
    ];
    const edges = [
      { id: 'e1', source: 'start', target: 'template' },
      { id: 'e2', source: 'template', target: 'llm' },
      { id: 'e3', source: 'llm', target: 'template' },
    ];

    const result = validateWorkflowGraph(draft(nodes, edges));

    expect(result.ok).toBe(false);
    expect(result.errors.some((issue) => issue.code === 'CYCLE_DETECTED')).toBe(
      true,
    );
  });

  it('blocks invalid number-based connections through the central validator', () => {
    const nodes = [
      node('start', 'startNode', '입력'),
      node('template', 'templateNode', '템플릿'),
    ];

    const result = validateConnection(nodes, [], {
      source: 'template',
      sourceHandle: 'source',
      target: 'start',
      targetHandle: 'target',
    });

    expect(result.ok).toBe(false);
    expect(result.errors[0].code).toBe('START_NODE_HAS_INCOMING_EDGE');
  });
});
