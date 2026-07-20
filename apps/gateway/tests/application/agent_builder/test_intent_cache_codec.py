import json

import pytest
from pydantic import create_model

from apps.gateway.application.agent_builder.intent_cache import (
    CachedIntentPlanV1,
    CanonicalIntentPlanCodec,
    IntentPlanCodecError,
)
from apps.gateway.application.agent_builder.intent_cache.contracts import (
    IntentPlanContractVersions,
    LogicalStepRef,
)


def _plan(*capabilities: str) -> CachedIntentPlanV1:
    counts: dict[str, int] = {}
    steps = []
    for capability in capabilities:
        counts[capability] = counts.get(capability, 0) + 1
        steps.append(
            LogicalStepRef(
                capability=capability,
                occurrence=counts[capability],
            )
        )
    return CachedIntentPlanV1(
        schema_version=1,
        request_type="new_workflow",
        draft_mode="new_workflow",
        ordered_capabilities=tuple(capabilities),
        logical_steps=tuple(steps),
        edit_placement=None,
        integration_actions=(),
        parameter_guidance_refs=(),
        knowledge_requirements=(),
        knowledge_placements=(),
        risk_flags=(),
        contract_versions=IntentPlanContractVersions(
            normalizer_version="normalizer-v1",
            cache_schema_version=1,
            planner_contract_version="planner-v1",
            catalog_version=3,
            canonical_text_registry_version="intent-text-v1",
            materializer_version="materializer-v1",
        ),
    )


MINIMAL_GOLDEN = (
    b'{"contract_versions":{"cache_schema_version":1,'
    b'"canonical_text_registry_version":"intent-text-v1","catalog_version":3,'
    b'"materializer_version":"materializer-v1",'
    b'"normalizer_version":"normalizer-v1",'
    b'"planner_contract_version":"planner-v1"},'
    b'"draft_mode":"new_workflow","edit_placement":null,'
    b'"integration_actions":[],"knowledge_placements":[],'
    b'"knowledge_requirements":[],"logical_steps":['
    b'{"capability":"start_input","occurrence":1},'
    b'{"capability":"answer","occurrence":1}],'
    b'"ordered_capabilities":["start_input","answer"],'
    b'"parameter_guidance_refs":[],"request_type":"new_workflow",'
    b'"risk_flags":[],"schema_version":1}'
)

FORBIDDEN_FIELDS = (
    "graph",
    "nodes",
    "edges",
    "position",
    "viewport",
    "workflow_id",
    "node_id",
    "edge_id",
    "request_id",
    "session_id",
    "operation_id",
    "credential",
    "credential_id",
    "credential_config",
    "secret",
    "token",
    "api_key",
    "password",
    "redis_url",
    "parameter_value",
    "actual_parameter_value",
    "explicit_parameter_value",
    "knowledge_base_id",
    "kb_id",
    "collection_id",
    "knowledge_base_name",
    "candidate_handle",
    "opaque_handle",
    "raw_provider_response",
    "raw_payload",
    "audit_payload",
    "intent_summary",
    "purpose",
    "reason",
    "input_guidance",
)


def _assert_error(call, code: str, path_category: str) -> IntentPlanCodecError:
    with pytest.raises(IntentPlanCodecError) as captured:
        call()
    error = captured.value
    assert error.code == code
    assert error.path_category == path_category
    assert str(error) == f"{code}:{path_category}"
    assert repr(error) == f"{code}:{path_category}"
    assert error.__cause__ is None
    assert error.__context__ is None
    return error


def test_codec_matches_literal_golden_and_round_trips_strict_tuples():
    codec = CanonicalIntentPlanCodec()
    plan = _plan("start_input", "answer")

    payload = codec.encode(plan, max_payload_bytes=4096)
    decoded = codec.decode(payload, max_payload_bytes=4096)

    assert payload == MINIMAL_GOLDEN
    assert decoded == plan
    assert isinstance(decoded.ordered_capabilities, tuple)
    assert isinstance(decoded.logical_steps, tuple)
    assert codec.encode(decoded, max_payload_bytes=4096) == payload


def test_codec_is_stable_for_model_construction_order_and_preserves_list_order():
    codec = CanonicalIntentPlanCodec()
    first = _plan("start_input", "llm", "answer")
    second = CachedIntentPlanV1.model_validate(
        dict(reversed(list(first.model_dump().items()))),
        strict=True,
    )
    reordered = _plan("start_input", "answer", "llm")

    assert codec.encode(first, 4096) == codec.encode(second, 4096)
    assert codec.encode(first, 4096) != codec.encode(reordered, 4096)


def test_codec_rejects_invalid_utf8_duplicate_nonfinite_and_non_object_json():
    codec = CanonicalIntentPlanCodec()

    _assert_error(
        lambda: codec.decode(b"\xff", 4096),
        "invalid_utf8",
        "root",
    )
    _assert_error(
        lambda: codec.decode(b'{"schema_version":1,"schema_version":1}', 4096),
        "invalid_json",
        "root",
    )
    _assert_error(
        lambda: codec.decode(b'{"schema_version":NaN}', 4096),
        "invalid_json",
        "root",
    )
    _assert_error(
        lambda: codec.decode(b"[]", 4096),
        "invalid_json",
        "root",
    )


def test_codec_rejects_oversized_unknown_version_and_noncanonical_payload():
    codec = CanonicalIntentPlanCodec()

    _assert_error(
        lambda: codec.decode(MINIMAL_GOLDEN, len(MINIMAL_GOLDEN) - 1),
        "payload_too_large",
        "payload_size",
    )
    _assert_error(
        lambda: codec.encode(_plan("start_input", "answer"), 8),
        "payload_too_large",
        "payload_size",
    )
    unknown_version = MINIMAL_GOLDEN.replace(
        b'"schema_version":1}', b'"schema_version":2}'
    )
    _assert_error(
        lambda: codec.decode(unknown_version, 4096),
        "unsupported_schema_version",
        "contract_version",
    )
    _assert_error(
        lambda: codec.decode(MINIMAL_GOLDEN + b" ", 4096),
        "non_canonical_payload",
        "root",
    )


@pytest.mark.parametrize(
    "field_name",
    FORBIDDEN_FIELDS,
)
@pytest.mark.parametrize(
    "location",
    ["root", "nested"],
)
def test_codec_decode_forbidden_field_corpus_is_fail_closed_and_redacted(
    field_name,
    location,
):
    codec = CanonicalIntentPlanCodec()
    unsafe_value = "synthetic-" + ("z" * 32)
    raw = json.loads(MINIMAL_GOLDEN)
    target = raw if location == "root" else raw["contract_versions"]
    target[field_name] = unsafe_value
    payload = json.dumps(
        raw,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    error = _assert_error(
        lambda: codec.decode(payload, 8192),
        "forbidden_cache_content",
        "cache_content",
    )
    rendered = str(error) + repr(error)
    assert unsafe_value not in rendered
    assert field_name not in rendered


@pytest.mark.parametrize("field_name", FORBIDDEN_FIELDS)
def test_codec_encode_forbidden_field_corpus_is_fail_closed(field_name):
    codec = CanonicalIntentPlanCodec()
    unsafe_plan_type = create_model(
        f"UnsafePlan_{field_name}",
        __base__=CachedIntentPlanV1,
        **{field_name: (str, ...)},
    )
    unsafe_plan = unsafe_plan_type(
        **_plan("start_input", "answer").model_dump(),
        **{field_name: "synthetic-forbidden-value"},
    )

    _assert_error(
        lambda: codec.encode(unsafe_plan, 8192),
        "forbidden_cache_content",
        "cache_content",
    )


@pytest.mark.parametrize(
    "uuid_value",
    [
        "123e4567-e89b-42d3-a456-426614174000",
        "01890f9a-7bcd-7def-8123-456789abcdef",
        "00000000-0000-0000-0000-000000000000",
    ],
)
def test_codec_rejects_uuid_values_independent_of_version(uuid_value):
    codec = CanonicalIntentPlanCodec()
    raw = json.loads(MINIMAL_GOLDEN)
    raw["contract_versions"]["normalizer_version"] = uuid_value
    payload = json.dumps(
        raw,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    plan = _plan("start_input", "answer").model_copy(
        update={
            "contract_versions": IntentPlanContractVersions(
                normalizer_version=uuid_value,
                cache_schema_version=1,
                planner_contract_version="planner-v1",
                catalog_version=3,
                canonical_text_registry_version="intent-text-v1",
                materializer_version="materializer-v1",
            )
        }
    )

    _assert_error(
        lambda: codec.decode(payload, 4096),
        "forbidden_cache_content",
        "cache_content",
    )
    _assert_error(
        lambda: codec.encode(plan, 4096),
        "forbidden_cache_content",
        "cache_content",
    )


def test_codec_encode_rejects_constructed_secret_like_content_without_echo():
    codec = CanonicalIntentPlanCodec()
    unsafe = "api_key=" + ("q" * 32)
    plan = _plan("start_input", "answer").model_copy(
        update={"risk_flags": (unsafe,)}
    )

    error = _assert_error(
        lambda: codec.encode(plan, 4096),
        "forbidden_cache_content",
        "cache_content",
    )
    assert unsafe not in str(error)
    assert "q" * 32 not in repr(error)


@pytest.mark.parametrize(
    "token_like_value",
    [
        "sk-synthetic-token-value",
        "ghp_synthetic_token_value",
        "xoxb-synthetic-token-value",
        "Bearer synthetic-token-value",
    ],
)
def test_codec_rejects_token_like_value_prefixes_on_encode_and_decode(
    token_like_value,
):
    codec = CanonicalIntentPlanCodec()
    raw = json.loads(MINIMAL_GOLDEN)
    raw["contract_versions"]["normalizer_version"] = token_like_value
    payload = json.dumps(
        raw,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    plan = _plan("start_input", "answer")
    unsafe_versions = plan.contract_versions.model_copy(
        update={"normalizer_version": token_like_value}
    )
    unsafe_plan = plan.model_copy(
        update={"contract_versions": unsafe_versions}
    )

    for call in (
        lambda: codec.encode(unsafe_plan, 4096),
        lambda: codec.decode(payload, 4096),
    ):
        error = _assert_error(
            call,
            "forbidden_cache_content",
            "cache_content",
        )
        rendered = str(error) + repr(error)
        assert token_like_value not in rendered


@pytest.mark.parametrize(
    "plan",
    [
        _plan("start_input", "answer").model_copy(
            update={"risk_flags": ("benign_unknown",)}
        ),
        create_model(
            "ExtendedIntentPlan",
            __base__=CachedIntentPlanV1,
            extension=(str, ...),
        )(
            **_plan("start_input", "answer").model_dump(),
            extension="unexpected-but-safe",
        ),
    ],
)
def test_codec_encode_rejects_typed_values_that_cannot_round_trip(plan):
    _assert_error(
        lambda: CanonicalIntentPlanCodec().encode(plan, 4096),
        "invalid_plan_schema",
        "payload_shape",
    )


def test_codec_converts_excessive_json_nesting_to_typed_failure():
    depth = 500
    payload = (
        '{"schema_version":1,"unexpected":'
        + ("[" * depth)
        + "0"
        + ("]" * depth)
        + "}"
    ).encode("utf-8")

    _assert_error(
        lambda: CanonicalIntentPlanCodec().decode(payload, 4096),
        "invalid_json",
        "root",
    )


def test_codec_classifies_reference_schema_failure_without_input_echo():
    codec = CanonicalIntentPlanCodec()
    payload = MINIMAL_GOLDEN.replace(
        b'"normalizer-v1"',
        b'"INVALID NORMALIZER VALUE"',
    )

    error = _assert_error(
        lambda: codec.decode(payload, 4096),
        "invalid_plan_schema",
        "reference",
    )
    assert "INVALID NORMALIZER VALUE" not in str(error)


def test_codec_error_rejects_unknown_code_path_pair_and_is_final():
    allowed_pairs = {
        ("payload_too_large", "payload_size"),
        ("invalid_utf8", "root"),
        ("invalid_json", "root"),
        ("unsupported_schema_version", "contract_version"),
        ("forbidden_cache_content", "cache_content"),
        ("invalid_plan_schema", "reference"),
        ("invalid_plan_schema", "payload_shape"),
        ("non_canonical_payload", "root"),
    }
    for code, path_category in allowed_pairs:
        error = IntentPlanCodecError(code, path_category)
        assert str(error) == f"{code}:{path_category}"
        assert repr(error) == f"{code}:{path_category}"
        assert error.__cause__ is None
        assert error.__context__ is None

    with pytest.raises(ValueError):
        IntentPlanCodecError("invalid_utf8", "payload_size")
    with pytest.raises(TypeError):

        class DerivedIntentPlanCodecError(IntentPlanCodecError):
            pass
