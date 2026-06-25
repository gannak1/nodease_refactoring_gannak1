/**
 * useWorkflowStore 테스트
 *
 * Zustand 스토어의 상태 관리 및 워크플로우 에디터 핵심 기능을 테스트합니다.
 * - 노드 추가/삭제
 * - Edge 생성/삭제
 * - 스토어 상태 관리
 *
 * 실행 방법:
 *   cd apps/client
 *   npm test -- --run
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useWorkflowStore } from './useWorkflowStore';
import { workflowApi } from '../api/workflowApi';
import type { DeploymentResponse } from '../types/Deployment';
import type { AnswerNode, CodeNode, Node, StartNode } from '../types/Workflow';
import type { Edge, Connection } from '@xyflow/react';
import { DEFAULT_NODES } from '../constants';

// API 모킹
vi.mock('../api/workflowApi', () => ({
  workflowApi: {
    getDraftWorkflow: vi.fn(),
    syncDraftWorkflow: vi.fn(),
    createWorkflow: vi.fn(),
    listWorkflowsByApp: vi.fn(),
  },
}));

// 테스트용 초기 상태 저장 및 리셋 헬퍼
const initialState = useWorkflowStore.getState();
const resetStore = () => {
  vi.clearAllMocks();
  useWorkflowStore.setState(initialState, true);
};

// ============================================================================
// 테스트용 Fixture 데이터
// ============================================================================

const createStartNode = (
  id: string,
  data: Partial<StartNode['data']> & Record<string, unknown> = {},
  position = { x: 0, y: 0 },
): StartNode => ({
  id,
  type: 'startNode',
  position,
  data: {
    title: `Node ${id}`,
    triggerType: 'manual',
    variables: [],
    ...data,
  },
});

const createAnswerNode = (
  id: string,
  data: Partial<AnswerNode['data']> & Record<string, unknown> = {},
  position = { x: 0, y: 0 },
): AnswerNode => ({
  id,
  type: 'answerNode',
  position,
  data: {
    title: `Node ${id}`,
    outputs: [],
    ...data,
  },
});

const createCodeNode = (
  id: string,
  data: Partial<CodeNode['data']> & Record<string, unknown> = {},
  position = { x: 0, y: 0 },
): CodeNode => ({
  id,
  type: 'codeNode',
  position,
  data: {
    title: `Node ${id}`,
    code: 'def main(inputs):\n    return {}',
    inputs: [],
    timeout: 10,
    ...data,
  },
});

const createMockNode = (
  id: string,
  type: NonNullable<Node['type']> = 'startNode',
  position = { x: 0, y: 0 },
): Node => {
  if (type === 'answerNode') return createAnswerNode(id, {}, position);
  if (type === 'codeNode') return createCodeNode(id, {}, position);
  if (type === 'startNode') return createStartNode(id, {}, position);
  return {
    id,
    type,
    position,
    data: { title: `Node ${id}` } as Node['data'],
  } as Node;
};

const createMockEdge = (id: string, source: string, target: string): Edge => ({
  id,
  source,
  target,
});

// ============================================================================
// 1. 노드 추가/삭제 테스트
// ============================================================================

describe('노드 추가/삭제 테스트', () => {
  beforeEach(() => {
    resetStore();
  });

  it('setNodes로 노드를 설정할 수 있다', () => {
    const nodes: Node[] = [
      createMockNode('node-1', 'startNode'),
      createMockNode('node-2', 'answerNode'),
    ];

    useWorkflowStore.getState().setNodes(nodes);

    const state = useWorkflowStore.getState();
    expect(state.nodes).toHaveLength(2);
    expect(state.nodes[0].id).toBe('node-1');
    expect(state.nodes[1].id).toBe('node-2');
  });

  it('onNodesChange로 노드를 추가할 수 있다', () => {
    // 초기 노드 설정
    useWorkflowStore.getState().setNodes([createMockNode('node-1')]);

    // 노드 추가 변경 적용
    const newNode = createMockNode('node-2', 'answerNode');
    useWorkflowStore.getState().onNodesChange([{ type: 'add', item: newNode }]);

    const state = useWorkflowStore.getState();
    expect(state.nodes).toHaveLength(2);
  });

  it('onNodesChange로 노드를 삭제할 수 있다', () => {
    // 초기에 2개 노드 설정
    useWorkflowStore
      .getState()
      .setNodes([createMockNode('node-1'), createMockNode('node-2')]);

    // node-1 삭제
    useWorkflowStore
      .getState()
      .onNodesChange([{ type: 'remove', id: 'node-1' }]);

    const state = useWorkflowStore.getState();
    expect(state.nodes).toHaveLength(1);
    expect(state.nodes[0].id).toBe('node-2');
  });

  it('onNodesChange로 노드 위치를 변경할 수 있다', () => {
    useWorkflowStore.getState().setNodes([createMockNode('node-1')]);

    useWorkflowStore.getState().onNodesChange([
      {
        type: 'position',
        id: 'node-1',
        position: { x: 100, y: 200 },
      },
    ]);

    const state = useWorkflowStore.getState();
    expect(state.nodes[0].position).toEqual({ x: 100, y: 200 });
  });

  it('기본 10px grid snap으로 노드 위치를 보정한다', () => {
    useWorkflowStore.getState().setNodes([createMockNode('node-1')]);

    useWorkflowStore.getState().onNodesChange([
      {
        type: 'position',
        id: 'node-1',
        position: { x: 104, y: 207 },
      },
    ]);

    const state = useWorkflowStore.getState();
    expect(state.nodes[0].position).toEqual({ x: 100, y: 210 });
  });

  it.each([
    {
      gridSize: 5 as const,
      position: { x: 103, y: 207 },
      expected: { x: 105, y: 205 },
    },
    {
      gridSize: 20 as const,
      position: { x: 111, y: 231 },
      expected: { x: 120, y: 240 },
    },
  ])(
    '$gridSize px grid snap으로 노드 위치를 보정한다',
    ({ gridSize, position, expected }) => {
      useWorkflowStore.getState().setSnapGridSize(gridSize);
      useWorkflowStore.getState().setNodes([createMockNode('node-1')]);

      useWorkflowStore.getState().onNodesChange([
        {
          type: 'position',
          id: 'node-1',
          position,
        },
      ]);

      const state = useWorkflowStore.getState();
      expect(state.nodes[0].position).toEqual(expected);
    },
  );

  it('snap 설정이 off면 노드 위치를 보정하지 않는다', () => {
    useWorkflowStore.getState().setSnapGridSize('off');
    useWorkflowStore.getState().setNodes([createMockNode('node-1')]);

    useWorkflowStore.getState().onNodesChange([
      {
        type: 'position',
        id: 'node-1',
        position: { x: 104, y: 207 },
      },
    ]);

    const state = useWorkflowStore.getState();
    expect(state.nodes[0].position).toEqual({ x: 104, y: 207 });
  });

  it('Alt로 snap이 임시 해제되면 노드 위치를 보정하지 않는다', () => {
    useWorkflowStore.getState().setSnapTemporarilyDisabled(true);
    useWorkflowStore.getState().setNodes([createMockNode('node-1')]);

    useWorkflowStore.getState().onNodesChange([
      {
        type: 'position',
        id: 'node-1',
        position: { x: 104, y: 207 },
      },
    ]);

    const state = useWorkflowStore.getState();
    expect(state.nodes[0].position).toEqual({ x: 104, y: 207 });
  });

  it('여러 노드 이동 시 그룹 origin의 snap delta로 상대 위치를 유지한다', () => {
    useWorkflowStore.getState().setNodes([
      createMockNode('node-1', 'startNode', { x: 3, y: 7 }),
      createMockNode('node-2', 'answerNode', { x: 18, y: 32 }),
    ]);

    useWorkflowStore.getState().onNodesChange([
      {
        type: 'position',
        id: 'node-1',
        position: { x: 16, y: 23 },
      },
      {
        type: 'position',
        id: 'node-2',
        position: { x: 31, y: 48 },
      },
    ]);

    const state = useWorkflowStore.getState();
    expect(state.nodes[0].position).toEqual({ x: 20, y: 20 });
    expect(state.nodes[1].position).toEqual({ x: 35, y: 45 });
  });

  it('positionChanges 순서가 노드 순서와 달라도 그룹 상대 위치를 유지한다', () => {
    useWorkflowStore.getState().setNodes([
      createMockNode('node-1', 'startNode', { x: 3, y: 7 }),
      createMockNode('node-2', 'answerNode', { x: 18, y: 32 }),
      createMockNode('node-3', 'codeNode', { x: 41, y: 11 }),
    ]);

    useWorkflowStore.getState().onNodesChange([
      {
        type: 'position',
        id: 'node-3',
        position: { x: 54, y: 27 },
      },
      {
        type: 'position',
        id: 'node-2',
        position: { x: 31, y: 48 },
      },
      {
        type: 'position',
        id: 'node-1',
        position: { x: 16, y: 23 },
      },
    ]);

    const state = useWorkflowStore.getState();
    expect(state.nodes[0].position).toEqual({ x: 20, y: 20 });
    expect(state.nodes[1].position).toEqual({ x: 35, y: 45 });
    expect(state.nodes[2].position).toEqual({ x: 58, y: 24 });
  });
});

// ============================================================================
// 1-1. 캔버스 히스토리/클립보드 테스트
// ============================================================================

describe('캔버스 히스토리/클립보드 테스트', () => {
  beforeEach(() => {
    resetStore();
  });

  it('undo/redo로 그래프 변경을 되돌리고 다시 적용할 수 있다', () => {
    useWorkflowStore.getState().setNodes([createMockNode('node-1')]);
    useWorkflowStore
      .getState()
      .setNodes([createMockNode('node-1'), createMockNode('node-2')]);

    useWorkflowStore.getState().undo();
    expect(useWorkflowStore.getState().nodes).toHaveLength(1);
    expect(useWorkflowStore.getState().nodes[0].id).toBe('node-1');

    useWorkflowStore.getState().redo();
    expect(useWorkflowStore.getState().nodes).toHaveLength(2);
    expect(useWorkflowStore.getState().nodes[1].id).toBe('node-2');
  });

  it('선택 변경은 undo 스택에 기록하지 않는다', () => {
    useWorkflowStore.getState().setNodes([createMockNode('node-1')]);
    useWorkflowStore.getState().onNodesChange([
      { type: 'select', id: 'node-1', selected: true },
    ]);

    useWorkflowStore.getState().undo();
    expect(useWorkflowStore.getState().nodes).toHaveLength(
      DEFAULT_NODES.length,
    );
  });

  it('선택 노드를 복사하고 붙여넣을 때 새 ID와 오프셋 위치를 부여한다', () => {
    const selectedNode = {
      ...createMockNode('node-1'),
      selected: true,
      position: { x: 10, y: 20 },
    };
    useWorkflowStore.getState().setNodes([selectedNode]);

    useWorkflowStore.getState().copySelectedNodes();
    useWorkflowStore.getState().pasteCopiedNodes();

    const pastedNode = useWorkflowStore
      .getState()
      .nodes.find((node) => node.id !== 'node-1');

    expect(useWorkflowStore.getState().nodes).toHaveLength(2);
    expect(pastedNode?.id).toContain('node-1-copy-');
    expect(pastedNode?.selected).toBe(true);
    expect(pastedNode?.position).toEqual({ x: 50, y: 60 });
  });

  it('붙여넣은 노드 데이터의 내부 노드 참조를 새 ID로 재매핑한다', () => {
    useWorkflowStore.getState().setNodes([
      {
        ...createMockNode('source-node'),
        selected: true,
        position: { x: 0, y: 0 },
      },
      {
        ...createAnswerNode('target-node', {
          title: 'Target',
          value_selector: ['source-node', 'output'],
        }),
        selected: true,
        position: { x: 100, y: 0 },
      },
    ]);

    useWorkflowStore.getState().copySelectedNodes();
    useWorkflowStore.getState().pasteCopiedNodes();

    const pastedSource = useWorkflowStore
      .getState()
      .nodes.find((node) => node.id.startsWith('source-node-copy-'));
    const pastedTarget = useWorkflowStore
      .getState()
      .nodes.find((node) => node.id.startsWith('target-node-copy-'));

    expect(pastedTarget?.data.value_selector).toEqual([
      pastedSource?.id,
      'output',
    ]);
  });

  it('붙여넣기 재매핑은 참조 필드만 바꾸고 사용자 텍스트와 displayNumber는 복제하지 않는다', () => {
    useWorkflowStore.getState().setNodes([
      {
        ...createStartNode('source-node', {
          title: 'source-node',
          description: 'source-node',
          content: 'source-node',
          displayNumber: 12,
        }),
        selected: true,
      },
      {
        ...createAnswerNode('target-node', {
          title: 'Target',
          value_selector: ['source-node', 'output'],
        }),
        selected: true,
      },
    ]);

    useWorkflowStore.getState().copySelectedNodes();
    useWorkflowStore.getState().pasteCopiedNodes();

    const pastedSource = useWorkflowStore
      .getState()
      .nodes.find((node) => node.id.startsWith('source-node-copy-'));
    const pastedTarget = useWorkflowStore
      .getState()
      .nodes.find((node) => node.id.startsWith('target-node-copy-'));

    expect(pastedSource?.data.title).toBe('source-node');
    expect(pastedSource?.data.description).toBe('source-node');
    expect(pastedSource?.data.content).toBe('source-node');
    expect(pastedSource?.data.displayNumber).toBeUndefined();
    expect(pastedTarget?.data.value_selector).toEqual([
      pastedSource?.id,
      'output',
    ]);
  });

  it('selector 배열은 첫 번째 슬롯만 새 ID로 재매핑하고 이후 key 값은 보존한다', () => {
    useWorkflowStore.getState().setNodes([
      {
        ...createMockNode('source-node'),
        selected: true,
      },
      {
        ...createMockNode('target-node'),
        selected: true,
      },
      {
        ...createAnswerNode('consumer-node', {
          title: 'Consumer',
          value_selector: ['source-node', 'target-node'],
        }),
        selected: true,
      },
    ]);

    useWorkflowStore.getState().duplicateSelectedNodes();

    const duplicatedSource = useWorkflowStore
      .getState()
      .nodes.find((node) => node.id.startsWith('source-node-copy-'));
    const duplicatedConsumer = useWorkflowStore
      .getState()
      .nodes.find((node) => node.id.startsWith('consumer-node-copy-'));

    expect(duplicatedConsumer?.data.value_selector).toEqual([
      duplicatedSource?.id,
      'target-node',
    ]);
  });

  it('선택 노드를 즉시 복제하고 클립보드 상태는 덮어쓰지 않는다', () => {
    useWorkflowStore.getState().setNodes([
      { ...createMockNode('clipboard-node'), selected: true },
    ]);
    useWorkflowStore.getState().copySelectedNodes();

    useWorkflowStore.getState().setNodes([
      {
        ...createStartNode('source-node', {
          title: 'source-node',
          description: 'source-node',
          content: 'source-node',
          name: 'source-node',
          displayNumber: 12,
        }),
        selected: true,
        position: { x: 10, y: 20 },
      },
      {
        ...createAnswerNode('target-node', {
          title: 'Target',
          value_selector: ['source-node', 'output'],
        }),
        selected: true,
        position: { x: 100, y: 20 },
      },
    ]);
    useWorkflowStore
      .getState()
      .setEdges([
        createMockEdge('edge-source-target', 'source-node', 'target-node'),
      ]);

    useWorkflowStore.getState().duplicateSelectedNodes();

    const state = useWorkflowStore.getState();
    const duplicatedSource = state.nodes.find((node) =>
      node.id.startsWith('source-node-copy-'),
    );
    const duplicatedTarget = state.nodes.find((node) =>
      node.id.startsWith('target-node-copy-'),
    );
    const duplicatedEdge = state.edges.find((edge) =>
      edge.id.startsWith('edge-source-target-copy-'),
    );

    expect(state.nodes).toHaveLength(4);
    expect(duplicatedSource?.selected).toBe(true);
    expect(duplicatedTarget?.selected).toBe(true);
    expect(duplicatedSource?.position).toEqual({ x: 50, y: 60 });
    expect(duplicatedTarget?.position).toEqual({ x: 140, y: 60 });
    expect(duplicatedEdge?.source).toBe(duplicatedSource?.id);
    expect(duplicatedEdge?.target).toBe(duplicatedTarget?.id);
    expect(duplicatedTarget?.data.value_selector).toEqual([
      duplicatedSource?.id,
      'output',
    ]);
    expect(duplicatedSource?.data.title).toBe('source-node');
    expect(duplicatedSource?.data.description).toBe('source-node');
    expect(duplicatedSource?.data.content).toBe('source-node');
    expect(duplicatedSource?.data.name).toBe('source-node');
    expect(duplicatedSource?.data.displayNumber).toBeUndefined();
    expect(state.copiedNodes.map((node) => node.id)).toEqual([
      'clipboard-node',
    ]);
  });

  it('code node와 upstream node를 함께 복제하면 inputs[].source의 node id만 새 ID로 재매핑한다', () => {
    useWorkflowStore.getState().setNodes([
      {
        ...createStartNode('source-node'),
        selected: true,
      },
      {
        ...createCodeNode('code-node', {
          inputs: [
            { name: 'result', source: 'source-node.output' },
            { name: 'external', source: 'external-node.output' },
            { name: 'literal', source: 'plain-user-text' },
          ],
        }),
        selected: true,
      },
    ]);

    useWorkflowStore.getState().duplicateSelectedNodes();

    const duplicatedSource = useWorkflowStore
      .getState()
      .nodes.find((node) => node.id.startsWith('source-node-copy-'));
    const duplicatedCode = useWorkflowStore
      .getState()
      .nodes.find(
        (node): node is CodeNode =>
          node.type === 'codeNode' && node.id.startsWith('code-node-copy-'),
      );

    expect(duplicatedCode?.data.inputs).toEqual([
      { name: 'result', source: `${duplicatedSource?.id}.output` },
      { name: 'external', source: 'external-node.output' },
      { name: 'literal', source: 'plain-user-text' },
    ]);
  });

  it('code node와 upstream node를 함께 붙여넣으면 inputs[].source의 node id만 새 ID로 재매핑한다', () => {
    useWorkflowStore.getState().setNodes([
      {
        ...createStartNode('source-node'),
        selected: true,
      },
      {
        ...createCodeNode('code-node', {
          inputs: [{ name: 'result', source: 'source-node.output' }],
        }),
        selected: true,
      },
    ]);

    useWorkflowStore.getState().copySelectedNodes();
    useWorkflowStore.getState().pasteCopiedNodes();

    const pastedSource = useWorkflowStore
      .getState()
      .nodes.find((node) => node.id.startsWith('source-node-copy-'));
    const pastedCode = useWorkflowStore
      .getState()
      .nodes.find(
        (node): node is CodeNode =>
          node.type === 'codeNode' && node.id.startsWith('code-node-copy-'),
      );

    expect(pastedCode?.data.inputs).toEqual([
      { name: 'result', source: `${pastedSource?.id}.output` },
    ]);
  });

  it('드래그 중 position 변경은 드래그 시작 지점 하나만 undo 스냅샷으로 기록한다', () => {
    useWorkflowStore.getState().setNodes([createMockNode('node-1')]);

    useWorkflowStore.getState().onNodesChange([
      {
        type: 'position',
        id: 'node-1',
        position: { x: 50, y: 50 },
        dragging: true,
      },
    ]);
    useWorkflowStore.getState().onNodesChange([
      {
        type: 'position',
        id: 'node-1',
        position: { x: 100, y: 100 },
        dragging: false,
      },
    ]);

    expect(useWorkflowStore.getState().nodes[0].position).toEqual({
      x: 100,
      y: 100,
    });

    useWorkflowStore.getState().undo();
    expect(useWorkflowStore.getState().nodes[0].position).toEqual({
      x: 0,
      y: 0,
    });
  });

  it('선택 노드를 삭제할 때 연결된 엣지도 함께 제거한다', () => {
    useWorkflowStore.getState().setNodes([
      { ...createMockNode('node-1'), selected: true },
      createMockNode('node-2'),
    ]);
    useWorkflowStore
      .getState()
      .setEdges([createMockEdge('edge-1', 'node-1', 'node-2')]);

    useWorkflowStore.getState().deleteSelectedElements();

    const state = useWorkflowStore.getState();
    expect(state.nodes).toHaveLength(1);
    expect(state.nodes[0].id).toBe('node-2');
    expect(state.edges).toHaveLength(0);
  });
});

// ============================================================================
// 2. Edge 생성/삭제 테스트
// ============================================================================

describe('Edge 생성/삭제 테스트', () => {
  beforeEach(() => {
    resetStore();
  });

  it('setEdges로 엣지를 설정할 수 있다', () => {
    const edges: Edge[] = [
      createMockEdge('edge-1', 'node-1', 'node-2'),
      createMockEdge('edge-2', 'node-2', 'node-3'),
    ];

    useWorkflowStore.getState().setEdges(edges);

    const state = useWorkflowStore.getState();
    expect(state.edges).toHaveLength(2);
    expect(state.edges[0].source).toBe('node-1');
    expect(state.edges[0].target).toBe('node-2');
  });

  it('onConnect로 새 엣지를 생성할 수 있다', () => {
    // 초기 엣지 없음
    useWorkflowStore.getState().setEdges([]);

    // 연결 생성
    const connection: Connection = {
      source: 'node-1',
      target: 'node-2',
      sourceHandle: null,
      targetHandle: null,
    };
    useWorkflowStore.getState().onConnect(connection);

    const state = useWorkflowStore.getState();
    expect(state.edges).toHaveLength(1);
    expect(state.edges[0].source).toBe('node-1');
    expect(state.edges[0].target).toBe('node-2');
  });

  it('onEdgesChange로 엣지를 삭제할 수 있다', () => {
    // 초기에 2개 엣지 설정
    useWorkflowStore
      .getState()
      .setEdges([
        createMockEdge('edge-1', 'node-1', 'node-2'),
        createMockEdge('edge-2', 'node-2', 'node-3'),
      ]);

    // edge-1 삭제
    useWorkflowStore
      .getState()
      .onEdgesChange([{ type: 'remove', id: 'edge-1' }]);

    const state = useWorkflowStore.getState();
    expect(state.edges).toHaveLength(1);
    expect(state.edges[0].id).toBe('edge-2');
  });
});

// ============================================================================
// 3. Zustand 스토어 상태 관리 테스트
// ============================================================================

describe('Zustand 스토어 상태 관리 테스트', () => {
  beforeEach(() => {
    resetStore();
  });

  it('updateNodeData로 특정 노드의 데이터를 업데이트할 수 있다', () => {
    const node = createMockNode('node-1');
    useWorkflowStore.getState().setNodes([node]);

    useWorkflowStore.getState().updateNodeData('node-1', {
      title: '업데이트된 제목',
      newField: 'newValue',
    });

    const state = useWorkflowStore.getState();
    expect(state.nodes[0].data.title).toBe('업데이트된 제목');
    expect(state.nodes[0].data.newField).toBe('newValue');
  });

  it('setWorkflowData로 전체 워크플로우 데이터를 설정할 수 있다', () => {
    const nodes: Node[] = [createMockNode('node-1'), createMockNode('node-2')];
    const edges: Edge[] = [createMockEdge('edge-1', 'node-1', 'node-2')];

    useWorkflowStore.getState().setWorkflowData({
      nodes,
      edges,
      viewport: { x: 100, y: 200, zoom: 1.5 },
      features: { key: 'value' },
      envVariables: [
        { id: 'env-1', key: 'API_KEY', value: 'secret', type: 'string' },
      ],
    });

    const state = useWorkflowStore.getState();
    expect(state.nodes).toHaveLength(2);
    expect(state.edges).toHaveLength(1);
    expect(state.features).toMatchObject({ key: 'value' });
    expect(state.envVariables).toHaveLength(1);
  });

  it('setFeatures로 기능 설정을 업데이트할 수 있다', () => {
    useWorkflowStore.getState().setFeatures({ debug: true, logging: false });

    const state = useWorkflowStore.getState();
    expect(state.features).toEqual({ debug: true, logging: false });
    expect(state.workflows[0].features).toEqual({
      debug: true,
      logging: false,
    });
  });

  it('setEnvVariables로 환경 변수를 설정할 수 있다', () => {
    useWorkflowStore.getState().setEnvVariables([
      { id: 'env-1', key: 'API_KEY', value: 'key123', type: 'string' },
      { id: 'env-2', key: 'DEBUG', value: 'true', type: 'string' },
    ]);

    const state = useWorkflowStore.getState();
    expect(state.envVariables).toHaveLength(2);
    expect(state.envVariables[0].key).toBe('API_KEY');
  });
});

// ============================================================================
// 4. 워크플로우 관리 테스트
// ============================================================================

describe('워크플로우 관리 테스트', () => {
  beforeEach(() => {
    resetStore();
  });

  it('setActiveWorkflow로 활성 워크플로우를 변경할 수 있다', () => {
    // 여러 워크플로우 설정
    useWorkflowStore.setState({
      workflows: [
        {
          id: 'wf-1',
          appId: 'app-1',
          nodes: [createMockNode('n1')],
          edges: [],
          features: { nextNodeDisplayNumber: 10 },
        },
        {
          id: 'wf-2',
          appId: 'app-1',
          nodes: [createMockNode('n2')],
          edges: [],
          features: { nextNodeDisplayNumber: 20 },
        },
      ],
      activeWorkflowId: 'wf-1',
    });

    // wf-2로 변경
    useWorkflowStore.getState().setActiveWorkflow('wf-2');

    const state = useWorkflowStore.getState();
    expect(state.activeWorkflowId).toBe('wf-2');
    expect(state.nodes[0].id).toBe('n2');
    expect(state.features.nextNodeDisplayNumber).toBe(20);
  });

  it('setActiveWorkflowIdSafe는 로드된 대상 워크플로우의 nodes/edges/features를 반영한다', () => {
    useWorkflowStore.setState({
      workflows: [
        {
          id: 'wf-1',
          appId: 'app-1',
          nodes: [createMockNode('n1')],
          edges: [],
          features: { nextNodeDisplayNumber: 10 },
        },
        {
          id: 'wf-2',
          appId: 'app-1',
          nodes: [createMockNode('n2')],
          edges: [],
          features: { nextNodeDisplayNumber: 20 },
        },
      ],
      activeWorkflowId: 'wf-1',
      nodes: [createMockNode('draft-node')],
      edges: [createMockEdge('edge-1', 'draft-node', 'n1')],
      features: { nextNodeDisplayNumber: 10 },
    });

    useWorkflowStore.getState().setActiveWorkflowIdSafe('wf-2');

    const state = useWorkflowStore.getState();
    expect(state.activeWorkflowId).toBe('wf-2');
    expect(state.nodes[0].id).toBe('n2');
    expect(state.edges).toEqual([]);
    expect(state.features.nextNodeDisplayNumber).toBe(20);
  });

  it('setActiveWorkflowIdSafe는 대상 workflow가 없으면 id만 변경한다', () => {
    const currentNodes = [createMockNode('draft-node')];
    const currentEdges = [createMockEdge('edge-1', 'draft-node', 'n1')];

    useWorkflowStore.setState({
      workflows: [
        {
          id: 'wf-1',
          appId: 'app-1',
          nodes: [createMockNode('n1')],
          edges: [],
          features: { nextNodeDisplayNumber: 10 },
        },
      ],
      activeWorkflowId: 'wf-1',
      nodes: currentNodes,
      edges: currentEdges,
      features: { nextNodeDisplayNumber: 10 },
    });

    useWorkflowStore.getState().setActiveWorkflowIdSafe('wf-missing');

    const state = useWorkflowStore.getState();
    expect(state.activeWorkflowId).toBe('wf-missing');
    expect(state.nodes).toBe(currentNodes);
    expect(state.edges).toBe(currentEdges);
    expect(state.features.nextNodeDisplayNumber).toBe(10);
  });

  it('inactive workflow 데이터가 먼저 로드된 뒤 safe active 전환 시 화면 store에 반영한다', () => {
    useWorkflowStore.setState({
      activeWorkflowId: 'wf-1',
      workflows: [
        {
          id: 'wf-1',
          appId: 'app-1',
          nodes: [createMockNode('wf-1-node')],
          edges: [],
          features: { nextNodeDisplayNumber: 10 },
        },
        {
          id: 'wf-2',
          appId: 'app-1',
          nodes: [],
          edges: [],
          features: { nextNodeDisplayNumber: 1 },
        },
      ],
      nodes: [createMockNode('wf-1-node')],
      edges: [],
      features: { nextNodeDisplayNumber: 10 },
    });

    const wf2Nodes = [createMockNode('wf-2-node', 'answerNode')];
    const wf2Edges = [createMockEdge('wf-2-edge', 'wf-2-node', 'wf-2-node')];

    useWorkflowStore.getState().setWorkflowData(
      {
        nodes: wf2Nodes,
        edges: wf2Edges,
        viewport: { x: 0, y: 0, zoom: 1 },
        features: { nextNodeDisplayNumber: 42 },
      },
      'wf-2',
    );

    let state = useWorkflowStore.getState();
    expect(state.activeWorkflowId).toBe('wf-1');
    expect(state.nodes[0].id).toBe('wf-1-node');
    expect(state.features.nextNodeDisplayNumber).toBe(10);
    expect(
      state.workflows.find((workflow) => workflow.id === 'wf-2')?.features
        .nextNodeDisplayNumber,
    ).toBe(43);

    useWorkflowStore.getState().setActiveWorkflowIdSafe('wf-2');

    state = useWorkflowStore.getState();
    expect(state.activeWorkflowId).toBe('wf-2');
    expect(state.nodes[0].id).toBe('wf-2-node');
    expect(state.edges[0].id).toBe('wf-2-edge');
    expect(state.features.nextNodeDisplayNumber).toBe(43);
    expect(
      state.workflows.find((workflow) => workflow.id === 'wf-1')?.features
        .nextNodeDisplayNumber,
    ).toBe(10);
  });

  it('deleteWorkflow로 워크플로우를 삭제할 수 있다', () => {
    useWorkflowStore.setState({
      workflows: [
        {
          id: 'wf-1',
          appId: 'app-1',
          nodes: [],
          edges: [],
          features: { nextNodeDisplayNumber: 10 },
        },
        {
          id: 'wf-2',
          appId: 'app-1',
          nodes: [],
          edges: [],
          features: { nextNodeDisplayNumber: 20 },
        },
      ],
      activeWorkflowId: 'wf-1',
    });

    useWorkflowStore.getState().deleteWorkflow('wf-1');

    const state = useWorkflowStore.getState();
    expect(state.workflows).toHaveLength(1);
    expect(state.workflows[0].id).toBe('wf-2');
    // 삭제된 워크플로우가 활성이었으면 다른 워크플로우로 전환
    expect(state.activeWorkflowId).toBe('wf-2');
    expect(state.features.nextNodeDisplayNumber).toBe(20);
  });

  it('updateWorkflowViewport로 뷰포트를 업데이트할 수 있다', () => {
    useWorkflowStore.setState({
      workflows: [
        {
          id: 'wf-1',
          appId: 'app-1',
          nodes: [],
          edges: [],
          features: { nextNodeDisplayNumber: 1 },
          viewport: { x: 0, y: 0, zoom: 1 },
        },
      ],
    });

    useWorkflowStore
      .getState()
      .updateWorkflowViewport('wf-1', { x: 50, y: 100, zoom: 2 });

    const state = useWorkflowStore.getState();
    expect(state.workflows[0].viewport).toEqual({ x: 50, y: 100, zoom: 2 });
  });

  it('addNode는 현재 nodes/features를 읽어 번호와 workflow features를 함께 갱신한다', () => {
    useWorkflowStore.setState({
      activeWorkflowId: 'wf-1',
      workflows: [
        {
          id: 'wf-1',
          appId: 'app-1',
          nodes: [createMockNode('n1')],
          edges: [],
          features: { nextNodeDisplayNumber: 3 },
        },
      ],
      nodes: [
        {
          id: 'n1',
          type: 'startNode',
          position: { x: 0, y: 0 },
          data: {
            title: 'Node n1',
            triggerType: 'manual',
            variables: [],
            displayNumber: 1,
          },
        } as Node,
      ],
      features: { nextNodeDisplayNumber: 3 },
    });

    const added = useWorkflowStore
      .getState()
      .addNode(createMockNode('n2', 'answerNode'));

    const state = useWorkflowStore.getState();
    expect(added.data.displayNumber).toBe(3);
    expect(state.nodes[1].data.displayNumber).toBe(3);
    expect(state.features.nextNodeDisplayNumber).toBe(4);
    expect(state.workflows[0].features.nextNodeDisplayNumber).toBe(4);
  });

  it('restoreVersion은 snapshot 번호를 보정한 뒤 draft와 store에 반영한다', async () => {
    useWorkflowStore.setState({
      activeWorkflowId: 'wf-1',
      workflows: [
        {
          id: 'wf-1',
          appId: 'app-1',
          nodes: [],
          edges: [],
          features: { nextNodeDisplayNumber: 1 },
        },
      ],
    });

    const version = {
      id: 'deployment-1',
      app_id: 'app-1',
      version: 1,
      created_by: 'user-1',
      created_at: '2026-06-25T00:00:00Z',
      type: 'api',
      is_active: false,
      graph_snapshot: {
        nodes: [
          createMockNode('n1', 'startNode'),
          createMockNode('n2', 'answerNode'),
          createMockNode('note-1', 'note'),
        ],
        edges: [],
        features: { nextNodeDisplayNumber: 1 },
      },
    } as DeploymentResponse;

    await useWorkflowStore.getState().restoreVersion(version);

    expect(workflowApi.syncDraftWorkflow).toHaveBeenCalledWith(
      'wf-1',
      expect.objectContaining({
        nodes: expect.arrayContaining([
          expect.objectContaining({
            id: 'n1',
            data: expect.objectContaining({ displayNumber: 1 }),
          }),
          expect.objectContaining({
            id: 'n2',
            data: expect.objectContaining({ displayNumber: 2 }),
          }),
          expect.objectContaining({
            id: 'note-1',
            data: expect.not.objectContaining({
              displayNumber: expect.any(Number),
            }),
          }),
        ]),
        features: expect.objectContaining({ nextNodeDisplayNumber: 3 }),
      }),
    );

    const state = useWorkflowStore.getState();
    expect(state.nodes.map((node) => node.data.displayNumber)).toEqual([
      1,
      2,
      undefined,
    ]);
    expect(state.features.nextNodeDisplayNumber).toBe(3);
  });
});

// ============================================================================
// 5. UI 상태 테스트
// ============================================================================

describe('UI 상태 테스트', () => {
  beforeEach(() => {
    resetStore();
  });

  it('toggleFullscreen으로 전체 화면 상태를 토글 할 수 있다', () => {
    expect(useWorkflowStore.getState().isFullscreen).toBe(false);

    useWorkflowStore.getState().toggleFullscreen();
    expect(useWorkflowStore.getState().isFullscreen).toBe(true);

    useWorkflowStore.getState().toggleFullscreen();
    expect(useWorkflowStore.getState().isFullscreen).toBe(false);
  });

  it('setInteractiveMode로 입력 모드를 변경할 수 있다', () => {
    expect(useWorkflowStore.getState().interactiveMode).toBe('mouse');

    useWorkflowStore.getState().setInteractiveMode('touchpad');
    expect(useWorkflowStore.getState().interactiveMode).toBe('touchpad');
  });

  it('toggleVersionHistory로 버전 기록 패널을 토글할 수 있다', () => {
    expect(useWorkflowStore.getState().isVersionHistoryOpen).toBe(false);

    useWorkflowStore.getState().toggleVersionHistory();
    expect(useWorkflowStore.getState().isVersionHistoryOpen).toBe(true);
  });

  it('setProjectInfo로 프로젝트 정보를 설정할 수 있다', () => {
    useWorkflowStore.getState().setProjectInfo('새 프로젝트', {
      type: 'emoji',
      content: '🚀',
      background_color: '#E0F7FA',
    });

    const state = useWorkflowStore.getState();
    expect(state.projectName).toBe('새 프로젝트');
    expect(state.projectIcon.content).toBe('🚀');
  });

  it('triggerWorkflowRun으로 실행 트리거를 증가시킬 수 있다', () => {
    const initialTrigger = useWorkflowStore.getState().runTrigger;

    useWorkflowStore.getState().triggerWorkflowRun();
    expect(useWorkflowStore.getState().runTrigger).toBe(initialTrigger + 1);

    useWorkflowStore.getState().triggerWorkflowRun();
    expect(useWorkflowStore.getState().runTrigger).toBe(initialTrigger + 2);
  });
});
