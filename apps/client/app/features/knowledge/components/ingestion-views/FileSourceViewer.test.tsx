import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import FileSourceViewer from './FileSourceViewer';

const CONTENT_URL = '/api/v1/knowledge/kb-1/documents/document-1/content';

describe('FileSourceViewer', () => {
  it('renders a loading state until both resource identifiers are available', () => {
    const { container } = render(
      <FileSourceViewer
        kbId=""
        documentId="document-1"
        filename="policy.pdf"
      />,
    );

    expect(screen.getByText('문서를 불러오는 중입니다...')).toBeInTheDocument();
    expect(container.querySelector('object')).not.toBeInTheDocument();
    expect(container.querySelector('iframe')).not.toBeInTheDocument();
  });

  it('does not request content when the document filename is unavailable', () => {
    const { container } = render(
      <FileSourceViewer kbId="kb-1" documentId="document-1" />,
    );

    expect(
      screen.getByText('원본 문서 정보를 확인할 수 없습니다.'),
    ).toBeInTheDocument();
    expect(container.querySelector('object')).not.toBeInTheDocument();
    expect(container.querySelector('iframe')).not.toBeInTheDocument();
  });

  it('uses the browser PDF viewer and a safe same-origin new-tab fallback', () => {
    const { container } = render(
      <FileSourceViewer
        kbId="kb-1"
        documentId="document-1"
        filename="Policy.PDF?version=2#page=1"
      />,
    );

    const object = container.querySelector('object');
    expect(object).toHaveAttribute('data', CONTENT_URL);
    expect(object).toHaveAttribute('type', 'application/pdf');
    expect(object).not.toHaveAttribute('sandbox');
    expect(container.querySelector('iframe')).not.toBeInTheDocument();

    const openLink = screen.getByRole('link', {
      name: 'PDF를 새 탭에서 열기',
    });
    expect(openLink).toHaveAttribute('href', CONTENT_URL);
    expect(openLink).toHaveAttribute('target', '_blank');
    expect(openLink).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('keeps non-PDF content in the existing scriptless sandbox', () => {
    const { container } = render(
      <FileSourceViewer
        kbId="kb-1"
        documentId="document-1"
        filename="policy.docx"
      />,
    );

    const iframe = container.querySelector('iframe');
    expect(iframe).toHaveAttribute('src', CONTENT_URL);
    expect(iframe).toHaveAttribute(
      'sandbox',
      'allow-same-origin allow-downloads',
    );
    expect(iframe?.getAttribute('sandbox')).not.toContain('allow-scripts');
    expect(container.querySelector('object')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('link', { name: 'PDF를 새 탭에서 열기' }),
    ).not.toBeInTheDocument();
  });
});
