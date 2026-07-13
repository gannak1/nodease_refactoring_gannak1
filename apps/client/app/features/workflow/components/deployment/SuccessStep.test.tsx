import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { SuccessStep } from './SuccessStep';

vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
  },
}));

afterEach(() => {
  cleanup();
});

describe('SuccessStep', () => {
  it('shows a non-blocking preflight warning after a successful deployment', () => {
    render(
      <SuccessStep
        deploymentType="api"
        onClose={vi.fn()}
        result={{
          success: true,
          version: 1,
          message:
            '배포 전 검사 경고가 있습니다.\n실행 시 지식 후보가 제한될 수 있습니다.',
        }}
      />,
    );

    expect(screen.getByRole('status')).toHaveTextContent(
      '배포 전 검사 경고가 있습니다.',
    );
    expect(screen.getByRole('status')).toHaveTextContent(
      '실행 시 지식 후보가 제한될 수 있습니다.',
    );
  });

  it('distinguishes public chatbot link from authenticated internal run link', () => {
    render(
      <SuccessStep
        deploymentType="chatbot"
        onClose={vi.fn()}
        result={{
          success: true,
          version: 1,
          url_slug: 'onboarding-bot',
          webAppUrl: 'http://localhost:3000/embed/chat/onboarding-bot',
          internalRunUrl:
            'http://localhost:3000/modules/workflow-1/run?deploymentId=deployment-1',
        }}
      />,
    );

    expect(screen.getByText('공개 챗봇 공유 링크')).toBeVisible();
    expect(
      screen.getByText(
        '인증 없이 접근하는 공개 링크입니다. 공개 Collection에 연결된 지식만 검색됩니다.',
      ),
    ).toBeVisible();
    expect(screen.getByText('사내 인증 실행 링크')).toBeVisible();
    expect(
      screen.getByText(
        '로그인한 사용자 권한으로 실행됩니다. 사내 private Knowledge/RAG는 이 링크에서 검증하세요.',
      ),
    ).toBeVisible();
    expect(
      screen.getByText('http://localhost:3000/embed/chat/onboarding-bot'),
    ).toBeVisible();
    expect(
      screen.getByText(
        'http://localhost:3000/modules/workflow-1/run?deploymentId=deployment-1',
      ),
    ).toBeVisible();
  });
});
