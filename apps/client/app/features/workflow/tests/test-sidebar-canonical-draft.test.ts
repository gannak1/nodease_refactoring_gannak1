import { describe, expect, it } from 'vitest';

import type { WorkflowDraftRequest } from '../types/Workflow';
import {
  canonicalDraftMatchesSnapshot,
  workflowDraftSnapshotsEqual,
} from '../utils/workflowDraftComparison';

describe('TestSidebar canonical draft comparison', () => {
  it('ignores editor-only env and runtime variables omitted by the canonical draft response', () => {
    const snapshot: WorkflowDraftRequest = {
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      features: {},
      envVariables: [
        {
          id: 'env-1',
          key: 'API_URL',
          value: 'https://example.invalid',
          type: 'string',
        },
      ],
      runtimeVariables: [
        { id: 'runtime-1', key: 'request_id', name: 'Request ID' },
      ],
    };
    const canonical = {
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      features: {},
    };

    expect(canonicalDraftMatchesSnapshot(canonical, snapshot)).toBe(true);
  });

  it('keeps the editor dirty when env or runtime variables change during a save', () => {
    const saved: WorkflowDraftRequest = {
      nodes: [],
      edges: [],
      viewport: { x: 0, y: 0, zoom: 1 },
      features: {},
      envVariables: [{ id: 'env-1', key: 'MODE', value: 'before', type: 'string' }],
      runtimeVariables: [],
    };
    const latest: WorkflowDraftRequest = {
      ...saved,
      envVariables: [{ id: 'env-1', key: 'MODE', value: 'after', type: 'string' }],
    };

    expect(workflowDraftSnapshotsEqual(latest, saved)).toBe(false);
  });
});
