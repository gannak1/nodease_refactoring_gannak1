"""Secure JSON acquisition and normalization for Korea Law Open Data."""

from __future__ import annotations

import json
import math
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tests.evaluation.corpus_authoring import AuthoredSection, AuthoredSource


LAW_OPEN_DATA_ORIGIN = "https://www.law.go.kr"
LAW_SEARCH_PATH = "/DRF/lawSearch.do"
LAW_SERVICE_PATH = "/DRF/lawService.do"
SAFE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
SOURCE_REF_PATTERN = re.compile(r"^src_[A-Za-z0-9_-]{16,64}$")
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_COLLECTION_BYTES = 128 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 250_000
DISCARDED_UPSTREAM_LINK_FIELDS = {
    "법령상세링크",
    "행정규칙상세링크",
    "판례상세링크",
}


class LawOpenDataError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class LawCatalogEntry(_StrictModel):
    source_key: str = Field(pattern=SAFE_ID_PATTERN, max_length=32)
    sampling_cluster_ref: str = Field(pattern=SAFE_ID_PATTERN, max_length=64)
    split: Literal["development", "holdout"]
    source_type: Literal["law", "administrative_rule", "precedent"]
    analysis_role: Literal["primary", "exploratory"] = "primary"
    exact_title: str = Field(min_length=1, max_length=300)
    resource_id: str | None = Field(default=None, pattern=r"^[0-9]{1,32}$")
    history_versions: int = Field(default=0, ge=0, le=3)

    @field_validator("exact_title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        normalized = unicodedata.normalize("NFC", value).strip()
        if not normalized or any(ord(character) < 32 for character in normalized):
            raise ValueError("invalid_law_catalog_title")
        return normalized

    @model_validator(mode="after")
    def validate_selector(self) -> "LawCatalogEntry":
        if self.source_type == "precedent":
            if self.resource_id is None:
                raise ValueError("precedent_resource_id_required")
            if self.history_versions:
                raise ValueError("precedent_history_not_supported")
        elif self.resource_id is not None:
            raise ValueError("search_catalog_must_not_pin_resource_id")
        return self


class LawSourceCatalog(_StrictModel):
    schema_version: Literal["1"]
    catalog_id: str = Field(pattern=SAFE_ID_PATTERN, max_length=64)
    license_ref: str = Field(pattern=SAFE_ID_PATTERN, max_length=64)
    entries: tuple[LawCatalogEntry, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_entries(self) -> "LawSourceCatalog":
        keys = [entry.source_key for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate_law_catalog_source_key")
        return self


@dataclass(frozen=True)
class LawCollectionResult:
    sources: tuple[AuthoredSource, ...]
    source_files: dict[str, bytes]
    provenance_rows: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class _VersionCandidate:
    official_id: str
    master_id: str | None
    effective_date: str
    title: str
    status: str
    version_role: str


Fetcher = Callable[[str, float, int], tuple[str, bytes]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _default_fetcher(url: str, timeout_seconds: float, max_bytes: int) -> tuple[str, bytes]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Nodease-Evaluation/1.0",
        },
        method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirect)
    with opener.open(request, timeout=timeout_seconds) as response:
        content_type = response.headers.get_content_type()
        return content_type, response.read(max_bytes + 1)


def load_law_source_catalog(path: str | Path) -> LawSourceCatalog:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return LawSourceCatalog.model_validate(raw)


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LawOpenDataError("law_open_data_duplicate_json_key")
        result[key] = value
    return result


def _reject_nonfinite_constant(_value: str) -> None:
    raise LawOpenDataError("law_open_data_nonfinite_json_number")


def _validate_json_shape(value: Any) -> None:
    remaining = MAX_JSON_NODES

    def visit(current: Any, depth: int) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining < 0:
            raise LawOpenDataError("law_open_data_json_too_complex")
        if depth > MAX_JSON_DEPTH:
            raise LawOpenDataError("law_open_data_json_too_deep")
        if isinstance(current, dict):
            for nested in current.values():
                visit(nested, depth + 1)
            return
        if isinstance(current, list):
            for nested in current:
                visit(nested, depth + 1)
            return
        if isinstance(current, float) and not math.isfinite(current):
            raise LawOpenDataError("law_open_data_nonfinite_json_number")
        if current is not None and not isinstance(current, (str, int, float, bool)):
            raise LawOpenDataError("law_open_data_invalid_json_value")

    visit(value, 0)


def _decode_json(payload: bytes) -> dict[str, Any]:
    try:
        decoded = payload.decode("utf-8-sig")
        value = json.loads(
            decoded,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite_constant,
        )
    except LawOpenDataError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise LawOpenDataError("law_open_data_invalid_json") from None
    if not isinstance(value, dict):
        raise LawOpenDataError("law_open_data_json_root_not_object")
    _validate_json_shape(value)
    return value


def _sanitize_upstream_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_upstream_json(nested)
            for key, nested in value.items()
            if key not in DISCARDED_UPSTREAM_LINK_FIELDS
        }
    if isinstance(value, list):
        return [_sanitize_upstream_json(nested) for nested in value]
    return value


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _api_result_code(root: Mapping[str, Any]) -> str:
    direct = root.get("resultCode")
    if direct is not None:
        return _scalar_text(direct)
    for nested in root.values():
        if isinstance(nested, Mapping) and "resultCode" in nested:
            return _scalar_text(nested.get("resultCode"))
    return ""


class LawOpenDataClient:
    def __init__(
        self,
        *,
        oc: str,
        fetcher: Fetcher = _default_fetcher,
        timeout_seconds: float = 20,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        max_collection_bytes: int = MAX_COLLECTION_BYTES,
        minimum_interval_seconds: float = 0.2,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not oc.strip():
            raise LawOpenDataError("law_open_data_credential_missing")
        if (
            timeout_seconds <= 0
            or max_response_bytes < 1
            or max_collection_bytes < 1
        ):
            raise ValueError("invalid_law_open_data_client_limits")
        self._oc = oc.strip()
        self._fetcher = fetcher
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._max_collection_bytes = max_collection_bytes
        self._minimum_interval_seconds = max(0.0, minimum_interval_seconds)
        self._sleeper = sleeper
        self._request_count = 0

    @classmethod
    def from_environment(cls, **kwargs) -> "LawOpenDataClient":  # noqa: ANN003
        return cls(oc=os.getenv("NODEASE_EVAL_LAW_OC", ""), **kwargs)

    def _request_json(
        self, path: str, params: dict[str, str]
    ) -> tuple[dict[str, Any], bytes]:
        if path not in {LAW_SEARCH_PATH, LAW_SERVICE_PATH}:
            raise ValueError("unsupported_law_open_data_path")
        if "OC" in params:
            raise ValueError("credential_parameter_owned_by_client")
        if self._request_count:
            self._sleeper(self._minimum_interval_seconds)
        query = urllib.parse.urlencode({**params, "OC": self._oc})
        url = f"{LAW_OPEN_DATA_ORIGIN}{path}?{query}"
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "www.law.go.kr"
            or parsed.path != path
        ):
            raise ValueError("law_open_data_origin_violation")
        try:
            content_type, payload = self._fetcher(
                url, self._timeout_seconds, self._max_response_bytes
            )
        except Exception:
            raise LawOpenDataError("law_open_data_request_failed") from None
        finally:
            self._request_count += 1
        if len(payload) > self._max_response_bytes:
            raise LawOpenDataError("law_open_data_response_too_large")
        if content_type != "application/json":
            decoded = payload.decode("utf-8", errors="replace")
            if "미신청된 목록/본문" in decoded:
                raise LawOpenDataError("law_open_data_scope_not_requested")
            if "인증" in decoded:
                raise LawOpenDataError("law_open_data_authentication_failed")
            raise LawOpenDataError("law_open_data_unexpected_content_type")
        root = _sanitize_upstream_json(_decode_json(payload))
        sanitized_payload = _canonical_json_bytes(root)
        credential_encodings = {
            self._oc.encode("utf-8"),
            urllib.parse.quote(self._oc, safe="").encode("ascii"),
            urllib.parse.quote_plus(self._oc, safe="").encode("ascii"),
        }
        if any(value and value in sanitized_payload for value in credential_encodings):
            raise LawOpenDataError("law_open_data_credential_echoed")
        result_code = _api_result_code(root)
        if result_code not in {"", "0", "00"}:
            raise LawOpenDataError("law_open_data_api_error")
        return root, sanitized_payload

    def probe(self, exact_title: str) -> None:
        self._request_json(
            LAW_SEARCH_PATH,
            {
                "display": "1",
                "page": "1",
                "query": exact_title,
                "search": "1",
                "target": "eflaw",
                "type": "JSON",
            },
        )

    def probe_catalog(self, catalog: LawSourceCatalog) -> int:
        probe_entries: dict[str, LawCatalogEntry] = {}
        for entry in catalog.entries:
            probe_entries.setdefault(entry.source_type, entry)
        for source_type, entry in sorted(probe_entries.items()):
            if source_type == "precedent":
                self._request_json(
                    LAW_SERVICE_PATH,
                    {
                        "ID": entry.resource_id or "",
                        "target": "prec",
                        "type": "JSON",
                    },
                )
                continue
            target = "eflaw" if source_type == "law" else "admrul"
            self._request_json(
                LAW_SEARCH_PATH,
                {
                    "display": "1",
                    "page": "1",
                    "query": entry.exact_title,
                    "search": "1",
                    "target": target,
                    "type": "JSON",
                },
            )
        return len(probe_entries)

    def collect_catalog(self, catalog: LawSourceCatalog) -> LawCollectionResult:
        sources: list[AuthoredSource] = []
        source_files: dict[str, bytes] = {}
        provenance_rows: list[dict[str, object]] = []
        collected_bytes = 0
        for entry in catalog.entries:
            if entry.source_type == "law":
                candidates = self._law_versions(entry)
            elif entry.source_type == "administrative_rule":
                candidates = self._administrative_rule_versions(entry)
            else:
                candidates = (
                    _VersionCandidate(
                        official_id=entry.resource_id or "",
                        master_id=None,
                        effective_date="selected",
                        title=entry.exact_title,
                        status="selected",
                        version_role="selected",
                    ),
                )
            for candidate_index, candidate in enumerate(candidates):
                source_ref = _source_ref(entry.source_key, candidate.version_role)
                root, payload = self._fetch_detail(entry, candidate)
                collected_bytes += len(payload)
                if collected_bytes > self._max_collection_bytes:
                    raise LawOpenDataError("law_open_data_collection_too_large")
                if entry.source_type == "law":
                    source = normalize_statute_json(
                        root,
                        source_ref=source_ref,
                        sampling_cluster_ref=entry.sampling_cluster_ref,
                        split=entry.split,
                        analysis_role=entry.analysis_role,
                        version_role=candidate.version_role,
                    )
                elif entry.source_type == "administrative_rule":
                    source = normalize_administrative_rule_json(
                        root,
                        source_ref=source_ref,
                        sampling_cluster_ref=entry.sampling_cluster_ref,
                        split=entry.split,
                        analysis_role=entry.analysis_role,
                        version_role=candidate.version_role,
                    )
                else:
                    source = normalize_precedent_json(
                        root,
                        source_ref=source_ref,
                        sampling_cluster_ref=entry.sampling_cluster_ref,
                        split=entry.split,
                        analysis_role=entry.analysis_role,
                        version_role=candidate.version_role,
                    )
                if _normalize_text(source.title) != _normalize_text(entry.exact_title):
                    raise LawOpenDataError("law_open_data_title_mismatch")
                source_path = f"source-json/{source_ref}.json"
                source_files[source_path] = payload
                provenance_rows.append(
                    {
                        "analysis_role": entry.analysis_role,
                        "captured_order": candidate_index,
                        "effective_date": candidate.effective_date,
                        "official_resource_id": candidate.official_id,
                        "official_resource_master_id": candidate.master_id,
                        "source_relative_path": source_path,
                        "source_ref": source_ref,
                        "source_type": entry.source_type,
                        "status": candidate.status,
                        "title": source.title,
                        "version_role": candidate.version_role,
                    }
                )
                sources.append(source)
        return LawCollectionResult(
            sources=tuple(sources),
            source_files=source_files,
            provenance_rows=tuple(provenance_rows),
        )

    def _law_versions(self, entry: LawCatalogEntry) -> tuple[_VersionCandidate, ...]:
        root, _ = self._request_json(
            LAW_SEARCH_PATH,
            {
                "display": "100",
                "nw": "1,3",
                "page": "1",
                "query": entry.exact_title,
                "search": "1",
                "target": "eflaw",
                "type": "JSON",
            },
        )
        container = _required_object(root, "LawSearch", "law_open_data_law_search_root_mismatch")
        matches = [
            _VersionCandidate(
                official_id=_scalar_text(row.get("법령ID")),
                master_id=_scalar_text(row.get("법령일련번호")),
                effective_date=_scalar_text(row.get("시행일자")),
                title=_scalar_text(row.get("법령명한글")),
                status=_scalar_text(row.get("현행연혁코드")),
                version_role="candidate",
            )
            for row in _object_list(container.get("law"), "law_open_data_law_search_shape_invalid")
            if _normalize_text(_scalar_text(row.get("법령명한글")))
            == _normalize_text(entry.exact_title)
        ]
        current = [candidate for candidate in matches if candidate.status == "현행"]
        if len(current) != 1:
            raise LawOpenDataError("law_open_data_exact_current_match_required")
        selected = [replace(current[0], version_role="current")]
        history = sorted(
            (candidate for candidate in matches if candidate.status == "연혁"),
            key=lambda candidate: candidate.effective_date,
            reverse=True,
        )
        if len(history) < entry.history_versions:
            raise LawOpenDataError("law_open_data_requested_history_unavailable")
        selected.extend(
            replace(candidate, version_role=f"history_{index:02d}")
            for index, candidate in enumerate(history[: entry.history_versions], start=1)
        )
        if any(
            not candidate.master_id
            or not candidate.effective_date.isdigit()
            or not candidate.official_id
            for candidate in selected
        ):
            raise LawOpenDataError("law_open_data_incomplete_version_metadata")
        return tuple(selected)

    def _administrative_rule_versions(
        self, entry: LawCatalogEntry
    ) -> tuple[_VersionCandidate, ...]:
        selected: list[_VersionCandidate] = []
        for history_index, nw in enumerate(("1", "2")):
            if history_index and not entry.history_versions:
                break
            root, _ = self._request_json(
                LAW_SEARCH_PATH,
                {
                    "display": "100",
                    "nw": nw,
                    "page": "1",
                    "query": entry.exact_title,
                    "search": "1",
                    "target": "admrul",
                    "type": "JSON",
                },
            )
            container = _required_object(
                root,
                "AdmRulSearch",
                "law_open_data_administrative_rule_search_root_mismatch",
            )
            matches = [
                _VersionCandidate(
                    official_id=_scalar_text(row.get("행정규칙일련번호")),
                    master_id=_scalar_text(row.get("행정규칙ID")) or None,
                    effective_date=_scalar_text(row.get("시행일자")),
                    title=_scalar_text(row.get("행정규칙명")),
                    status=_scalar_text(row.get("현행연혁구분")),
                    version_role="current" if nw == "1" else "candidate",
                )
                for row in _object_list(
                    container.get("admrul"),
                    "law_open_data_administrative_rule_search_shape_invalid",
                )
                if _normalize_text(_scalar_text(row.get("행정규칙명")))
                == _normalize_text(entry.exact_title)
            ]
            if nw == "1":
                if len(matches) != 1:
                    raise LawOpenDataError("law_open_data_exact_current_match_required")
                selected.append(matches[0])
            else:
                matches.sort(key=lambda candidate: candidate.effective_date, reverse=True)
                if len(matches) < entry.history_versions:
                    raise LawOpenDataError("law_open_data_requested_history_unavailable")
                selected.extend(
                    replace(candidate, version_role=f"history_{index:02d}")
                    for index, candidate in enumerate(
                        matches[: entry.history_versions], start=1
                    )
                )
        if any(not candidate.official_id for candidate in selected):
            raise LawOpenDataError("law_open_data_incomplete_version_metadata")
        return tuple(selected)

    def _fetch_detail(
        self, entry: LawCatalogEntry, candidate: _VersionCandidate
    ) -> tuple[dict[str, Any], bytes]:
        if entry.source_type == "law":
            params = {
                "MST": candidate.master_id or "",
                "efYd": candidate.effective_date,
                "target": "eflaw",
                "type": "JSON",
            }
        elif entry.source_type == "administrative_rule":
            params = {
                "ID": candidate.official_id,
                "target": "admrul",
                "type": "JSON",
            }
        else:
            params = {
                "ID": candidate.official_id,
                "target": "prec",
                "type": "JSON",
            }
        return self._request_json(LAW_SERVICE_PATH, params)


def _source_ref(source_key: str, version_role: str) -> str:
    value = f"src_{source_key}_{version_role}"
    if SOURCE_REF_PATTERN.fullmatch(value) is None:
        raise ValueError("generated_source_ref_invalid")
    return value


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value)).strip()


def _scalar_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return _normalize_text(str(value))
    if isinstance(value, Mapping) and set(value) <= {"content"}:
        return _scalar_text(value.get("content"))
    raise LawOpenDataError("law_open_data_scalar_shape_invalid")


def _content_text(value: Any) -> str:
    if isinstance(value, list):
        return _normalize_text(" ".join(_content_text(item) for item in value))
    return _scalar_text(value)


def _required_object(
    root: Mapping[str, Any], key: str, error_code: str
) -> dict[str, Any]:
    value = root.get(key)
    if not isinstance(value, dict):
        raise LawOpenDataError(error_code)
    return value


def _object_list(value: Any, error_code: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    if not all(isinstance(item, dict) for item in values):
        raise LawOpenDataError(error_code)
    return values


def _string_list(value: Any, error_code: str) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    if not all(isinstance(item, str) for item in values):
        raise LawOpenDataError(error_code)
    return [_normalize_text(item) for item in values if _normalize_text(item)]


def _article_label(number: str, title: str) -> str:
    normalized_number = _normalize_text(number)
    if normalized_number and not normalized_number.startswith("제"):
        normalized_number = f"제{normalized_number}조"
    return _normalize_text(" ".join(part for part in (normalized_number, title) if part))


def _update_heading_path(
    headings: list[tuple[int, str]], heading: str
) -> list[tuple[int, str]]:
    match = re.match(r"^제[0-9가-힣]+(편|장|절|관)", heading)
    if match is None:
        return headings
    level = {"편": 1, "장": 2, "절": 3, "관": 4}[match.group(1)]
    return [item for item in headings if item[0] < level] + [(level, heading)]


def normalize_statute_json(
    root: Mapping[str, Any],
    *,
    source_ref: str,
    sampling_cluster_ref: str,
    split: Literal["development", "holdout"],
    analysis_role: Literal["primary", "exploratory"],
    version_role: str,
) -> AuthoredSource:
    law = _required_object(root, "법령", "law_open_data_statute_root_mismatch")
    basic = law.get("기본정보")
    if not isinstance(basic, Mapping):
        raise LawOpenDataError("law_open_data_statute_basic_info_missing")
    title = _scalar_text(basic.get("법령명_한글"))
    if not title:
        raise LawOpenDataError("law_open_data_title_missing")
    article_container = law.get("조문")
    if not isinstance(article_container, Mapping):
        raise LawOpenDataError("law_open_data_statute_articles_missing")
    units = _object_list(
        article_container.get("조문단위"),
        "law_open_data_statute_article_shape_invalid",
    )
    headings: list[tuple[int, str]] = []
    sections: list[AuthoredSection] = []
    article_index = 0
    for unit in units:
        article_kind = _scalar_text(unit.get("조문여부"))
        unit_text = _content_text(unit.get("조문내용"))
        unit_title = _scalar_text(unit.get("조문제목"))
        if article_kind == "전문":
            heading = unit_text or unit_title
            if heading:
                headings = _update_heading_path(headings, heading)
            continue
        if article_kind != "조문":
            continue
        article_heading = _article_label(_scalar_text(unit.get("조문번호")), unit_title)
        if not article_heading:
            article_heading = f"article-{article_index:04d}"
        path = tuple(item[1] for item in headings) + (article_heading,)
        paragraphs = _object_list(
            unit.get("항"), "law_open_data_statute_paragraph_shape_invalid"
        )
        if paragraphs:
            for paragraph_index, paragraph in enumerate(paragraphs, start=1):
                paragraph_number = _scalar_text(paragraph.get("항번호"))
                paragraph_heading = _normalize_text(
                    " ".join(part for part in (article_heading, paragraph_number) if part)
                )
                paragraph_path = path + ((paragraph_number,) if paragraph_number else ())
                paragraph_content = _content_text(paragraph.get("항내용"))
                items = _object_list(
                    paragraph.get("호"), "law_open_data_statute_item_shape_invalid"
                )
                if paragraph_content:
                    sections.append(
                        AuthoredSection(
                            section_key=(
                                f"article-{article_index:04d}-"
                                f"paragraph-{paragraph_index:03d}"
                            ),
                            hierarchy_path=paragraph_path,
                            heading=paragraph_heading,
                            text=_normalize_text(f"{paragraph_heading} {paragraph_content}"),
                        )
                    )
                for item_index, item in enumerate(items, start=1):
                    item_number = _scalar_text(item.get("호번호"))
                    item_heading = _normalize_text(
                        " ".join(part for part in (paragraph_heading, item_number) if part)
                    )
                    item_path = paragraph_path + ((item_number,) if item_number else ())
                    item_content = _content_text(item.get("호내용"))
                    subitems = _object_list(
                        item.get("목"), "law_open_data_statute_subitem_shape_invalid"
                    )
                    if item_content:
                        sections.append(
                            AuthoredSection(
                                section_key=(
                                    f"article-{article_index:04d}-"
                                    f"paragraph-{paragraph_index:03d}-"
                                    f"item-{item_index:03d}"
                                ),
                                hierarchy_path=item_path,
                                heading=item_heading,
                                text=_normalize_text(f"{item_heading} {item_content}"),
                            )
                        )
                    for subitem_index, subitem in enumerate(subitems, start=1):
                        subitem_number = _scalar_text(subitem.get("목번호"))
                        subitem_heading = _normalize_text(
                            " ".join(
                                part for part in (item_heading, subitem_number) if part
                            )
                        )
                        subitem_content = _content_text(subitem.get("목내용"))
                        if not subitem_content:
                            continue
                        sections.append(
                            AuthoredSection(
                                section_key=(
                                    f"article-{article_index:04d}-"
                                    f"paragraph-{paragraph_index:03d}-"
                                    f"item-{item_index:03d}-"
                                    f"subitem-{subitem_index:03d}"
                                ),
                                hierarchy_path=(
                                    item_path
                                    + ((subitem_number,) if subitem_number else ())
                                ),
                                heading=subitem_heading,
                                text=_normalize_text(f"{subitem_heading} {subitem_content}"),
                            )
                        )
        elif unit_text:
            sections.append(
                AuthoredSection(
                    section_key=f"article-{article_index:04d}-paragraph-000",
                    hierarchy_path=path,
                    heading=article_heading,
                    text=unit_text,
                )
            )
        article_index += 1
    if not sections:
        raise LawOpenDataError("law_open_data_no_normalized_sections")
    return AuthoredSource(
        source_ref=source_ref,
        sampling_cluster_ref=sampling_cluster_ref,
        split=split,
        source_type="law",
        analysis_role=analysis_role,
        version_role=version_role,
        title=title,
        sections=tuple(sections),
    )


def normalize_administrative_rule_json(
    root: Mapping[str, Any],
    *,
    source_ref: str,
    sampling_cluster_ref: str,
    split: Literal["development", "holdout"],
    analysis_role: Literal["primary", "exploratory"],
    version_role: str,
) -> AuthoredSource:
    rule = _required_object(
        root,
        "AdmRulService",
        "law_open_data_administrative_rule_root_mismatch",
    )
    basic = rule.get("행정규칙기본정보")
    if not isinstance(basic, Mapping):
        raise LawOpenDataError("law_open_data_administrative_rule_basic_info_missing")
    title = _scalar_text(basic.get("행정규칙명"))
    if not title:
        raise LawOpenDataError("law_open_data_title_missing")
    article_rows = _object_list(
        rule.get("조문"), "law_open_data_administrative_rule_article_shape_invalid"
    )
    body_blocks = _string_list(
        rule.get("조문내용"), "law_open_data_administrative_rule_body_shape_invalid"
    )
    if article_rows and body_blocks:
        raise LawOpenDataError("law_open_data_administrative_rule_body_ambiguous")
    sections: list[AuthoredSection] = []
    for index, row in enumerate(article_rows):
        heading = _article_label(
            _scalar_text(row.get("조문번호")), _scalar_text(row.get("조문제목"))
        )
        content = _content_text(row.get("조문내용"))
        if heading and content:
            sections.append(
                AuthoredSection(
                    section_key=f"article-{index:04d}",
                    hierarchy_path=(heading,),
                    heading=heading,
                    text=content,
                )
            )
    for index, content in enumerate(body_blocks):
        heading = f"행정규칙 본문 {index + 1}"
        sections.append(
            AuthoredSection(
                section_key=f"body-{index:04d}",
                hierarchy_path=(heading,),
                heading=heading,
                text=content,
            )
        )
    if not sections:
        raise LawOpenDataError("law_open_data_no_normalized_sections")
    return AuthoredSource(
        source_ref=source_ref,
        sampling_cluster_ref=sampling_cluster_ref,
        split=split,
        source_type="administrative_rule",
        analysis_role=analysis_role,
        version_role=version_role,
        title=title,
        sections=tuple(sections),
    )


def _bounded_chunks(value: str, maximum_characters: int = 4_000) -> tuple[str, ...]:
    value = _normalize_text(value)
    if len(value) <= maximum_characters:
        return (value,) if value else ()
    chunks: list[str] = []
    remaining = value
    while remaining:
        if len(remaining) <= maximum_characters:
            chunks.append(remaining)
            break
        boundary = remaining.rfind(" ", 0, maximum_characters + 1)
        if boundary < maximum_characters // 2:
            boundary = maximum_characters
        chunks.append(remaining[:boundary].strip())
        remaining = remaining[boundary:].strip()
    return tuple(chunk for chunk in chunks if chunk)


def normalize_precedent_json(
    root: Mapping[str, Any],
    *,
    source_ref: str,
    sampling_cluster_ref: str,
    split: Literal["development", "holdout"],
    analysis_role: Literal["primary", "exploratory"],
    version_role: str,
) -> AuthoredSource:
    precedent = _required_object(
        root, "PrecService", "law_open_data_precedent_root_mismatch"
    )
    title = _scalar_text(precedent.get("사건명"))
    if not title:
        raise LawOpenDataError("law_open_data_title_missing")
    fields = (
        ("issues", "판시사항"),
        ("summary", "판결요지"),
        ("references", "참조조문"),
        ("decision", "판례내용"),
    )
    sections: list[AuthoredSection] = []
    for field_key, field_name in fields:
        content = _content_text(precedent.get(field_name))
        for chunk_index, chunk in enumerate(_bounded_chunks(content), start=1):
            sections.append(
                AuthoredSection(
                    section_key=f"{field_key}-{chunk_index:03d}",
                    hierarchy_path=(field_name,),
                    heading=field_name,
                    text=chunk,
                )
            )
    if not sections:
        raise LawOpenDataError("law_open_data_no_normalized_sections")
    return AuthoredSource(
        source_ref=source_ref,
        sampling_cluster_ref=sampling_cluster_ref,
        split=split,
        source_type="precedent",
        analysis_role=analysis_role,
        version_role=version_role,
        title=title,
        sections=tuple(sections),
    )
