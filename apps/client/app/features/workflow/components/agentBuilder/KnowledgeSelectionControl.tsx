'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

export type KnowledgeSelectionCandidate = {
  selection_id?: string;
  candidate_id: string;
  label: string;
  confidence?: number | null;
  score?: number | null;
  reason?: string | null;
};

export type KnowledgeSelectionChild = {
  kb_handle: string;
  selection_key: string;
  safe_label?: string | null;
  score?: number | null;
  shared_collection_count?: number;
};

export type KnowledgeSelectionCollection = {
  collection_handle: string;
  safe_label?: string | null;
  score?: number | null;
  children: KnowledgeSelectionChild[];
};

export type KnowledgeHierarchySubmission = {
  collectionHandles: string[];
  kbHandles: string[];
};

export const KnowledgeSelectionControl = ({
  candidates,
  collections = [],
  ungroupedKbs = [],
  onSubmit,
  onSubmitHierarchy,
  disabled = false,
  timing = 'before_graph',
  initialSelectedIds = [],
  initialSelectedCollectionHandles = [],
  initialSelectedKbHandles = [],
  errorMessage = null,
}: {
  candidates: KnowledgeSelectionCandidate[];
  collections?: KnowledgeSelectionCollection[];
  ungroupedKbs?: KnowledgeSelectionChild[];
  onSubmit: (selectionIds: string[]) => void;
  onSubmitHierarchy?: (selection: KnowledgeHierarchySubmission) => void;
  disabled?: boolean;
  timing?: 'before_graph' | 'after_graph';
  initialSelectedIds?: string[];
  initialSelectedCollectionHandles?: string[];
  initialSelectedKbHandles?: string[];
  errorMessage?: string | null;
}) => {
  const selectionId = (candidate: KnowledgeSelectionCandidate) =>
    candidate.selection_id ?? candidate.candidate_id;
  const visibleCandidates = candidates.slice(0, 20);
  const initialSelection = visibleCandidates
    .filter((candidate) => {
      const id = selectionId(candidate);
      return (
        initialSelectedIds.includes(id) ||
        initialSelectedIds.includes(candidate.candidate_id)
      );
    })
    .map(selectionId);
  const [selectedIds, setSelectedIds] = useState<string[]>(initialSelection);
  const [selectedCollectionHandles, setSelectedCollectionHandles] = useState<
    string[]
  >(initialSelectedCollectionHandles);

  const allHierarchyKbs = useMemo(() => {
    const rows = [
      ...collections.flatMap((collection) => collection.children),
      ...ungroupedKbs,
    ];
    const bySelectionKey = new Map<string, KnowledgeSelectionChild>();
    rows.forEach((row) => bySelectionKey.set(row.selection_key, row));
    return { rows, bySelectionKey };
  }, [collections, ungroupedKbs]);
  const initialKbKeys = useMemo(
    () =>
      Array.from(allHierarchyKbs.bySelectionKey.values())
        .filter(
          (item) =>
            initialSelectedKbHandles.includes(item.kb_handle) ||
            initialSelectedKbHandles.includes(item.selection_key),
        )
        .map((item) => item.selection_key),
    [allHierarchyKbs, initialSelectedKbHandles],
  );
  const [selectedKbKeys, setSelectedKbKeys] = useState<string[]>(initialKbKeys);
  const hierarchyMode = collections.length > 0 || ungroupedKbs.length > 0;

  const selectionScope = JSON.stringify({
    timing,
    flat: visibleCandidates.map(selectionId),
    collections: collections.map((item) => item.collection_handle),
    kbs: Array.from(allHierarchyKbs.bySelectionKey.keys()),
    initialSelection,
    initialSelectedCollectionHandles,
    initialKbKeys,
  });
  const previousSelectionScopeRef = useRef(selectionScope);
  useEffect(() => {
    if (previousSelectionScopeRef.current === selectionScope) return;
    previousSelectionScopeRef.current = selectionScope;
    setSelectedIds(initialSelection);
    setSelectedCollectionHandles(initialSelectedCollectionHandles);
    setSelectedKbKeys(initialKbKeys);
  }, [
    initialKbKeys,
    initialSelection,
    initialSelectedCollectionHandles,
    selectionScope,
  ]);

  const toggleValue = (value: string, setter: typeof setSelectedIds) => {
    setter((current) =>
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value],
    );
  };

  const selectedCount = hierarchyMode
    ? selectedCollectionHandles.length + selectedKbKeys.length
    : selectedIds.length;
  const submitLabel =
    selectedCount === 0
      ? timing === 'after_graph'
        ? 'Knowledge Base 없이 계속'
        : 'Knowledge Base 없이 생성'
      : timing === 'after_graph'
        ? '선택 적용'
        : hierarchyMode
          ? '선택한 Knowledge로 생성'
          : '선택한 Knowledge Base로 생성';

  const hierarchySubmission = (): KnowledgeHierarchySubmission => {
    const kbHandles = Array.from(
      new Set(
        selectedKbKeys
          .map((key) => allHierarchyKbs.bySelectionKey.get(key)?.kb_handle)
          .filter((value): value is string => Boolean(value)),
      ),
    );
    return { collectionHandles: selectedCollectionHandles, kbHandles };
  };

  const submit = () => {
    if (!hierarchyMode || !onSubmitHierarchy) {
      onSubmit(selectedIds);
      return;
    }
    onSubmitHierarchy(hierarchySubmission());
  };

  const renderKb = (candidate: KnowledgeSelectionChild) => (
    <label
      key={`${candidate.selection_key}:${candidate.kb_handle}`}
      className="flex min-h-[48px] items-center gap-3 border-t border-neutral-200 px-3 py-2 pl-8 dark:border-neutral-800"
    >
      <input
        type="checkbox"
        aria-label={candidate.safe_label ?? 'Knowledge Base'}
        checked={selectedKbKeys.includes(candidate.selection_key)}
        disabled={disabled}
        onChange={() => toggleValue(candidate.selection_key, setSelectedKbKeys)}
      />
      <span className="min-w-0 flex-1 truncate text-sm">
        {candidate.safe_label ?? 'Knowledge Base'}
        {(candidate.shared_collection_count ?? 0) > 1 ? (
          <span className="ml-2 text-xs text-neutral-500">[공유 KB]</span>
        ) : null}
      </span>
      {typeof candidate.score === 'number' ? (
        <span className="text-xs tabular-nums text-neutral-500">
          {candidate.score.toFixed(2)}
        </span>
      ) : null}
    </label>
  );

  return (
    <div className="space-y-3">
      <p className="text-xs leading-5 text-neutral-500 dark:text-neutral-400">
        추천 점수 내림차순으로 표시됩니다. Collection은 실행 시 자동 라우팅하고,
        하위 Knowledge Base는 Workflow에 직접 고정합니다.
      </p>
      <div className="max-h-[156px] overflow-y-auto rounded-md border border-neutral-200 dark:border-neutral-800">
        {hierarchyMode ? (
          <>
            {collections.map((collection) => (
              <div key={collection.collection_handle}>
                <label className="flex min-h-[52px] items-center gap-3 px-3 py-2">
                  <input
                    type="checkbox"
                    aria-label={collection.safe_label ?? 'Knowledge Collection'}
                    checked={selectedCollectionHandles.includes(
                      collection.collection_handle,
                    )}
                    disabled={disabled}
                    onChange={() =>
                      toggleValue(
                        collection.collection_handle,
                        setSelectedCollectionHandles,
                      )
                    }
                  />
                  <span className="min-w-0 flex-1 text-sm">
                    <span className="block truncate">
                      {collection.safe_label ?? 'Knowledge Collection'}
                    </span>
                    <span className="block text-xs text-neutral-500">
                      실행 시 Collection에서 자동 라우팅
                    </span>
                  </span>
                  {typeof collection.score === 'number' ? (
                    <span className="text-xs tabular-nums text-neutral-500">
                      {collection.score.toFixed(2)}
                    </span>
                  ) : null}
                </label>
                {collection.children.map(renderKb)}
              </div>
            ))}
            {ungroupedKbs.length > 0 ? (
              <section aria-label="직접 연결된 KB">
                <h4 className="border-t border-neutral-200 px-3 py-2 text-xs font-medium text-neutral-600 dark:border-neutral-800 dark:text-neutral-300">
                  직접 연결된 KB
                </h4>
                {ungroupedKbs.map(renderKb)}
              </section>
            ) : null}
          </>
        ) : (
          visibleCandidates.map((candidate, index) => (
            <label
              key={selectionId(candidate)}
              className="flex min-h-[52px] items-center gap-3 border-b border-neutral-200 px-3 py-2 last:border-b-0 dark:border-neutral-800"
            >
              <input
                type="checkbox"
                aria-label={candidate.label}
                checked={selectedIds.includes(selectionId(candidate))}
                disabled={disabled}
                onChange={() =>
                  toggleValue(selectionId(candidate), setSelectedIds)
                }
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
                {visibleCandidates.length > 1 ? (
                  <span>{index + 1}순위</span>
                ) : null}
                {typeof candidate.score === 'number' ||
                typeof candidate.confidence === 'number' ? (
                  <span>
                    {(candidate.score ?? candidate.confidence)?.toFixed(2)}
                  </span>
                ) : null}
              </span>
            </label>
          ))
        )}
      </div>
      {errorMessage ? (
        <p
          role="alert"
          className="text-xs leading-5 text-amber-700 dark:text-amber-300"
        >
          {errorMessage}
        </p>
      ) : null}
      {hierarchyMode && onSubmitHierarchy ? (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() =>
              onSubmitHierarchy({ collectionHandles: [], kbHandles: [] })
            }
            disabled={disabled}
            className="rounded-md border border-neutral-300 px-3 py-2 text-sm font-medium hover:bg-neutral-50 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-900"
          >
            {timing === 'after_graph'
              ? 'Knowledge Base 없이 계속'
              : 'Knowledge Base 없이 생성'}
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={disabled || selectedCount === 0}
            className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {timing === 'after_graph' ? '선택 적용' : '선택한 Knowledge로 생성'}
          </button>
        </div>
      ) : (
        <button
          type="button"
          onClick={submit}
          disabled={disabled}
          className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {submitLabel}
        </button>
      )}
    </div>
  );
};
