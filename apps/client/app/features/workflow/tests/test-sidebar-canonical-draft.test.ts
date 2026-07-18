import { describe, expect, it } from 'vitest';

import type { WorkflowDraftRequest } from '../types/Workflow';
import { canonicalDraftMatchesSnapshot } from '../utils/workflowDraftComparison';

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
});
