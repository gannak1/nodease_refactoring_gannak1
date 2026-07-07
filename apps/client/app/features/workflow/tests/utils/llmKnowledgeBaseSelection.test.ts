import { afterEach, describe, expect, it, vi } from 'vitest';

import { knowledgeApi } from '@/app/features/knowledge/api/knowledgeApi';
import {
  fetchEligibleKnowledgeBases,
  sanitizeSelectedKnowledgeBases,
} from '../../utils/llmKnowledgeBaseSelection';

vi.mock('@/app/features/knowledge/api/knowledgeApi', () => ({
  knowledgeApi: {
    getKnowledgeBases: vi.fn(),
    getKnowledgeBase: vi.fn(),
  },
}));

describe('llmKnowledgeBaseSelection', () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.restoreAllMocks();
  });

  it('preserves selected knowledge bases when detail lookup transiently fails without logging raw payloads', async () => {
    const consoleWarn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const rawError = {
      response: {
        status: 500,
        data: { raw_payload: 'do-not-log-this' },
      },
    };

    vi.mocked(knowledgeApi.getKnowledgeBases).mockResolvedValueOnce([
      {
        id: 'kb-ok',
        name: '완료 문서 KB',
        description: 'ok',
        document_count: 1,
        created_at: '2026-07-01T00:00:00Z',
        embedding_model: 'text-embedding-3-small',
      },
      {
        id: 'kb-detail-fails',
        name: '상세 실패 KB',
        description: 'fails',
        document_count: 1,
        created_at: '2026-07-01T00:00:00Z',
        embedding_model: 'text-embedding-3-small',
      },
      {
        id: 'kb-no-docs',
        name: '문서 없는 KB',
        description: 'empty',
        document_count: 0,
        created_at: '2026-07-01T00:00:00Z',
        embedding_model: 'text-embedding-3-small',
      },
    ]);
    vi.mocked(knowledgeApi.getKnowledgeBase)
      .mockResolvedValueOnce({
        id: 'kb-ok',
        name: '완료 문서 KB',
        description: 'ok',
        document_count: 1,
        created_at: '2026-07-01T00:00:00Z',
        embedding_model: 'text-embedding-3-small',
        documents: [
          {
            id: 'doc-1',
            filename: 'policy.md',
            status: 'completed',
            created_at: '2026-07-01T00:00:00Z',
            updated_at: '2026-07-01T00:00:00Z',
            chunk_count: 1,
            token_count: 20,
          },
        ],
      })
      .mockRejectedValueOnce(rawError);

    const result = await fetchEligibleKnowledgeBases();

    expect(result.bases.map((base) => base.id)).toEqual(['kb-ok']);
    expect(Object.keys(result.detailsById)).toEqual(['kb-ok']);
    expect(result.preserveSelectionIds).toEqual(['kb-detail-fails']);
    expect(knowledgeApi.getKnowledgeBase).toHaveBeenCalledTimes(2);
    expect(consoleWarn).toHaveBeenCalledWith(
      '[LLMReference] Failed to load knowledge base detail',
      { knowledgeBaseId: 'kb-detail-fails', status: 500 },
    );
    expect(JSON.stringify(consoleWarn.mock.calls)).not.toContain(
      'do-not-log-this',
    );

    expect(
      sanitizeSelectedKnowledgeBases(
        [
          { id: 'kb-detail-fails', name: '상세 실패 KB' },
          { id: 'kb-removed', name: '삭제된 KB' },
          { id: 'kb-ok', name: '이전 이름' },
        ],
        result.bases,
        { preserveMissingIds: result.preserveSelectionIds },
      ),
    ).toEqual([
      { id: 'kb-detail-fails', name: '상세 실패 KB' },
      { id: 'kb-ok', name: '완료 문서 KB' },
    ]);
  });

  it('removes selected knowledge bases when detail lookup confirms missing resource', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.mocked(knowledgeApi.getKnowledgeBases).mockResolvedValueOnce([
      {
        id: 'kb-hidden',
        name: '숨겨진 KB',
        description: 'hidden',
        document_count: 1,
        created_at: '2026-07-01T00:00:00Z',
        embedding_model: 'text-embedding-3-small',
      },
    ]);
    vi.mocked(knowledgeApi.getKnowledgeBase).mockRejectedValueOnce({
      response: { status: 404 },
    });

    const result = await fetchEligibleKnowledgeBases();

    expect(result.bases).toEqual([]);
    expect(result.preserveSelectionIds).toEqual([]);
    expect(
      sanitizeSelectedKnowledgeBases(
        [{ id: 'kb-hidden', name: '숨겨진 KB' }],
        result.bases,
        { preserveMissingIds: result.preserveSelectionIds },
      ),
    ).toEqual([]);
  });
});
