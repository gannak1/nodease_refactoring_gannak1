import { isEqual } from 'lodash';

import type { WorkflowDraftRequest } from '../types/Workflow';
import { buildWorkflowDraftPayload } from './workflowDraftPayload';

const buildComparableDraftPayload = (
  draft: WorkflowDraftRequest,
  noteNodesSource?: 'nodes' | 'features',
) => {
  const payload = buildWorkflowDraftPayload(draft, draft.viewport, {
    noteNodesSource,
  });
  delete payload.envVariables;
  delete payload.runtimeVariables;
  return payload;
};

const buildFullDraftPayload = (
  draft: WorkflowDraftRequest,
  noteNodesSource?: 'nodes' | 'features',
) => buildWorkflowDraftPayload(draft, draft.viewport, { noteNodesSource });

export const canonicalDraftMatchesSnapshot = (
  canonical: unknown,
  snapshot: WorkflowDraftRequest,
) => {
  if (
    typeof canonical !== 'object' ||
    canonical === null ||
    !Array.isArray((canonical as WorkflowDraftRequest).nodes) ||
    !Array.isArray((canonical as WorkflowDraftRequest).edges)
  ) {
    return false;
  }
  const canonicalDraft = canonical as WorkflowDraftRequest;
  return isEqual(
    buildComparableDraftPayload(canonicalDraft, 'features'),
    buildComparableDraftPayload(snapshot),
  );
};

export const workflowDraftSnapshotsEqual = (
  latest: WorkflowDraftRequest,
  saved: WorkflowDraftRequest,
) =>
  isEqual(
    buildFullDraftPayload(latest, 'features'),
    buildFullDraftPayload(saved),
  );
