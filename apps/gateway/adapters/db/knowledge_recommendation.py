from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, cast

from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session, sessionmaker

from apps.gateway.application.agent_builder.knowledge_recommendation import (
    CandidateSemanticScore,
    KnowledgeRecommendationRetrievalRequest,
    KnowledgeRecommendationRetrievalResult,
    RecommendationEmbeddingResolver,
    SafeReasonCode,
    SemanticState,
    normalize_cosine_similarity,
    semantic_state_for_embedding_failure,
)


MAX_COHORTS = 4
MAX_EMBEDDING_TIMEOUT_SECONDS = 4.0
MAX_PARENT_TIMEOUT_SECONDS = 2.0


class PostgresParentRecommendationAdapter:
    """Bounded score-only parent retrieval for authorized KB candidates."""

    def __init__(
        self,
        caller_db: Session,
        *,
        embedding_resolver: RecommendationEmbeddingResolver,
        retrieval_session_factory: Callable[[], Session] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if embedding_resolver is None:
            raise ValueError("embedding_resolver is required")
        session_factory = retrieval_session_factory or self._default_session_factory(
            caller_db
        )
        if session_factory is None:
            raise ValueError("a dedicated retrieval session factory is required")
        self._caller_db = caller_db
        self._embedding_resolver = embedding_resolver
        self._retrieval_session_factory = session_factory
        self._monotonic = monotonic

    def retrieve(
        self,
        request: KnowledgeRecommendationRetrievalRequest,
    ) -> KnowledgeRecommendationRetrievalResult:
        started_at = self._monotonic()
        candidate_ids = list(request.candidate_kb_ids)
        deadline = request.deadline
        if request.is_cancellation_requested() or deadline is None or (
            deadline.remaining_seconds(now_monotonic=started_at) <= 0
        ):
            return self._all_unavailable(
                candidate_ids,
                state="deadline_exceeded",
                started_at=started_at,
            )

        try:
            discovery_timeout_ms = self._seconds_to_timeout_ms(
                deadline.remaining_seconds(now_monotonic=self._monotonic())
            )
            artifact_rows = self._execute_discovery(
                request=request,
                candidate_ids=candidate_ids,
                timeout_ms=discovery_timeout_ms,
            )
        except Exception as exc:
            state: SemanticState = (
                "deadline_exceeded"
                if request.is_cancellation_requested()
                or self._deadline_expired(request)
                else (
                    "deadline_exceeded"
                    if self._is_timeout(exc)
                    else "retrieval_unavailable"
                )
            )
            return self._all_unavailable(
                candidate_ids,
                state=state,
                started_at=started_at,
            )

        artifact_by_kb: dict[Any, set[tuple[str, int]]] = {
            candidate_id: set() for candidate_id in candidate_ids
        }
        for row in artifact_rows:
            candidate_id = row.get("knowledge_base_id")
            if candidate_id not in artifact_by_kb:
                continue
            embedding_model = row.get("embedding_model")
            embedding_dimension = row.get("embedding_dimension")
            if (
                isinstance(embedding_model, str)
                and embedding_model
                and isinstance(embedding_dimension, int)
                and not isinstance(embedding_dimension, bool)
                and embedding_dimension > 0
            ):
                artifact_by_kb[candidate_id].add(
                    (embedding_model, embedding_dimension)
                )

        scores: list[CandidateSemanticScore] = []
        cohorts: dict[tuple[str, int], list[Any]] = {}
        for candidate_id in candidate_ids:
            artifacts = artifact_by_kb[candidate_id]
            if not artifacts:
                scores.append(
                    self._fallback_score(candidate_id, "hierarchy_unavailable")
                )
            elif len(artifacts) != 1:
                scores.append(
                    self._fallback_score(candidate_id, "artifact_inconsistent")
                )
            else:
                cohort = next(iter(artifacts))
                cohorts.setdefault(cohort, []).append(candidate_id)

        ordered_cohorts = sorted(
            cohorts.items(),
            key=lambda item: (-len(item[1]), item[0][0], item[0][1]),
        )
        cohort_count = len(ordered_cohorts)
        if request.is_cancellation_requested() or not deadline.accepts_result(
            completed_at_monotonic=self._monotonic()
        ):
            return self._all_unavailable(
                candidate_ids,
                state="deadline_exceeded",
                started_at=started_at,
                cohort_count=cohort_count,
            )

        failed_cohort_count = len(ordered_cohorts[MAX_COHORTS:])
        for _cohort, skipped_ids in ordered_cohorts[MAX_COHORTS:]:
            scores.extend(
                self._fallback_score(candidate_id, "cohort_budget_exceeded")
                for candidate_id in skipped_ids
            )

        safe_query = "\n".join(request.safe_query_topics)
        active_cohorts = ordered_cohorts[:MAX_COHORTS]
        for cohort_index, (
            (embedding_model, dimension),
            cohort_ids,
        ) in enumerate(active_cohorts):
            remaining_seconds = deadline.remaining_seconds(
                now_monotonic=self._monotonic()
            )
            if request.is_cancellation_requested() or remaining_seconds <= 0:
                remaining_cohorts = active_cohorts[cohort_index:]
                failed_cohort_count += self._append_unavailable_cohorts(
                    scores,
                    remaining_cohorts,
                    "deadline_exceeded",
                )
                break

            try:
                embedding = self._embedding_resolver.embed_query(
                    organization_id=request.organization_id,
                    actor_id=request.actor_id,
                    embedding_model=embedding_model,
                    safe_query=safe_query,
                    timeout_seconds=min(
                        MAX_EMBEDDING_TIMEOUT_SECONDS,
                        remaining_seconds,
                    ),
                    deadline=deadline,
                )
            except Exception:
                if request.is_cancellation_requested():
                    remaining_cohorts = active_cohorts[cohort_index:]
                    failed_cohort_count += self._append_unavailable_cohorts(
                        scores,
                        remaining_cohorts,
                        "deadline_exceeded",
                    )
                    break
                failed_cohort_count += 1
                state = (
                    "deadline_exceeded"
                    if self._deadline_expired(request)
                    else "provider_unavailable"
                )
                scores.extend(
                    self._fallback_score(candidate_id, state)
                    for candidate_id in cohort_ids
                )
                continue

            if request.is_cancellation_requested() or not deadline.accepts_result(
                completed_at_monotonic=self._monotonic()
            ):
                remaining_cohorts = active_cohorts[cohort_index:]
                failed_cohort_count += self._append_unavailable_cohorts(
                    scores,
                    remaining_cohorts,
                    "deadline_exceeded",
                )
                break
            if embedding.vector is None:
                failed_cohort_count += 1
                state = semantic_state_for_embedding_failure(
                    embedding.failure_reason
                )
                scores.extend(
                    self._fallback_score(candidate_id, state)
                    for candidate_id in cohort_ids
                )
                continue
            if len(embedding.vector) != dimension:
                failed_cohort_count += 1
                scores.extend(
                    self._fallback_score(candidate_id, "provider_unavailable")
                    for candidate_id in cohort_ids
                )
                continue

            remaining_seconds = deadline.remaining_seconds(
                now_monotonic=self._monotonic()
            )
            if request.is_cancellation_requested() or remaining_seconds <= 0:
                remaining_cohorts = active_cohorts[cohort_index:]
                failed_cohort_count += self._append_unavailable_cohorts(
                    scores,
                    remaining_cohorts,
                    "deadline_exceeded",
                )
                break
            parent_timeout_seconds = min(
                MAX_PARENT_TIMEOUT_SECONDS,
                remaining_seconds,
            )
            try:
                rows = self._execute_parent_search(
                    request=request,
                    candidate_ids=cohort_ids,
                    embedding_model=embedding_model,
                    embedding_dimension=dimension,
                    query_vector=embedding.vector,
                    timeout_ms=self._seconds_to_timeout_ms(
                        parent_timeout_seconds
                    ),
                )
            except Exception as exc:
                if request.is_cancellation_requested():
                    remaining_cohorts = active_cohorts[cohort_index:]
                    failed_cohort_count += self._append_unavailable_cohorts(
                        scores,
                        remaining_cohorts,
                        "deadline_exceeded",
                    )
                    break
                failed_cohort_count += 1
                state = (
                    "deadline_exceeded"
                    if self._deadline_expired(request)
                    else (
                        "parent_search_timeout"
                        if self._is_timeout(exc)
                        else "retrieval_unavailable"
                    )
                )
                scores.extend(
                    self._fallback_score(candidate_id, state)
                    for candidate_id in cohort_ids
                )
                continue

            if request.is_cancellation_requested() or not deadline.accepts_result(
                completed_at_monotonic=self._monotonic()
            ):
                remaining_cohorts = active_cohorts[cohort_index:]
                failed_cohort_count += self._append_unavailable_cohorts(
                    scores,
                    remaining_cohorts,
                    "deadline_exceeded",
                )
                break

            returned_ids: set[Any] = set()
            cohort_id_set = set(cohort_ids)
            for row in rows:
                candidate_id = row.get("knowledge_base_id")
                if candidate_id not in cohort_id_set or candidate_id in returned_ids:
                    continue
                try:
                    relevance = normalize_cosine_similarity(
                        float(row["parent_relevance"])
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                returned_ids.add(candidate_id)
                scores.append(
                    CandidateSemanticScore(
                        knowledge_base_id=candidate_id,
                        semantic_state="available",
                        parent_relevance=relevance,
                        safe_reason_code="content_match",
                    )
                )
            scores.extend(
                self._fallback_score(candidate_id, "hierarchy_unavailable")
                for candidate_id in cohort_ids
                if candidate_id not in returned_ids
            )

        positions = {
            candidate_id: position
            for position, candidate_id in enumerate(candidate_ids)
        }
        ordered_scores = tuple(
            sorted(
                scores,
                key=lambda item: positions[item.knowledge_base_id],
            )
        )
        degraded = any(
            score.semantic_state != "available" for score in ordered_scores
        )
        return KnowledgeRecommendationRetrievalResult(
            state="degraded" if degraded else "complete",
            scores=ordered_scores,
            failed_cohort_count_bucket=self._count_bucket(failed_cohort_count),
            latency_bucket=self._latency_bucket(started_at),
            candidate_count_bucket=self._count_bucket(len(candidate_ids)),
            result_count_bucket=self._count_bucket(len(ordered_scores)),
            cohort_count_bucket=self._count_bucket(cohort_count),
            metadata_fallback_count_bucket=self._count_bucket(
                sum(
                    score.semantic_state != "available"
                    for score in ordered_scores
                )
            ),
        )

    def _execute_discovery(
        self,
        *,
        request: KnowledgeRecommendationRetrievalRequest,
        candidate_ids: list[Any],
        timeout_ms: int,
    ) -> list[dict[str, Any]]:
        with self._retrieval_session() as retrieval_db:
            self._set_statement_timeout(retrieval_db, timeout_ms)
            return list(
                retrieval_db.execute(
                    self._discovery_statement(),
                    {
                        "organization_id": request.organization_id,
                        "candidate_kb_ids": candidate_ids,
                    },
                )
                .mappings()
                .all()
            )

    def _execute_parent_search(
        self,
        *,
        request: KnowledgeRecommendationRetrievalRequest,
        candidate_ids: list[Any],
        embedding_model: str,
        embedding_dimension: int,
        query_vector: tuple[float, ...],
        timeout_ms: int,
    ) -> list[dict[str, Any]]:
        with self._retrieval_session() as retrieval_db:
            self._set_statement_timeout(retrieval_db, timeout_ms)
            return list(
                retrieval_db.execute(
                    self._parent_statement(),
                    {
                        "organization_id": request.organization_id,
                        "candidate_kb_ids": candidate_ids,
                        "embedding_model": embedding_model,
                        "embedding_dimension": embedding_dimension,
                        "query_vector": list(query_vector),
                    },
                )
                .mappings()
                .all()
            )

    @staticmethod
    def _discovery_statement():
        statement = text(
            """
            SELECT
                kb.id AS knowledge_base_id,
                COALESCE(dv.embedding_model, kb.embedding_model) AS embedding_model,
                vector_dims(dc.embedding) AS embedding_dimension
            FROM knowledge_bases AS kb
            JOIN document_chunks AS dc
              ON dc.knowledge_base_id = kb.id
            JOIN documents AS d
              ON d.id = dc.document_id
             AND d.knowledge_base_id = kb.id
            LEFT JOIN document_versions AS dv
              ON dv.id = dc.document_version_id
             AND dv.knowledge_base_id = kb.id
             AND dv.organization_id = kb.organization_id
            WHERE kb.organization_id = :organization_id
              AND kb.id IN :candidate_kb_ids
              AND kb.lifecycle_state = 'active'
              AND kb.sync_state <> 'source_deleted'
              AND dc.chunk_level = 'parent'
              AND d.status = 'completed'
              AND (
                    (kb.active_document_version_id IS NULL
                     AND dc.document_version_id IS NULL)
                 OR (kb.active_document_version_id IS NOT NULL
                     AND dc.document_version_id = kb.active_document_version_id
                     AND dv.status = 'ready')
              )
            GROUP BY
                kb.id,
                COALESCE(dv.embedding_model, kb.embedding_model),
                vector_dims(dc.embedding)
            """
        )
        return statement.bindparams(bindparam("candidate_kb_ids", expanding=True))

    @staticmethod
    def _parent_statement():
        statement = text(
            """
            WITH eligible_parents AS (
                SELECT DISTINCT ON (dc.id)
                    dc.id AS parent_chunk_id,
                    dc.knowledge_base_id,
                    dc.embedding <=> CAST(:query_vector AS vector)
                        AS parent_distance
                FROM document_chunks AS dc
                JOIN knowledge_bases AS kb
                  ON kb.id = dc.knowledge_base_id
                JOIN documents AS d
                  ON d.id = dc.document_id
                 AND d.knowledge_base_id = kb.id
                LEFT JOIN document_versions AS dv
                  ON dv.id = dc.document_version_id
                 AND dv.knowledge_base_id = kb.id
                 AND dv.organization_id = kb.organization_id
                WHERE kb.organization_id = :organization_id
                  AND kb.id IN :candidate_kb_ids
                  AND kb.lifecycle_state = 'active'
                  AND kb.sync_state <> 'source_deleted'
                  AND dc.chunk_level = 'parent'
                  AND d.status = 'completed'
                  AND COALESCE(dv.embedding_model, kb.embedding_model) = :embedding_model
                  AND vector_dims(dc.embedding) = :embedding_dimension
                  AND (
                        (kb.active_document_version_id IS NULL
                         AND dc.document_version_id IS NULL)
                     OR (kb.active_document_version_id IS NOT NULL
                         AND dc.document_version_id = kb.active_document_version_id
                         AND dv.status = 'ready')
                  )
                ORDER BY dc.id, parent_distance
            ),
            ranked_parents AS (
                SELECT
                    knowledge_base_id,
                    GREATEST(
                        0.0,
                        LEAST(
                            1.0,
                            1.0 - parent_distance
                        )
                    ) AS parent_score,
                    ROW_NUMBER() OVER (
                        PARTITION BY knowledge_base_id
                        ORDER BY parent_distance, parent_chunk_id
                    ) AS parent_rank
                FROM eligible_parents
            ),
            top_parents AS (
                SELECT knowledge_base_id, parent_score
                FROM ranked_parents
                WHERE parent_rank <= 3
            )
            SELECT
                knowledge_base_id,
                0.7 * MAX(parent_score) + 0.3 * AVG(parent_score)
                    AS parent_relevance
            FROM top_parents
            GROUP BY knowledge_base_id
            """
        )
        return statement.bindparams(
            bindparam("candidate_kb_ids", expanding=True),
            bindparam("query_vector", type_=Vector()),
        )

    @contextmanager
    def _retrieval_session(self) -> Iterator[Session]:
        retrieval_db = self._retrieval_session_factory()
        if retrieval_db is self._caller_db:
            raise ValueError("retrieval session must be separate from caller session")
        try:
            yield retrieval_db
        except BaseException:
            self._safe_rollback(retrieval_db)
            raise
        finally:
            retrieval_db.close()

    @staticmethod
    def _default_session_factory(
        caller_db: Session,
    ) -> Callable[[], Session] | None:
        get_bind = getattr(caller_db, "get_bind", None)
        if not callable(get_bind):
            return None
        bind = get_bind()
        engine = getattr(bind, "engine", bind)
        return sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )

    @staticmethod
    def _set_statement_timeout(db: Session, timeout_ms: int) -> None:
        connection = db.connection()
        connection.exec_driver_sql(
            f"SET LOCAL statement_timeout = {max(1, int(timeout_ms))}"
        )

    @staticmethod
    def _safe_rollback(db: Session) -> None:
        try:
            db.rollback()
        except Exception:
            return

    def _deadline_expired(
        self,
        request: KnowledgeRecommendationRetrievalRequest,
    ) -> bool:
        deadline = request.deadline
        return deadline is None or deadline.remaining_seconds(
            now_monotonic=self._monotonic()
        ) <= 0

    @staticmethod
    def _seconds_to_timeout_ms(seconds: float) -> int:
        if not math.isfinite(seconds) or seconds <= 0:
            return 1
        return max(1, math.ceil(seconds * 1000 - 1e-9))

    @staticmethod
    def _is_timeout(exc: Exception) -> bool:
        return isinstance(exc, TimeoutError) or "timeout" in str(exc).casefold()

    @staticmethod
    def _fallback_score(
        candidate_id: Any,
        state: SemanticState,
    ) -> CandidateSemanticScore:
        return CandidateSemanticScore(
            knowledge_base_id=candidate_id,
            semantic_state=state,
            parent_relevance=None,
            safe_reason_code=cast(SafeReasonCode, state),
        )

    @classmethod
    def _append_unavailable_cohorts(
        cls,
        scores: list[CandidateSemanticScore],
        cohorts: list[tuple[tuple[str, int], list[Any]]],
        state: SemanticState,
    ) -> int:
        for _cohort, candidate_ids in cohorts:
            scores.extend(
                cls._fallback_score(candidate_id, state)
                for candidate_id in candidate_ids
            )
        return len(cohorts)

    def _all_unavailable(
        self,
        candidate_ids: list[Any],
        *,
        state: SemanticState,
        started_at: float,
        cohort_count: int = 0,
    ) -> KnowledgeRecommendationRetrievalResult:
        scores = tuple(
            self._fallback_score(candidate_id, state)
            for candidate_id in candidate_ids
        )
        return KnowledgeRecommendationRetrievalResult(
            state="degraded",
            scores=scores,
            failed_cohort_count_bucket="zero",
            latency_bucket=self._latency_bucket(started_at),
            candidate_count_bucket=self._count_bucket(len(candidate_ids)),
            result_count_bucket=self._count_bucket(len(scores)),
            cohort_count_bucket=self._count_bucket(cohort_count),
            metadata_fallback_count_bucket=self._count_bucket(len(scores)),
        )

    @staticmethod
    def _count_bucket(count: int):
        if count <= 0:
            return "zero"
        if count == 1:
            return "one"
        if count <= 4:
            return "few"
        return "many"

    def _latency_bucket(self, started_at: float) -> str:
        elapsed = max(0.0, self._monotonic() - started_at)
        if elapsed < 1:
            return "under_1s"
        if elapsed < 3:
            return "1_to_3s"
        if elapsed < 8:
            return "3_to_8s"
        return "over_8s"
