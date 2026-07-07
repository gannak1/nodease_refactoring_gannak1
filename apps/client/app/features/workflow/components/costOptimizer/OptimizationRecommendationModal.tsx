'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Play, Wand2, X } from 'lucide-react';

import { workflowApi } from '../../api/workflowApi';
import type {
  CostOptimizerParameterRecommendation,
  CostOptimizerParameterRecommendationsResponse,
} from '../../types/Api';

export type OptimizationRecommendationNode = {
  id: string;
  title: string;
};

interface OptimizationRecommendationModalProps {
  workflowId: string;
  workflowName?: string;
  llmNodes: OptimizationRecommendationNode[];
  initialNodeId?: string;
  appliedIds?: string[];
  onClose: () => void;
  onMarkForReview?: (recommendationIds: string[]) => void;
}

const parameterRecommendationLabelOf = (parameterKey: string) =>
  ({
    max_tokens: '최대 응답 길이 줄이기',
    temperature: '출력 안정성 높이기',
    top_p: 'Claude 호환 설정 정리',
    frequency_penalty: '반복 답변 줄이기',
    'rag.top_k': '검색 문서 개수 줄이기',
    'rag.retrieved_context_max_chars': '검색 문서 길이 제한하기',
    'rag.retrieved_context_compression': '검색 문서 압축 켜기',
  })[parameterKey] || parameterKey;

const parameterRecommendationTargetOf = (parameterKey: string) =>
  parameterKey.startsWith('rag.') ? '지식 베이스' : '고급 설정';

const formatRecommendationValue = (
  value: unknown,
  parameterKey?: string,
): string => {
  if (value == null) return '설정 없음';
  if (typeof value === 'number') {
    const formatted = value.toLocaleString('ko-KR');
    if (parameterKey === 'max_tokens') return `${formatted} 토큰`;
    if (parameterKey === 'rag.top_k') return `${formatted}개`;
    if (parameterKey === 'rag.retrieved_context_max_chars') {
      return `${formatted}자`;
    }
    return formatted;
  }
  if (typeof value === 'string') return value || '설정 없음';
  if (typeof value === 'boolean') return value ? '켜짐' : '꺼짐';
  return JSON.stringify(value);
};

const evidenceLabelOf = (key: string) =>
  ({
    sample_count: '운영 로그 수',
    completion_tokens_p95: '대부분의 최근 응답 길이',
    prompt_tokens_p95: '대부분의 최근 입력 길이',
    context_token_estimate_p95: '검색 문서가 차지한 길이',
    retrieved_chunk_count_p95: '불러온 검색 문서 수',
    schema_pass_rate: '스키마 통과율',
    downstream_success_rate: '후속 노드 성공률',
    schema_fail_rate: '스키마 실패율',
    downstream_fail_rate: '후속 노드 실패율',
    truncation_rate: '길이 잘림률',
    retry_rate: '재시도율',
    fallback_rate: 'Fallback 비율',
    repetition_rate: '반복률',
    model_family: '모델 계열',
    compatibility: '호환성',
  })[key] || key;

const formatEvidenceValue = (key: string, value: unknown) => {
  if (typeof value === 'number') {
    if (
      key.endsWith('_rate') ||
      key === 'schema_pass_rate' ||
      key === 'downstream_success_rate'
    ) {
      return `${Math.round(value * 1000) / 10}%`;
    }
    if (key === 'completion_tokens_p95' || key === 'prompt_tokens_p95') {
      return `${value.toLocaleString('ko-KR')}토큰 이하`;
    }
    if (key === 'context_token_estimate_p95') {
      return `${value.toLocaleString('ko-KR')}토큰 정도`;
    }
    if (key === 'retrieved_chunk_count_p95') {
      return `${value.toLocaleString('ko-KR')}개 정도`;
    }
    return value.toLocaleString('ko-KR');
  }
  if (typeof value === 'boolean') return value ? '예' : '아니오';
  if (value == null) return '-';
  return String(value);
};

const collectCandidatePatches = (
  recommendations: CostOptimizerParameterRecommendation[],
) =>
  recommendations
    .map((recommendation) => recommendation.candidate_patch)
    .filter(
      (patch): patch is Record<string, unknown> =>
        typeof patch === 'object' && patch !== null && !Array.isArray(patch),
    );

const EMPTY_APPLIED_IDS: string[] = [];

export function OptimizationRecommendationModal({
  workflowId,
  workflowName = '현재 workflow',
  llmNodes,
  initialNodeId,
  appliedIds = EMPTY_APPLIED_IDS,
  onClose,
  onMarkForReview,
}: OptimizationRecommendationModalProps) {
  const router = useRouter();
  const [selectedNodeId, setSelectedNodeId] = useState(
    initialNodeId || llmNodes[0]?.id || '',
  );
  const selectedNode =
    llmNodes.find((node) => node.id === selectedNodeId) || llmNodes[0];
  const selectedNodeTitle = selectedNode?.title || 'LLM 노드';
  const [recommendationResponse, setRecommendationResponse] =
    useState<CostOptimizerParameterRecommendationsResponse | null>(null);
  const [isLoadingRecommendations, setIsLoadingRecommendations] =
    useState(false);
  const [recommendationError, setRecommendationError] = useState('');
  const [actionError, setActionError] = useState('');
  const [isApplyingRecommendations, setIsApplyingRecommendations] =
    useState(false);
  const recommendations = recommendationResponse?.recommendations || [];
  const [selectedIds, setSelectedIds] = useState<string[]>(appliedIds);

  useEffect(() => {
    if (!workflowId || !selectedNodeId) return;

    let active = true;
    setIsLoadingRecommendations(true);
    setRecommendationError('');
    setRecommendationResponse(null);

    workflowApi
      .getCostOptimizerParameterRecommendations(workflowId, selectedNodeId)
      .then((response) => {
        if (!active) return;
        setRecommendationResponse(response);
        setSelectedIds(
          appliedIds.length > 0
            ? appliedIds
            : response.recommendations.map(
                (recommendation) => recommendation.parameter_key,
              ),
        );
      })
      .catch(() => {
        if (!active) return;
        setRecommendationError('파라미터 추천 결과를 불러오지 못했습니다.');
        setSelectedIds([]);
      })
      .finally(() => {
        if (active) setIsLoadingRecommendations(false);
      });

    return () => {
      active = false;
    };
  }, [appliedIds, selectedNodeId, workflowId]);

  const toggleRecommendation = (id: string) => {
    setActionError('');
    setSelectedIds((current) =>
      current.includes(id)
        ? current.filter((item) => item !== id)
        : [...current, id],
    );
  };

  const selectedRecommendations = recommendations.filter((recommendation) =>
    selectedIds.includes(recommendation.parameter_key),
  );
  const canRunAction =
    Boolean(workflowId && selectedNodeId) &&
    selectedRecommendations.length > 0 &&
    !isLoadingRecommendations &&
    !isApplyingRecommendations;

  const handleTestRecommendations = () => {
    if (!workflowId || !selectedNodeId) return;
    setActionError('');
    const patches = collectCandidatePatches(selectedRecommendations);
    const presetKey = `cost-optimizer-recommendations:${workflowId}:${selectedNodeId}:${Date.now()}`;
    window.sessionStorage.setItem(presetKey, JSON.stringify(patches));
    router.push(
      `/modules/${workflowId}/cost-optimizer/${selectedNodeId}?baseline=latest&recommendationPresetKey=${encodeURIComponent(
        presetKey,
      )}`,
    );
  };

  const handleApplyRecommendations = async () => {
    if (!workflowId || !selectedNodeId) return;
    setActionError('');
    setIsApplyingRecommendations(true);
    try {
      await workflowApi.applyCostOptimizerRecommendations(
        workflowId,
        selectedNodeId,
        { recommendation_ids: selectedIds },
      );
      onMarkForReview?.(selectedIds);
    } catch {
      setActionError(
        '추천 설정을 적용하지 못했습니다. 모델 권한, 지식 베이스 권한, 최신 추천 상태를 확인해 주세요.',
      );
    } finally {
      setIsApplyingRecommendations(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 px-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="optimization-recommendation-title"
    >
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-5">
          <div>
            <p className="text-xs font-bold text-violet-600">
              비용 최적화 검토
            </p>
            <h2
              id="optimization-recommendation-title"
              className="mt-1 text-xl font-bold text-slate-950"
            >
              LLM 노드 설정 추천
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              {workflowName}의 운영 로그를 기준으로, 바로 적용하지 않고 먼저
              A/B 검증해볼 설정 후보를 보여줍니다.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50"
            aria-label="나가기"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <div className="mb-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
            {llmNodes.length > 1 ? (
              <label className="block">
                <span className="text-xs font-bold text-slate-600">
                  검토할 LLM 노드
                </span>
                <select
                  value={selectedNodeId}
                  onChange={(event) => setSelectedNodeId(event.target.value)}
                  className="mt-2 h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm font-semibold text-slate-800 outline-none focus:border-violet-400 focus:ring-2 focus:ring-violet-100"
                >
                  {llmNodes.map((node) => (
                    <option key={node.id} value={node.id}>
                      {node.title}
                    </option>
                  ))}
                </select>
                <span className="mt-1 block text-xs text-slate-500">
                  LLM 노드가 여러 개라서 어떤 노드의 설정을 검토할지 먼저
                  선택합니다.
                </span>
              </label>
            ) : (
              <div>
                <span className="text-xs font-bold text-slate-600">
                  검토할 LLM 노드
                </span>
                <p className="mt-1 text-sm font-semibold text-slate-900">
                  {selectedNodeTitle}
                </p>
              </div>
            )}
          </div>

          {isLoadingRecommendations ? (
            <div className="rounded-lg border border-slate-200 bg-white px-4 py-6 text-sm font-medium text-slate-500">
              추천 엔진 결과를 불러오는 중입니다.
            </div>
          ) : null}

          {recommendationError ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
              {recommendationError}
            </div>
          ) : null}

          {!isLoadingRecommendations &&
          !recommendationError &&
          recommendationResponse?.analysis_stage === 'insufficient_logs' ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              <p className="font-semibold">
                배포 후 운영 로그가 부족해 추천을 만들지 않았습니다.
              </p>
              <p className="mt-1">
                현재 샘플 수:{' '}
                {formatRecommendationValue(
                  recommendationResponse.profile?.sample_count,
                )}
              </p>
            </div>
          ) : null}

          {!isLoadingRecommendations &&
          !recommendationError &&
          recommendationResponse?.warnings
            ? recommendationResponse.warnings.map((warning) => (
                <div
                  key={`${warning.code}-${warning.message}`}
                  className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
                >
                  <span className="font-semibold">추천 제한 안내</span>
                  {warning.message ? (
                    <span className="ml-2">{warning.message}</span>
                  ) : null}
                </div>
              ))
            : null}

          <div className="space-y-3">
            {recommendations.map((recommendation) => {
              const recommendationId = recommendation.parameter_key;
              const checked = selectedIds.includes(recommendationId);
              return (
                <label
                  key={recommendationId}
                  className={`flex cursor-pointer gap-3 rounded-lg border p-4 transition-colors ${
                    checked
                      ? 'border-violet-200 bg-violet-50/70'
                      : 'border-slate-200 bg-white hover:bg-slate-50'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleRecommendation(recommendationId)}
                    className="mt-1 h-4 w-4 rounded border-slate-300 text-violet-600 focus:ring-violet-500"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="font-bold text-slate-950">
                        {parameterRecommendationLabelOf(
                          recommendation.parameter_key,
                        )}
                      </span>
                      <span className="rounded-md border border-slate-200 bg-white px-1.5 py-0.5 text-[11px] font-semibold text-slate-600">
                        {recommendation.parameter_key}
                      </span>
                      <span className="rounded-md border border-slate-200 bg-white px-1.5 py-0.5 text-[11px] font-semibold text-slate-600">
                        {parameterRecommendationTargetOf(
                          recommendation.parameter_key,
                        )}
                      </span>
                      <span className="rounded-md border border-violet-100 bg-white px-1.5 py-0.5 text-[11px] font-semibold text-violet-700">
                        대상: {selectedNodeTitle}
                      </span>
                    </span>
                    <span className="mt-2 block text-sm leading-6 text-slate-600">
                      {recommendation.reason || '추천 엔진이 생성한 후보입니다.'}
                    </span>
                    <span className="mt-3 grid gap-2 text-xs md:grid-cols-2">
                      <span className="rounded-md border border-slate-200 bg-white px-3 py-2">
                        <span className="block font-semibold text-slate-500">
                          현재 설정
                        </span>
                        <span className="mt-1 block font-medium text-slate-800">
                          {formatRecommendationValue(
                            recommendation.current_value,
                            recommendation.parameter_key,
                          )}
                        </span>
                      </span>
                      <span className="rounded-md border border-violet-200 bg-white px-3 py-2">
                        <span className="block font-semibold text-violet-600">
                          추천 설정
                        </span>
                        <span className="mt-1 block font-medium text-slate-800">
                          {formatRecommendationValue(
                            recommendation.suggested_value,
                            recommendation.parameter_key,
                          )}
                        </span>
                      </span>
                    </span>
                    {recommendation.evidence &&
                    Object.keys(recommendation.evidence).length > 0 ? (
                      <span className="mt-3 block rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
                        <span className="block font-semibold text-slate-500">
                          추천 근거
                        </span>
                        <span className="mt-2 grid gap-2 sm:grid-cols-2">
                          {Object.entries(recommendation.evidence).map(
                            ([key, value]) => (
                              <span
                                key={key}
                                className="flex items-center justify-between gap-3 rounded-md bg-slate-50 px-2 py-1"
                              >
                                <span className="text-slate-500">
                                  {evidenceLabelOf(key)}
                                </span>
                                <span className="font-semibold text-slate-800">
                                  {formatEvidenceValue(key, value)}
                                </span>
                              </span>
                            ),
                          )}
                        </span>
                      </span>
                    ) : null}
                  </span>
                </label>
              );
            })}
          </div>

          <div className="mt-5 rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
            테스트하기는 최신 실행 로그를 A 기준으로 잡고 선택한 추천을 B
            후보 설정에 넣어 A/B 화면으로 이동합니다. 적용하기는 선택한 추천을
            현재 workflow draft의 해당 LLM 노드 설정에 바로 반영합니다.
          </div>

          {actionError ? (
            <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
              {actionError}
            </div>
          ) : null}
        </div>

        <div className="flex flex-wrap justify-end gap-2 border-t border-slate-100 px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            닫기
          </button>
          <button
            type="button"
            disabled={!canRunAction}
            onClick={handleTestRecommendations}
            className="inline-flex items-center gap-2 rounded-md border border-violet-200 bg-white px-4 py-2 text-sm font-semibold text-violet-700 hover:bg-violet-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-300"
          >
            <Play className="h-4 w-4" />
            테스트하기
          </button>
          <button
            type="button"
            disabled={!canRunAction}
            onClick={handleApplyRecommendations}
            className="inline-flex items-center gap-2 rounded-md bg-violet-600 px-4 py-2 text-sm font-semibold text-white hover:bg-violet-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            <Wand2 className="h-4 w-4" />
            {isApplyingRecommendations ? '적용 중' : '적용하기'}
          </button>
        </div>
      </div>
    </div>
  );
}
