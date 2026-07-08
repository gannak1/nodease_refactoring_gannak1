import { X, BookOpen, ChevronDown, ChevronUp } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { useWorkflowStore } from '@/app/features/workflow/store/useWorkflowStore';
import {
  knowledgeApi,
  KnowledgeBaseResponse,
  KnowledgeBaseDetailResponse,
} from '@/app/features/knowledge/api/knowledgeApi';
import { LLMNodeData } from '../../../../types/Nodes';
import {
  fetchEligibleKnowledgeBases,
  sanitizeSelectedKnowledgeBases,
  isSameKnowledgeSelection,
} from '@/app/features/workflow/utils/llmKnowledgeBaseSelection';

interface LLMReferenceSidePanelProps {
  nodeId: string;
  data: LLMNodeData;
  onClose: () => void;
  embedded?: boolean;
  readOnly?: boolean;
  onDataChange?: (updates: Partial<LLMNodeData>) => void;
}

export function LLMReferenceSidePanel({
  nodeId,
  data,
  onClose,
  embedded = false,
  readOnly = false,
  onDataChange,
}: LLMReferenceSidePanelProps) {
  const { updateNodeData } = useWorkflowStore();
  const applyNodeData = useCallback((updates: Partial<LLMNodeData>) => {
    if (readOnly) return;
    if (onDataChange) {
      onDataChange(updates);
      return;
    }
    updateNodeData(nodeId, updates);
  }, [nodeId, onDataChange, readOnly, updateNodeData]);

  // Knowledge base state
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseResponse[]>(
    [],
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [details, setDetails] = useState<
    Record<string, KnowledgeBaseDetailResponse>
  >({});
  const [detailLoading, setDetailLoading] = useState<Record<string, boolean>>(
    {},
  );
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [hasLoadedBases, setHasLoadedBases] = useState(false);
  const [preserveSelectionIds, setPreserveSelectionIds] = useState<string[]>([]);

  // Selected knowledge bases from LLM node data
  const selectedKnowledgeBases = useMemo(
    () => data.knowledgeBases || [],
    [data.knowledgeBases],
  );
  const effectiveSelectedKnowledgeBases = useMemo(() => {
    if (!hasLoadedBases) return selectedKnowledgeBases;
    return sanitizeSelectedKnowledgeBases(
      selectedKnowledgeBases,
      knowledgeBases,
      { preserveMissingIds: preserveSelectionIds },
    );
  }, [
    hasLoadedBases,
    knowledgeBases,
    preserveSelectionIds,
    selectedKnowledgeBases,
  ]);
  const selectedIds = useMemo(
    () => new Set(effectiveSelectedKnowledgeBases.map((kb) => kb.id)),
    [effectiveSelectedKnowledgeBases],
  );

  // Search settings
  const scoreThreshold = data.scoreThreshold ?? 0.5;
  const topK = data.topK ?? 3;
  const dedupeRetrievedContext = data.dedupeRetrievedContext ?? false;
  const retrievedContextMaxChars = data.retrievedContextMaxChars ?? '';
  const retrievedContextCompression = data.retrievedContextCompression ?? 'off';
  const answerGroundingCheck = data.answerGroundingCheck ?? 'off';
  const recommendedScoreRange: [number, number] = [0.3, 0.6];
  const recommendedTopKRange: [number, number] = [3, 8];

  // Fetch knowledge bases on mount
  useEffect(() => {
    const fetchBases = async () => {
      setLoading(true);
      setError(null);
      try {
        const {
          bases,
          detailsById,
          preserveSelectionIds: nextPreserveSelectionIds = [],
        } = await fetchEligibleKnowledgeBases();
        setKnowledgeBases(bases);
        setDetails((prev) => ({ ...prev, ...detailsById }));
        setPreserveSelectionIds(nextPreserveSelectionIds);
        setHasLoadedBases(true);
        const nextSelected = sanitizeSelectedKnowledgeBases(
          selectedKnowledgeBases,
          bases,
          { preserveMissingIds: nextPreserveSelectionIds },
        );
        if (
          !readOnly &&
          !isSameKnowledgeSelection(nextSelected, selectedKnowledgeBases)
        ) {
          applyNodeData({ knowledgeBases: nextSelected });
        }
      } catch {
        setError('지식을 불러오지 못했습니다.');
      } finally {
        setLoading(false);
      }
    };
    fetchBases();
  }, [applyNodeData, nodeId, readOnly, selectedKnowledgeBases]);

  // Toggle selection
  const toggleKnowledgeBase = (kb: KnowledgeBaseResponse) => {
    if (readOnly) return;
    const current = effectiveSelectedKnowledgeBases;
    let next;
    if (selectedIds.has(kb.id)) {
      next = current.filter((item) => item.id !== kb.id);
    } else {
      next = [...current, { id: kb.id, name: kb.name }];
    }
    applyNodeData({ knowledgeBases: next });
  };

  // Toggle expand/collapse for document list
  const handleToggleExpand = async (kb: KnowledgeBaseResponse) => {
    const nextExpanded = new Set(expandedIds);
    if (nextExpanded.has(kb.id)) {
      nextExpanded.delete(kb.id);
      setExpandedIds(nextExpanded);
      return;
    }

    nextExpanded.add(kb.id);
    setExpandedIds(nextExpanded);

    if (!details[kb.id]) {
      setDetailLoading((prev) => ({ ...prev, [kb.id]: true }));
      try {
        const detail = await knowledgeApi.getKnowledgeBase(kb.id);
        setDetails((prev) => ({ ...prev, [kb.id]: detail }));
      } catch {
        // 상세 문서 목록은 보조 정보라 실패해도 선택 흐름은 유지한다.
      } finally {
        setDetailLoading((prev) => ({ ...prev, [kb.id]: false }));
      }
    }
  };

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    if (Number.isNaN(date.getTime())) return '-';
    return date.toLocaleDateString('ko-KR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    });
  };

  return (
    <div
      className={
        embedded
          ? 'flex h-full min-h-0 flex-col bg-white'
          : 'absolute right-[400px] top-14 bottom-0 w-[360px] bg-white shadow-xl z-40 flex flex-col border-l border-gray-200'
      }
      style={{ transition: 'transform 0.3s ease-in-out' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 bg-indigo-50/50">
        <div className="flex items-center gap-2">
          <BookOpen className="w-4 h-4 text-indigo-600" />
          <div>
            <h3 className="font-semibold text-gray-800 text-sm">지식 베이스</h3>
            <p className="text-[10px] text-gray-500 mt-0.5">
              LLM이 참조할 지식 베이스를 선택합니다
            </p>
          </div>
        </div>
        {!embedded && (
          <button
            onClick={onClose}
            className="p-1 hover:bg-gray-200 rounded text-gray-500 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {/* Knowledge Base Selection */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-gray-700">
              지식 베이스 선택
            </span>
            <span className="text-xs text-gray-500">
              선택됨:{' '}
              <span className="font-semibold text-indigo-600">
                {selectedIds.size}
              </span>
            </span>
          </div>

          {loading && (
            <div className="text-xs text-indigo-600 animate-pulse">
              불러오는 중...
            </div>
          )}
          {error && <div className="text-xs text-red-500">{error}</div>}

          <div className="flex flex-col gap-2 max-h-72 overflow-y-auto pr-1">
            {(knowledgeBases || []).map((kb) => {
              const isSelected = selectedIds.has(kb.id);
              const isExpanded = expandedIds.has(kb.id);
              const kbDetail = details[kb.id];
              const kbDetailLoading = detailLoading[kb.id];
              const completedDocs =
                kbDetail?.documents?.filter(
                  (doc) => doc.status === 'completed',
                ) || [];

              return (
                <div
                  key={kb.id}
                  className={`rounded-lg border p-3 transition-colors ${
                    isSelected
                      ? 'border-indigo-500 bg-indigo-50'
                      : 'border-gray-200 hover:border-indigo-200 hover:bg-gray-50'
                  }`}
                >
                  <label
                    className={`flex items-start gap-3 ${
                      readOnly ? 'cursor-default' : 'cursor-pointer'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      disabled={readOnly}
                      onChange={() => toggleKnowledgeBase(kb)}
                      className="mt-0.5 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-semibold text-gray-900 truncate">
                          {kb.name}
                        </span>
                        <span className="text-[10px] text-gray-500 whitespace-nowrap">
                          {formatDate(kb.created_at)} · {kb.document_count}건
                        </span>
                      </div>
                      {kb.description && (
                        <p className="text-xs text-gray-600 mt-1 line-clamp-2">
                          {kb.description}
                        </p>
                      )}
                    </div>
                  </label>

                  {/* Expand/Collapse Button */}
                  <button
                    type="button"
                    onClick={() => handleToggleExpand(kb)}
                    className="mt-2 w-full flex items-center justify-center gap-1 text-[11px] text-indigo-600 hover:text-indigo-800 py-1 rounded hover:bg-indigo-100/50"
                  >
                    {isExpanded ? (
                      <>
                        <ChevronUp className="w-3 h-3" />
                        지식 목록 숨기기
                      </>
                    ) : (
                      <>
                        <ChevronDown className="w-3 h-3" />
                        지식 목록 보기
                      </>
                    )}
                  </button>

                  {/* Document List */}
                  {isExpanded && (
                    <div className="mt-2 rounded border border-gray-200 bg-white">
                      {kbDetailLoading ? (
                        <div className="px-3 py-2 text-xs text-indigo-600 animate-pulse">
                          불러오는 중...
                        </div>
                      ) : completedDocs.length > 0 ? (
                        <div className="max-h-24 overflow-y-auto divide-y divide-gray-100">
                          {completedDocs.slice(0, 5).map((doc, index) => (
                            <div
                              key={doc.id || `${kb.id}-doc-${index}`}
                              className="px-3 py-1.5 text-xs text-gray-900 flex items-center justify-between"
                            >
                              <span className="truncate flex-1">
                                {(() => {
                                  const filename = doc.filename;
                                  // API source: URL이면 도메인만 추출
                                  if (
                                    filename.startsWith('http://') ||
                                    filename.startsWith('https://')
                                  ) {
                                    try {
                                      return new URL(filename).hostname;
                                    } catch {
                                      return filename;
                                    }
                                  }
                                  // FILE source: UUID prefix 제거
                                  if (
                                    filename.length > 37 &&
                                    filename[36] === '_'
                                  ) {
                                    return filename.substring(37);
                                  }
                                  // DB source 등: 그대로 반환
                                  return filename;
                                })()}
                              </span>
                              <span className="text-[10px] text-gray-500 ml-2">
                                {doc.chunk_count ?? 0}청크
                              </span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="px-3 py-2 text-xs text-gray-500">
                          완료된 문서가 없습니다.
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}

            {!loading && knowledgeBases.length === 0 && !error && (
              <div className="rounded border border-dashed border-gray-300 bg-gray-50 p-3 text-sm text-gray-600">
                완료된 문서가 있는 지식 베이스가 없습니다.
              </div>
            )}
          </div>
        </div>

        {/* Search Settings */}
        <div className="space-y-4 border-t border-gray-100 pt-4">
          <span className="text-sm font-medium text-gray-700">검색 설정</span>

          {/* Score Threshold */}
          <div className="space-y-2">
            <div className="flex justify-between items-center">
              <label className="text-xs font-medium text-gray-600">
                Score Threshold
              </label>
              <span className="text-xs font-mono text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">
                {scoreThreshold.toFixed(2)}
              </span>
            </div>
            <div className="relative h-7">
              <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-2.5 rounded-full bg-gray-100 ring-1 ring-gray-200 overflow-hidden pointer-events-none">
                <div
                  className="absolute inset-y-0 bg-indigo-200"
                  style={{
                    left: `${recommendedScoreRange[0] * 100}%`,
                    right: `${(1 - recommendedScoreRange[1]) * 100}%`,
                  }}
                />
              </div>
              <input
                type="range"
                min={0}
                max={1}
                step={0.01}
                value={scoreThreshold}
                onChange={(e) => {
                  const value = Number(e.target.value);
                  applyNodeData({
                    scoreThreshold: Number.isNaN(value) ? undefined : value,
                  });
                }}
                disabled={readOnly}
                className="absolute inset-0 w-full h-6 bg-transparent accent-indigo-600 appearance-none cursor-pointer
                  [&::-webkit-slider-runnable-track]:bg-transparent
                  [&::-moz-range-track]:bg-transparent
                  [&::-ms-track]:bg-transparent"
                style={{ background: 'transparent' }}
              />
            </div>
            <div className="flex justify-between text-[10px] text-gray-400">
              <span>느슨하게</span>
              <span className="text-indigo-500">
                권장: {recommendedScoreRange[0]}~{recommendedScoreRange[1]}
              </span>
              <span>엄격하게</span>
            </div>
          </div>

          {/* Top K */}
          <div className="space-y-2">
            <div className="flex justify-between items-center">
              <label className="text-xs font-medium text-gray-600">
                Top K (반환 개수)
              </label>
              <span className="text-xs font-mono text-gray-500 bg-gray-100 px-1.5 py-0.5 rounded">
                {topK}
              </span>
            </div>
            <div className="relative h-7">
              <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-2.5 rounded-full bg-gray-100 ring-1 ring-gray-200 overflow-hidden pointer-events-none">
                <div
                  className="absolute inset-y-0 bg-indigo-200"
                  style={{
                    left: `${(recommendedTopKRange[0] / 20) * 100}%`,
                    right: `${(1 - recommendedTopKRange[1] / 20) * 100}%`,
                  }}
                />
              </div>
              <input
                type="range"
                min={1}
                max={20}
                step={1}
                value={topK}
                onChange={(e) => {
                  const value = Number(e.target.value);
                  applyNodeData({
                    topK: Number.isNaN(value) ? undefined : value,
                  });
                }}
                disabled={readOnly}
                className="absolute inset-0 w-full h-6 bg-transparent accent-indigo-600 appearance-none cursor-pointer
                  [&::-webkit-slider-runnable-track]:bg-transparent
                  [&::-moz-range-track]:bg-transparent
                  [&::-ms-track]:bg-transparent"
                style={{ background: 'transparent' }}
              />
            </div>
            <div className="flex justify-between text-[10px] text-gray-400">
              <span>1</span>
              <span className="text-indigo-500">
                권장: {recommendedTopKRange[0]}~{recommendedTopKRange[1]}
              </span>
              <span>20</span>
            </div>
          </div>
        </div>

        {/* Cost Optimization Settings */}
        <div className="space-y-4 border-t border-gray-100 pt-4">
          <div className="space-y-1">
            <span className="text-sm font-medium text-gray-700">
              비용 최적화
            </span>
            <p className="text-[11px] leading-4 text-gray-500">
              직접 작성한 프롬프트는 유지하고, 검색으로 가져온 근거
              context만 줄이거나 검증합니다.
            </p>
          </div>

          <label className="flex items-start gap-3 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
            <input
              type="checkbox"
              checked={dedupeRetrievedContext}
              disabled={readOnly}
              onChange={(event) =>
                applyNodeData({
                  dedupeRetrievedContext: event.target.checked,
                })
              }
              className="mt-0.5 h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
            />
            <span className="min-w-0">
              <span className="block text-xs font-medium text-gray-700">
                중복 근거 제거
              </span>
              <span className="block text-[11px] leading-4 text-gray-500">
                같은 내용이 반복 검색되면 가장 관련도 높은 근거만
                사용합니다.
              </span>
            </span>
          </label>

          <div className="space-y-1.5">
            <label
              htmlFor={`${nodeId}-retrieved-context-max-chars`}
              className="text-xs font-medium text-gray-600"
            >
              참조 문서 길이 제한
            </label>
            <input
              id={`${nodeId}-retrieved-context-max-chars`}
              type="number"
              min={1}
              placeholder="제한 없음"
              value={retrievedContextMaxChars}
              disabled={readOnly}
              onChange={(event) => {
                const rawValue = event.target.value;
                const value = Number(rawValue);
                applyNodeData({
                  retrievedContextMaxChars:
                    rawValue === '' || Number.isNaN(value)
                      ? undefined
                      : value,
                });
              }}
              className="w-full rounded-md border border-gray-200 px-3 py-2 text-xs text-gray-800 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:bg-gray-100"
            />
            <p className="text-[11px] leading-4 text-gray-500">
              Knowledge/RAG context에만 적용됩니다. system/user/assistant
              프롬프트는 자르지 않습니다.
            </p>
          </div>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label
                htmlFor={`${nodeId}-retrieved-context-compression`}
                className="text-xs font-medium text-gray-600"
              >
                검색 문서 압축
              </label>
              <select
                id={`${nodeId}-retrieved-context-compression`}
                value={retrievedContextCompression}
                disabled={readOnly}
                onChange={(event) =>
                  applyNodeData({
                    retrievedContextCompression: event.target.value as
                      | 'off'
                      | 'light'
                      | 'strong',
                  })
                }
                className="w-full rounded-md border border-gray-200 px-2 py-2 text-xs text-gray-800 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:bg-gray-100"
              >
                <option value="off">사용 안 함</option>
                <option value="light">약하게 압축</option>
                <option value="strong">강하게 압축</option>
              </select>
            </div>

            <div className="space-y-1.5">
              <label
                htmlFor={`${nodeId}-answer-grounding-check`}
                className="text-xs font-medium text-gray-600"
              >
                답변 근거 확인
              </label>
              <select
                id={`${nodeId}-answer-grounding-check`}
                value={answerGroundingCheck}
                disabled={readOnly}
                onChange={(event) =>
                  applyNodeData({
                    answerGroundingCheck: event.target.value as
                      | 'off'
                      | 'basic'
                      | 'strict',
                  })
                }
                className="w-full rounded-md border border-gray-200 px-2 py-2 text-xs text-gray-800 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:bg-gray-100"
              >
                <option value="off">끄기</option>
                <option value="basic">기본</option>
                <option value="strict">엄격</option>
              </select>
            </div>
          </div>
        </div>

        {/* Info Box */}
        <div className="rounded-lg bg-blue-50 border border-blue-200 p-3 space-y-1">
          <p className="text-xs font-medium text-blue-800">💡 사용 방법</p>
          <p className="text-[11px] text-blue-700">
            선택한 지식 베이스에서 사용자 프롬프트를 기반으로 관련 문서를
            검색하여 LLM에 컨텍스트로 제공합니다.
          </p>
        </div>
      </div>
    </div>
  );
}
