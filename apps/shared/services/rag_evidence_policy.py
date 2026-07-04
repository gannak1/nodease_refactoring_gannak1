from dataclasses import dataclass, field
from typing import Any, Iterable

from apps.shared.schemas.rag import ChunkPreview, RAGCitation


MINIMUM_EVIDENCE_POLICY = "minimum_evidence"
STRICT_CITATION_POLICY = "strict_citation"
DEFAULT_MIN_EVIDENCE_SCORE = 0.15
STRICT_MIN_CITATION_COUNT = 2


@dataclass(frozen=True)
class RAGEvidenceDecision:
    evidence_sufficient: bool
    insufficiency_reason: str | None = None
    source_tier_used: dict[str, Any] = field(default_factory=dict)


class RAGEvidencePolicy:
    """Authorized evidence만 입력으로 받아 safe sufficiency summary를 만든다."""

    def __init__(
        self,
        *,
        min_score: float = DEFAULT_MIN_EVIDENCE_SCORE,
        strict_min_citations: int = STRICT_MIN_CITATION_COUNT,
    ) -> None:
        self.min_score = min_score
        self.strict_min_citations = strict_min_citations

    def evaluate(
        self,
        citations: Iterable[RAGCitation],
        *,
        policy: str = MINIMUM_EVIDENCE_POLICY,
    ) -> RAGEvidenceDecision:
        citation_list = list(citations)
        source_tier_used = self._source_tier_summary(citation_list)
        if not citation_list:
            return RAGEvidenceDecision(
                evidence_sufficient=False,
                insufficiency_reason="no_evidence",
                source_tier_used=source_tier_used,
            )

        scores = [citation.score for citation in citation_list if citation.score is not None]
        max_score = max(scores) if scores else None
        if max_score is not None and max_score < self.min_score:
            return RAGEvidenceDecision(
                evidence_sufficient=False,
                insufficiency_reason="low_score",
                source_tier_used=source_tier_used,
            )

        if policy == STRICT_CITATION_POLICY and len(citation_list) < self.strict_min_citations:
            return RAGEvidenceDecision(
                evidence_sufficient=False,
                insufficiency_reason="insufficient_citation",
                source_tier_used=source_tier_used,
            )

        return RAGEvidenceDecision(
            evidence_sufficient=True,
            source_tier_used=source_tier_used,
        )

    def evaluate_chunks(
        self,
        chunks: Iterable[ChunkPreview],
        *,
        policy: str = MINIMUM_EVIDENCE_POLICY,
    ) -> RAGEvidenceDecision:
        chunk_list = list(chunks)
        source_tier_used = self._chunk_source_tier_summary(chunk_list)
        if not chunk_list:
            return RAGEvidenceDecision(
                evidence_sufficient=False,
                insufficiency_reason="no_evidence",
                source_tier_used=source_tier_used,
            )

        scores = [
            self._chunk_score(chunk)
            for chunk in chunk_list
            if self._chunk_score(chunk) is not None
        ]
        max_score = max(scores) if scores else None
        if max_score is not None and max_score < self.min_score:
            return RAGEvidenceDecision(
                evidence_sufficient=False,
                insufficiency_reason="low_score",
                source_tier_used=source_tier_used,
            )

        if policy == STRICT_CITATION_POLICY and len(chunk_list) < self.strict_min_citations:
            return RAGEvidenceDecision(
                evidence_sufficient=False,
                insufficiency_reason="insufficient_citation",
                source_tier_used=source_tier_used,
            )

        return RAGEvidenceDecision(
            evidence_sufficient=True,
            source_tier_used=source_tier_used,
        )

    @staticmethod
    def _source_tier_summary(citations: list[RAGCitation]) -> dict[str, Any]:
        tiers = sorted(
            {
                str(citation.metadata_summary.get("source_tier"))
                for citation in citations
                if citation.metadata_summary.get("source_tier")
            }
        )
        if not tiers:
            return {}
        return {
            "tiers": tiers,
            "tier_count": len(tiers),
        }

    @staticmethod
    def _chunk_score(chunk: ChunkPreview) -> float | None:
        if chunk.score is not None:
            return chunk.score
        return chunk.similarity_score

    @staticmethod
    def _chunk_source_tier_summary(chunks: list[ChunkPreview]) -> dict[str, Any]:
        tiers = sorted(
            {
                str(chunk.metadata_summary.get("source_tier"))
                for chunk in chunks
                if chunk.metadata_summary.get("source_tier")
            }
        )
        if not tiers:
            return {}
        return {
            "tiers": tiers,
            "tier_count": len(tiers),
        }
