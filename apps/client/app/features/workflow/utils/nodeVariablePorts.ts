import { AppNode } from '../types/Nodes';

export const NODE_OUTPUT_DRAG_MIME = 'application/x-node-output-variable';

export type NodeOutputVariable = {
  key: string;
  label: string;
  outputId?: string;
  sourceNodeId: string;
  sourceTitle: string;
};

export type DraggedOutputVariable = NodeOutputVariable;

type ReferencedVariableLike = {
  name?: unknown;
  value_selector?: unknown;
};

const toOutput = (
  node: AppNode,
  key: string,
  label = key,
  outputId?: string,
): NodeOutputVariable => ({
  key,
  label,
  outputId,
  sourceNodeId: node.id,
  sourceTitle: node.data.title || node.id,
});

const uniqueOutputs = (outputs: NodeOutputVariable[]) => {
  const seen = new Set<string>();
  return outputs.filter((output) => {
    const id = `${output.sourceNodeId}:${output.key}`;
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });
};

export const getNodeOutputVariables = (node?: AppNode | null) => {
  if (!node) return [];

  const data = node.data as Record<string, unknown>;
  const outputs: NodeOutputVariable[] = [];

  if (node.type === 'startNode' && Array.isArray(data.variables)) {
    for (const variable of data.variables as Array<Record<string, unknown>>) {
      const key = String(variable.name || variable.label || '').trim();
      const outputId = String(variable.id || '').trim();
      if (key) {
        outputs.push(
          toOutput(node, key, String(variable.label || key), outputId || key),
        );
      }
    }
  }

  if (node.type === 'answerNode' && Array.isArray(data.outputs)) {
    for (const output of data.outputs as Array<Record<string, unknown>>) {
      const key = String(output.variable || '').trim();
      if (key) outputs.push(toOutput(node, key));
    }
  }

  if (node.type === 'workflowNode' && Array.isArray(data.outputs)) {
    for (const output of data.outputs as string[]) {
      const key = String(output).trim();
      if (key) outputs.push(toOutput(node, key));
    }
  }

  if (node.type === 'variableExtractionNode' && Array.isArray(data.mappings)) {
    for (const mapping of data.mappings as Array<Record<string, unknown>>) {
      const key = String(mapping.name || '').trim();
      if (key) outputs.push(toOutput(node, key));
    }
  }

  if (node.type === 'loopNode' && Array.isArray(data.outputs)) {
    for (const output of data.outputs as Array<Record<string, unknown>>) {
      const key = String(output.name || '').trim();
      if (key) outputs.push(toOutput(node, key));
    }
  }

  const fallbackByType: Partial<Record<NonNullable<AppNode['type']>, string[]>> =
    {
      llmNode: ['text'],
      codeNode: ['result'],
      templateNode: ['result'],
      httpRequestNode: ['status_code', 'body', 'headers'],
      slackPostNode: ['ok', 'message_ts'],
      githubNode: ['result'],
      mailNode: ['messages'],
      fileExtractionNode: ['text'],
      webhookTrigger: ['payload'],
      scheduleTrigger: ['triggered_at'],
      conditionNode: ['result'],
    };

  for (const key of fallbackByType[node.type || 'note'] || []) {
    outputs.push(toOutput(node, key));
  }

  return uniqueOutputs(outputs);
};

const selectorFor = (output: DraggedOutputVariable) => [
  output.sourceNodeId,
  output.key,
];

const sourceFor = (output: DraggedOutputVariable) =>
  `${output.sourceNodeId}.${output.key}`;

export const parseDraggedOutput = (dataTransfer: DataTransfer) => {
  const raw = dataTransfer.getData(NODE_OUTPUT_DRAG_MIME);
  if (!raw) return null;

  try {
    return JSON.parse(raw) as DraggedOutputVariable;
  } catch {
    return null;
  }
};

export const upsertNamedSelector = (
  list: unknown,
  output: DraggedOutputVariable,
  selectorKey: string,
) => {
  const current = Array.isArray(list) ? list : [];
  const name = output.key;
  const nextItem = { name, [selectorKey]: selectorFor(output) };
  const index = current.findIndex(
    (item) =>
      item &&
      typeof item === 'object' &&
      (item as Record<string, unknown>).name === name,
  );

  if (index >= 0) {
    return current.map((item, itemIndex) =>
      itemIndex === index ? { ...(item as object), ...nextItem } : item,
    );
  }

  return [...current, nextItem];
};

export const getTokenLabelMap = (
  references: unknown,
  upstreamNodes: AppNode[],
) => {
  const labelMap: Record<string, string> = {};
  const current = Array.isArray(references) ? references : [];

  for (const reference of current as ReferencedVariableLike[]) {
    const name = String(reference.name || '').trim();
    const selector = reference.value_selector;
    if (!name || !Array.isArray(selector)) continue;

    const [sourceNodeId, outputKey] = selector;
    const sourceNode = upstreamNodes.find((node) => node.id === sourceNodeId);
    const sourceOutput = getNodeOutputVariables(sourceNode).find(
      (output) => output.key === outputKey || output.outputId === outputKey,
    );
    const label = String(sourceOutput?.label || '').trim();
    if (label) labelMap[name] = label;
  }

  return labelMap;
};

const ACCEPT_DROPPED_OUTPUT_NODE_TYPES = new Set<NonNullable<AppNode['type']>>([
  'llmNode',
  'httpRequestNode',
  'slackPostNode',
  'githubNode',
  'mailNode',
  'fileExtractionNode',
  'templateNode',
  'workflowNode',
  'loopNode',
  'codeNode',
  'answerNode',
  'variableExtractionNode',
  'conditionNode',
]);

export const canAcceptDroppedOutput = (node: AppNode) =>
  Boolean(node.type && ACCEPT_DROPPED_OUTPUT_NODE_TYPES.has(node.type));

const createConditionId = () =>
  globalThis.crypto?.randomUUID?.() || `condition-${Date.now()}`;

const conditionSelectorFor = (output: DraggedOutputVariable) => [
  output.sourceNodeId,
  output.outputId || output.key,
];

const appendDroppedOutputToCondition = (
  cases: unknown,
  output: DraggedOutputVariable,
) => {
  const currentCases = Array.isArray(cases) ? cases : [];
  const selector = conditionSelectorFor(output);
  const nextCondition = {
    id: createConditionId(),
    variable_selector: selector,
    operator: 'equals',
    value: '',
  };

  if (currentCases.length === 0) {
    return [
      {
        id: createConditionId(),
        case_name: 'Default',
        conditions: [nextCondition],
        logical_operator: 'and',
      },
    ];
  }

  const firstCase = currentCases[0] as Record<string, unknown>;
  const conditions = Array.isArray(firstCase.conditions)
    ? firstCase.conditions
    : [];
  const existingIndex = conditions.findIndex((condition) => {
    if (!condition || typeof condition !== 'object') return false;
    const variableSelector = (condition as Record<string, unknown>)
      .variable_selector;
    return (
      Array.isArray(variableSelector) &&
      variableSelector[0] === selector[0] &&
      variableSelector[1] === selector[1]
    );
  });
  const emptyIndex = conditions.findIndex((condition) => {
    if (!condition || typeof condition !== 'object') return false;
    const variableSelector = (condition as Record<string, unknown>)
      .variable_selector;
    return !Array.isArray(variableSelector) || variableSelector.length < 2;
  });
  const updateIndex = existingIndex >= 0 ? existingIndex : emptyIndex;
  const nextConditions =
    updateIndex >= 0
      ? conditions.map((condition, index) =>
          index === updateIndex
            ? { ...(condition as object), variable_selector: selector }
            : condition,
        )
      : [...conditions, nextCondition];

  return currentCases.map((item, index) =>
    index === 0
      ? {
          ...(item as object),
          conditions: nextConditions,
        }
      : item,
  );
};

export const applyDroppedOutputToNodeData = (
  node: AppNode,
  output: DraggedOutputVariable,
) => {
  const data = node.data as Record<string, unknown>;

  switch (node.type) {
    case 'llmNode':
    case 'httpRequestNode':
    case 'slackPostNode':
    case 'githubNode':
    case 'mailNode':
    case 'fileExtractionNode':
      return {
        referenced_variables: upsertNamedSelector(
          data.referenced_variables,
          output,
          'value_selector',
        ),
      };

    case 'templateNode':
    case 'workflowNode':
    case 'loopNode':
      return {
        inputs: upsertNamedSelector(data.inputs, output, 'value_selector'),
      };

    case 'codeNode': {
      const current = Array.isArray(data.inputs) ? data.inputs : [];
      const name = output.key;
      const nextItem = { name, source: sourceFor(output) };
      const index = current.findIndex(
        (item) =>
          item &&
          typeof item === 'object' &&
          (item as Record<string, unknown>).name === name,
      );
      return {
        inputs:
          index >= 0
            ? current.map((item, itemIndex) =>
                itemIndex === index ? { ...(item as object), ...nextItem } : item,
              )
            : [...current, nextItem],
      };
    }

    case 'answerNode':
      return {
        outputs: [
          ...(Array.isArray(data.outputs) ? data.outputs : []),
          { variable: output.key, value_selector: selectorFor(output) },
        ],
      };

    case 'variableExtractionNode':
      return {
        source_selector: selectorFor(output),
      };

    case 'conditionNode':
      return {
        cases: appendDroppedOutputToCondition(data.cases, output),
      };

    default:
      return null;
  }
};
