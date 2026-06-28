import type { WorkflowDraftRequest } from '../types/Workflow';

export const buildWorkflowDraftPayload = (
  data: WorkflowDraftRequest,
  viewport: WorkflowDraftRequest['viewport'],
): WorkflowDraftRequest => {
  const realNodes = data.nodes.filter((node) => node.type !== 'note');
  const noteNodes = data.nodes.filter((node) => node.type === 'note');

  return {
    nodes: realNodes,
    edges: data.edges,
    viewport,
    features: {
      ...data.features,
      noteNodes,
    },
    envVariables: data.envVariables,
    runtimeVariables: data.runtimeVariables,
  };
};
