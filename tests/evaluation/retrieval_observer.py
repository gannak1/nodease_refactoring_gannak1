"""Process-local retrieval diagnostics collector for paired evaluation."""

from __future__ import annotations

from collections.abc import Mapping

from apps.shared.services.rag_retrieval_diagnostics import RetrievalDiagnosticEvent
from tests.evaluation.evidence_refs import OpaqueEvidenceRegistry
from tests.evaluation.paired_runner import Condition
from tests.evaluation.schemas import FrozenProtocol


class EvaluationRetrievalDiagnostics:
    """Translate internal candidate IDs without persisting the reverse mapping."""

    def __init__(
        self,
        *,
        evidence_mapping: Mapping[Condition, Mapping[str, str]],
        scan_cap: int,
        score_precision: int,
    ) -> None:
        if scan_cap < 1 or scan_cap > 10_000:
            raise ValueError("invalid_diagnostic_scan_cap")
        if not 0 <= score_precision <= 15:
            raise ValueError("invalid_diagnostic_score_precision")
        self._scan_cap = scan_cap
        self._score_precision = score_precision
        self._evidence_mapping = evidence_mapping
        self._fallback_registry = OpaqueEvidenceRegistry()
        self._condition: Condition | None = None
        self._events: list[RetrievalDiagnosticEvent] = []
        self._missing_final_mapping = False

    @classmethod
    def from_protocol(
        cls,
        *,
        evidence_mapping: Mapping[Condition, Mapping[str, str]],
        protocol: FrozenProtocol,
    ) -> "EvaluationRetrievalDiagnostics":
        return cls(
            evidence_mapping=evidence_mapping,
            scan_cap=protocol.tie_policy.complete_tie_group_cap,
            score_precision=protocol.tie_policy.score_precision,
        )

    @property
    def scan_cap(self) -> int:
        return self._scan_cap

    @property
    def score_precision(self) -> int:
        return self._score_precision

    def start_condition(self, condition: Condition) -> None:
        self._condition = condition
        self._events = []
        self._missing_final_mapping = False

    def reference_for(self, stage: str, internal_id: str) -> str:
        if self._condition is None:
            raise RuntimeError("diagnostic_condition_not_started")
        mapped = self._evidence_mapping[self._condition].get(internal_id)
        if mapped is not None:
            return mapped
        if stage == "final_selection":
            self._missing_final_mapping = True
        return self._fallback_registry.issue(
            f"{self._condition}:{stage}:{internal_id}"
        )

    def observe(self, event: RetrievalDiagnosticEvent) -> None:
        if self._condition is None:
            raise RuntimeError("diagnostic_condition_not_started")
        self._events.append(event)

    def consume_final_selection(
        self,
    ) -> tuple[RetrievalDiagnosticEvent | None, bool, bool]:
        final_events = [event for event in self._events if event.stage == "final_selection"]
        if len(final_events) > 1:
            raise ValueError("ambiguous_final_selection_diagnostics")
        final_event = final_events[0] if final_events else None
        any_truncated = any(event.tie_group_truncated for event in self._events)
        return final_event, self._missing_final_mapping, any_truncated
