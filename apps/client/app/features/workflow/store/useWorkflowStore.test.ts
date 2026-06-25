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
import type { Node } from '../types/Workflow';
import type { Edge, Connection } from '@xyflow/react';

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

const createMockNode = (
  id: string,
  type: NonNullable<Node['type']> = 'startNode',
  position = { x: 0, y: 0 },
): Node =>
  ({
    id,
    type,
    position,
    data: { title: `Node ${id}` } as Node['data'],
  }) as Node;

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
