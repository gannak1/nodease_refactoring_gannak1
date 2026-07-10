import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/activeOrganization', () => ({
  activeOrganizationHeaders: vi.fn((organizationId: string | null) =>
    organizationId ? { 'X-Organization-Id': organizationId } : {},
  ),
  getStoredActiveOrganizationId: vi.fn(() => 'org-1'),
}));

vi.mock('@/lib/apiClient', () => ({
  apiBaseUrl: 'http://localhost:8000/api/v1',
  apiClient: {
    delete: vi.fn(),
    get: vi.fn(),
    patch: vi.fn(),
    post: vi.fn(),
  },
}));

import { knowledgeApi, RAGAgentStreamEvent } from './knowledgeApi';
import { apiClient } from '@/lib/apiClient';

const streamResponse = (chunks: Array<string | Uint8Array>, status = 200): Response => {
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(typeof chunk === 'string' ? encoder.encode(chunk) : chunk);
      }
      controller.close();
    },
  });

  return new Response(body, { status });
};

const payload = {
  knowledge_base_id: 'kb-1',
  query: 'policy',
  generation_model_id: 'model-1',
  credential_id: 'credential-1',
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('knowledgeApi.streamAgentAnswer', () => {
  it('sends the active organization header and emits streamed events', async () => {
    const events: RAGAgentStreamEvent[] = [];
    const fetchMock = vi.fn(async () =>
      streamResponse([
        'event: retrieval.started\n',
        'data: {"answer_run_id":"run-1","correlation_id":"corr-1"}\n\n',
        'event: answer.completed\n',
        'data: {"answer_run_id":"run-1","status":"completed"}\n\n',
      ]),
    );
    vi.stubGlobal('fetch', fetchMock);

    await knowledgeApi.streamAgentAnswer(payload, (event) => events.push(event));

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/rag/agent/answer/stream',
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
          'X-Organization-Id': 'org-1',
        }),
        body: JSON.stringify(payload),
      }),
    );
    expect(events.map((event) => event.event)).toEqual([
      'retrieval.started',
      'answer.completed',
    ]);
  });

  it('raises terminal SSE error events after notifying the consumer', async () => {
    const events: RAGAgentStreamEvent[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        streamResponse([
          'event: retrieval.started\n',
          'data: {"answer_run_id":"run-1","correlation_id":"corr-1"}\n\n',
          'event: error\n',
          'data: {"reason_code":"pii_policy_blocked","retryable":false}\n\n',
        ]),
      ),
    );

    await expect(
      knowledgeApi.streamAgentAnswer(payload, (event) => events.push(event)),
    ).rejects.toThrow('RAG answer stream failed: pii_policy_blocked');
    expect(events.map((event) => event.event)).toEqual([
      'retrieval.started',
      'error',
    ]);
  });

  it('parses the final buffered SSE event when the stream closes', async () => {
    const events: RAGAgentStreamEvent[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        streamResponse([
          'event: summary\n',
          'data: {"answer_run_id":"run-1","status":"completed"}',
        ]),
      ),
    );

    await knowledgeApi.streamAgentAnswer(payload, (event) => events.push(event));

    expect(events).toEqual([
      {
        event: 'summary',
        data: { answer_run_id: 'run-1', status: 'completed' },
      },
    ]);
  });

  it('raises a final buffered SSE error after notifying the consumer', async () => {
    const events: RAGAgentStreamEvent[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        streamResponse([
          'event: error\n',
          'data: {"reason_code":"stream.timeout","retryable":true}',
        ]),
      ),
    );

    await expect(
      knowledgeApi.streamAgentAnswer(payload, (event) => events.push(event)),
    ).rejects.toThrow('RAG answer stream failed: stream.timeout');
    expect(events).toEqual([
      {
        event: 'error',
        data: { reason_code: 'stream.timeout', retryable: true },
      },
    ]);
  });

  it('flushes the decoder before parsing the final buffered event', async () => {
    const events: RAGAgentStreamEvent[] = [];
    const encoded = new TextEncoder().encode(
      'event: summary\n' +
        'data: {"answer_run_id":"run-1","message":"완료"}',
    );
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        streamResponse([
          encoded.slice(0, encoded.length - 2),
          encoded.slice(encoded.length - 2),
        ]),
      ),
    );

    await knowledgeApi.streamAgentAnswer(payload, (event) => events.push(event));

    expect(events).toEqual([
      {
        event: 'summary',
        data: { answer_run_id: 'run-1', message: '완료' },
      },
    ]);
  });

  it('parses CRLF separated SSE events', async () => {
    const events: RAGAgentStreamEvent[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        streamResponse([
          'event: retrieval.started\r\n',
          'data: {"answer_run_id":"run-1","correlation_id":"corr-1"}\r\n\r\n',
          'event: answer.completed\r\n',
          'data: {"answer_run_id":"run-1","status":"completed"}\r\n\r\n',
        ]),
      ),
    );

    await knowledgeApi.streamAgentAnswer(payload, (event) => events.push(event));

    expect(events).toEqual([
      {
        event: 'retrieval.started',
        data: { answer_run_id: 'run-1', correlation_id: 'corr-1' },
      },
      {
        event: 'answer.completed',
        data: { answer_run_id: 'run-1', status: 'completed' },
      },
    ]);
  });

  it('parses multi-line data SSE events', async () => {
    const events: RAGAgentStreamEvent[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        streamResponse([
          'event: summary\n',
          'data: {"answer_run_id":"run-1",\n',
          'data: "status":"completed"}\n\n',
        ]),
      ),
    );

    await knowledgeApi.streamAgentAnswer(payload, (event) => events.push(event));

    expect(events).toEqual([
      {
        event: 'summary',
        data: { answer_run_id: 'run-1', status: 'completed' },
      },
    ]);
  });

  it('uses sanitized HTTP error messages from the API envelope', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            error: { code: 'permission.denied', message: 'Permission denied.' },
          }),
          {
            status: 403,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
      ),
    );

    await expect(
      knowledgeApi.streamAgentAnswer(payload, () => undefined),
    ).rejects.toThrow('Permission denied.');
  });
});

describe('knowledgeApi safe failure logging', () => {
  it('does not log raw upload errors or response payloads', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const error = {
      response: {
        status: 500,
        data: { detail: 'raw-response-payload-should-not-be-logged' },
      },
      config: {
        headers: { 'X-Test-Debug': 'request-config-should-not-be-logged' },
      },
    };
    vi.mocked(apiClient.post).mockRejectedValueOnce(error);

    await expect(
      knowledgeApi.uploadKnowledgeBase({
        name: '사내 문서',
        description: '테스트',
        embeddingModel: 'text-embedding-3-small',
        topK: 5,
        similarity: 0.7,
        chunkSize: 1000,
        chunkOverlap: 100,
        apiHeaders: '{"X-Test-Debug":"request-config-should-not-be-logged"}',
        apiBody: '{"payload":"request-body-should-not-be-logged"}',
      }),
    ).rejects.toBe(error);

    expect(warnSpy).toHaveBeenCalledWith('[knowledgeApi] request failed', {
      operation: 'uploadKnowledgeBase',
      status: 500,
    });
    expect(warnSpy).not.toHaveBeenCalledWith(expect.anything(), error);
  });

  it('logs only safe list failure metadata', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const error = {
      response: {
        status: 403,
        data: { detail: 'hidden-resource-name' },
      },
    };
    vi.mocked(apiClient.get).mockRejectedValueOnce(error);

    await expect(knowledgeApi.getKnowledgeBases()).rejects.toBe(error);

    expect(warnSpy).toHaveBeenCalledWith('[knowledgeApi] request failed', {
      operation: 'getKnowledgeBases',
      status: 403,
    });
    expect(warnSpy).not.toHaveBeenCalledWith(expect.anything(), error);
  });
});

describe('knowledgeApi collection management', () => {
  it('updates Knowledge Base safe metadata', async () => {
    vi.mocked(apiClient.patch).mockResolvedValueOnce({
      data: { id: 'kb-1' },
    });

    await knowledgeApi.updateKnowledgeBase('kb-1', {
      safe_metadata: {
        safe_label: 'People Ops',
        kb_safe_topics: ['onboarding'],
      },
    });

    expect(apiClient.patch).toHaveBeenCalledWith('/knowledge/kb-1', {
      safe_metadata: {
        safe_label: 'People Ops',
        kb_safe_topics: ['onboarding'],
      },
    });
  });

  it('loads Knowledge Collections from the management endpoint', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: {
        collections: [
          {
            id: 'collection-1',
            organization_id: 'org-1',
            name: 'HR',
            is_system_managed: false,
            sync_state: 'manual',
            lifecycle_state: 'active',
            visibility: 'private',
            linked_kb_count_bucket: '1',
            active_kb_count_bucket: '1',
            can_read: true,
            can_route: true,
            can_manage: true,
            can_sync: false,
            safe_metadata: {},
            created_at: '2026-07-07T00:00:00Z',
            updated_at: '2026-07-07T00:00:00Z',
          },
        ],
        can_create_collection: true,
        can_change_public_visibility: true,
      },
    });

    const collections = await knowledgeApi.getKnowledgeCollections();

    expect(apiClient.get).toHaveBeenCalledWith('/knowledge/collections', {
      params: undefined,
    });
    expect(collections).toHaveLength(1);
    expect(JSON.stringify(collections)).not.toContain('raw_source_url');
  });

  it('loads Knowledge Collection management capabilities', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: {
        collections: [],
        can_create_collection: false,
        can_change_public_visibility: false,
      },
    });

    const response = await knowledgeApi.getKnowledgeCollectionsResponse();

    expect(response.collections).toEqual([]);
    expect(response.can_create_collection).toBe(false);
    expect(response.can_change_public_visibility).toBe(false);
  });

  it('updates public visibility with explicit acknowledgement', async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: {
        collection: { id: 'collection-1', visibility: 'public' },
        public_runtime_effect: 'anonymous_public_only_candidate',
        linked_kb_count_bucket: '1',
        active_kb_count_bucket: '1',
        sensitive_content_warning: 'unknown_or_present',
      },
    });

    await knowledgeApi.updateKnowledgeCollectionVisibility('collection-1', {
      visibility: 'public',
      acknowledged_public_runtime_exposure: true,
    });

    expect(apiClient.post).toHaveBeenCalledWith(
      '/knowledge/collections/collection-1/visibility',
      {
        visibility: 'public',
        acknowledged_public_runtime_exposure: true,
      },
    );
  });

  it('links KBs through the Collection item endpoint', async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: { items: [] },
    });

    await knowledgeApi.linkKnowledgeCollectionItem('collection-1', {
      knowledge_base_id: 'kb-1',
    });

    expect(apiClient.post).toHaveBeenCalledWith(
      '/knowledge/collections/collection-1/items',
      { knowledge_base_id: 'kb-1' },
    );
  });
});
