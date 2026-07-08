import {
  knowledgeApi,
  KnowledgeBaseDetailResponse,
  KnowledgeBaseResponse,
} from '@/app/features/knowledge/api/knowledgeApi';

/**
 * LLM 노드의 "지식" 선택/필터링 전용 유틸입니다.
 * 지식 탭에서 사용하는 그룹/문서 목록 로직과는 분리되어 있으며,
 * 그 로직을 재사용하거나 수정하지 않기 위해 별도 파일로 유지합니다.
 *
 * 이 유틸은 LLM 노드에서 아래 역할만 담당합니다.
 * - 완료된 문서가 있는 지식 베이스만 보여주기
 * - 외부에서 삭제된 베이스가 기존 선택에 남는 문제 정리
 * - 선택 목록의 이름/중복을 최신 상태로 정리
 */
type KnowledgeBaseSelection = { id: string; name: string };

type EligibleKnowledgeBasesResult = {
  bases: KnowledgeBaseResponse[];
  detailsById: Record<string, KnowledgeBaseDetailResponse>;
  preserveSelectionIds?: string[];
};

type SanitizeSelectedKnowledgeBasesOptions = {
  preserveMissingIds?: Iterable<string>;
};

// LLM 노드에서 실제로 사용할 수 있는지 판단하기 위해 검색 가능한 완료 문서 수를 계산합니다.
const getCompletedCount = (detail: KnowledgeBaseDetailResponse) => {
  const documents = Array.isArray(detail.documents) ? detail.documents : [];
  return documents.filter(
    (doc) => doc.status === 'completed' && (doc.chunk_count || 0) > 0,
  ).length;
};

const shouldPreserveSelectionOnDetailFailure = (status?: number) => {
  return status === undefined || status === 408 || status === 429 || status >= 500;
};

/**
 * LLM 노드에서 표시 가능한 지식 베이스만 가져옵니다.
 * - 목록 응답에서 후보를 고른 뒤 상세를 조회해 완료 문서가 있는지 확인합니다.
 * - 404/403 상세 실패는 삭제 또는 권한 상실로 보고 후보/선택 정리 대상에서 제외합니다.
 * - 일시적 상세 실패는 후보 표시에서는 제외하되 기존 선택값은 보존할 수 있게 id를 반환합니다.
 * - 로그에는 원본 오류 객체 대신 status와 KB id만 남겨 민감한 응답 payload 노출을 피합니다.
 */
export const fetchEligibleKnowledgeBases =
  async (): Promise<EligibleKnowledgeBasesResult> => {
    const bases = await knowledgeApi.getKnowledgeBases();
    const candidates = bases.filter((kb) => (kb.document_count || 0) > 0);
    const detailResults = await Promise.allSettled(
      candidates.map((kb) => knowledgeApi.getKnowledgeBase(kb.id)),
    );

    const detailsById: Record<string, KnowledgeBaseDetailResponse> = {};
    const eligibleBases: KnowledgeBaseResponse[] = [];
    const preserveSelectionIds: string[] = [];

    detailResults.forEach((result, index) => {
      const base = candidates[index];
      if (result.status !== 'fulfilled') {
        const status = result.reason?.response?.status;
        console.warn(
          '[LLMReference] Failed to load knowledge base detail',
          { knowledgeBaseId: base.id, status },
        );
        if (shouldPreserveSelectionOnDetailFailure(status)) {
          preserveSelectionIds.push(base.id);
        }
        return;
      }
      const detail = result.value;
      const completedCount = getCompletedCount(detail);
      if (completedCount > 0) {
        eligibleBases.push(base);
        detailsById[base.id] = detail;
      }
    });

    return { bases: eligibleBases, detailsById, preserveSelectionIds };
  };

/**
 * 기존 선택된 지식 베이스를 최신 상태로 정리합니다.
 * - 현재 목록에 없는 항목은 제거
 * - 상세 조회가 일시 실패한 기존 선택 항목은 이름을 유지한 채 보존
 * - 중복 제거
 * - 이름은 최신 목록 기준으로 갱신
 */
export const sanitizeSelectedKnowledgeBases = (
  selected: KnowledgeBaseSelection[],
  eligibleBases: KnowledgeBaseResponse[],
  options: SanitizeSelectedKnowledgeBasesOptions = {},
) => {
  const nameById = new Map(
    eligibleBases.map((kb) => [kb.id, kb.name]),
  );
  const preserveMissingIds = new Set(options.preserveMissingIds ?? []);
  const seen = new Set<string>();
  const next: KnowledgeBaseSelection[] = [];

  selected.forEach((kb) => {
    const name = nameById.get(kb.id);
    if (!name && !preserveMissingIds.has(kb.id)) return;
    if (seen.has(kb.id)) return;
    seen.add(kb.id);
    next.push({ id: kb.id, name: name ?? kb.name });
  });

  return next;
};

/**
 * 선택 목록이 변경되었는지 판단하기 위한 순서/값 비교 헬퍼입니다.
 * LLM 노드의 불필요한 상태 업데이트를 줄이기 위해 사용합니다.
 */
export const isSameKnowledgeSelection = (
  a: KnowledgeBaseSelection[],
  b: KnowledgeBaseSelection[],
) => {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i].id !== b[i].id || a[i].name !== b[i].name) return false;
  }
  return true;
};
