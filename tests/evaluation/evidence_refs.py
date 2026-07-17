"""Opaque benchmark evidence reference issuance."""

from __future__ import annotations

import re
import secrets
from collections.abc import Mapping

from tests.evaluation.schemas import OPAQUE_EVIDENCE_PATTERN


class OpaqueEvidenceRegistry:
    """Process-local one-to-one mapping kept out of sanitized artifacts."""

    def __init__(self, initial: Mapping[str, str] | None = None) -> None:
        self._by_internal: dict[str, str] = {}
        self._internal_by_ref: dict[str, str] = {}
        for internal_key, evidence_ref in (initial or {}).items():
            self.bind(internal_key, evidence_ref)

    def bind(self, internal_key: str, evidence_ref: str) -> None:
        if not internal_key:
            raise ValueError("empty_internal_evidence_key")
        if not re.fullmatch(OPAQUE_EVIDENCE_PATTERN, evidence_ref):
            raise ValueError("invalid_evidence_ref")
        existing_ref = self._by_internal.get(internal_key)
        if existing_ref is not None and existing_ref != evidence_ref:
            raise ValueError("immutable_evidence_mapping")
        existing_key = self._internal_by_ref.get(evidence_ref)
        if existing_key is not None and existing_key != internal_key:
            raise ValueError("duplicate_evidence_ref")
        self._by_internal[internal_key] = evidence_ref
        self._internal_by_ref[evidence_ref] = internal_key

    def issue(self, internal_key: str) -> str:
        existing = self._by_internal.get(internal_key)
        if existing is not None:
            return existing
        for _attempt in range(128):
            evidence_ref = "ev:" + secrets.token_hex(16)
            if evidence_ref not in self._internal_by_ref:
                self.bind(internal_key, evidence_ref)
                return evidence_ref
        raise RuntimeError("evidence_ref_generation_exhausted")

    def reference_for(self, internal_key: str) -> str:
        try:
            return self._by_internal[internal_key]
        except KeyError as exc:
            raise KeyError("unknown_internal_evidence_key") from exc

    def __len__(self) -> int:
        return len(self._by_internal)
