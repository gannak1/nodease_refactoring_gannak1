import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { Edge } from '@xyflow/react';
import type { AppNode } from '../../types/Nodes';
import { calculateAutoLayout } from '../../utils/layoutHelpers';

type LayoutCase = {
  name: string;
  nodes: AppNode[];
  edges: Edge[];
  expected_positions: Record<string, { x: number; y: number }>;
};

const fixturePath = resolve(
  process.cwd(),
  '../../tests/fixtures/workflow_layout_cases.json',
);
const fixtures = JSON.parse(readFileSync(fixturePath, 'utf8')) as {
  cases: LayoutCase[];
};

describe('calculateAutoLayout canonical fixtures', () => {
  it.each(fixtures.cases)('$name', ({ nodes, edges, expected_positions }) => {
    const layouted = calculateAutoLayout(nodes, edges);
    const positions = Object.fromEntries(
      layouted.map((node) => [node.id, node.position]),
    );

    expect(positions).toEqual(expected_positions);
  });
});
