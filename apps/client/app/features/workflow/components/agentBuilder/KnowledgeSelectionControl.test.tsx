import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { KnowledgeSelectionControl } from './KnowledgeSelectionControl';

const candidates = Array.from({ length: 25 }, (_, index) => ({
  candidate_id: `candidate-${index + 1}`,
  label: `Knowledge ${index + 1}`,
  confidence: 1 - index / 100,
}));

describe('KnowledgeSelectionControl', () => {
  it('explains that multiple candidates are displayed in recommendation order', () => {
    render(
      <KnowledgeSelectionControl
        candidates={candidates.slice(0, 3)}
        onSubmit={vi.fn()}
      />,
    );

    expect(
      screen.getByText(
        '위에서 아래 순서로 요청과의 추천 점수가 높은 후보입니다. 점수가 같으면 현재 사용 가능 상태와 출처 우선순위를 먼저 반영합니다.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('1순위')).toBeInTheDocument();
    expect(screen.getByText('3순위')).toBeInTheDocument();
  });

  it('limits candidates to 20 and submits multiple selections', () => {
    const onSubmit = vi.fn();
    render(
      <KnowledgeSelectionControl candidates={candidates} onSubmit={onSubmit} />,
    );

    expect(screen.getAllByRole('checkbox')).toHaveLength(20);
    fireEvent.click(screen.getByLabelText('Knowledge 1'));
    fireEvent.click(screen.getByLabelText('Knowledge 2'));
    expect(
      screen.getByRole('button', {
        name: '\uC120\uD0DD\uD55C Knowledge Base\uB85C \uC0DD\uC131',
      }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', {
        name: '\uC120\uD0DD\uD55C Knowledge Base\uB85C \uC0DD\uC131',
      }),
    );

    expect(onSubmit).toHaveBeenCalledWith(['candidate-1', 'candidate-2']);
  });

  it('submits an empty array when no candidate is selected', () => {
    const onSubmit = vi.fn();
    render(
      <KnowledgeSelectionControl candidates={candidates} onSubmit={onSubmit} />,
    );

    fireEvent.click(
      screen.getByRole('button', {
        name: 'Knowledge Base \uC5C6\uC774 \uC0DD\uC131',
      }),
    );

    expect(onSubmit).toHaveBeenCalledWith([]);
  });

  it('hydrates a persisted candidate id into the current selection id', () => {
    const onSubmit = vi.fn();
    render(
      <KnowledgeSelectionControl
        timing="after_graph"
        candidates={[
          {
            candidate_id: 'candidate-1',
            selection_id: 'candidate-1:resolution-1:requirement-1',
            label: 'Knowledge 1',
          },
        ]}
        initialSelectedIds={['candidate-1']}
        disabled
        onSubmit={onSubmit}
      />,
    );

    expect(screen.getByLabelText('Knowledge 1')).toBeChecked();
    expect(screen.getByLabelText('Knowledge 1')).toBeDisabled();
    expect(screen.getByRole('button', { name: '선택 적용' })).toBeDisabled();
  });

  it('keeps the selected candidates visible when an apply attempt fails', () => {
    const { rerender } = render(
      <KnowledgeSelectionControl candidates={candidates.slice(0, 2)} onSubmit={vi.fn()} />,
    );

    fireEvent.click(screen.getByLabelText('Knowledge 1'));
    rerender(
      <KnowledgeSelectionControl
        candidates={candidates.slice(0, 2)}
        errorMessage="Knowledge Base 선택을 적용하지 못했습니다. 현재 선택은 유지됩니다. 다시 시도해주세요."
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByLabelText('Knowledge 1')).toBeChecked();
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Knowledge Base 선택을 적용하지 못했습니다. 현재 선택은 유지됩니다. 다시 시도해주세요.',
    );
    expect(
      screen.getByRole('button', { name: '선택한 Knowledge Base로 생성' }),
    ).toBeEnabled();
  });

  it('shows the four timing-specific CTA labels', () => {
    const onSubmit = vi.fn();
    const { rerender } = render(
      <KnowledgeSelectionControl
        timing="before_graph"
        candidates={candidates}
        onSubmit={onSubmit}
      />,
    );

    expect(
      screen.getByRole('button', {
        name: 'Knowledge Base \uC5C6\uC774 \uC0DD\uC131',
      }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Knowledge 1'));
    expect(
      screen.getByRole('button', {
        name: '\uC120\uD0DD\uD55C Knowledge Base\uB85C \uC0DD\uC131',
      }),
    ).toBeInTheDocument();

    rerender(
      <KnowledgeSelectionControl
        timing="after_graph"
        candidates={candidates}
        onSubmit={onSubmit}
      />,
    );
    expect(
      screen.getByRole('button', {
        name: 'Knowledge Base \uC5C6\uC774 \uACC4\uC18D',
      }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Knowledge 1'));
    expect(
      screen.getByRole('button', { name: '\uC120\uD0DD \uC801\uC6A9' }),
    ).toBeInTheDocument();
  });
});
