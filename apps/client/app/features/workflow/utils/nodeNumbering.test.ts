import { describe, expect, it } from 'vitest';
import type { Node } from '../types/Workflow';
import {
  assignMissingNodeDisplayNumbers,
  assignNewNodeDisplayNumbers,
} from './nodeNumbering';

const createNode = (
  id: string,
  displayNumber?: number,
  type: NonNullable<Node['type']> = 'startNode',
): Node =>
  ({
    id,
    type,
    position: { x: 0, y: 0 },
    data: {
      title: id,
      ...(displayNumber ? { displayNumber } : {}),
    },
  }) as Node;

describe('nodeNumbering', () => {
  it('복제된 workflow node에는 기존 displayNumber 대신 새 번호를 발급한다', () => {
    const existingNodes = [createNode('node-1', 1), createNode('node-2', 2)];
    const copiedNodes = [createNode('node-1-copy', 1)];

    const result = assignNewNodeDisplayNumbers(copiedNodes, existingNodes, {
      nextNodeDisplayNumber: 3,
    });

    expect(result.nodes[0].data.displayNumber).toBe(3);
    expect(result.features.nextNodeDisplayNumber).toBe(4);
  });

  it('삭제로 비어 있는 번호를 재사용하지 않고 nextNodeDisplayNumber를 따른다', () => {
    const existingNodes = [createNode('node-1', 1), createNode('node-3', 3)];
    const copiedNodes = [createNode('node-copy', 1)];

    const result = assignNewNodeDisplayNumbers(copiedNodes, existingNodes, {
      nextNodeDisplayNumber: 4,
    });

    expect(result.nodes[0].data.displayNumber).toBe(4);
    expect(result.features.nextNodeDisplayNumber).toBe(5);
  });

  it('note는 번호 발급 대상에서 제외하고 기존 displayNumber도 제거한다', () => {
    const note = createNode('note-1', 99, 'note');
    const result = assignNewNodeDisplayNumbers(
      [note],
      [createNode('node-1', 1)],
      {
        nextNodeDisplayNumber: 2,
      },
    );

    expect(result.nodes[0].data.displayNumber).toBeUndefined();
    expect(result.features.nextNodeDisplayNumber).toBe(2);
  });

  it('로드 보정 시 번호 누락과 중복을 보정하고 note 번호는 제거한다', () => {
    const numbered = createNode('node-1', 1);
    const duplicate = createNode('node-2', 1, 'answerNode');
    const missing = createNode('node-3', undefined, 'llmNode');
    const note = createNode('note-1', 42, 'note');

    const result = assignMissingNodeDisplayNumbers(
      [numbered, duplicate, missing, note],
      { nextNodeDisplayNumber: 2 },
    );

    expect(result.nodes.map((node) => node.data.displayNumber)).toEqual([
      1,
      2,
      3,
      undefined,
    ]);
    expect(result.features.nextNodeDisplayNumber).toBe(4);
  });
});
