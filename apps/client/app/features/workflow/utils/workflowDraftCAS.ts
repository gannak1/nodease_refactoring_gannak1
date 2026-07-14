import { workflowApi } from '../api/workflowApi';
import { useWorkflowStore } from '../store/useWorkflowStore';

export type WorkflowDraftCASExpectation = {
  expected_graph_hash: string;
  expected_updated_at: string;
};

export const resolveWorkflowDraftCASExpectation = async (
  workflowId: string,
  options: { refresh?: boolean } = {},
): Promise<WorkflowDraftCASExpectation> => {
  const store = useWorkflowStore.getState();
  let metadata = options.refresh
    ? null
    : store.getCanonicalDraftMetadata(workflowId);

  if (!metadata) {
    const canonical = await workflowApi.getDraftWorkflow(workflowId);
    metadata = store.ingestCanonicalDraftMetadata(canonical, workflowId);
  }
  if (!metadata) {
    throw new Error('canonical_draft_metadata_unavailable');
  }

  return {
    expected_graph_hash: metadata.graphHash,
    expected_updated_at: metadata.updatedAt,
  };
};

export const ingestWorkflowDraftCASResult = (
  workflowId: string,
  value: unknown,
) => useWorkflowStore.getState().ingestCanonicalDraftMetadata(value, workflowId);
