import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import KnowledgeDetailPage from './page';
import { knowledgeApi } from '@/app/features/knowledge/api/knowledgeApi';

const { routerPush } = vi.hoisted(() => ({
  routerPush: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'kb-1' }),
  useRouter: () => ({ push: routerPush }),
}));

vi.mock('@/app/features/knowledge/api/knowledgeApi', () => ({
  knowledgeApi: {
    getKnowledgeBase: vi.fn(),
    deleteDocument: vi.fn(),
    updateKnowledgeBase: vi.fn(),
    deleteKnowledgeBase: vi.fn(),
  },
}));

vi.mock('@/app/features/knowledge/components/create-knowledge-modal', () => ({
  default: () => null,
}));

vi.mock('@/app/features/knowledge/components/knowledge-search-modal', () => ({
  default: () => null,
}));

vi.mock(
  '@/app/features/knowledge/components/change-embedding-model-modal',
  () => ({
    default: () => null,
  }),
);

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const mockedKnowledgeApi = vi.mocked(knowledgeApi);

describe('KnowledgeDetailPage source processing actions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedKnowledgeApi.getKnowledgeBase.mockResolvedValue({
      id: 'kb-1',
      name: '사내 문서',
      description: '온보딩 자료',
      document_count: 3,
      created_at: '2026-07-08T00:00:00Z',
      embedding_model: 'text-embedding-3-small',
      documents: [
        {
          id: 'doc-pending',
          filename: 'commit-convention.md',
          status: 'pending',
          created_at: '2026-07-08T00:00:00Z',
          updated_at: '2026-07-08T00:00:00Z',
          chunk_count: 0,
          token_count: 0,
          source_type: 'FILE',
        },
        {
          id: 'doc-failed',
          filename: 'salary-policy.md',
          status: 'failed',
          created_at: '2026-07-08T00:00:00Z',
          updated_at: '2026-07-08T00:00:00Z',
          error_message: '처리 실패',
          chunk_count: 0,
          token_count: 0,
          source_type: 'FILE',
        },
        {
          id: 'doc-completed',
          filename: 'onboarding.md',
          status: 'completed',
          created_at: '2026-07-08T00:00:00Z',
          updated_at: '2026-07-08T00:00:00Z',
          chunk_count: 3,
          token_count: 120,
          source_type: 'FILE',
        },
      ],
    });
  });

  afterEach(() => {
    cleanup();
  });

  it('shows processing CTAs for pending and failed sources only', async () => {
    render(<KnowledgeDetailPage />);

    expect(
      await screen.findByRole('heading', { name: '사내 문서' }),
    ).toBeVisible();
    expect(screen.getByText('처리 전')).toBeVisible();
    expect(
      screen.getByText('처리 시작 전에는 RAG 검색에 사용되지 않습니다.'),
    ).toBeVisible();
    expect(
      screen.getAllByRole('button', { name: /처리 시작|재처리/ }),
    ).toHaveLength(2);

    fireEvent.click(screen.getByRole('button', { name: '처리 시작' }));
    expect(routerPush).toHaveBeenCalledWith(
      '/dashboard/knowledge/kb-1/document/doc-pending',
    );

    fireEvent.click(screen.getByRole('button', { name: '재처리' }));
    expect(routerPush).toHaveBeenCalledWith(
      '/dashboard/knowledge/kb-1/document/doc-failed',
    );

    await waitFor(() => {
      expect(screen.getAllByTitle('삭제')).toHaveLength(3);
    });
    expect(screen.getByText('완료')).toBeVisible();
  });
});
