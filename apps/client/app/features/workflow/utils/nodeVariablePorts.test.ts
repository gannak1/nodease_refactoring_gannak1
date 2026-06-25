import { describe, expect, it } from 'vitest';

import {
  applyDroppedOutputToNodeData,
  getNodeOutputVariables,
  upsertNamedSelector,
} from './nodeVariablePorts';
import { AppNode } from '../types/Nodes';

const makeNode = (
  type: NonNullable<AppNode['type']>,
  data: Record<string, unknown>,
): AppNode =>
  ({
    id: `${type}-1`,
    type,
    position: { x: 0, y: 0 },
    data: {
      title: `${type} title`,
      ...data,
    },
  }) as AppNode;

describe('nodeVariablePorts', () => {
  it('start node variables를 output chip으로 변환한다', () => {
    const node = makeNode('startNode', {
      variables: [
        { name: 'customer_message', label: '고객 문의' },
        { name: 'priority', label: '우선순위' },
      ],
    });

    expect(getNodeOutputVariables(node)).toEqual([
      {
        key: 'customer_message',
        label: '고객 문의',
        outputId: 'customer_message',
        sourceNodeId: 'startNode-1',
        sourceTitle: 'startNode title',
      },
      {
        key: 'priority',
        label: '우선순위',
        outputId: 'priority',
        sourceNodeId: 'startNode-1',
        sourceTitle: 'startNode title',
      },
    ]);
  });

  it('code node에 output을 drop하면 inputs source를 갱신한다', () => {
    const node = makeNode('codeNode', {
      inputs: [{ name: 'result', source: 'old-node.result' }],
      code: '',
      timeout: 10,
    });

    expect(
      applyDroppedOutputToNodeData(node, {
        key: 'result',
        label: 'result',
        sourceNodeId: 'source-node',
        sourceTitle: 'Source',
      }),
    ).toEqual({
      inputs: [{ name: 'result', source: 'source-node.result' }],
    });
  });

  it('llm node에 output을 drop하면 referenced_variables에 value selector를 추가한다', () => {
    const node = makeNode('llmNode', {
      referenced_variables: [],
      provider: '',
      model_id: '',
      parameters: {},
    });

    expect(
      applyDroppedOutputToNodeData(node, {
        key: 'text',
        label: 'text',
        sourceNodeId: 'source-node',
        sourceTitle: 'Source',
      }),
    ).toEqual({
      referenced_variables: [
        { name: 'text', value_selector: ['source-node', 'text'] },
      ],
    });
  });

  it('같은 output을 다시 drop하면 입력변수를 중복 추가하지 않고 selector를 갱신한다', () => {
    expect(
      upsertNamedSelector(
        [{ name: 'text', value_selector: ['old-node', 'text'] }],
        {
          key: 'text',
          label: 'text',
          sourceNodeId: 'source-node',
          sourceTitle: 'Source',
        },
        'value_selector',
      ),
    ).toEqual([{ name: 'text', value_selector: ['source-node', 'text'] }]);
  });

  it('condition node에 start output을 drop하면 변수 id로 첫 번째 조건을 갱신한다', () => {
    const node = makeNode('conditionNode', {
      cases: [
        {
          id: 'case-1',
          case_name: 'Default',
          conditions: [
            {
              id: 'condition-1',
              variable_selector: [],
              operator: 'equals',
              value: '',
            },
          ],
          logical_operator: 'and',
        },
      ],
    });

    const patch = applyDroppedOutputToNodeData(node, {
      key: 'customer_message',
      label: '고객 문의',
      outputId: 'start-variable-id',
      sourceNodeId: 'start-node',
      sourceTitle: 'Start',
    });

    expect(patch).toMatchObject({
      cases: [
        {
          conditions: [
            {
              variable_selector: ['start-node', 'start-variable-id'],
            },
          ],
        },
      ],
    });
  });
});
