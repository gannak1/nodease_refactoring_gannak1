from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

import pytest

from tests.evaluation.law_open_data import (
    LawCatalogEntry,
    LawOpenDataClient,
    LawOpenDataError,
    LawSourceCatalog,
    load_law_source_catalog,
    normalize_administrative_rule_json,
    normalize_precedent_json,
    normalize_statute_json,
)


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


STATUTE_SEARCH = {
    "LawSearch": {
        "resultCode": "00",
        "law": [
            {
                "법령일련번호": "100",
                "현행연혁코드": "현행",
                "법령명한글": "개인정보 보호법",
                "법령ID": "law-current",
                "시행일자": "20260701",
            },
            {
                "법령일련번호": "90",
                "현행연혁코드": "연혁",
                "법령명한글": "개인정보 보호법",
                "법령ID": "law-history",
                "시행일자": "20250101",
            },
            {
                "법령일련번호": "80",
                "현행연혁코드": "현행",
                "법령명한글": "개인정보 보호법 시행령",
                "법령ID": "other",
                "시행일자": "20260701",
            },
        ],
    }
}


def _statute_detail(title: str = "개인정보 보호법") -> bytes:
    return _json_bytes(
        {
            "법령": {
                "기본정보": {"법령명_한글": title},
                "조문": {
                    "조문단위": [
                        {"조문여부": "전문", "조문내용": [["제1장", "총칙"]]},
                        {
                            "조문여부": "조문",
                            "조문번호": "1",
                            "조문제목": "목적",
                            "항": {
                                "항번호": "①",
                                "항내용": "이 법은 개인정보를 보호함을 목적으로 한다.",
                            },
                        },
                    ]
                },
            }
        }
    )


def _catalog(*, history_versions: int = 1) -> LawSourceCatalog:
    return LawSourceCatalog(
        schema_version="1",
        catalog_id="kr-law-v1",
        license_ref="korea-law-open-data",
        entries=(
            LawCatalogEntry(
                source_key="privacy_statute",
                sampling_cluster_ref="privacy",
                split="development",
                source_type="law",
                exact_title="개인정보 보호법",
                history_versions=history_versions,
            ),
        ),
    )


def test_probe_uses_https_fixed_origin_json_and_injects_credential_once() -> None:
    captured: list[str] = []

    def fetcher(url: str, _timeout: float, _limit: int) -> tuple[str, bytes]:
        captured.append(url)
        return "application/json", _json_bytes({"LawSearch": {"resultCode": "00"}})

    client = LawOpenDataClient(
        oc="credential-sentinel",
        fetcher=fetcher,
        minimum_interval_seconds=0,
    )
    client.probe("개인정보 보호법")

    parsed = urllib.parse.urlsplit(captured[0])
    query = urllib.parse.parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "www.law.go.kr"
    assert parsed.path == "/DRF/lawSearch.do"
    assert query["OC"] == ["credential-sentinel"]
    assert query["target"] == ["eflaw"]
    assert query["type"] == ["JSON"]


def test_client_requires_a_nonempty_environment_credential(monkeypatch) -> None:
    monkeypatch.delenv("NODEASE_EVAL_LAW_OC", raising=False)

    with pytest.raises(LawOpenDataError, match="law_open_data_credential_missing"):
        LawOpenDataClient.from_environment()


def test_scope_error_is_safe_and_never_discloses_credential() -> None:
    credential = "credential-do-not-disclose"

    def fetcher(_url: str, _timeout: float, _limit: int) -> tuple[str, bytes]:
        return "text/html", "미신청된 목록/본문에 대한 접근입니다.".encode()

    client = LawOpenDataClient(
        oc=credential,
        fetcher=fetcher,
        minimum_interval_seconds=0,
    )
    with pytest.raises(
        LawOpenDataError, match="law_open_data_scope_not_requested"
    ) as captured:
        client.probe("개인정보 보호법")

    assert credential not in str(captured.value)


def test_catalog_probe_checks_each_declared_api_target_once() -> None:
    targets: list[str] = []

    def fetcher(url: str, _timeout: float, _limit: int) -> tuple[str, bytes]:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        target = query["target"][0]
        targets.append(target)
        roots = {
            "eflaw": {"LawSearch": {"resultCode": "00"}},
            "admrul": {"AdmRulSearch": {"resultCode": "00"}},
            "prec": {"PrecService": {"사건명": "probe"}},
        }
        return "application/json", _json_bytes(roots[target])

    catalog = LawSourceCatalog(
        schema_version="1",
        catalog_id="probe-v1",
        license_ref="korea-law-open-data",
        entries=(
            _catalog(history_versions=0).entries[0],
            LawCatalogEntry(
                source_key="privacy_rule",
                sampling_cluster_ref="privacy",
                split="development",
                source_type="administrative_rule",
                exact_title="개인정보의 안전성 확보조치 기준",
            ),
            LawCatalogEntry(
                source_key="privacy_precedent",
                sampling_cluster_ref="privacy",
                split="development",
                source_type="precedent",
                analysis_role="exploratory",
                exact_title="개인정보보호법위반",
                resource_id="618473",
            ),
        ),
    )
    client = LawOpenDataClient(
        oc="safe-test-credential",
        fetcher=fetcher,
        minimum_interval_seconds=0,
    )

    assert client.probe_catalog(catalog) == 3
    assert targets == ["admrul", "eflaw", "prec"]


@pytest.mark.parametrize(
    ("content_type", "payload", "limit", "expected_code"),
    [
        ("application/json", b"12345", 4, "law_open_data_response_too_large"),
        (
            "application/json",
            b'{"root":1,"root":2}',
            1024,
            "law_open_data_duplicate_json_key",
        ),
        (
            "application/json",
            b'{"value":NaN}',
            1024,
            "law_open_data_nonfinite_json_number",
        ),
        ("application/json", b'{"broken":', 1024, "law_open_data_invalid_json"),
        ("application/json", b"[]", 1024, "law_open_data_json_root_not_object"),
    ],
)
def test_client_rejects_oversized_or_invalid_json(
    content_type,
    payload,
    limit,
    expected_code,
) -> None:
    client = LawOpenDataClient(
        oc="safe-test-credential",
        fetcher=lambda *_: (content_type, payload),
        max_response_bytes=limit,
        minimum_interval_seconds=0,
    )

    with pytest.raises(LawOpenDataError, match=expected_code):
        client.probe("개인정보 보호법")


def test_client_rejects_excessively_deep_json() -> None:
    value: object = "leaf"
    for _ in range(70):
        value = {"nested": value}
    client = LawOpenDataClient(
        oc="safe-test-credential",
        fetcher=lambda *_: ("application/json", _json_bytes(value)),
        minimum_interval_seconds=0,
    )

    with pytest.raises(LawOpenDataError, match="law_open_data_json_too_deep"):
        client.probe("개인정보 보호법")


def test_client_rejects_a_response_that_echoes_the_credential() -> None:
    credential = "echo-sentinel"
    client = LawOpenDataClient(
        oc=credential,
        fetcher=lambda *_: (
            "application/json",
            _json_bytes({"value": credential}),
        ),
        minimum_interval_seconds=0,
    )

    with pytest.raises(LawOpenDataError, match="law_open_data_credential_echoed"):
        client.probe("개인정보 보호법")


def test_client_discards_allowlisted_detail_links_before_credential_check() -> None:
    credential = "credential-link-sentinel"
    payload = {
        "LawSearch": {
            "resultCode": "00",
            "law": {
                "법령명한글": "시험법",
                "법령상세링크": f"/detail?OC={credential}&ID=1",
            },
        }
    }
    client = LawOpenDataClient(
        oc=credential,
        fetcher=lambda *_: ("application/json", _json_bytes(payload)),
        minimum_interval_seconds=0,
    )

    root, sanitized = client._request_json(  # noqa: SLF001
        "/DRF/lawSearch.do",
        {"target": "eflaw", "type": "JSON"},
    )

    row = root["LawSearch"]["law"]
    assert "법령상세링크" not in row
    assert credential.encode() not in sanitized


def test_nested_api_error_code_is_rejected() -> None:
    client = LawOpenDataClient(
        oc="safe-test-credential",
        fetcher=lambda *_: (
            "application/json",
            _json_bytes({"LawSearch": {"resultCode": "99"}}),
        ),
        minimum_interval_seconds=0,
    )

    with pytest.raises(LawOpenDataError, match="law_open_data_api_error"):
        client.probe("개인정보 보호법")


def test_request_failure_is_mapped_without_disclosing_fetcher_details() -> None:
    def failing_fetcher(*_args):
        raise RuntimeError("transport-detail-sentinel")

    client = LawOpenDataClient(
        oc="credential-detail-sentinel",
        fetcher=failing_fetcher,
        minimum_interval_seconds=0,
    )

    with pytest.raises(LawOpenDataError, match="law_open_data_request_failed") as exc:
        client.probe("개인정보 보호법")
    assert "transport-detail-sentinel" not in str(exc.value)
    assert "credential-detail-sentinel" not in str(exc.value)


def test_collect_catalog_selects_current_and_latest_history_exactly() -> None:
    responses = iter(
        (
            ("application/json", _json_bytes(STATUTE_SEARCH)),
            ("application/json", _statute_detail()),
            ("application/json", _statute_detail()),
        )
    )
    client = LawOpenDataClient(
        oc="safe-test-credential",
        fetcher=lambda *_: next(responses),
        minimum_interval_seconds=0,
    )

    result = client.collect_catalog(_catalog())

    assert [source.version_role for source in result.sources] == [
        "current",
        "history_01",
    ]
    assert all(source.title == "개인정보 보호법" for source in result.sources)
    assert all(source.sections for source in result.sources)
    assert sorted(result.source_files) == [
        "source-json/src_privacy_statute_current.json",
        "source-json/src_privacy_statute_history_01.json",
    ]
    assert result.provenance_rows[0]["effective_date"] == "20260701"
    assert result.provenance_rows[1]["effective_date"] == "20250101"


def test_law_search_accepts_a_single_result_object() -> None:
    search = json.loads(json.dumps(STATUTE_SEARCH, ensure_ascii=False))
    search["LawSearch"]["law"] = search["LawSearch"]["law"][0]
    responses = iter(
        (
            ("application/json", _json_bytes(search)),
            ("application/json", _statute_detail()),
        )
    )
    client = LawOpenDataClient(
        oc="safe-test-credential",
        fetcher=lambda *_: next(responses),
        minimum_interval_seconds=0,
    )

    result = client.collect_catalog(_catalog(history_versions=0))

    assert len(result.sources) == 1


def test_collect_catalog_fails_closed_on_ambiguous_current_title() -> None:
    ambiguous = json.loads(json.dumps(STATUTE_SEARCH, ensure_ascii=False))
    duplicate = dict(ambiguous["LawSearch"]["law"][0])
    duplicate["법령일련번호"] = "101"
    ambiguous["LawSearch"]["law"].append(duplicate)
    client = LawOpenDataClient(
        oc="safe-test-credential",
        fetcher=lambda *_: ("application/json", _json_bytes(ambiguous)),
        minimum_interval_seconds=0,
    )

    with pytest.raises(
        LawOpenDataError, match="law_open_data_exact_current_match_required"
    ):
        client.collect_catalog(_catalog(history_versions=0))


def test_collect_catalog_requires_every_requested_history_version() -> None:
    client = LawOpenDataClient(
        oc="safe-test-credential",
        fetcher=lambda *_: ("application/json", _json_bytes(STATUTE_SEARCH)),
        minimum_interval_seconds=0,
    )

    with pytest.raises(
        LawOpenDataError, match="law_open_data_requested_history_unavailable"
    ):
        client.collect_catalog(_catalog(history_versions=2))


def test_collect_catalog_fails_closed_when_detail_title_changes() -> None:
    responses = iter(
        (
            ("application/json", _json_bytes(STATUTE_SEARCH)),
            ("application/json", _statute_detail("다른 법률")),
        )
    )
    client = LawOpenDataClient(
        oc="safe-test-credential",
        fetcher=lambda *_: next(responses),
        minimum_interval_seconds=0,
    )

    with pytest.raises(LawOpenDataError, match="law_open_data_title_mismatch"):
        client.collect_catalog(_catalog(history_versions=0))


def test_collect_catalog_enforces_an_aggregate_raw_response_limit() -> None:
    responses = iter(
        (
            ("application/json", _json_bytes(STATUTE_SEARCH)),
            ("application/json", _statute_detail()),
        )
    )
    client = LawOpenDataClient(
        oc="safe-test-credential",
        fetcher=lambda *_: next(responses),
        max_collection_bytes=len(_statute_detail()) - 1,
        minimum_interval_seconds=0,
    )

    with pytest.raises(LawOpenDataError, match="law_open_data_collection_too_large"):
        client.collect_catalog(_catalog(history_versions=0))


def test_statute_normalization_preserves_chapter_article_and_paragraph() -> None:
    source = normalize_statute_json(
        json.loads(_statute_detail()),
        source_ref="src_DDDDDDDDDDDDDDDD",
        sampling_cluster_ref="privacy",
        split="development",
        analysis_role="primary",
        version_role="current",
    )

    assert source.sections[0].hierarchy_path == ("제1장 총칙", "제1조 목적", "①")
    assert source.sections[0].heading == "제1조 목적 ①"


def test_statute_normalization_preserves_item_only_and_subitem_boundaries() -> None:
    root = {
        "법령": {
            "기본정보": {"법령명_한글": "시험법"},
            "조문": {
                "조문단위": {
                    "조문여부": "조문",
                    "조문번호": "2",
                    "조문제목": "의무",
                    "항": {
                        "호": [
                            {
                                "호번호": "1.",
                                "호내용": "보호 조치를 한다.",
                                "목": {
                                    "목번호": "가.",
                                    "목내용": "접근을 제한한다.",
                                },
                            }
                        ]
                    },
                }
            },
        }
    }
    source = normalize_statute_json(
        root,
        source_ref="src_FFFFFFFFFFFFFFFF",
        sampling_cluster_ref="privacy",
        split="development",
        analysis_role="primary",
        version_role="current",
    )

    assert [section.section_key for section in source.sections] == [
        "article-0000-paragraph-001-item-001",
        "article-0000-paragraph-001-item-001-subitem-001",
    ]
    assert source.sections[-1].hierarchy_path == ("제2조 의무", "1.", "가.")


def test_statute_normalization_rejects_non_object_article_rows() -> None:
    root = {
        "법령": {
            "기본정보": {"법령명_한글": "시험법"},
            "조문": {"조문단위": ["invalid"]},
        }
    }

    with pytest.raises(
        LawOpenDataError, match="law_open_data_statute_article_shape_invalid"
    ):
        normalize_statute_json(
            root,
            source_ref="src_GGGGGGGGGGGGGGGG",
            sampling_cluster_ref="privacy",
            split="development",
            analysis_role="primary",
            version_role="current",
        )


def test_administrative_rule_normalizes_single_article_object() -> None:
    root = {
        "AdmRulService": {
            "행정규칙기본정보": {"행정규칙명": "안전 기준"},
            "조문": {"조문번호": "1", "조문제목": "목적", "조문내용": "목적이다."},
        }
    }

    source = normalize_administrative_rule_json(
        root,
        source_ref="src_BBBBBBBBBBBBBBBB",
        sampling_cluster_ref="security",
        split="development",
        analysis_role="primary",
        version_role="current",
    )

    assert [section.heading for section in source.sections] == ["제1조 목적"]


def test_administrative_rule_normalizes_repeated_body_blocks() -> None:
    root = {
        "AdmRulService": {
            "행정규칙기본정보": {"행정규칙명": "안전 기준"},
            "조문내용": ["첫 번째 본문", "두 번째 본문"],
        }
    }

    source = normalize_administrative_rule_json(
        root,
        source_ref="src_HHHHHHHHHHHHHHHH",
        sampling_cluster_ref="security",
        split="development",
        analysis_role="primary",
        version_role="current",
    )

    assert [section.heading for section in source.sections] == [
        "행정규칙 본문 1",
        "행정규칙 본문 2",
    ]


def test_administrative_rule_rejects_ambiguous_dual_body_shapes() -> None:
    root = {
        "AdmRulService": {
            "행정규칙기본정보": {"행정규칙명": "안전 기준"},
            "조문": {"조문번호": "1", "조문제목": "목적", "조문내용": "목적이다."},
            "조문내용": ["중복 본문"],
        }
    }

    with pytest.raises(
        LawOpenDataError, match="law_open_data_administrative_rule_body_ambiguous"
    ):
        normalize_administrative_rule_json(
            root,
            source_ref="src_IIIIIIIIIIIIIIII",
            sampling_cluster_ref="security",
            split="development",
            analysis_role="primary",
            version_role="current",
        )


def test_precedent_normalization_is_exploratory_and_bounded() -> None:
    root = {
        "PrecService": {
            "사건명": "개인정보보호법위반",
            "판시사항": "쟁점",
            "판결요지": "요지",
            "참조조문": "제1조",
            "판례내용": "판결 내용",
        }
    }

    source = normalize_precedent_json(
        root,
        source_ref="src_CCCCCCCCCCCCCCCC",
        sampling_cluster_ref="privacy",
        split="development",
        analysis_role="exploratory",
        version_role="selected",
    )

    assert source.analysis_role == "exploratory"
    assert {section.heading for section in source.sections} == {
        "판시사항",
        "판결요지",
        "참조조문",
        "판례내용",
    }


def test_long_precedent_content_is_split_into_bounded_sections() -> None:
    long_content = " ".join("판결" for _ in range(2_000))
    root = {"PrecService": {"사건명": "시험판례", "판례내용": long_content}}

    source = normalize_precedent_json(
        root,
        source_ref="src_EEEEEEEEEEEEEEEE",
        sampling_cluster_ref="privacy",
        split="development",
        analysis_role="exploratory",
        version_role="selected",
    )

    assert len(source.sections) > 1
    assert max(len(section.text) for section in source.sections) <= 4_000


def test_tracked_law_catalog_separates_primary_and_exploratory_tracks() -> None:
    repo = Path(__file__).resolve().parents[3]
    catalog = load_law_source_catalog(
        repo
        / "tests/evaluation/datasets/flat_hierarchical/kr-law-dry-run-v1/catalog.json"
    )

    assert len(catalog.entries) == 15
    assert {entry.sampling_cluster_ref for entry in catalog.entries} == {
        "privacy",
        "labor",
        "safety",
        "records",
        "procedure",
        "electronic-documents",
    }
    precedents = [entry for entry in catalog.entries if entry.source_type == "precedent"]
    assert len(precedents) == 1
    assert precedents[0].analysis_role == "exploratory"
    assert all(
        entry.analysis_role == "primary"
        for entry in catalog.entries
        if entry.source_type != "precedent"
    )
