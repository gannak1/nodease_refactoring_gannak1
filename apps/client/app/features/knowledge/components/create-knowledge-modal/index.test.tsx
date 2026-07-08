import {
  createEvent,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import CreateKnowledgeModal from './index';

const routerPushMock = vi.hoisted(() => vi.fn());
const knowledgeApiMock = vi.hoisted(() => ({
  getPresignedUploadUrl: vi.fn(),
  uploadKnowledgeBase: vi.fn(),
  uploadToS3: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: routerPushMock, refresh: vi.fn() }),
}));

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock('@/app/features/knowledge/api/knowledgeApi', () => ({
  knowledgeApi: knowledgeApiMock,
}));

vi.mock('@/app/features/knowledge/api/connectorApi', () => ({
  connectorApi: {
    testConnection: vi.fn(),
  },
}));

const fetchMock = vi.fn();

const renderOpenFileSourceModal = () =>
  render(
    <CreateKnowledgeModal
      isOpen
      onClose={vi.fn()}
      knowledgeBaseId="kb-1"
      initialTab="FILE"
    />,
  );

const fileDropEvent = (
  target: Window | Element,
  dataTransfer: DataTransfer | object,
) => createEvent.drop(target, { dataTransfer });

beforeEach(() => {
  vi.clearAllMocks();
  knowledgeApiMock.getPresignedUploadUrl.mockResolvedValue({
    use_backend_proxy: true,
  });
  knowledgeApiMock.uploadKnowledgeBase.mockResolvedValue({
    knowledge_base_id: 'kb-1',
    document_id: 'doc-1',
    status: 'pending',
    message: 'ok',
  });
  fetchMock.mockResolvedValue({
    ok: true,
    json: async () => [],
  });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('CreateKnowledgeModal file drag and drop', () => {
  it('prevents browser file drop defaults inside the modal', async () => {
    const { container } = renderOpenFileSourceModal();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const modalOverlay = container.firstElementChild;
    expect(modalOverlay).toBeInTheDocument();

    const fileDrop = fileDropEvent(modalOverlay!, {
      types: ['Files'],
      files: [],
    });

    expect(fireEvent(modalOverlay!, fileDrop)).toBe(false);
    expect(fileDrop.defaultPrevented).toBe(true);

    const textDrop = fileDropEvent(modalOverlay!, {
      types: ['text/plain'],
      files: [],
    });

    expect(fireEvent(modalOverlay!, textDrop)).toBe(true);
    expect(textDrop.defaultPrevented).toBe(false);
  });

  it('keeps drag upload in the drop zone without opening the file', async () => {
    const { container } = renderOpenFileSourceModal();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    const fileInput = container.querySelector('input[type="file"]');
    expect(fileInput).toBeInTheDocument();

    const dropZone = fileInput?.parentElement;
    expect(dropZone).toBeInTheDocument();

    const upload = new File(['hello'], 'guide.md', {
      type: 'text/markdown',
    });
    const dataTransfer = {
      types: ['Files'],
      files: [upload],
      dropEffect: 'none',
    };
    const drop = fileDropEvent(dropZone!, dataTransfer);

    expect(fireEvent(dropZone!, drop)).toBe(false);
    expect(drop.defaultPrevented).toBe(true);
    expect(dataTransfer.dropEffect).toBe('copy');
    expect(await screen.findByText('guide.md')).toBeInTheDocument();
  });

  it('returns to the source list after adding a file source', async () => {
    const onClose = vi.fn();
    const { container } = render(
      <CreateKnowledgeModal
        isOpen
        onClose={onClose}
        knowledgeBaseId="kb-1"
        initialTab="FILE"
      />,
    );
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    const fileInput = container.querySelector('input[type="file"]');
    expect(fileInput).toBeInTheDocument();
    const upload = new File(['hello'], 'guide.md', {
      type: 'text/markdown',
    });
    fireEvent.change(fileInput!, {
      target: { files: [upload] },
    });

    const buttons = screen.getAllByRole('button');
    fireEvent.click(buttons[buttons.length - 1]);

    await waitFor(() => {
      expect(knowledgeApiMock.uploadKnowledgeBase).toHaveBeenCalled();
    });
    expect(onClose).toHaveBeenCalled();
    expect(routerPushMock).toHaveBeenCalledWith('/dashboard/knowledge/kb-1');
    expect(routerPushMock).not.toHaveBeenCalledWith(
      '/dashboard/knowledge/kb-1/document/doc-1',
    );
  });
});
