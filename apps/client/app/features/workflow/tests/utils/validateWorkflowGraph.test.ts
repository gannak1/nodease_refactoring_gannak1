import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
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
  it('matches catalog entry, terminal, and condition connection policies', () => {
    const catalog = JSON.parse(
      readFileSync(
        resolve(
          process.cwd(),
          '../../apps/shared/config/workflow_node_catalog.json',
        ),
        'utf8',
      ),
    ) as {
      nodes: Array<{
        node_type: AppNode['type'];
        connection_policy: {
          incoming: string;
          outgoing: string;
          outgoing_handles: string;
        };
      }>;
    };

    for (const definition of catalog.nodes) {
      if (definition.connection_policy.incoming === 'forbidden') {
        const result = validateWorkflowGraph(
          draft(
            [
              node('source', 'templateNode', 'Source'),
              node('target', definition.node_type, 'Target'),
            ],
            [{ id: 'edge', source: 'source', target: 'target' }],
          ),
        );
        expect(result.ok).toBe(false);
      }
      if (definition.connection_policy.outgoing === 'forbidden') {
        const result = validateWorkflowGraph(
          draft(
            [
              node('source', definition.node_type, 'Source'),
              node('target', 'templateNode', 'Target'),
            ],
            [{ id: 'edge', source: 'source', target: 'target' }],
          ),
        );
        expect(result.ok).toBe(false);
      }
    }
  });
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

  it('blocks condition edges that use an unknown branch handle', () => {
    const condition = {
      ...node('condition', 'conditionNode', '조건'),
      data: { title: '조건', cases: [{ id: 'case-1', value: 'yes' }] },
    } as AppNode;
    const result = validateWorkflowGraph(
      draft(
        [condition, node('template', 'templateNode', '템플릿')],
        [
          {
            id: 'bad-condition-edge',
            source: 'condition',
            sourceHandle: 'missing-case',
            target: 'template',
          },
        ],
      ),
    );

    expect(result.ok).toBe(false);
    expect(result.errors[0].code).toBe('INVALID_CONDITION_SOURCE_HANDLE');
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

  it('preserves LLM RAG selection data when cleaning invalid edges', () => {
    const llmNode = {
      ...node('llm', 'llmNode', 'LLM'),
      data: {
        title: 'LLM',
        knowledgeBases: [{ id: 'kb-1', name: '제품 정책' }],
        topK: 4,
        scoreThreshold: 0.6,
        dedupeRetrievedContext: true,
        retrievedContextMaxChars: 4000,
        retrievedContextCompression: 'light',
        answerGroundingCheck: 'basic',
      },
    } as AppNode;
    const graph = draft(
      [node('start', 'startNode', '입력'), llmNode],
      [
        {
          id: 'bad-edge',
          source: 'llm',
          sourceHandle: 'source',
          target: 'start',
          targetHandle: 'target',
        },
        {
          id: 'good-edge',
          source: 'start',
          sourceHandle: 'source',
          target: 'llm',
          targetHandle: 'target',
        },
      ],
    );

    const result = cleanupInvalidEdges(graph);
    const cleanedLlmNode = result.graph.nodes.find(
      (cleanedNode) => cleanedNode.id === 'llm',
    );

    expect(result.graph.edges.map((edge) => edge.id)).toEqual(['good-edge']);
    expect(cleanedLlmNode?.data).toMatchObject({
      knowledgeBases: [{ id: 'kb-1', name: '제품 정책' }],
      topK: 4,
      scoreThreshold: 0.6,
      dedupeRetrievedContext: true,
      retrievedContextMaxChars: 4000,
      retrievedContextCompression: 'light',
      answerGroundingCheck: 'basic',
    });
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
