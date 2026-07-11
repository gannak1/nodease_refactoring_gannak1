import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { nodeTypes } from '../components/nodes';
import { getImplementedNodes } from './nodeRegistry';

type CatalogNode = {
  node_type: string;
  implemented: boolean;
  agent_builder_supported: boolean;
};

const catalog = JSON.parse(
  readFileSync(
    resolve(
      process.cwd(),
      '../../apps/shared/config/workflow_node_catalog.json',
    ),
    'utf8',
  ),
) as { nodes: CatalogNode[] };

const sorted = (items: string[]) => [...items].sort();

describe('workflow node capability catalog', () => {
  it('matches the implemented frontend node library and React Flow registry', () => {
    const implementedTypes = catalog.nodes
      .filter((node) => node.implemented)
      .map((node) => node.node_type);

    expect(sorted(getImplementedNodes().map((node) => node.type))).toEqual(
      sorted(implementedTypes),
    );
    expect(sorted(Object.keys(nodeTypes))).toEqual(sorted(implementedTypes));
  });

  it('excludes product-unavailable nodes from Agent Builder', () => {
    const implementedTypes = catalog.nodes
      .filter((node) => node.implemented)
      .map((node) => node.node_type);
    const builderTypes = catalog.nodes
      .filter((node) => node.agent_builder_supported)
      .map((node) => node.node_type);

    expect(sorted(builderTypes)).toEqual(
      sorted(implementedTypes.filter((nodeType) => nodeType !== 'loopNode')),
    );
  });
});
