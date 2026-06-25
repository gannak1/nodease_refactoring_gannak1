import type { Features } from '../types/Workflow';
import type { AppNode } from '../types/Nodes';

export const NODE_NUMBER_FEATURE_KEY = 'nextNodeDisplayNumber';

const isValidNodeNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isInteger(value) && value > 0;

export const shouldAssignNodeDisplayNumber = (node: AppNode) =>
  node.type !== 'note';

const withoutNodeDisplayNumber = <T extends AppNode>(node: T): T => {
  if (!('displayNumber' in node.data)) {
    return node;
  }

  const nextNode = {
    ...node,
    data: { ...node.data },
  } as T;
  delete nextNode.data.displayNumber;
  return nextNode;
};

const getMaxNodeNumber = (nodes: AppNode[]) =>
  nodes.reduce((max, node) => {
    if (!shouldAssignNodeDisplayNumber(node)) {
      return max;
    }

    const value = node.data?.displayNumber;
    return isValidNodeNumber(value) ? Math.max(max, value) : max;
  }, 0);

export const getNextNodeDisplayNumber = (
  nodes: AppNode[],
  features?: Features,
) => {
  const savedNext = features?.[NODE_NUMBER_FEATURE_KEY];
  const nextFromFeatures = isValidNodeNumber(savedNext) ? savedNext : 1;
  return Math.max(nextFromFeatures, getMaxNodeNumber(nodes) + 1);
};

export const withNodeDisplayNumber = <T extends AppNode>(
  node: T,
  displayNumber: number,
): T => ({
  ...node,
  data: {
    ...node.data,
    displayNumber,
  },
});

export const createNumberedNode = <T extends AppNode>(
  node: T,
  nodes: AppNode[],
  features?: Features,
) => {
  if (!shouldAssignNodeDisplayNumber(node)) {
    return {
      node: withoutNodeDisplayNumber(node),
      nextNodeDisplayNumber: getNextNodeDisplayNumber(nodes, features),
    };
  }

  const displayNumber = getNextNodeDisplayNumber(nodes, features);
  return {
    node: withNodeDisplayNumber(node, displayNumber),
    nextNodeDisplayNumber: displayNumber + 1,
  };
};

export const assignNewNodeDisplayNumbers = <T extends AppNode>(
  nodesToNumber: T[],
  existingNodes: AppNode[],
  features?: Features,
) => {
  let nextNodeDisplayNumber = getNextNodeDisplayNumber(existingNodes, features);

  const nodes = nodesToNumber.map((node) => {
    if (!shouldAssignNodeDisplayNumber(node)) {
      return withoutNodeDisplayNumber(node);
    }

    const numberedNode = withNodeDisplayNumber(node, nextNodeDisplayNumber);
    nextNodeDisplayNumber += 1;
    return numberedNode;
  });

  return {
    nodes,
    features: {
      ...(features || {}),
      [NODE_NUMBER_FEATURE_KEY]: nextNodeDisplayNumber,
    },
  };
};

export const assignMissingNodeDisplayNumbers = (
  nodes: AppNode[],
  features?: Features,
) => {
  let nextNodeDisplayNumber = getNextNodeDisplayNumber(nodes, features);
  let changed = false;
  const usedNodeNumbers = new Set<number>();

  const numberedNodes = nodes.map((node) => {
    if (!shouldAssignNodeDisplayNumber(node)) {
      const nodeWithoutNumber = withoutNodeDisplayNumber(node);
      changed = changed || nodeWithoutNumber !== node;
      return nodeWithoutNumber;
    }

    const currentNodeNumber = node.data?.displayNumber;

    if (
      isValidNodeNumber(currentNodeNumber) &&
      !usedNodeNumbers.has(currentNodeNumber)
    ) {
      usedNodeNumbers.add(currentNodeNumber);
      return node;
    }

    changed = true;
    const numberedNode = withNodeDisplayNumber(node, nextNodeDisplayNumber);
    usedNodeNumbers.add(nextNodeDisplayNumber);
    nextNodeDisplayNumber += 1;
    return numberedNode;
  });

  const savedNext = features?.[NODE_NUMBER_FEATURE_KEY];
  const shouldUpdateFeature =
    !isValidNodeNumber(savedNext) || savedNext !== nextNodeDisplayNumber;

  return {
    nodes: changed ? numberedNodes : nodes,
    features: shouldUpdateFeature
      ? {
          ...(features || {}),
          [NODE_NUMBER_FEATURE_KEY]: nextNodeDisplayNumber,
        }
      : features || {},
  };
};
