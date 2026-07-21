import uuid
from inspect import getsource

import pytest
from pgvector.sqlalchemy import Vector

from apps.gateway.adapters.db.knowledge_recommendation import (
    PostgresParentRecommendationAdapter,
)
from apps.gateway.application.agent_builder.knowledge_recommendation import (
    EmbeddingResolution,
    RecommendationDeadline,
    KnowledgeRecommendationRetrievalRequest,
)


class FakeRows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class FakeDB:
    def __init__(self, responses):
        self.responses = list(responses)
        self.executions = []
        self.rollback_calls = 0
        self.close_calls = 0
        self.open_sessions = 0
        self.session_count = 0
        self.statement_timeouts = []

    def __call__(self):
        self.session_count += 1
        self.open_sessions += 1
        return FakeRetrievalSession(self)


class FakeRetrievalSession:
    def __init__(self, owner):
        self.owner = owner
        self.closed = False

    def execute(self, statement, params):
        self.owner.executions.append((str(statement), params))
        response = self.owner.responses.pop(0)
        if callable(response):
            response = response()
        if isinstance(response, Exception):
            raise response
        return FakeRows(response)

    def rollback(self):
        self.owner.rollback_calls += 1

    def connection(self):
        return self

    def exec_driver_sql(self, statement):
        self.owner.statement_timeouts.append(int(statement.rsplit(" ", 1)[1]))

    def close(self):
        if not self.closed:
            self.closed = True
            self.owner.close_calls += 1
            self.owner.open_sessions -= 1


class FakeEmbeddingResolver:
    def __init__(self, outcomes=None, *, before_call=None, after_call=None):
        self.outcomes = dict(outcomes or {})
        self.calls = []
        self.before_call = before_call
        self.after_call = after_call

    def embed_query(
        self,
        *,
        organization_id,
        actor_id,
        embedding_model,
        safe_query,
        timeout_seconds,
        deadline,
    ):
        if self.before_call is not None:
            self.before_call()
        self.calls.append(
            {
                "organization_id": organization_id,
                "actor_id": actor_id,
                "embedding_model": embedding_model,
                "safe_query": safe_query,
                "timeout_seconds": timeout_seconds,
                "deadline": deadline,
            }
        )
        outcome = self.outcomes.get(
            embedding_model,
            EmbeddingResolution(vector=(0.1, 0.2, 0.3)),
        )
        if callable(outcome):
            outcome = outcome()
        if self.after_call is not None:
            self.after_call()
        return outcome


class FakeClock:
    def __init__(self, now):
        self.now = float(now)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class ScriptedCancellation:
    def __init__(self, *states):
        self.states = list(states)
        self.checks = 0

    def __call__(self):
        index = min(self.checks, len(self.states) - 1)
        self.checks += 1
        return self.states[index]


def _request(*candidate_ids, deadline=None, cancellation_predicate=None):
    kwargs = {}
    if deadline is not None:
        kwargs["deadline"] = deadline
    if cancellation_predicate is not None:
        kwargs["cancellation_predicate"] = cancellation_predicate
    return KnowledgeRecommendationRetrievalRequest(
        organization_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        safe_query_topics=("approved topic",),
        candidate_kb_ids=tuple(candidate_ids),
        candidate_snapshot_ref="snapshot-1",
        **kwargs,
    )


def _adapter(db, embedding, *, clock=None):
    kwargs = {}
    if clock is not None:
        kwargs["monotonic"] = clock
    return PostgresParentRecommendationAdapter(
        object(),
        embedding_resolver=embedding,
        retrieval_session_factory=db,
        **kwargs,
    )


def test_one_discovery_and_one_parent_query_score_a_whole_cohort():
    first = uuid.uuid4()
    second = uuid.uuid4()
    db = FakeDB(
        [
            [
                {
                    "knowledge_base_id": first,
                    "embedding_model": "text-embedding-3-small",
                    "embedding_dimension": 3,
                },
                {
                    "knowledge_base_id": second,
                    "embedding_model": "text-embedding-3-small",
                    "embedding_dimension": 3,
                },
            ],
            [
                {"knowledge_base_id": first, "parent_relevance": 0.91},
                {"knowledge_base_id": second, "parent_relevance": 0.64},
            ],
        ]
    )
    def assert_discovery_transaction_closed():
        assert db.open_sessions == 0

    embedding = FakeEmbeddingResolver(
        before_call=assert_discovery_transaction_closed,
    )

    result = _adapter(db, embedding).retrieve(_request(first, second))

    assert len(db.executions) == 2
    assert db.session_count == 2
    assert db.close_calls == 2
    assert db.open_sessions == 0
    assert len(embedding.calls) == 1
    assert db.executions[0][1]["candidate_kb_ids"] == [first, second]
    assert db.executions[1][1]["candidate_kb_ids"] == [first, second]
    assert {item.knowledge_base_id for item in result.scores} == {first, second}
    assert {item.parent_relevance for item in result.scores} == {0.91, 0.64}
    assert all(item.semantic_state == "available" for item in result.scores)
    assert result.candidate_count_bucket == "few"
    assert result.result_count_bucket == "few"
    assert result.cohort_count_bucket == "one"
    assert result.metadata_fallback_count_bucket == "zero"

    parent_sql = db.executions[1][0].lower()
    assert "chunk_level = 'parent'" in parent_sql
    assert "<=>" in parent_sql
    assert "row_number() over" in parent_sql
    assert "to_tsvector" not in parent_sql
    assert "ts_rank" not in parent_sql
    assert "<->" not in parent_sql
    assert isinstance(
        PostgresParentRecommendationAdapter._parent_statement()._bindparams[  # noqa: SLF001
            "query_vector"
        ].type,
        Vector,
    )


def test_parent_statement_deduplicates_chunk_id_before_top_three_ranking():
    parent_sql = str(
        PostgresParentRecommendationAdapter._parent_statement()  # noqa: SLF001
    ).lower()

    dedup_position = parent_sql.index("distinct on (dc.id)")
    ranking_position = parent_sql.index("row_number() over")
    assert "dc.id as parent_chunk_id" in parent_sql
    assert "from eligible_parents" in parent_sql
    assert dedup_position < ranking_position


def test_missing_or_inconsistent_parent_artifacts_never_call_provider():
    missing = uuid.uuid4()
    inconsistent = uuid.uuid4()
    db = FakeDB(
        [
            [
                {
                    "knowledge_base_id": inconsistent,
                    "embedding_model": "model-a",
                    "embedding_dimension": 3,
                },
                {
                    "knowledge_base_id": inconsistent,
                    "embedding_model": "model-a",
                    "embedding_dimension": 4,
                },
            ]
        ]
    )
    embedding = FakeEmbeddingResolver()

    result = _adapter(db, embedding).retrieve(_request(missing, inconsistent))

    by_id = {item.knowledge_base_id: item for item in result.scores}
    assert by_id[missing].semantic_state == "hierarchy_unavailable"
    assert by_id[inconsistent].semantic_state == "artifact_inconsistent"
    assert embedding.calls == []
    assert len(db.executions) == 1
    assert result.state == "degraded"


def test_model_and_dimension_pairs_form_separate_cohorts():
    first = uuid.uuid4()
    second = uuid.uuid4()
    db = FakeDB(
        [
            [
                {
                    "knowledge_base_id": first,
                    "embedding_model": "model-a",
                    "embedding_dimension": 3,
                },
                {
                    "knowledge_base_id": second,
                    "embedding_model": "model-b",
                    "embedding_dimension": 3,
                },
            ],
            [{"knowledge_base_id": first, "parent_relevance": 0.8}],
            [{"knowledge_base_id": second, "parent_relevance": 0.7}],
        ]
    )
    embedding = FakeEmbeddingResolver()

    result = _adapter(db, embedding).retrieve(_request(first, second))

    assert len(db.executions) == 3
    assert [call["embedding_model"] for call in embedding.calls] == [
        "model-a",
        "model-b",
    ]
    assert result.state == "complete"


def test_provider_failure_degrades_only_its_cohort():
    failed = uuid.uuid4()
    succeeded = uuid.uuid4()
    db = FakeDB(
        [
            [
                {
                    "knowledge_base_id": failed,
                    "embedding_model": "model-a",
                    "embedding_dimension": 3,
                },
                {
                    "knowledge_base_id": succeeded,
                    "embedding_model": "model-b",
                    "embedding_dimension": 3,
                },
            ],
            [{"knowledge_base_id": succeeded, "parent_relevance": 0.72}],
        ]
    )
    embedding = FakeEmbeddingResolver(
        {
            "model-a": EmbeddingResolution(
                vector=None,
                failure_reason="credential_unavailable",
            )
        }
    )

    result = _adapter(db, embedding).retrieve(_request(failed, succeeded))

    by_id = {item.knowledge_base_id: item for item in result.scores}
    assert by_id[failed].semantic_state == "credential_unavailable"
    assert by_id[succeeded].semantic_state == "available"
    assert result.state == "degraded"
    assert len(db.executions) == 2


def test_failed_cohort_bucket_counts_cohorts_not_candidates():
    failed_candidates = [uuid.uuid4(), uuid.uuid4()]
    db = FakeDB(
        [
            [
                {
                    "knowledge_base_id": candidate_id,
                    "embedding_model": "model-a",
                    "embedding_dimension": 3,
                }
                for candidate_id in failed_candidates
            ]
        ]
    )
    embedding = FakeEmbeddingResolver(
        {
            "model-a": EmbeddingResolution(
                vector=None,
                failure_reason="provider_unavailable",
            )
        }
    )

    result = _adapter(db, embedding).retrieve(_request(*failed_candidates))

    assert result.state == "degraded"
    assert result.failed_cohort_count_bucket == "one"


def test_parent_statement_timeout_discards_the_whole_cohort():
    candidate = uuid.uuid4()
    db = FakeDB(
        [
            [
                {
                    "knowledge_base_id": candidate,
                    "embedding_model": "model-a",
                    "embedding_dimension": 3,
                }
            ],
            TimeoutError("statement timeout"),
        ]
    )

    result = _adapter(db, FakeEmbeddingResolver()).retrieve(_request(candidate))

    score = result.scores[0]
    assert score.knowledge_base_id == candidate
    assert score.semantic_state == "parent_search_timeout"
    assert score.parent_relevance is None
    assert result.state == "degraded"
    assert db.rollback_calls == 1


def test_processing_is_capped_at_four_stably_ordered_cohorts():
    candidate_ids = [uuid.uuid4() for _ in range(5)]
    discovery = [
        {
            "knowledge_base_id": candidate_id,
            "embedding_model": f"model-{index}",
            "embedding_dimension": 3,
        }
        for index, candidate_id in enumerate(candidate_ids)
    ]
    parent_rows = [
        [{"knowledge_base_id": candidate_id, "parent_relevance": 0.8}]
        for candidate_id in candidate_ids[:4]
    ]
    db = FakeDB([discovery, *parent_rows])
    embedding = FakeEmbeddingResolver()

    result = _adapter(db, embedding).retrieve(_request(*candidate_ids))

    assert len(embedding.calls) == 4
    assert len(db.executions) == 5
    by_id = {item.knowledge_base_id: item for item in result.scores}
    assert by_id[candidate_ids[4]].semantic_state == "cohort_budget_exceeded"
    assert result.candidate_count_bucket == "many"
    assert result.result_count_bucket == "many"
    assert result.cohort_count_bucket == "many"
    assert result.metadata_fallback_count_bucket == "one"


def test_five_thousand_candidates_do_not_create_candidate_level_queries():
    candidate_ids = [uuid.uuid4() for _ in range(5000)]
    discovery = [
        {
            "knowledge_base_id": candidate_id,
            "embedding_model": "model-a",
            "embedding_dimension": 3,
        }
        for candidate_id in candidate_ids
    ]
    parent_rows = [
        {"knowledge_base_id": candidate_id, "parent_relevance": 0.5}
        for candidate_id in candidate_ids
    ]
    db = FakeDB([discovery, parent_rows])
    embedding = FakeEmbeddingResolver()

    result = _adapter(db, embedding).retrieve(_request(*candidate_ids))

    assert len(db.executions) == 2
    assert len(embedding.calls) == 1
    assert len(result.scores) == 5000


def test_embedding_resolver_is_mandatory_and_adapter_has_no_lazy_p3_import():
    with pytest.raises(TypeError):
        PostgresParentRecommendationAdapter(object())

    source = getsource(PostgresParentRecommendationAdapter)
    assert "knowledge_recommendation_credentials" not in source


def test_absolute_deadline_bounds_embedding_and_parent_timeouts():
    candidate = uuid.uuid4()
    clock = FakeClock(100.0)
    deadline = RecommendationDeadline.from_timeout_ms(
        3_000,
        now_monotonic=clock(),
    )
    db = FakeDB(
        [
            [
                {
                    "knowledge_base_id": candidate,
                    "embedding_model": "model-a",
                    "embedding_dimension": 3,
                }
            ],
            [{"knowledge_base_id": candidate, "parent_relevance": 0.8}],
        ]
    )
    embedding = FakeEmbeddingResolver(after_call=lambda: clock.advance(2.0))

    result = _adapter(db, embedding, clock=clock).retrieve(
        _request(candidate, deadline=deadline)
    )

    assert result.scores[0].semantic_state == "available"
    assert embedding.calls[0]["timeout_seconds"] == pytest.approx(3.0)
    assert embedding.calls[0]["deadline"] is deadline
    assert db.statement_timeouts == [3000, 1000]


def test_embedding_result_observed_after_absolute_deadline_is_discarded():
    candidate = uuid.uuid4()
    clock = FakeClock(200.0)
    deadline = RecommendationDeadline.from_timeout_ms(
        1_000,
        now_monotonic=clock(),
    )
    db = FakeDB(
        [
            [
                {
                    "knowledge_base_id": candidate,
                    "embedding_model": "model-a",
                    "embedding_dimension": 3,
                }
            ]
        ]
    )
    embedding = FakeEmbeddingResolver(after_call=lambda: clock.advance(1.001))

    result = _adapter(db, embedding, clock=clock).retrieve(
        _request(candidate, deadline=deadline)
    )

    assert result.scores[0].semantic_state == "deadline_exceeded"
    assert result.scores[0].parent_relevance is None
    assert len(db.executions) == 1
    assert db.session_count == 1


def test_parent_rows_observed_after_absolute_deadline_are_discarded():
    candidate = uuid.uuid4()
    clock = FakeClock(300.0)
    deadline = RecommendationDeadline.from_timeout_ms(
        1_000,
        now_monotonic=clock(),
    )

    def late_parent_rows():
        clock.advance(1.001)
        return [{"knowledge_base_id": candidate, "parent_relevance": 0.99}]

    db = FakeDB(
        [
            [
                {
                    "knowledge_base_id": candidate,
                    "embedding_model": "model-a",
                    "embedding_dimension": 3,
                }
            ],
            late_parent_rows,
        ]
    )

    result = _adapter(db, FakeEmbeddingResolver(), clock=clock).retrieve(
        _request(candidate, deadline=deadline)
    )

    assert result.scores[0].semantic_state == "deadline_exceeded"
    assert result.scores[0].parent_relevance is None


def test_cancellation_before_discovery_skips_all_external_work():
    candidate = uuid.uuid4()
    db = FakeDB([])
    embedding = FakeEmbeddingResolver()

    result = _adapter(db, embedding).retrieve(
        _request(candidate, cancellation_predicate=lambda: True)
    )

    assert result.scores[0].semantic_state == "deadline_exceeded"
    assert result.scores[0].safe_reason_code == "deadline_exceeded"
    assert db.executions == []
    assert embedding.calls == []
    assert result.candidate_count_bucket == "one"
    assert result.result_count_bucket == "one"
    assert result.cohort_count_bucket == "zero"
    assert result.metadata_fallback_count_bucket == "one"


def test_cancellation_after_discovery_skips_provider():
    candidate = uuid.uuid4()
    cancelled = False

    def discovery_rows():
        nonlocal cancelled
        cancelled = True
        return [
            {
                "knowledge_base_id": candidate,
                "embedding_model": "model-a",
                "embedding_dimension": 3,
            }
        ]

    db = FakeDB([discovery_rows])
    embedding = FakeEmbeddingResolver()

    result = _adapter(db, embedding).retrieve(
        _request(candidate, cancellation_predicate=lambda: cancelled)
    )

    assert result.scores[0].semantic_state == "deadline_exceeded"
    assert len(db.executions) == 1
    assert embedding.calls == []
    assert result.cohort_count_bucket == "one"


def test_discovery_failure_populates_safe_aggregate_buckets():
    candidates = (uuid.uuid4(), uuid.uuid4())
    result = _adapter(
        FakeDB([RuntimeError("protected database detail")]),
        FakeEmbeddingResolver(),
    ).retrieve(_request(*candidates))

    assert result.candidate_count_bucket == "few"
    assert result.result_count_bucket == "few"
    assert result.cohort_count_bucket == "zero"
    assert result.metadata_fallback_count_bucket == "few"
    assert {score.semantic_state for score in result.scores} == {
        "retrieval_unavailable"
    }
    assert "protected database detail" not in repr(result)


def test_cancellation_is_checked_immediately_before_provider():
    candidate = uuid.uuid4()
    cancellation = ScriptedCancellation(False, False, True)
    db = FakeDB(
        [
            [
                {
                    "knowledge_base_id": candidate,
                    "embedding_model": "model-a",
                    "embedding_dimension": 3,
                }
            ]
        ]
    )
    embedding = FakeEmbeddingResolver()

    result = _adapter(db, embedding).retrieve(
        _request(candidate, cancellation_predicate=cancellation)
    )

    assert result.scores[0].semantic_state == "deadline_exceeded"
    assert len(db.executions) == 1
    assert embedding.calls == []


def test_cancellation_after_provider_discards_embedding_and_skips_parent_sql():
    candidate = uuid.uuid4()
    cancelled = False

    def cancel_after_provider():
        nonlocal cancelled
        cancelled = True

    db = FakeDB(
        [
            [
                {
                    "knowledge_base_id": candidate,
                    "embedding_model": "model-a",
                    "embedding_dimension": 3,
                }
            ]
        ]
    )
    embedding = FakeEmbeddingResolver(after_call=cancel_after_provider)

    result = _adapter(db, embedding).retrieve(
        _request(candidate, cancellation_predicate=lambda: cancelled)
    )

    assert result.scores[0].semantic_state == "deadline_exceeded"
    assert len(db.executions) == 1
    assert len(embedding.calls) == 1


def test_cancellation_is_checked_immediately_before_parent_sql():
    candidate = uuid.uuid4()
    cancellation = ScriptedCancellation(False, False, False, False, True)
    db = FakeDB(
        [
            [
                {
                    "knowledge_base_id": candidate,
                    "embedding_model": "model-a",
                    "embedding_dimension": 3,
                }
            ]
        ]
    )

    result = _adapter(db, FakeEmbeddingResolver()).retrieve(
        _request(candidate, cancellation_predicate=cancellation)
    )

    assert result.scores[0].semantic_state == "deadline_exceeded"
    assert len(db.executions) == 1


def test_cancellation_after_parent_sql_discards_raw_rows():
    candidate = uuid.uuid4()
    cancelled = False

    def parent_rows():
        nonlocal cancelled
        cancelled = True
        return [{"knowledge_base_id": candidate, "parent_relevance": 0.99}]

    db = FakeDB(
        [
            [
                {
                    "knowledge_base_id": candidate,
                    "embedding_model": "model-a",
                    "embedding_dimension": 3,
                }
            ],
            parent_rows,
        ]
    )

    result = _adapter(db, FakeEmbeddingResolver()).retrieve(
        _request(candidate, cancellation_predicate=lambda: cancelled)
    )

    assert result.scores[0].semantic_state == "deadline_exceeded"
    assert result.scores[0].parent_relevance is None
    assert len(db.executions) == 2


def test_cancellation_between_cohorts_preserves_only_completed_safe_score():
    first = uuid.uuid4()
    second = uuid.uuid4()
    cancellation = ScriptedCancellation(
        False,
        False,
        False,
        False,
        False,
        False,
        True,
    )
    db = FakeDB(
        [
            [
                {
                    "knowledge_base_id": first,
                    "embedding_model": "model-a",
                    "embedding_dimension": 3,
                },
                {
                    "knowledge_base_id": second,
                    "embedding_model": "model-b",
                    "embedding_dimension": 3,
                },
            ],
            [{"knowledge_base_id": first, "parent_relevance": 0.81}],
        ]
    )
    embedding = FakeEmbeddingResolver()

    result = _adapter(db, embedding).retrieve(
        _request(first, second, cancellation_predicate=cancellation)
    )

    by_id = {score.knowledge_base_id: score for score in result.scores}
    assert by_id[first].semantic_state == "available"
    assert by_id[second].semantic_state == "deadline_exceeded"
    assert [call["embedding_model"] for call in embedding.calls] == ["model-a"]
    assert len(db.executions) == 2
    assert result.metadata_fallback_count_bucket == "one"


def test_retrieval_sessions_never_touch_the_caller_transaction():
    candidate = uuid.uuid4()
    db = FakeDB(
        [
            [
                {
                    "knowledge_base_id": candidate,
                    "embedding_model": "model-a",
                    "embedding_dimension": 3,
                }
            ],
            [{"knowledge_base_id": candidate, "parent_relevance": 0.7}],
        ]
    )

    class CallerSession:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("caller execute must not be used")

        def commit(self):
            raise AssertionError("caller commit must not be used")

        def rollback(self):
            raise AssertionError("caller rollback must not be used")

        def close(self):
            raise AssertionError("caller close must not be used")

    result = PostgresParentRecommendationAdapter(
        CallerSession(),
        embedding_resolver=FakeEmbeddingResolver(),
        retrieval_session_factory=db,
    ).retrieve(_request(candidate))

    assert result.scores[0].semantic_state == "available"
    assert db.session_count == 2
    assert db.close_calls == 2
