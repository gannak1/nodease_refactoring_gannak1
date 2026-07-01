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
