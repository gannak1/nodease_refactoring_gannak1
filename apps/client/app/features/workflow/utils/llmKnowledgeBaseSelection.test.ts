import { describe, expect, it, vi, beforeEach } from 'vitest';

import { knowledgeApi } from '@/app/features/knowledge/api/knowledgeApi';
import { fetchEligibleKnowledgeBases } from './llmKnowledgeBaseSelection';

vi.mock('@/app/features/knowledge/api/knowledgeApi', () => ({
  knowledgeApi: {
    getKnowledgeBases: vi.fn(),
    getKnowledgeBase: vi.fn(),
  },
}));

describe('llmKnowledgeBaseSelection', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('keeps KBs with retrieval chunks even when the legacy document status is not completed', async () => {
    const kb = {
      id: 'kb-1',
      name: 'Internal docs',
      document_count: 1,
      created_at: '2026-07-08T00:00:00Z',
      embedding_model: 'text-embedding-3-small',
    };
    vi.mocked(knowledgeApi.getKnowledgeBases).mockResolvedValue([kb]);
    vi.mocked(knowledgeApi.getKnowledgeBase).mockResolvedValue({
      ...kb,
      documents: [
        {
          id: 'doc-1',
          filename: 'internal.md',
          status: 'indexing',
          created_at: '2026-07-08T00:00:00Z',
          updated_at: '2026-07-08T00:00:00Z',
          chunk_count: 3,
          token_count: 0,
        },
      ],
    });

    const result = await fetchEligibleKnowledgeBases();

    expect(result.bases).toEqual([kb]);
    expect(result.detailsById['kb-1']?.documents[0]?.chunk_count).toBe(3);
  });
});
