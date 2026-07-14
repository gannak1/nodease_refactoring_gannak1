'use client';

import { useEffect, useRef, useState } from 'react';

export type KnowledgeSelectionCandidate = {
  selection_id?: string;
  candidate_id: string;
  label: string;
  confidence?: number | null;
  score?: number | null;
  reason?: string | null;
};

export const KnowledgeSelectionControl = ({
  candidates,
  onSubmit,
  disabled = false,
  timing = 'before_graph',
  initialSelectedIds = [],
  errorMessage = null,
}: {
  candidates: KnowledgeSelectionCandidate[];
  onSubmit: (selectionIds: string[]) => void;
  disabled?: boolean;
  timing?: 'before_graph' | 'after_graph';
  initialSelectedIds?: string[];
  errorMessage?: string | null;
}) => {
  const selectionId = (candidate: KnowledgeSelectionCandidate) =>
    candidate.selection_id ?? candidate.candidate_id;
  const visibleCandidates = candidates.slice(0, 20);
  const hasMultipleCandidates = visibleCandidates.length > 1;
  const initialSelection = visibleCandidates
    .filter((candidate) => {
      const candidateSelectionId = selectionId(candidate);
      return (
        initialSelectedIds.includes(candidateSelectionId) ||
        initialSelectedIds.includes(candidate.candidate_id)
      );
    })
    .map(selectionId);
  const [selectedIds, setSelectedIds] = useState<string[]>(initialSelection);
  const candidateSignature = visibleCandidates.map(selectionId).join('\u001f');
  const initialSelectionSignature = initialSelection.join('\u001f');
  const selectionScope = `${timing}\u001e${candidateSignature}\u001e${initialSelectionSignature}`;
  const previousSelectionScopeRef = useRef(selectionScope);

  useEffect(() => {
    if (previousSelectionScopeRef.current === selectionScope) return;
    previousSelectionScopeRef.current = selectionScope;
    setSelectedIds(initialSelection);
  }, [initialSelection, selectionScope]);

  const toggle = (candidateId: string) => {
    setSelectedIds((current) =>
      current.includes(candidateId)
        ? current.filter((item) => item !== candidateId)
        : [...current, candidateId],
    );
  };

  const submitLabel =
    selectedIds.length === 0
      ? timing === 'after_graph'
        ? 'Knowledge Base \uC5C6\uC774 \uACC4\uC18D'
        : 'Knowledge Base \uC5C6\uC774 \uC0DD\uC131'
      : timing === 'after_graph'
        ? '\uC120\uD0DD \uC801\uC6A9'
        : '\uC120\uD0DD\uD55C Knowledge Base\uB85C \uC0DD\uC131';

  return (
    <div className="space-y-3">
      {hasMultipleCandidates ? (
        <p
          data-testid="knowledge-candidate-order-description"
          className="text-xs leading-5 text-neutral-500 dark:text-neutral-400"
        >
          위에서 아래 순서로 요청과의 추천 점수가 높은 후보입니다. 점수가 같으면 현재 사용 가능 상태와 출처 우선순위를 먼저 반영합니다.
        </p>
      ) : null}
      <div className="max-h-[156px] overflow-y-auto rounded-md border border-neutral-200 dark:border-neutral-800">
        {visibleCandidates.map((candidate, index) => (
          <label
            key={selectionId(candidate)}
            className="flex min-h-[52px] items-center gap-3 border-b border-neutral-200 px-3 py-2 last:border-b-0 dark:border-neutral-800"
          >
            <input
              type="checkbox"
              aria-label={candidate.label}
              checked={selectedIds.includes(selectionId(candidate))}
              disabled={disabled}
              onChange={() => toggle(selectionId(candidate))}
            />
            <span className="min-w-0 flex-1 text-sm">
              <span className="block truncate">{candidate.label}</span>
              {candidate.reason ? (
                <span className="block truncate text-xs text-neutral-500">
                  {candidate.reason}
                </span>
              ) : null}
            </span>
            <span className="flex shrink-0 items-center gap-2 text-xs tabular-nums text-neutral-500">
              {hasMultipleCandidates ? (
                <span className="font-medium text-neutral-600 dark:text-neutral-300">
                  {index + 1}순위
                </span>
              ) : null}
              {typeof candidate.score === 'number' ||
              typeof candidate.confidence === 'number' ? (
                <span>{(candidate.score ?? candidate.confidence)?.toFixed(2)}</span>
              ) : null}
            </span>
          </label>
        ))}
      </div>
      {errorMessage ? (
        <p
          role="alert"
          className="text-xs leading-5 text-amber-700 dark:text-amber-300"
        >
          {errorMessage}
        </p>
      ) : null}
      <button
        type="button"
        onClick={() => onSubmit(selectedIds)}
        disabled={disabled}
        className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700"
      >
        {submitLabel}
      </button>
    </div>
  );
};
