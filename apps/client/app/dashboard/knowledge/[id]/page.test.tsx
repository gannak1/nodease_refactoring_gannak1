import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
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
    updateKnowledgeSafeMetadata: vi.fn(),
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

const knowledgeBaseFixture = {
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
};

describe('KnowledgeDetailPage source processing actions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedKnowledgeApi.getKnowledgeBase.mockResolvedValue(knowledgeBaseFixture);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
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
  }, 10000);

  it('shows a safe not-found state for hidden or missing knowledge bases', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    mockedKnowledgeApi.getKnowledgeBase.mockRejectedValueOnce({
      response: { status: 404, data: { detail: 'raw hidden detail' } },
    });

    render(<KnowledgeDetailPage />);

    expect(
      await screen.findByRole('heading', {
        name: '자료 그룹을 찾을 수 없습니다',
      }),
    ).toBeVisible();
    expect(
      screen.getByText('삭제되었거나 현재 계정으로 접근할 수 없는 자료 그룹입니다.'),
    ).toBeVisible();
    expect(alertSpy).not.toHaveBeenCalled();
    expect(routerPush).not.toHaveBeenCalled();
  });

  it('keeps the current page when background polling fails', async () => {
    const alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
    let poll: (() => void) | undefined;
    vi.spyOn(globalThis, 'setInterval').mockImplementation(
      (handler: TimerHandler) => {
        if (typeof handler === 'function') {
          poll = handler as () => void;
        }
        return 1 as unknown as ReturnType<typeof setInterval>;
      },
    );
    mockedKnowledgeApi.getKnowledgeBase
      .mockResolvedValueOnce({
        ...knowledgeBaseFixture,
        documents: [
          {
            ...knowledgeBaseFixture.documents[0],
            status: 'processing',
          },
        ],
      })
      .mockRejectedValueOnce({
        response: { status: 500, data: { detail: 'transient failure' } },
      });

    render(<KnowledgeDetailPage />);

    expect(
      await screen.findByRole('heading', { name: '사내 문서' }),
    ).toBeVisible();

    expect(poll).toBeDefined();
    await act(async () => {
      poll?.();
    });

    await waitFor(() => {
      expect(mockedKnowledgeApi.getKnowledgeBase).toHaveBeenCalledTimes(2);
    });
    expect(screen.getByRole('heading', { name: '사내 문서' })).toBeVisible();
    expect(alertSpy).not.toHaveBeenCalled();
    expect(routerPush).not.toHaveBeenCalled();
  });

  it('generates and saves KB safe metadata from the detail page', async () => {
    mockedKnowledgeApi.getKnowledgeBase.mockResolvedValue({
      ...knowledgeBaseFixture,
      name: 'People Ops KB',
      description: 'Onboarding guide for benefits',
      safe_metadata: {},
      can_edit_settings: false,
      can_manage_safe_metadata: true,
    });
    mockedKnowledgeApi.updateKnowledgeSafeMetadata.mockResolvedValue({
      safe_metadata: {
        safe_label: 'People Ops KB',
        kb_safe_topics: ['People', 'Ops', 'KB', 'Onboarding', 'guide', 'benefits'],
      },
      can_manage_safe_metadata: true,
    });

    render(<KnowledgeDetailPage />);

    expect(
      await screen.findByRole('heading', { name: 'People Ops KB' }),
    ).toBeVisible();

    fireEvent.click(screen.getByRole('button', { name: 'generate safe label' }));
    fireEvent.click(screen.getByRole('button', { name: 'generate safe topics' }));

    expect(screen.getByLabelText('KB safe label')).toHaveValue('People Ops KB');
    expect(screen.getByLabelText('KB safe topics')).toHaveValue(
      'People, Ops, KB, Onboarding, guide, benefits',
    );

    fireEvent.click(screen.getByRole('button', { name: 'save safe metadata' }));

    await waitFor(() => {
      expect(
        mockedKnowledgeApi.updateKnowledgeSafeMetadata,
      ).toHaveBeenCalledWith('kb-1', {
          safe_label: 'People Ops KB',
          kb_safe_topics: ['People', 'Ops', 'KB', 'Onboarding', 'guide', 'benefits'],
      });
    });

    expect(
      screen.queryByRole('button', { name: '소스 추가' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: '삭제' }),
    ).not.toBeInTheDocument();
  });

  it('hides safe metadata editing without KB manage permission', async () => {
    mockedKnowledgeApi.getKnowledgeBase.mockResolvedValue({
      ...knowledgeBaseFixture,
      safe_metadata: { safe_label: 'People Ops' },
      can_edit_settings: false,
      can_manage_safe_metadata: false,
    });

    render(<KnowledgeDetailPage />);

    expect(
      await screen.findByRole('heading', { name: '사내 문서' }),
    ).toBeVisible();
    expect(screen.queryByLabelText('KB safe label')).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText('save safe metadata'),
    ).not.toBeInTheDocument();
  });
});
