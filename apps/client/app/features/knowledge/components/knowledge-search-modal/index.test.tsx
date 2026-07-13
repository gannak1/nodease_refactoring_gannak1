import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const axiosPostMock = vi.hoisted(() => vi.fn());
const activeOrganizationMock = vi.hoisted(() => ({
  activeOrganizationHeaders: vi.fn(),
  getStoredActiveOrganizationId: vi.fn(),
}));

vi.mock('axios', () => ({
  default: { post: axiosPostMock },
}));

vi.mock('@/lib/activeOrganization', () => activeOrganizationMock);

import KnowledgeSearchModal from './index';

describe('KnowledgeSearchModal', () => {
  beforeEach(() => {
    activeOrganizationMock.getStoredActiveOrganizationId.mockReturnValue('org-1');
    activeOrganizationMock.activeOrganizationHeaders.mockReturnValue({
      'X-Organization-Id': 'org-1',
    });
    axiosPostMock.mockResolvedValue({ data: { answer: '', references: [] } });
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => [] }),
    );
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it('sends the active organization header with a RAG chat request', async () => {
    render(
      <KnowledgeSearchModal
        isOpen
        knowledgeBaseId="10200000-0000-0000-0000-000000000334"
        onClose={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'AI 답변 (RAG Chat)' }));
    const textarea = screen.getByPlaceholderText(
      '지식 베이스에 대해 질문해보세요...',
    );
    fireEvent.change(textarea, { target: { value: '커밋 컨벤션' } });
    fireEvent.keyDown(textarea, { key: 'Enter' });

    await waitFor(() =>
      expect(axiosPostMock).toHaveBeenCalledWith(
        '/api/v1/rag/search-test/chat',
        {
          query: '커밋 컨벤션',
          knowledge_base_id: '10200000-0000-0000-0000-000000000334',
          generation_model: '',
        },
        {
          withCredentials: true,
          headers: { 'X-Organization-Id': 'org-1' },
        },
      ),
    );
  });
});
