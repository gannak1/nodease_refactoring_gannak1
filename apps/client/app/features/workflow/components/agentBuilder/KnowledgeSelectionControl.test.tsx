import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { KnowledgeSelectionControl } from './KnowledgeSelectionControl';

const candidates = Array.from({ length: 25 }, (_, index) => ({
  candidate_id: `candidate-${index + 1}`,
  label: `Knowledge ${index + 1}`,
  confidence: 1 - index / 100,
}));

describe('KnowledgeSelectionControl', () => {
  it('keeps a shared KB checked across Collections while Collection selection stays independent', () => {
    const onSubmit = vi.fn();
    render(
      <KnowledgeSelectionControl
        candidates={[]}
        collections={[
          {
            collection_handle: 'collection-a',
            safe_label: '사내 문서 Collection',
            score: 0.84,
            children: [
              {
                kb_handle: 'kb-1',
                selection_key: 'shared-kb-1',
                safe_label: '사내 인사 KB',
                score: 0.9,
                shared_collection_count: 2,
              },
            ],
          },
          {
            collection_handle: 'collection-b',
            safe_label: '경영 문서 Collection',
            score: 0.72,
            children: [
              {
                kb_handle: 'kb-1',
                selection_key: 'shared-kb-1',
                safe_label: '사내 인사 KB',
                score: 0.9,
                shared_collection_count: 2,
              },
            ],
          },
        ]}
        onSubmitHierarchy={onSubmit}
        onSubmit={vi.fn()}
      />,
    );

    const sharedKbCheckboxes = screen.getAllByLabelText('사내 인사 KB');
    fireEvent.click(sharedKbCheckboxes[0]);
    expect(sharedKbCheckboxes[0]).toBeChecked();
    expect(sharedKbCheckboxes[1]).toBeChecked();

    fireEvent.click(screen.getByLabelText('사내 문서 Collection'));
    expect(screen.getByLabelText('사내 문서 Collection')).toBeChecked();
    expect(screen.getByLabelText('경영 문서 Collection')).not.toBeChecked();

    expect(
      screen.getByRole('button', { name: 'Knowledge Base 없이 생성' }),
    ).toBeEnabled();

    fireEvent.click(
      screen.getByRole('button', { name: '선택한 Knowledge로 생성' }),
    );
    expect(onSubmit).toHaveBeenCalledWith({
      collectionHandles: ['collection-a'],
      kbHandles: ['kb-1'],
    });
  });

  it('submits an explicit empty hierarchy selection independently from checked values', () => {
    const onSubmit = vi.fn();
    render(
      <KnowledgeSelectionControl
        timing="after_graph"
        candidates={[]}
        collections={[
          {
            collection_handle: 'collection-a',
            safe_label: '사내 문서 Collection',
            score: 0.8,
            children: [],
          },
        ]}
        onSubmitHierarchy={onSubmit}
        onSubmit={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByLabelText('사내 문서 Collection'));
    fireEvent.click(
      screen.getByRole('button', { name: 'Knowledge Base 없이 계속' }),
    );

    expect(onSubmit).toHaveBeenCalledWith({
      collectionHandles: [],
      kbHandles: [],
    });
  });
  it('explains that multiple candidates are displayed in recommendation order', () => {
    render(
      <KnowledgeSelectionControl
        candidates={candidates.slice(0, 3)}
        onSubmit={vi.fn()}
      />,
    );

    expect(
      screen.getByText(
        '추천 점수 내림차순으로 표시됩니다. Collection은 실행 시 자동 라우팅하고, 하위 Knowledge Base는 Workflow에 직접 고정합니다.',
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
      <KnowledgeSelectionControl
        candidates={candidates.slice(0, 2)}
        onSubmit={vi.fn()}
      />,
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
