import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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
  useDocumentProcess: vi.fn(),
}));

vi.mock('@/app/features/knowledge/hooks/useGenericCredential', () => ({
  useGenericCredential: () => ({ hasKey: true, isLoading: false }),
}));

vi.mock('@/app/features/knowledge/api/connectorApi', () => ({
  connectorApi: {},
}));

vi.mock(
  '@/app/features/knowledge/components/ingestion-views/FileSourceViewer',
  () => ({
    default: ({ filename }: { filename?: string | null }) => (
      <div data-testid="file-source" data-filename={filename ?? ''}>
        file source
      </div>
    ),
  }),
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
import { useDocumentProcess } from '@/app/features/knowledge/hooks/useDocumentProcess';

const mockedUseDocumentProcess = vi.mocked(useDocumentProcess);

const createDocumentProcessResult = (handleSaveClick = vi.fn()) => ({
  isAnalyzing: false,
  analyzingAction: null,
  isPreviewLoading: false,
  showCostConfirm: false,
  setShowCostConfirm: vi.fn(),
  analyzeResult: null,
  setAnalyzeResult: vi.fn(),
  setPendingAction: vi.fn(),
  previewSegments: [],
  handleSaveClick,
  handlePreviewClick: vi.fn(),
  handleConfirmCost: vi.fn(),
});

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

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

beforeEach(() => {
  vi.clearAllMocks();
  mocks.params = { id: 'kb-1', documentId: 'document-1' };
  mocks.getKnowledgeBase.mockResolvedValue(knowledgeBase);
  mocks.getDocumentEditConfig.mockResolvedValue(editConfig(1000));
  mockedUseDocumentProcess.mockReturnValue(
    createDocumentProcessResult() as ReturnType<typeof useDocumentProcess>,
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('DocumentSettingsPage request scoping', () => {
  it('keeps an already completed document open for preview', async () => {
    const timeoutSpy = vi.spyOn(globalThis, 'setTimeout');
    mocks.getDocument.mockResolvedValue({
      ...documentResponse('document-1'),
      status: 'completed',
    });
    mocks.getDocumentEditConfig.mockResolvedValue(editConfig(1000));

    render(<DocumentSettingsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('file-source')).toHaveAttribute(
        'data-filename',
        'document-1.pdf',
      );
    });
    expect(
      timeoutSpy.mock.calls.some(([, delay]) => delay === 3000),
    ).toBe(false);
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it('schedules the existing redirect after observed processing completes', async () => {
    class FakeEventSource {
      static readonly CLOSED = 2;
      static latest: FakeEventSource | null = null;

      readyState = 1;
      onmessage: ((event: { data: string }) => void) | null = null;
      onerror: (() => void) | null = null;

      constructor() {
        FakeEventSource.latest = this;
      }

      close() {
        this.readyState = FakeEventSource.CLOSED;
      }
    }
    vi.stubGlobal('EventSource', FakeEventSource);
    const timeoutSpy = vi.spyOn(globalThis, 'setTimeout');
    mocks.getDocument.mockResolvedValue({
      ...documentResponse('document-1'),
      status: 'processing',
      meta_info: { progress: 50 },
    });
    mocks.getDocumentEditConfig.mockResolvedValue(editConfig(1000));

    render(<DocumentSettingsPage />);

    await waitFor(() => {
      expect(FakeEventSource.latest).not.toBeNull();
    });
    act(() => {
      FakeEventSource.latest?.onmessage?.({
        data: JSON.stringify({ status: 'completed', progress: 100 }),
      });
    });

    await waitFor(() => {
      expect(
        timeoutSpy.mock.calls.some(([, delay]) => delay === 3000),
      ).toBe(true);
    });
  });

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
      expect(screen.getByTestId('file-source')).toHaveAttribute(
        'data-filename',
        'document-2.pdf',
      );
      expect(
        screen.getByRole('button', { name: '처리 시작' }),
      ).toBeEnabled();
    });

    await act(async () => {
      firstDocument.resolve(documentResponse('document-1'));
      await firstDocument.promise;
    });

    expect(screen.getByTestId('chunk-size')).toHaveTextContent('2222');
    expect(screen.getByTestId('file-source')).toHaveAttribute(
      'data-filename',
      'document-2.pdf',
    );
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


describe('DocumentSettingsPage completion redirect', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it('keeps an already-completed document settings page open', async () => {
    mocks.getDocument.mockResolvedValue({
      ...documentResponse('doc-1'),
      filename: 'guide.md',
      status: 'completed',
    });

    await act(async () => {
      render(<DocumentSettingsPage />);
    });

    expect(screen.getByRole('heading', { name: 'guide.md' })).toBeVisible();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it('returns to the knowledge base after this page starts processing and it completes', async () => {
    mocks.getDocument.mockResolvedValue({
      ...documentResponse('doc-1'),
      filename: 'guide.md',
    });
    mockedUseDocumentProcess.mockImplementation((props) =>
      createDocumentProcessResult(() => {
        props.setStatus('completed');
        props.setProgress(100);
      }) as ReturnType<typeof useDocumentProcess>,
    );

    await act(async () => {
      render(<DocumentSettingsPage />);
    });

    expect(screen.getByRole('heading', { name: 'guide.md' })).toBeVisible();
    act(() => {
      fireEvent.click(screen.getByRole('button', { name: '처리 시작' }));
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(mocks.push).toHaveBeenCalledWith('/dashboard/knowledge/kb-1');
  });
});
