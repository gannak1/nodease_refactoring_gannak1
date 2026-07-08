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
 * - 완료된 retrieval-visible 문서가 있는 지식 베이스만 보여주기
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

/**
 * LLM 노드에서 표시 가능한 지식 베이스만 가져옵니다.
 * - Gateway의 LLM 전용 후보 API가 active organization, KB use 권한,
 *   retrieval-visible completed chunk 기준을 적용합니다.
 * - client는 malformed payload 방어와 최신 이름/중복 정리만 수행합니다.
 */
export const fetchEligibleKnowledgeBases =
  async (): Promise<EligibleKnowledgeBasesResult> => {
    const details = await knowledgeApi.getLLMSelectableKnowledgeBases();
    const detailsById: Record<string, KnowledgeBaseDetailResponse> = {};
    const eligibleBases: KnowledgeBaseResponse[] = [];

    details.forEach((detail) => {
      const completedCount = getCompletedCount(detail);
      if (completedCount > 0) {
        eligibleBases.push(detail);
        detailsById[detail.id] = detail;
      }
    });

    return { bases: eligibleBases, detailsById };
  };

/**
 * 기존 선택된 지식 베이스를 최신 상태로 정리합니다.
 * - 현재 목록에 없는 항목은 제거
 * - 일시 장애 등으로 보존 요청된 기존 선택 항목은 이름을 유지한 채 보존
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
