import { act, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => {
  const push = vi.fn();
  return {
    params: { id: 'kb-1', documentId: 'document-1' } as Record<string, string>,
    push,
    router: { push },
    getKnowledgeBase: vi.fn(),
    getDocument: vi.fn(),
    getDocumentEditConfig: vi.fn(),
    toastError: vi.fn(),
  };
});

vi.mock('next/navigation', () => ({
  useParams: () => mocks.params,
  useRouter: () => mocks.router,
}));

vi.mock('next/link', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('sonner', () => ({
  toast: {
    error: mocks.toastError,
    success: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock('@/app/features/knowledge/api/knowledgeApi', () => ({
  knowledgeApi: {
    getKnowledgeBase: mocks.getKnowledgeBase,
    getDocument: mocks.getDocument,
    getDocumentEditConfig: mocks.getDocumentEditConfig,
    getProgressUrl: vi.fn(),
  },
}));

vi.mock('@/app/features/knowledge/hooks/useDocumentProcess', () => ({
  useDocumentProcess: () => ({
    isAnalyzing: false,
    analyzingAction: null,
    isPreviewLoading: false,
    showCostConfirm: false,
    setShowCostConfirm: vi.fn(),
    analyzeResult: null,
    setAnalyzeResult: vi.fn(),
    setPendingAction: vi.fn(),
    previewSegments: [],
    handleSaveClick: vi.fn(),
    handlePreviewClick: vi.fn(),
    handleConfirmCost: vi.fn(),
  }),
}));

vi.mock('@/app/features/knowledge/hooks/useGenericCredential', () => ({
  useGenericCredential: () => ({ hasKey: true, isLoading: false }),
}));

vi.mock('@/app/features/knowledge/api/connectorApi', () => ({
  connectorApi: {},
}));

vi.mock(
  '@/app/features/knowledge/components/ingestion-views/FileSourceViewer',
  () => ({ default: () => <div>file source</div> }),
);
vi.mock(
  '@/app/features/knowledge/components/ingestion-views/ApiSourceViewer',
  () => ({ default: () => <div>api source</div> }),
);
vi.mock(
  '@/app/features/knowledge/components/ingestion-views/DbSourceViewer',
  () => ({ default: () => <div>db source</div> }),
);
vi.mock(
  '@/app/features/knowledge/components/document-settings/CommonChunkSettings',
  () => ({
    default: ({ chunkSize }: { chunkSize: number }) => (
      <div data-testid="chunk-size">{chunkSize}</div>
    ),
  }),
);
vi.mock(
  '@/app/features/knowledge/components/document-settings/ParsingStrategySettings',
  () => ({ default: () => <div>parsing settings</div> }),
);
vi.mock(
  '@/app/features/knowledge/components/preview/ChunkPreviewList',
  () => ({ default: () => <div>chunk preview</div> }),
);
vi.mock(
  '@/app/features/knowledge/components/create-knowledge-modal/DBConnectionForm',
  () => ({ default: () => <div>connection form</div> }),
);
vi.mock(
  '@/app/features/knowledge/components/document-settings/ColumnAutocomplete',
  () => ({ default: () => <div>column autocomplete</div> }),
);

import DocumentSettingsPage from './page';

const knowledgeBase = {
  id: 'kb-1',
  name: 'Knowledge Base',
  can_write: true,
};

const documentResponse = (id: string) => ({
  id,
  filename: `${id}.pdf`,
  status: 'pending',
  created_at: '2026-07-13T00:00:00Z',
  updated_at: '2026-07-13T00:00:00Z',
  chunk_count: 0,
  token_count: 0,
  source_type: 'FILE',
  meta_info: {},
});

const editConfig = (chunkSize: number) => ({
  editable: true,
  source_type: 'FILE',
  chunk_size: chunkSize,
  chunk_overlap: 20,
  segment_identifier: '\\n\\n',
  remove_urls_emails: false,
  remove_whitespace: true,
  strategy: 'general',
  chunking_mode: 'flat',
  selection_mode: 'all',
});

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.params = { id: 'kb-1', documentId: 'document-1' };
  mocks.getKnowledgeBase.mockResolvedValue(knowledgeBase);
});

describe('DocumentSettingsPage request scoping', () => {
  it('ignores a late response from the previously selected document', async () => {
    const firstDocument = deferred<ReturnType<typeof documentResponse>>();
    mocks.getDocument.mockImplementation(
      (_kbId: string, documentId: string) =>
        documentId === 'document-1'
          ? firstDocument.promise
          : Promise.resolve(documentResponse('document-2')),
    );
    mocks.getDocumentEditConfig.mockImplementation(
      (_kbId: string, documentId: string) =>
        Promise.resolve(editConfig(documentId === 'document-2' ? 2222 : 1111)),
    );

    const { rerender } = render(<DocumentSettingsPage />);
    mocks.params = { id: 'kb-1', documentId: 'document-2' };
    rerender(<DocumentSettingsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('chunk-size')).toHaveTextContent('2222');
      expect(
        screen.getByRole('button', { name: '처리 시작' }),
      ).toBeEnabled();
    });

    await act(async () => {
      firstDocument.resolve(documentResponse('document-1'));
      await firstDocument.promise;
    });

    expect(screen.getByTestId('chunk-size')).toHaveTextContent('2222');
    expect(mocks.getDocumentEditConfig).not.toHaveBeenCalledWith(
      'kb-1',
      'document-1',
    );
  });

  it('resets the edit gate when the next document request fails', async () => {
    mocks.getDocument.mockImplementation(
      (_kbId: string, documentId: string) =>
        documentId === 'document-1'
          ? Promise.resolve(documentResponse(documentId))
          : Promise.reject(new Error('request failed')),
    );
    mocks.getDocumentEditConfig.mockResolvedValue(editConfig(1111));

    const { rerender } = render(<DocumentSettingsPage />);
    await waitFor(() => {
      expect(screen.getByTestId('chunk-size')).toHaveTextContent('1111');
      expect(
        screen.getByRole('button', { name: '처리 시작' }),
      ).toBeEnabled();
    });

    mocks.params = { id: 'kb-1', documentId: 'document-2' };
    rerender(<DocumentSettingsPage />);

    await waitFor(() => {
      expect(mocks.toastError).toHaveBeenCalledWith(
        '문서 정보를 불러오는데 실패했습니다.',
      );
      expect(
        screen.getByRole('button', { name: '처리 시작' }),
      ).toBeDisabled();
    });
    expect(screen.getByTestId('chunk-size')).toHaveTextContent('1000');
  });
});
