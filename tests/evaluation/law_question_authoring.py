"""Draft public-law development questions from an immutable corpus snapshot.

The generated bundle is deliberately not a frozen benchmark dataset. It keeps
machine-assisted questions and evidence mappings local until a human reviewer
confirms semantics, answerability, and evidence sufficiency.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tests.evaluation.corpus_authoring import (
    PreparedCorpusSummary,
    QuestionBlueprint,
    QuestionBlueprintPackage,
)
from tests.evaluation.law_open_data import LawSourceCatalog
from tests.evaluation.protocol import canonical_hash
from tests.evaluation.schemas import BenchmarkQuestion, OPAQUE_EVIDENCE_PATTERN


PILOT_CATEGORY_TARGETS: Mapping[str, int] = {
    "single_fact": 20,
    "section_context": 20,
    "ambiguous_context": 15,
    "multi_evidence": 15,
    "distractor": 10,
    "boundary": 10,
    "unanswerable": 10,
}
QUESTION_ID_CATEGORY = {
    "single_fact": "fact",
    "section_context": "section",
    "ambiguous_context": "ambiguous",
    "multi_evidence": "multi",
    "distractor": "distractor",
    "boundary": "boundary",
    "unanswerable": "unanswerable",
}
DIFFICULTY_BY_CATEGORY = {
    "single_fact": "easy",
    "section_context": "medium",
    "ambiguous_context": "hard",
    "multi_evidence": "hard",
    "distractor": "hard",
    "boundary": "hard",
    "unanswerable": "medium",
}
CLUSTER_DISPLAY_LABELS = {
    "privacy": "개인정보 보호",
    "labor": "근로관계",
    "safety": "산업안전보건",
    "records": "공공기록물 관리",
    "procedure": "행정절차",
    "electronic-documents": "전자문서·전자거래",
}
UNANSWERABLE_PROMPTS: Mapping[str, tuple[str, ...]] = {
    "privacy": (
        "개인정보 보호 관련 법령이 모든 개인정보처리자에게 AES-256 알고리즘만 사용하도록 의무화하고 있나요?",
        "개인정보 유출 사고마다 피해자 한 명당 동일한 정액 배상금을 지급하도록 현행 법령이 정하고 있나요?",
    ),
    "labor": (
        "근로기준 관련 법령이 모든 사업장에 주 3일 원격근무를 일률적으로 의무화하고 있나요?",
        "근로기준 관련 법령이 직무와 경력에 관계없이 모든 근로자에게 동일한 연봉을 보장하나요?",
    ),
    "safety": (
        "산업안전보건 관련 법령이 모든 작업장에 특정 제조사의 보호구만 사용하도록 정하고 있나요?",
        "산업안전보건 관련 법령이 업종과 규모에 관계없이 동일한 안전관리 예산액을 의무화하나요?",
    ),
    "records": (
        "공공기록물 관련 법령이 모든 기록을 특정 상용 클라우드 서비스에만 저장하도록 의무화하나요?",
        "공공기록물 관련 법령이 모든 기록물에 동일한 100년 보존기간을 적용하도록 정하고 있나요?",
    ),
    "procedure": (
        "행정절차 관련 법령이 모든 청문을 특정 화상회의 제품으로만 진행하도록 정하고 있나요?",
        "행정절차 관련 법령이 모든 처분에 대하여 예외 없이 동일한 30일 처리기간을 정하고 있나요?",
    ),
    "electronic-documents": (
        "전자문서 관련 법령이 모든 전자문서를 PDF 형식으로만 작성하도록 의무화하고 있나요?",
        "전자문서 관련 법령이 모든 전자거래에 특정 민간 인증서 한 종류만 사용하도록 정하고 있나요?",
    ),
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class LawQuestionDraftSummary(_StrictModel):
    schema_version: Literal["law_question_draft_v1"]
    review_state: Literal["pending_human_review"]
    bundle_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    base_snapshot_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    base_snapshot_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_manifest_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    canonical_children_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    question_draft_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    question_count: Literal[100]
    answerable_count: int = Field(ge=1)
    unanswerable_count: int = Field(ge=1)
    sampling_cluster_count: int = Field(ge=1)
    maximum_questions_per_cluster: int = Field(ge=1)
    category_counts: dict[str, int]
    evidence_mapping_verified: Literal[True]
    category_floor_verified: Literal[True]
    structural_pilot_ready: Literal[True]
    quality_pilot_ready: Literal[False]
    blockers: tuple[
        Literal[
            "human_semantic_review_pending",
            "paired_index_binding_pending",
            "development_protocol_pending",
        ],
        ...,
    ]

    @model_validator(mode="after")
    def validate_totals(self) -> "LawQuestionDraftSummary":
        if self.answerable_count + self.unanswerable_count != self.question_count:
            raise ValueError("question_draft_answerability_count_mismatch")
        if self.category_counts != dict(PILOT_CATEGORY_TARGETS):
            raise ValueError("question_draft_category_plan_mismatch")
        return self


@dataclass(frozen=True)
class _SectionCandidate:
    source_ref: str
    source_key: str
    sampling_cluster_ref: str
    title: str
    version_role: str
    analysis_role: str
    section_key: str
    evidence_ref: str
    ordinal: int
    hierarchy_path: tuple[str, ...]
    content: str

    @property
    def section_ref(self) -> str:
        return f"{self.source_ref}:{self.section_key}"

    @property
    def article_key(self) -> str:
        match = re.match(r"^(article-[0-9]+)", self.section_key)
        return match.group(1) if match else self.section_key


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _jsonl_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for row in rows
    ).encode("utf-8")


def _content_hash(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _entry_for_source(
    source_ref: str,
    version_role: str,
    catalog: LawSourceCatalog,
):
    matches = [
        entry
        for entry in catalog.entries
        if source_ref == f"src_{entry.source_key}_{version_role}"
    ]
    if len(matches) != 1:
        raise ValueError("law_question_source_catalog_mapping_ambiguous")
    return matches[0]


def _load_candidates(
    snapshot: Path,
    catalog: LawSourceCatalog,
) -> tuple[PreparedCorpusSummary, list[_SectionCandidate]]:
    summary = PreparedCorpusSummary.model_validate(_read_json(snapshot / "summary.json"))
    source_manifest = _read_json(snapshot / "source_manifest.json")
    canonical_rows = _read_jsonl(snapshot / "canonical_children.jsonl")
    index_rows = _read_jsonl(snapshot / "index_input.jsonl")
    provenance = _read_json(snapshot / "provenance.json")

    if summary.corpus_id != catalog.catalog_id:
        raise ValueError("law_question_catalog_id_mismatch")
    if canonical_hash(source_manifest) != summary.source_manifest_hash:
        raise ValueError("law_question_source_manifest_hash_mismatch")
    if canonical_hash(canonical_rows) != summary.canonical_children_hash:
        raise ValueError("law_question_canonical_children_hash_mismatch")
    if len(canonical_rows) != summary.canonical_child_count:
        raise ValueError("law_question_canonical_child_count_mismatch")
    if len(index_rows) != len(canonical_rows):
        raise ValueError("law_question_index_child_count_mismatch")

    canonical_by_ref = {row["evidence_ref"]: row for row in canonical_rows}
    if len(canonical_by_ref) != len(canonical_rows):
        raise ValueError("law_question_duplicate_evidence_ref")
    if any(
        not isinstance(row, dict)
        or set(row)
        != {
            "content",
            "evidence_ref",
            "hierarchy_path",
            "safe_source_ref",
            "section_key",
        }
        for row in index_rows
    ):
        raise ValueError("law_question_index_row_shape_invalid")
    index_evidence_refs = [row["evidence_ref"] for row in index_rows]
    if len(set(index_evidence_refs)) != len(index_evidence_refs):
        raise ValueError("law_question_duplicate_index_evidence_ref")
    if set(index_evidence_refs) != set(canonical_by_ref):
        raise ValueError("law_question_index_evidence_set_mismatch")
    provenance_by_ref = {
        row["source_ref"]: row for row in provenance.get("records", ())
    }
    if len(provenance_by_ref) != len(provenance.get("records", ())):
        raise ValueError("law_question_duplicate_provenance_source")

    candidates: list[_SectionCandidate] = []
    seen_sections: set[str] = set()
    for row in index_rows:
        evidence_ref = row["evidence_ref"]
        canonical = canonical_by_ref.get(evidence_ref)
        if canonical is None:
            raise ValueError("law_question_index_evidence_missing")
        source_ref = row["safe_source_ref"]
        if canonical["safe_source_ref"] != source_ref:
            raise ValueError("law_question_index_source_mismatch")
        provenance_row = provenance_by_ref.get(source_ref)
        if provenance_row is None:
            raise ValueError("law_question_provenance_missing")
        entry = _entry_for_source(
            source_ref,
            provenance_row["version_role"],
            catalog,
        )
        if provenance_row["title"] != entry.exact_title:
            raise ValueError("law_question_catalog_title_mismatch")
        section_ref = f"{source_ref}:{row['section_key']}"
        if section_ref in seen_sections:
            raise ValueError("law_question_duplicate_section_ref")
        seen_sections.add(section_ref)
        if not re.fullmatch(OPAQUE_EVIDENCE_PATTERN, evidence_ref):
            raise ValueError("law_question_invalid_evidence_ref")
        raw_content = row["content"]
        if not isinstance(raw_content, str):
            raise ValueError("law_question_index_content_invalid")
        if _content_hash(raw_content) != canonical["content_hash"]:
            raise ValueError("law_question_index_content_hash_mismatch")
        content = raw_content.strip()
        hierarchy = tuple(row["hierarchy_path"])
        if not content or not hierarchy:
            raise ValueError("law_question_empty_index_content")
        candidates.append(
            _SectionCandidate(
                source_ref=source_ref,
                source_key=entry.source_key,
                sampling_cluster_ref=entry.sampling_cluster_ref,
                title=entry.exact_title,
                version_role=provenance_row["version_role"],
                analysis_role=entry.analysis_role,
                section_key=row["section_key"],
                evidence_ref=evidence_ref,
                ordinal=int(canonical["ordinal"]),
                hierarchy_path=hierarchy,
                content=content,
            )
        )
    return summary, candidates


def _allocate_targets(clusters: Sequence[str]) -> dict[str, dict[str, int]]:
    if not clusters:
        raise ValueError("law_question_empty_cluster_set")
    allocations = {cluster: {} for cluster in clusters}
    offset = 0
    for category, total in PILOT_CATEGORY_TARGETS.items():
        base, remainder = divmod(total, len(clusters))
        selected = {
            clusters[(offset + index) % len(clusters)] for index in range(remainder)
        }
        for cluster in clusters:
            allocations[cluster][category] = base + int(cluster in selected)
        offset = (offset + remainder) % len(clusters)
    return allocations


def _interleaved(candidates: Sequence[_SectionCandidate]) -> list[_SectionCandidate]:
    by_source: dict[str, list[_SectionCandidate]] = defaultdict(list)
    for candidate in sorted(candidates, key=lambda item: (item.source_ref, item.ordinal)):
        by_source[candidate.source_ref].append(candidate)
    result: list[_SectionCandidate] = []
    sources = sorted(by_source)
    for index in range(max(len(rows) for rows in by_source.values())):
        for source in sources:
            rows = by_source[source]
            if index < len(rows):
                result.append(rows[index])
    return result


def _spread_select(
    candidates: Sequence[_SectionCandidate],
    count: int,
    *,
    used: set[str],
) -> list[_SectionCandidate]:
    available = [item for item in _interleaved(candidates) if item.section_ref not in used]
    if len(available) < count:
        raise ValueError("law_question_insufficient_section_candidates")
    selected = [
        available[min(len(available) - 1, int((index + 0.5) * len(available) / count))]
        for index in range(count)
    ]
    if len({item.section_ref for item in selected}) != count:
        raise ValueError("law_question_spread_selection_collision")
    used.update(item.section_ref for item in selected)
    return selected


def _context_label(candidate: _SectionCandidate) -> str:
    path = [re.sub(r"\s*<[^>]+>\s*$", "", value).strip() for value in candidate.hierarchy_path]
    article_indexes = [
        index
        for index, value in enumerate(path)
        if re.match(r"^제[0-9]+조(?:의[0-9]+)?(?:\s|$)", value)
    ]
    if article_indexes:
        return " > ".join(path[article_indexes[-1] :])
    return " > ".join(path[-2:] if len(path) > 1 else path)


def _topic_label(candidate: _SectionCandidate) -> str:
    for value in reversed(candidate.hierarchy_path):
        normalized = re.sub(r"^제[0-9]+조(?:의[0-9]+)?\s*", "", value)
        normalized = re.sub(r"\s*<[^>]+>\s*$", "", normalized).strip()
        if re.search(r"[가-힣]", normalized) and not re.fullmatch(
            r"[①-⑳]|[가-하]\.|[0-9]+(?:의[0-9]+)?\.", normalized
        ):
            return normalized
    return _context_label(candidate)


def _blueprint(
    *,
    question_id: str,
    cluster: str,
    category: str,
    query: str,
    required: Sequence[_SectionCandidate],
) -> QuestionBlueprint:
    answerable = category != "unanswerable"
    return QuestionBlueprint(
        question_id=question_id,
        sampling_cluster_ref=cluster,
        split="development",
        category=category,
        difficulty=DIFFICULTY_BY_CATEGORY[category],
        answerable=answerable,
        query=query,
        safe_display_label=f"{cluster} {category} development question",
        required_section_refs=tuple(item.section_ref for item in required),
    )


def _question_id(cluster: str, category: str, index: int) -> str:
    safe_cluster = re.sub(r"[^A-Za-z0-9]+", "-", cluster).strip("-")[:24]
    return f"kr-{safe_cluster}-{QUESTION_ID_CATEGORY[category]}-{index:03d}"


def _regular_questions(
    cluster: str,
    category: str,
    count: int,
    candidates: Sequence[_SectionCandidate],
    used: set[str],
) -> list[QuestionBlueprint]:
    selection_pool = list(candidates)
    if category == "ambiguous_context":
        unique_topics: dict[str, _SectionCandidate] = {}
        for candidate in _interleaved(selection_pool):
            if candidate.section_ref in used:
                continue
            unique_topics.setdefault(_topic_label(candidate), candidate)
        selection_pool = list(unique_topics.values())
    selected = _spread_select(selection_pool, count, used=used)
    questions: list[QuestionBlueprint] = []
    for index, candidate in enumerate(selected, start=1):
        context = _context_label(candidate)
        if category == "single_fact":
            query = f"현행 {candidate.title}의 [{context}] 규정 내용은 무엇인가요?"
        elif category == "section_context":
            query = (
                f"{candidate.title}의 [{context}] 규정을 적용할 때 확인해야 할 요건이나 의무를 설명해 주세요."
            )
        elif category == "ambiguous_context":
            cluster_label = CLUSTER_DISPLAY_LABELS.get(cluster, cluster)
            query = (
                f"{cluster_label} 맥락에서 '{_topic_label(candidate)}'에 해당하는 상황에는 "
                "어떤 현행 법적 기준이 적용되나요? "
                "근거가 되는 규정을 함께 제시해 주세요."
            )
        else:
            raise ValueError("law_question_unsupported_regular_category")
        questions.append(
            _blueprint(
                question_id=_question_id(cluster, category, index),
                cluster=cluster,
                category=category,
                query=query,
                required=(candidate,),
            )
        )
    return questions


def _multi_evidence_questions(
    cluster: str,
    count: int,
    candidates: Sequence[_SectionCandidate],
    used: set[str],
) -> list[QuestionBlueprint]:
    by_source: dict[str, list[_SectionCandidate]] = defaultdict(list)
    for candidate in candidates:
        if candidate.section_ref not in used:
            by_source[candidate.source_ref].append(candidate)
    sources = sorted(by_source)
    if len(sources) < 2:
        raise ValueError("law_question_multi_evidence_requires_two_sources")
    pair_candidates: list[
        tuple[float, str, str, _SectionCandidate, _SectionCandidate]
    ] = []
    for source_index, source_a in enumerate(sources):
        rows_a = sorted(by_source[source_a], key=lambda item: item.ordinal)
        sample_a = [
            rows_a[min(len(rows_a) - 1, int((i + 0.5) * len(rows_a) / min(80, len(rows_a))))]
            for i in range(min(80, len(rows_a)))
        ]
        for source_b in sources[source_index + 1 :]:
            rows_b = sorted(by_source[source_b], key=lambda item: item.ordinal)
            sample_b = [
                rows_b[
                    min(
                        len(rows_b) - 1,
                        int((i + 0.5) * len(rows_b) / min(80, len(rows_b))),
                    )
                ]
                for i in range(min(80, len(rows_b)))
            ]
            for first in sample_a:
                topic_a = _topic_label(first)
                if topic_a in {"목적", "정의", "적용 범위", "적용범위"}:
                    continue
                for second in sample_b:
                    topic_b = _topic_label(second)
                    if topic_b in {"목적", "정의", "적용 범위", "적용범위"}:
                        continue
                    score = SequenceMatcher(None, topic_a, topic_b).ratio()
                    pair_candidates.append(
                        (
                            score,
                            first.section_ref,
                            second.section_ref,
                            first,
                            second,
                        )
                    )
    pair_candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    selected_pairs: list[tuple[_SectionCandidate, _SectionCandidate]] = []
    for _score, _first_ref, _second_ref, first, second in pair_candidates:
        if first.section_ref in used or second.section_ref in used:
            continue
        used.update((first.section_ref, second.section_ref))
        selected_pairs.append((first, second))
        if len(selected_pairs) == count:
            break
    if len(selected_pairs) != count:
        raise ValueError("law_question_insufficient_multi_evidence_candidates")

    questions: list[QuestionBlueprint] = []
    for index, (first, second) in enumerate(selected_pairs, start=1):
        query = (
            f"현행 {first.title}의 [{_context_label(first)}] 규정과 {second.title}의 "
            f"[{_context_label(second)}] 규정이 각각 무엇을 정하는지 비교해 설명해 주세요."
        )
        questions.append(
            _blueprint(
                question_id=_question_id(cluster, "multi_evidence", index),
                cluster=cluster,
                category="multi_evidence",
                query=query,
                required=(first, second),
            )
        )
    return questions


def _boundary_questions(
    cluster: str,
    count: int,
    candidates: Sequence[_SectionCandidate],
    used: set[str],
) -> list[QuestionBlueprint]:
    pairs: list[tuple[_SectionCandidate, _SectionCandidate]] = []
    by_source: dict[str, list[_SectionCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_source[candidate.source_ref].append(candidate)
    for rows in by_source.values():
        ordered = sorted(rows, key=lambda item: item.ordinal)
        for first, second in zip(ordered, ordered[1:]):
            if (
                first.article_key == second.article_key
                and first.section_ref not in used
                and second.section_ref not in used
            ):
                pairs.append((first, second))
    if len(pairs) < count:
        raise ValueError("law_question_insufficient_boundary_pairs")
    selected_pairs: list[tuple[_SectionCandidate, _SectionCandidate]] = []
    for index in range(count):
        start = min(len(pairs) - 1, int((index + 0.5) * len(pairs) / count))
        ordered = pairs[start:] + pairs[:start]
        selected = next(
            (
                pair
                for pair in ordered
                if pair[0].section_ref not in used
                and pair[1].section_ref not in used
                and all(
                    pair[0].section_ref not in {
                        existing[0].section_ref,
                        existing[1].section_ref,
                    }
                    and pair[1].section_ref not in {
                        existing[0].section_ref,
                        existing[1].section_ref,
                    }
                    for existing in selected_pairs
                )
            ),
            None,
        )
        if selected is None:
            raise ValueError("law_question_insufficient_nonoverlapping_boundary_pairs")
        selected_pairs.append(selected)
    questions: list[QuestionBlueprint] = []
    for index, (first, second) in enumerate(selected_pairs, start=1):
        if first.section_ref in used or second.section_ref in used:
            raise ValueError("law_question_boundary_pair_reused")
        used.update((first.section_ref, second.section_ref))
        query = (
            f"현행 {first.title}의 [{_context_label(first)}] 규정과 바로 이어지는 "
            f"[{_context_label(second)}] 규정이 각각 정한 내용을 함께 설명해 주세요."
        )
        questions.append(
            _blueprint(
                question_id=_question_id(cluster, "boundary", index),
                cluster=cluster,
                category="boundary",
                query=query,
                required=(first, second),
            )
        )
    return questions


def _distractor_questions(
    cluster: str,
    count: int,
    candidates: Sequence[_SectionCandidate],
    used: set[str],
) -> list[QuestionBlueprint]:
    history_keys = {
        (item.source_key, item.section_key)
        for item in candidates
        if item.version_role.startswith("history_")
    }
    eligible = [
        item
        for item in candidates
        if item.version_role == "current"
        and (item.source_key, item.section_key) in history_keys
        and item.section_ref not in used
    ]
    selected = _spread_select(eligible, count, used=used)
    return [
        _blueprint(
            question_id=_question_id(cluster, "distractor", index),
            cluster=cluster,
            category="distractor",
            query=(
                f"과거 연혁이 아니라 현행 {candidate.title}의 "
                f"[{_context_label(candidate)}]에 규정된 기준은 무엇인가요?"
            ),
            required=(candidate,),
        )
        for index, candidate in enumerate(selected, start=1)
    ]


def _unanswerable_questions(cluster: str, count: int) -> list[QuestionBlueprint]:
    prompts = UNANSWERABLE_PROMPTS.get(
        cluster,
        (
            f"{cluster} 관련 법령이 특정 상용 소프트웨어 제품 하나만 사용하도록 의무화하고 있나요?",
            f"{cluster} 관련 법령이 모든 대상에게 예외 없이 동일한 정액 비용을 부과하나요?",
        ),
    )
    if count > len(prompts):
        raise ValueError("law_question_insufficient_unanswerable_prompts")
    return [
        _blueprint(
            question_id=_question_id(cluster, "unanswerable", index),
            cluster=cluster,
            category="unanswerable",
            query=prompt,
            required=(),
        )
        for index, prompt in enumerate(prompts[:count], start=1)
    ]


def generate_law_development_questions(
    candidates: Sequence[_SectionCandidate],
    *,
    corpus_id: str,
) -> QuestionBlueprintPackage:
    clusters = sorted(
        {
            item.sampling_cluster_ref
            for item in candidates
            if item.analysis_role == "primary" and item.version_role == "current"
        }
    )
    allocations = _allocate_targets(clusters)
    questions: list[QuestionBlueprint] = []
    for cluster in clusters:
        cluster_rows = [item for item in candidates if item.sampling_cluster_ref == cluster]
        current_primary = [
            item
            for item in cluster_rows
            if item.analysis_role == "primary"
            and item.version_role == "current"
            and "삭제" not in item.content
            and len(item.content) >= 40
        ]
        used: set[str] = set()
        plan = allocations[cluster]
        questions.extend(
            _boundary_questions(
                cluster, plan["boundary"], current_primary, used
            )
        )
        questions.extend(
            _multi_evidence_questions(
                cluster, plan["multi_evidence"], current_primary, used
            )
        )
        questions.extend(
            _distractor_questions(cluster, plan["distractor"], cluster_rows, used)
        )
        for category in ("single_fact", "section_context", "ambiguous_context"):
            questions.extend(
                _regular_questions(
                    cluster,
                    category,
                    plan[category],
                    current_primary,
                    used,
                )
            )
        questions.extend(_unanswerable_questions(cluster, plan["unanswerable"]))

    questions.sort(key=lambda item: item.question_id)
    package = QuestionBlueprintPackage(
        schema_version="1",
        corpus_id=corpus_id,
        questions=tuple(questions),
    )
    category_counts = Counter(question.category for question in package.questions)
    if dict(category_counts) != dict(PILOT_CATEGORY_TARGETS):
        raise ValueError("law_question_category_target_mismatch")
    queries = [question.query for question in package.questions]
    if len(queries) != len(set(queries)):
        raise ValueError("law_question_duplicate_query")
    return package


def _map_benchmark_questions(
    package: QuestionBlueprintPackage,
    candidates: Sequence[_SectionCandidate],
) -> tuple[tuple[BenchmarkQuestion, ...], list[dict[str, Any]]]:
    by_section = {candidate.section_ref: candidate for candidate in candidates}
    benchmark: list[BenchmarkQuestion] = []
    worksheet: list[dict[str, Any]] = []
    for blueprint in package.questions:
        required = []
        evidence_review = []
        for section_ref in blueprint.required_section_refs:
            candidate = by_section.get(section_ref)
            if candidate is None:
                raise ValueError("law_question_required_section_missing")
            if candidate.sampling_cluster_ref != blueprint.sampling_cluster_ref:
                raise ValueError("law_question_required_section_cluster_mismatch")
            required.append(candidate.evidence_ref)
            evidence_review.append(
                {
                    "evidence_preview": candidate.content[:600],
                    "evidence_ref": candidate.evidence_ref,
                    "hierarchy_path": list(candidate.hierarchy_path),
                    "section_ref": candidate.section_ref,
                    "source_title": candidate.title,
                }
            )
        question = BenchmarkQuestion(
            question_id=blueprint.question_id,
            sampling_cluster_ref=blueprint.sampling_cluster_ref,
            split=blueprint.split,
            category=blueprint.category,
            difficulty=blueprint.difficulty,
            answerable=blueprint.answerable,
            query=blueprint.query,
            safe_display_label=blueprint.safe_display_label,
            required_evidence_refs=tuple(required),
        )
        benchmark.append(question)
        worksheet.append(
            {
                "answerability_review": "pending",
                "category": question.category,
                "evidence_review": evidence_review,
                "evidence_sufficiency_review": "pending",
                "question_id": question.question_id,
                "query": question.query,
                "semantic_review": "pending",
            }
        )
    return tuple(benchmark), worksheet


def prepare_law_question_draft(
    *,
    base_snapshot_dir: str | Path,
    base_snapshot_id: str,
    catalog: LawSourceCatalog,
    bundle_id: str,
    output_dir: str | Path,
) -> LawQuestionDraftSummary:
    snapshot = Path(base_snapshot_dir)
    output = Path(output_dir)
    if snapshot.name != base_snapshot_id:
        raise ValueError("law_question_base_snapshot_id_mismatch")
    if os.path.lexists(output):
        raise FileExistsError("law_question_draft_output_exists")
    source_summary, candidates = _load_candidates(snapshot, catalog)
    package = generate_law_development_questions(
        candidates,
        corpus_id=source_summary.corpus_id,
    )
    benchmark, worksheet = _map_benchmark_questions(package, candidates)
    category_counts = dict(Counter(item.category for item in benchmark))
    cluster_counts = Counter(item.sampling_cluster_ref for item in benchmark)
    answerable_count = sum(item.answerable for item in benchmark)
    question_rows = [item.model_dump(mode="json") for item in benchmark]
    base_snapshot_hash = canonical_hash(
        {
            "canonical_children_hash": source_summary.canonical_children_hash,
            "source_manifest_hash": source_summary.source_manifest_hash,
        }
    )
    summary = LawQuestionDraftSummary(
        schema_version="law_question_draft_v1",
        review_state="pending_human_review",
        bundle_id=bundle_id,
        base_snapshot_id=base_snapshot_id,
        base_snapshot_hash=base_snapshot_hash,
        source_manifest_hash=source_summary.source_manifest_hash,
        canonical_children_hash=source_summary.canonical_children_hash,
        question_draft_hash=canonical_hash(question_rows),
        question_count=len(benchmark),
        answerable_count=answerable_count,
        unanswerable_count=len(benchmark) - answerable_count,
        sampling_cluster_count=len(cluster_counts),
        maximum_questions_per_cluster=max(cluster_counts.values()),
        category_counts=category_counts,
        evidence_mapping_verified=True,
        category_floor_verified=True,
        structural_pilot_ready=True,
        quality_pilot_ready=False,
        blockers=(
            "human_semantic_review_pending",
            "paired_index_binding_pending",
            "development_protocol_pending",
        ),
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    try:
        (stage / "question_blueprints.json").write_bytes(
            _json_bytes(package.model_dump(mode="json"))
        )
        (stage / "question_draft.jsonl").write_bytes(_jsonl_bytes(question_rows))
        (stage / "review_worksheet.jsonl").write_bytes(_jsonl_bytes(worksheet))
        (stage / "summary.json").write_bytes(
            _json_bytes(summary.model_dump(mode="json"))
        )
        if os.path.lexists(output):
            raise FileExistsError("law_question_draft_output_exists")
        stage.rename(output)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return summary
