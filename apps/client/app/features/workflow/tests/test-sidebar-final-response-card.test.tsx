import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { FinalResponseCard } from '../components/editor/TestSidebar';
import type { FinalResponsePreview } from '../utils/testExecutionFinalResponse';

afterEach(() => {
  cleanup();
});

describe('TestSidebar final response card', () => {
  it('최종 사용자가 받는 text 응답을 별도 카드로 표시한다', () => {
    render(
      <FinalResponseCard
        preview={{
          kind: 'text',
          text: '개발팀 커밋 컨벤션은 feat: 설명 형식입니다.',
          isEmpty: false,
          sourceLabel: '정책 답변 LLM',
        }}
      />,
    );

    expect(screen.getByRole('heading', { name: '최종 응답' })).toBeVisible();
    expect(screen.getByText('정책 답변 LLM')).toBeVisible();
    expect(
      screen.getByText('개발팀 커밋 컨벤션은 feat: 설명 형식입니다.'),
    ).toBeVisible();
  });

  it('JSON 응답은 raw dump 대신 필드 preview로 표시한다', () => {
    const preview: FinalResponsePreview = {
      kind: 'json',
      items: [
        { label: 'summary', value: '온보딩 절차 안내' },
        { label: 'next_steps', value: '2개 항목' },
      ],
      text: 'summary: 온보딩 절차 안내\nnext_steps: 2개 항목',
      isEmpty: false,
      sourceLabel: '워크플로우 최종 출력',
    };

    render(<FinalResponseCard preview={preview} />);

    expect(screen.getByText('summary')).toBeVisible();
    expect(screen.getByText('온보딩 절차 안내')).toBeVisible();
    expect(screen.getByText('next_steps')).toBeVisible();
    expect(screen.getByText('2개 항목')).toBeVisible();
    expect(screen.queryByText(/"summary"/)).not.toBeInTheDocument();
  });

  it('빈 최종 응답은 empty state를 표시한다', () => {
    render(
      <FinalResponseCard
        preview={{
          kind: 'text',
          text: '',
          isEmpty: true,
          sourceLabel: '실행 결과',
        }}
      />,
    );

    expect(
      screen.getByText('최종 사용자에게 표시할 응답이 비어 있습니다.'),
    ).toBeVisible();
  });
});
