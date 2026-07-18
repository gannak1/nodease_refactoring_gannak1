"""초기 자동 모델 라우팅에서 사용할 짧은 Judge 호출 경계.

Judge는 실제 요청을 실행하기 전에 현재 실행 주체가 사용할 수 있는 후보 안에서
모델 하나를 고른다. 이 모듈은 응답을 엄격히 검증하고, trace/DB에 남길 수 있는
안전한 메타데이터만 만든다. 원문 입력이나 prompt는 반환하거나 저장하지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from apps.shared.services.model_routing_global_profile_catalog import (
    deduplicate_model_routing_ids,
)


class RuntimeJudgeResponseError(ValueError):
    """Judge가 계약 밖의 응답을 반환했을 때 사용하는 오류다."""


class RuntimeJudgeClient(Protocol):
    def invoke_sync(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RuntimeJudgeDecision:
    selected_model_id: str | None
    confidence: float
    reason_short: str | None
    reason_code: str
    usage: dict[str, Any]
    decision_detail: dict[str, Any] | None = None

    def safe_metadata(self) -> dict[str, Any]:
        """원문 없이 trace에 남길 Judge 판단 요약이다."""

        metadata = {
            "confidence": self.confidence,
            "reason_code": self.reason_code,
            "usage": dict(self.usage),
        }
        if self.selected_model_id:
            metadata["selected_model"] = self.selected_model_id
        if self.reason_short:
            metadata["reason_short"] = self.reason_short
        return metadata


class ModelRoutingRuntimeJudge:
    """초기 표본을 만들기 위한 runtime Judge.

    모델 능력의 절대 순위를 추측하지 않는다. 현재 노드 계약과 렌더된 요청을 보고
    *지금 실행 주체가 실제로 쓸 수 있는 후보* 중 하나만 선택하게 한다.
    """

    MAX_FEATURE_CHARS = 3_000
    # Judge가 후보 비교와 짧은 선택 근거를 함께 끝낼 수 있도록 둔 상한이다.
    MAX_OUTPUT_TOKENS = 512
    # 진단은 후보별 제외 근거까지 반환하므로 운영 경로와 별도 예산을 사용한다.
    DIAGNOSTIC_MAX_OUTPUT_TOKENS = 2_000
    _RETRY_FEATURE_CHARS = 1_200
    _RETRYABLE_PROVIDER_REASON_CODES = {"responses_incomplete"}
    _REASON_SHORT_BY_CODE = {
        "simple_response": "단순 응답 처리",
        "multi_constraint": "여러 조건 종합",
        "evidence_synthesis": "근거 종합 판단",
        "structured_precision": "정확한 형식 필요",
        "high_risk_reasoning": "고위험 판단 필요",
        "ambiguous_request": "모호한 요청 해석",
        "long_context": "긴 문맥 종합",
    }

    @classmethod
    def decide(
        cls,
        *,
        client: RuntimeJudgeClient,
        candidate_model_ids: list[str],
        routing_feature_text: str,
        rag_context: dict[str, Any] | None = None,
        candidate_profiles: list[dict[str, Any]] | None = None,
        diagnostic_mode: bool = False,
    ) -> RuntimeJudgeDecision:
        candidates = cls._normalized_candidates(candidate_model_ids)
        if not candidates:
            raise RuntimeJudgeResponseError("no candidate models")

        request_kwargs = {
            "temperature": 0,
            "max_tokens": (
                cls.DIAGNOSTIC_MAX_OUTPUT_TOKENS
                if diagnostic_mode
                else cls.MAX_OUTPUT_TOKENS
            ),
            "response_format": {"type": "json_object"},
        }
        try:
            response = client.invoke_sync(
                messages=cls._messages(
                    candidate_model_ids=candidates,
                    routing_feature_text=routing_feature_text,
                    rag_context=rag_context,
                    candidate_profiles=candidate_profiles,
                    diagnostic_mode=diagnostic_mode,
                ),
                **request_kwargs,
            )
        except Exception as exc:
            # GPT-5.4 계열은 internal reasoning을 끝내지 못할 수 있다. 동일 한도에서 한 번만 더 짧은
            # 계약으로 재시도한다. 정상 요청에는 추가 호출이 없다.
            if str(getattr(exc, "reason_code", "")) not in cls._RETRYABLE_PROVIDER_REASON_CODES:
                raise
            response = client.invoke_sync(
                messages=cls._retry_messages(
                    candidate_model_ids=candidates,
                    routing_feature_text=routing_feature_text,
                    rag_context=rag_context,
                    candidate_profiles=candidate_profiles,
                    diagnostic_mode=diagnostic_mode,
                ),
                **request_kwargs,
            )
        content = cls._response_content(response)
        try:
            payload = json.loads(content)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeJudgeResponseError("invalid JSON response") from exc
        if not isinstance(payload, dict):
            raise RuntimeJudgeResponseError("response must be an object")

        selected_model_id = str(payload.get("selected_model_id") or "").strip() or None
        reason_code = str(payload.get("reason_code") or "judge_selected").strip()[:80]
        reason_short = str(payload.get("reason_short") or "").strip() or None
        if reason_short is None:
            reason_short = cls._REASON_SHORT_BY_CODE.get(reason_code)
        if not selected_model_id:
            raise RuntimeJudgeResponseError("selected model is missing")
        if selected_model_id not in candidates:
            raise RuntimeJudgeResponseError("unavailable model selected by judge")
        if not reason_short or len(reason_short) > 14 or not any("가" <= char <= "힣" for char in reason_short):
            raise RuntimeJudgeResponseError("invalid short reason")
        try:
            confidence = float(payload.get("confidence"))
        except (TypeError, ValueError) as exc:
            raise RuntimeJudgeResponseError("invalid confidence") from exc
        if not 0.0 <= confidence <= 1.0:
            raise RuntimeJudgeResponseError("confidence must be between 0 and 1")
        decision_detail = (
            cls._safe_decision_detail(
                payload.get("decision_detail"),
                candidates,
                selected_model_id=selected_model_id,
            )
            if diagnostic_mode
            else None
        )

        return RuntimeJudgeDecision(
            selected_model_id=selected_model_id,
            confidence=confidence,
            reason_short=reason_short,
            reason_code=reason_code,
            usage=cls._safe_usage(response.get("usage") if isinstance(response, dict) else None),
            decision_detail=decision_detail,
        )

    @classmethod
    def _messages(
        cls,
        *,
        candidate_model_ids: list[str],
        routing_feature_text: str,
        rag_context: dict[str, Any] | None,
        candidate_profiles: list[dict[str, Any]] | None,
        diagnostic_mode: bool = False,
    ) -> list[dict[str, str]]:
        candidate_profiles = cls._compact_candidate_profiles(
            cls._safe_candidate_profiles(candidate_model_ids, candidate_profiles)
        )
        instruction = (
            "당신은 워크플로우 LLM 모델 선택 Judge입니다. 현재 요청과 실제 RAG 검색량을 보고 "
            "candidate_models 중 정확히 하나를 selected_model_id로 고르세요. 기본 모델과 fallback 모델은 고려하지 않습니다. "
            "CURRENT_REQUEST는 이번 실행에서 달라지는 난이도 판단의 주된 근거입니다. NODE_TASK_CONTRACT는 이 노드가 허용하는 출력·역할의 고정 경계일 뿐이므로, "
            "고정 계약의 주제나 단어만으로 이번 요청의 난이도를 단정하지 마세요. "
            "먼저 이 요청의 내용과 실제 RAG 검색량을 바탕으로 필요한 능력 수준을 내부적으로 판단하세요. 반드시 다음 세 축을 서로 독립적으로 평가한 뒤, "
            "가장 높은 필요 수준에 맞는 후보를 선택하세요. 첫째, 작업 복잡도는 지시·조건·예외가 몇 개이며 서로 의존하는지, 여러 단계를 거쳐 결론을 내야 하는지를 봅니다. "
            "둘째, 결정 영향도는 모델 출력이 실제 승인·거절·변경·약속·집행처럼 되돌리기 어려운 행동 또는 중요한 판단을 직접 결정하는지를 봅니다. "
            "셋째, 근거 종합 범위는 긴 검색 근거, 여러 출처, 서로 충돌하는 정보, 누락된 정보를 비교·해석해야 하는지를 봅니다. "
            "특정 업무 분야의 단어만으로 고성능 모델을 고르면 안 됩니다. 같은 주제라도 정해진 절차를 안내하거나 값을 추출·분류하는 요청은 낮은 능력으로 충분할 수 있고, "
            "반대로 짧은 요청이라도 여러 제약을 풀거나 실제 결정을 내려야 하면 높은 능력이 필요할 수 있습니다. 문장이 짧거나 JSON 출력이라는 이유만으로 저성능 모델을 선택해서도 안 됩니다. "
            "고성능 모델은 충돌·누락된 근거를 해석해야 하거나, 여러 조건과 예외를 단계적으로 해결해야 하거나, 출력이 중요한 결정을 직접 좌우하는 경우에 선택하세요. "
            "세 축을 각각 0(없음)부터 3(높음)까지 내부적으로 채점하되, 이 점수로 economy·balanced·advanced 중 하나를 기계적으로 먼저 고르지 마세요. "
            "후보마다 필요한 능력과 실제 계약 성적을 직접 비교해, 이번 요청을 안정적으로 수행할 최소 충분 후보 하나를 선택하세요. "
            "후보 목록의 순서, 모델 ID의 숫자, capability_tier 하나만으로 선택하지 말고 모든 후보를 비교하세요. capability_tier는 약한 사전 정보일 뿐이며, 가격·지연·실패율은 필요한 능력을 만족하는 후보들 사이에서만 비교하세요. "
            "candidate_models의 capability_tier와 official_position은 provider가 공개한 역할 구분을 구조화한 약한 사전 정보이며, 측정된 품질·지연·실패율이 아닙니다. "
            "공급자 공식 특화 태그는 약한 사전 정보입니다. 요청에 실제로 필요한 능력과 태그가 직접 맞을 때만 사용하고, 일반 전문 업무 능력과 전문 추론 능력을 같은 것으로 취급하지 마세요. "
            "예를 들어 전문 업무 전반에 맞는 후보와 수학·과학·코드의 다단계 추론에 특화된 후보가 모두 있으면, 단순히 둘 다 advanced라는 이유로 같은 후보처럼 보지 마세요. "
            "model_role이 reasoning_specialist인 후보는 형식 논증이나 다단계 추론 자체가 핵심일 때 우선 검토하고, 전문 문서 작성·종합 결과물처럼 폭넓은 업무 완성도가 핵심이면 frontier_generalist를 우선 검토하세요. "
            "quality_for_*와 latency_ms_for_*가 있는 경우에만 Nodease가 별도로 보유한 사전 측정치입니다. "
            "candidate_models의 operational_*은 실제 배포 실행에서 나온 workflow 계약 성적입니다. "
            "operational_run_count가 5건 이상이면, schema·후속 노드 성공률이 낮거나 fallback 비율이 높은 후보를 "
            "카탈로그 사전 품질값이 높더라도 우선 선택하지 마세요. 표본이 5건 미만이면 실제 성적은 참고만 하고 카탈로그를 약한 사전 정보로 사용하세요. "
            "reason_short에는 판단 이유를 한국어 8~14자로만 작성하세요. "
            "반드시 JSON object 하나만 반환하세요: "
            '{"selected_model_id":"candidate id","confidence":0.0,'
            '"reason_short":"여러 조건 종합","reason_code":"balanced_quality"}.'
        )
        if diagnostic_mode:
            instruction += (
                " 진단 모드입니다. 아래 JSON 구조를 빠짐없이 반환하세요. 특히 "
                "candidate_comparison에는 candidate_models의 모든 id를 각각 한 번씩 넣어야 합니다. "
                "요청 원문을 반복하지 말고 후보별 능력 적합성만 간단히 설명하세요: "
                '{"selected_model_id":"candidate id","confidence":0.0,'
                '"reason_short":"여러 조건 종합","reason_code":"balanced_quality",'
                '"decision_detail":{"task_assessment":"한 문장 판단",'
                '"difficulty_analysis":{"overall_level":"low|medium|high",'
                '"task_complexity":0,"decision_impact":0,"evidence_synthesis":0,'
                '"reason":"난이도 판단 근거"},'
                '"selection_explanation":"선택 모델이 다른 후보보다 적합한 구체적 이유",'
                '"candidate_comparison":[{"model_id":"candidate id",'
                '"decision":"selected|not_selected","reason":"짧은 이유"}]}}.'
            )
        body = {
            "request_feature": str(routing_feature_text or "")[: cls.MAX_FEATURE_CHARS],
            "rag_context": cls._safe_rag_context(rag_context),
            "candidate_models": candidate_profiles,
        }
        return [
            {"role": "system", "content": instruction},
            {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
        ]

    @classmethod
    def _retry_messages(
        cls,
        *,
        candidate_model_ids: list[str],
        routing_feature_text: str,
        rag_context: dict[str, Any] | None,
        candidate_profiles: list[dict[str, Any]] | None,
        diagnostic_mode: bool = False,
    ) -> list[dict[str, str]]:
        """응답 미완료 때만 쓰는 최소 Judge 계약이다."""

        instruction = (
            "candidate_models 중 요청 유형과 필요한 추론 수준에 가장 합리적인 모델 하나를 고르세요. "
            "고성능 모델은 고위험 판단·복수 근거 종합·다단계 추론일 때만 선택하세요. "
            "JSON 하나만 반환: {\"selected_model_id\":\"id\",\"confidence\":0.0,"
            "\"reason_code\":\"simple_response|multi_constraint|evidence_synthesis|"
            "structured_precision|high_risk_reasoning|ambiguous_request|long_context\"}."
        )
        if diagnostic_mode:
            instruction += (
                " decision_detail도 포함하세요: task_assessment 한 문장, "
                "difficulty_analysis(overall_level, task_complexity, decision_impact, evidence_synthesis, reason), "
                "selection_explanation, 모든 후보의 model_id, decision(selected|not_selected), reason."
            )
        body = {
            "request_feature": str(routing_feature_text or "")[: cls._RETRY_FEATURE_CHARS],
            "rag_context": cls._safe_rag_context(rag_context),
            "candidate_models": cls._compact_candidate_profiles(
                cls._safe_candidate_profiles(candidate_model_ids, candidate_profiles)
            ),
        }
        return [
            {"role": "system", "content": instruction},
            {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
        ]

    @staticmethod
    def _safe_decision_detail(
        value: Any,
        candidates: list[str],
        *,
        selected_model_id: str,
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise RuntimeJudgeResponseError("diagnostic decision detail is missing")
        task_assessment = str(value.get("task_assessment") or "").strip()
        difficulty_analysis = value.get("difficulty_analysis")
        selection_explanation = str(value.get("selection_explanation") or "").strip()
        comparisons = value.get("candidate_comparison")
        if not task_assessment or len(task_assessment) > 240:
            raise RuntimeJudgeResponseError("invalid diagnostic task assessment")
        if not isinstance(difficulty_analysis, dict):
            raise RuntimeJudgeResponseError("diagnostic difficulty analysis is missing")
        overall_level = str(difficulty_analysis.get("overall_level") or "").strip()
        if overall_level not in {"low", "medium", "high"}:
            raise RuntimeJudgeResponseError("invalid diagnostic difficulty level")
        safe_difficulty: dict[str, Any] = {"overall_level": overall_level}
        for key in ("task_complexity", "decision_impact", "evidence_synthesis"):
            value = difficulty_analysis.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 3:
                raise RuntimeJudgeResponseError("invalid diagnostic difficulty score")
            safe_difficulty[key] = value
        difficulty_reason = str(difficulty_analysis.get("reason") or "").strip()
        if not difficulty_reason or len(difficulty_reason) > 240:
            raise RuntimeJudgeResponseError("invalid diagnostic difficulty reason")
        safe_difficulty["reason"] = difficulty_reason
        if not selection_explanation or len(selection_explanation) > 240:
            raise RuntimeJudgeResponseError("invalid diagnostic selection explanation")
        if not isinstance(comparisons, list) or not comparisons:
            raise RuntimeJudgeResponseError("diagnostic candidate comparison is missing")

        safe_comparisons: list[dict[str, str]] = []
        seen_model_ids: set[str] = set()
        for comparison in comparisons[: len(candidates)]:
            if not isinstance(comparison, dict):
                raise RuntimeJudgeResponseError("invalid diagnostic candidate comparison")
            model_id = str(comparison.get("model_id") or "").strip()
            decision = str(comparison.get("decision") or "").strip()
            reason = str(comparison.get("reason") or "").strip()
            if model_id not in candidates or model_id in seen_model_ids:
                raise RuntimeJudgeResponseError("invalid diagnostic candidate model")
            if decision not in {"selected", "not_selected"}:
                raise RuntimeJudgeResponseError("invalid diagnostic candidate decision")
            if not reason or len(reason) > 240:
                raise RuntimeJudgeResponseError("invalid diagnostic candidate reason")
            seen_model_ids.add(model_id)
            safe_comparisons.append(
                {"model_id": model_id, "decision": decision, "reason": reason}
            )
        if seen_model_ids != set(candidates):
            raise RuntimeJudgeResponseError("incomplete diagnostic candidate comparison")
        selected = [
            row["model_id"]
            for row in safe_comparisons
            if row["decision"] == "selected"
        ]
        if selected != [selected_model_id]:
            raise RuntimeJudgeResponseError("diagnostic selection does not match selected model")
        return {
            "task_assessment": task_assessment,
            "difficulty_analysis": safe_difficulty,
            "selection_explanation": selection_explanation,
            "candidate_comparison": safe_comparisons,
        }

    @staticmethod
    def _safe_rag_context(value: dict[str, Any] | None) -> dict[str, Any]:
        """Judge에 KB 원문 없이 실제 검색량만 전달한다."""

        if not isinstance(value, dict) or not bool(value.get("used")):
            return {"used": False}

        safe: dict[str, Any] = {"used": True}
        for key in (
            "retrieved_context_token_estimate",
            "retrieved_context_chars",
            "retrieved_chunk_count",
            "source_count",
        ):
            raw_value = value.get(key)
            if isinstance(raw_value, int) and raw_value >= 0:
                safe[key] = raw_value
        if isinstance(value.get("evidence_sufficient"), bool):
            safe["evidence_sufficient"] = value["evidence_sufficient"]
        return safe

    @staticmethod
    def _safe_candidate_profiles(
        candidate_model_ids: list[str],
        profiles: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        """현재 실행 주체가 쓸 수 있는 후보의 비밀 없는 카탈로그만 남긴다."""

        profile_by_model_id: dict[str, dict[str, Any]] = {}
        for profile in profiles or []:
            if not isinstance(profile, dict):
                continue
            model_id = str(profile.get("model_id") or "").strip()
            if model_id:
                profile_by_model_id[model_id] = profile

        result: list[dict[str, Any]] = []
        for model_id in candidate_model_ids:
            raw = profile_by_model_id.get(model_id, {})
            safe: dict[str, Any] = {"model_id": model_id}
            for key in ("input_price_per_1k", "output_price_per_1k"):
                value = raw.get(key)
                if isinstance(value, (int, float)) and value >= 0:
                    safe[key] = float(value)
            context_window = raw.get("context_window")
            if isinstance(context_window, int) and context_window > 0:
                safe["context_window"] = context_window
            capability_tier = raw.get("capability_tier")
            if capability_tier in {"economy", "balanced", "advanced"}:
                safe["capability_tier"] = capability_tier
            official_position = raw.get("official_position")
            if isinstance(official_position, str) and official_position:
                safe["official_position"] = official_position[:80]
            model_role = raw.get("model_role")
            if model_role in {
                "efficient_generalist",
                "balanced_generalist",
                "non_reasoning_generalist",
                "frontier_generalist",
                "reasoning_generalist",
                "reasoning_specialist",
                "general_purpose",
            }:
                safe["model_role"] = model_role
            canonical_model_id = raw.get("canonical_model_id")
            if isinstance(canonical_model_id, str) and canonical_model_id:
                safe["canonical_model_id"] = canonical_model_id[:120]
            evidence_type = raw.get("catalog_evidence_type") or raw.get("evidence_type")
            if evidence_type == "provider_documentation":
                safe["evidence_type"] = evidence_type
            specialization_tags = raw.get("specialization_tags")
            if isinstance(specialization_tags, list):
                safe_tags = [
                    tag[:80]
                    for tag in specialization_tags
                    if isinstance(tag, str) and tag
                ][:12]
                if safe_tags:
                    safe["specialization_tags"] = safe_tags
            catalog_lifecycle = raw.get("catalog_lifecycle")
            if catalog_lifecycle in {"listed", "preview"}:
                safe["catalog_lifecycle"] = catalog_lifecycle
            quality_by_difficulty = raw.get("quality_by_difficulty")
            if isinstance(quality_by_difficulty, dict):
                safe_quality = {
                    difficulty: float(value)
                    for difficulty, value in quality_by_difficulty.items()
                    if difficulty in {"economy", "balanced", "advanced"}
                    and isinstance(value, (int, float))
                    and 0.0 <= float(value) <= 1.0
                }
                if safe_quality:
                    safe["quality_by_difficulty"] = safe_quality
            expected_latency = raw.get("expected_latency_ms_by_input_profile")
            if isinstance(expected_latency, dict):
                safe_latency = {
                    profile: int(value)
                    for profile, value in expected_latency.items()
                    if profile in {"short", "medium", "long", "unknown"}
                    and isinstance(value, (int, float))
                    and int(value) > 0
                }
                if safe_latency:
                    safe["expected_latency_ms_by_input_profile"] = safe_latency
            fallback_rate = raw.get("fallback_rate")
            if isinstance(fallback_rate, (int, float)) and 0.0 <= float(fallback_rate) <= 1.0:
                safe["fallback_rate"] = float(fallback_rate)
            operational_run_count = raw.get("operational_run_count")
            if isinstance(operational_run_count, int) and operational_run_count >= 0:
                safe["operational_run_count"] = operational_run_count
            for key in (
                "operational_success_rate",
                "operational_schema_pass_rate",
                "operational_downstream_success_rate",
                "operational_fallback_rate",
            ):
                value = raw.get(key)
                if isinstance(value, (int, float)) and 0.0 <= float(value) <= 1.0:
                    safe[key] = float(value)
            result.append(safe)
        return result

    @staticmethod
    def _compact_candidate_profiles(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Judge가 추측하지 않도록 후보 지표를 이름 있는 값으로 전달한다."""

        compact: list[dict[str, Any]] = []
        for profile in profiles:
            row: dict[str, Any] = {"id": profile["model_id"]}
            input_price = profile.get("input_price_per_1k")
            output_price = profile.get("output_price_per_1k")
            if isinstance(input_price, (int, float)):
                row["input_price_per_1k"] = input_price
            if isinstance(output_price, (int, float)):
                row["output_price_per_1k"] = output_price
            for key in (
                "capability_tier",
                "official_position",
                "model_role",
                "catalog_lifecycle",
            ):
                value = profile.get(key)
                if isinstance(value, str) and value:
                    row[key] = value
            canonical_model_id = profile.get("canonical_model_id")
            if isinstance(canonical_model_id, str) and canonical_model_id:
                row["canonical_model_id"] = canonical_model_id
            evidence_type = profile.get("evidence_type")
            if evidence_type == "provider_documentation":
                row["evidence_type"] = evidence_type
            specialization_tags = profile.get("specialization_tags")
            if isinstance(specialization_tags, list) and specialization_tags:
                row["specialization_tags"] = specialization_tags
            quality = profile.get("quality_by_difficulty")
            if isinstance(quality, dict):
                for source_key, output_key in (
                    ("economy", "quality_for_routine"),
                    ("balanced", "quality_for_multi_constraint"),
                    ("advanced", "quality_for_complex_reasoning"),
                ):
                    value = quality.get(source_key)
                    if isinstance(value, (int, float)):
                        row[output_key] = value
            latency = profile.get("expected_latency_ms_by_input_profile")
            if isinstance(latency, dict):
                for source_key, output_key in (
                    ("short", "latency_ms_for_short_input"),
                    ("medium", "latency_ms_for_medium_input"),
                    ("long", "latency_ms_for_long_input"),
                ):
                    value = latency.get(source_key)
                    if isinstance(value, (int, float)):
                        row[output_key] = int(value)
            if isinstance(profile.get("fallback_rate"), (int, float)):
                row["fallback_rate"] = profile["fallback_rate"]
            operational_run_count = profile.get("operational_run_count")
            if isinstance(operational_run_count, int):
                row["operational_run_count"] = operational_run_count
            for key in (
                "operational_success_rate",
                "operational_schema_pass_rate",
                "operational_downstream_success_rate",
                "operational_fallback_rate",
            ):
                value = profile.get(key)
                if isinstance(value, (int, float)):
                    row[key] = value
            compact.append(row)
        return compact

    @staticmethod
    def _normalized_candidates(candidate_model_ids: list[str]) -> list[str]:
        return deduplicate_model_routing_ids(candidate_model_ids)

    @staticmethod
    def _response_content(response: Any) -> str:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeJudgeResponseError("response content is missing") from exc
        if not isinstance(content, str) or not content.strip():
            raise RuntimeJudgeResponseError("response content is empty")
        return content

    @staticmethod
    def _safe_usage(usage: Any) -> dict[str, Any]:
        if not isinstance(usage, dict):
            return {}
        return {
            key: value
            for key, value in usage.items()
            if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
            and isinstance(value, (int, float))
        }
