"""초기 자동 모델 라우팅에서 사용할 짧은 Judge 호출 경계.

Judge는 실제 요청을 실행하기 전에 현재 실행 주체가 사용할 수 있는 후보 안에서
모델 하나를 고른다. 이 모듈은 응답을 엄격히 검증하고, trace/DB에 남길 수 있는
안전한 메타데이터만 만든다. 원문 입력이나 prompt는 반환하거나 저장하지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol


class RuntimeJudgeResponseError(ValueError):
    """Judge가 계약 밖의 응답을 반환했을 때 사용하는 오류다."""


class RuntimeJudgeClient(Protocol):
    def invoke_sync(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RuntimeJudgeDecision:
    selected_model_id: str | None
    required_difficulty: str | None
    difficulty_score: int | None
    confidence: float
    reason_short: str | None
    reason_code: str
    usage: dict[str, Any]

    def safe_metadata(self) -> dict[str, Any]:
        """원문 없이 trace에 남길 Judge 판단 요약이다."""

        metadata = {
            "confidence": self.confidence,
            "reason_code": self.reason_code,
            "usage": dict(self.usage),
        }
        if self.selected_model_id:
            metadata["selected_model"] = self.selected_model_id
        if self.required_difficulty:
            metadata["required_difficulty"] = self.required_difficulty
        if self.difficulty_score is not None:
            metadata["difficulty_score"] = self.difficulty_score
        if self.reason_short:
            metadata["reason_short"] = self.reason_short
        return metadata


@dataclass(frozen=True)
class CatalogSelection:
    selected_model_id: str | None
    eligible_model_count: int
    required_quality_floor: float | None


class ModelRoutingRuntimeJudge:
    """초기 표본을 만들기 위한 runtime Judge.

    모델 능력의 절대 순위를 추측하지 않는다. 현재 노드 계약과 렌더된 요청을 보고
    *지금 실행 주체가 실제로 쓸 수 있는 후보* 중 하나만 선택하게 한다.
    """

    MAX_FEATURE_CHARS = 3_000
    # Judge 비용 상한은 제품 설정으로 정한 256 token을 유지한다.
    MAX_OUTPUT_TOKENS = 256
    MIN_CONFIDENCE_FOR_CATALOG_SELECTION = 0.65
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
    def confidence_allows_catalog_selection(cls, confidence: float) -> bool:
        """Judge가 충분히 확신할 때만 점수 기반 모델 교체를 허용한다."""

        return confidence >= cls.MIN_CONFIDENCE_FOR_CATALOG_SELECTION

    @classmethod
    def decide(
        cls,
        *,
        client: RuntimeJudgeClient,
        candidate_model_ids: list[str],
        routing_feature_text: str,
        rag_context: dict[str, Any] | None = None,
        candidate_profiles: list[dict[str, Any]] | None = None,
    ) -> RuntimeJudgeDecision:
        candidates = cls._normalized_candidates(candidate_model_ids)
        if not candidates:
            raise RuntimeJudgeResponseError("no candidate models")

        request_kwargs = {
            "temperature": 0,
            "max_tokens": cls.MAX_OUTPUT_TOKENS,
            "response_format": {"type": "json_object"},
        }
        try:
            response = client.invoke_sync(
                messages=cls._messages(
                    candidate_model_ids=candidates,
                    routing_feature_text=routing_feature_text,
                    rag_context=rag_context,
                    candidate_profiles=candidate_profiles,
                ),
                **request_kwargs,
            )
        except Exception as exc:
            # GPT-5.4 계열은 minimal effort를 지원하지 않아 256 token 안에서
            # 내부 추론을 끝내지 못할 수 있다. 동일 한도에서 한 번만 더 짧은
            # 계약으로 재시도한다. 정상 요청에는 추가 호출이 없다.
            if str(getattr(exc, "reason_code", "")) not in cls._RETRYABLE_PROVIDER_REASON_CODES:
                raise
            response = client.invoke_sync(
                messages=cls._retry_messages(
                    routing_feature_text=routing_feature_text,
                    rag_context=rag_context,
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
        required_difficulty = str(payload.get("required_difficulty") or "").strip() or None
        raw_difficulty_score = payload.get("difficulty_score")
        difficulty_score: int | None = None
        if raw_difficulty_score is not None:
            if isinstance(raw_difficulty_score, bool):
                raise RuntimeJudgeResponseError("invalid difficulty score")
            try:
                difficulty_score = int(raw_difficulty_score)
            except (TypeError, ValueError) as exc:
                raise RuntimeJudgeResponseError("invalid difficulty score") from exc
            if not 0 <= difficulty_score <= 100:
                raise RuntimeJudgeResponseError("difficulty score must be between 0 and 100")
        reason_code = str(payload.get("reason_code") or "judge_selected").strip()[:80]
        reason_short = str(payload.get("reason_short") or "").strip() or None
        if reason_short is None:
            reason_short = cls._REASON_SHORT_BY_CODE.get(reason_code)
        if difficulty_score is not None:
            if not reason_short or len(reason_short) > 14 or not any("가" <= char <= "힣" for char in reason_short):
                raise RuntimeJudgeResponseError("invalid short reason")
        if selected_model_id and selected_model_id not in candidates:
            raise RuntimeJudgeResponseError("unavailable model selected by judge")
        if not selected_model_id and difficulty_score is None and required_difficulty not in {"economy", "balanced", "advanced"}:
            raise RuntimeJudgeResponseError("invalid required difficulty")
        try:
            confidence = float(payload.get("confidence"))
        except (TypeError, ValueError) as exc:
            raise RuntimeJudgeResponseError("invalid confidence") from exc
        if not 0.0 <= confidence <= 1.0:
            raise RuntimeJudgeResponseError("confidence must be between 0 and 1")

        return RuntimeJudgeDecision(
            selected_model_id=selected_model_id,
            required_difficulty=(
                required_difficulty
                if required_difficulty in {"economy", "balanced", "advanced"}
                else cls._difficulty_band(difficulty_score)
            ),
            difficulty_score=difficulty_score,
            confidence=confidence,
            reason_short=reason_short,
            reason_code=reason_code,
            usage=cls._safe_usage(response.get("usage") if isinstance(response, dict) else None),
        )

    @staticmethod
    def select_catalog_candidate(
        candidate_profiles: list[dict[str, Any]],
        *,
        difficulty_score: int | None,
        required_difficulty: str | None = None,
    ) -> CatalogSelection:
        """점수에 필요한 품질을 만족하는 가장 저렴한 실행 가능 후보를 고른다.

        Judge는 난이도만 판단한다. 모델 선택은 저장된 공개 카탈로그 수치로
        결정해, 짧은 Judge 응답 예산이 모델별 가격·품질 비교에 소모되지 않게 한다.
        """

        if difficulty_score is None:
            legacy_scores = {"economy": 20, "balanced": 50, "advanced": 80}
            difficulty_score = legacy_scores.get(required_difficulty or "")
        if difficulty_score is None:
            return CatalogSelection(None, 0, None)
        threshold = 0.70 + (float(difficulty_score) / 100.0) * 0.20

        eligible: list[tuple[float, float, str]] = []
        for profile in candidate_profiles:
            model_id = str(profile.get("model_id") or "").strip()
            quality = profile.get("quality_by_difficulty")
            if not model_id or not isinstance(quality, dict):
                continue
            expected_quality = ModelRoutingRuntimeJudge._quality_at_score(
                quality,
                difficulty_score,
            )
            if expected_quality is None or expected_quality < threshold:
                continue
            input_price = profile.get("input_price_per_1k")
            output_price = profile.get("output_price_per_1k")
            if not isinstance(input_price, (int, float)) or not isinstance(output_price, (int, float)):
                continue
            fallback_rate = profile.get("fallback_rate")
            eligible.append(
                (
                    float(input_price) + float(output_price),
                    float(fallback_rate) if isinstance(fallback_rate, (int, float)) else 1.0,
                    model_id,
                )
            )
        return CatalogSelection(
            selected_model_id=min(eligible)[2] if eligible else None,
            eligible_model_count=len(eligible),
            required_quality_floor=round(threshold, 3),
        )

    @staticmethod
    def _difficulty_band(score: int | None) -> str | None:
        if score is None:
            return None
        if score < 35:
            return "economy"
        if score < 65:
            return "balanced"
        return "advanced"

    @staticmethod
    def _quality_at_score(
        quality_by_difficulty: dict[str, Any],
        difficulty_score: int,
    ) -> float | None:
        values = []
        for key in ("economy", "balanced", "advanced"):
            value = quality_by_difficulty.get(key)
            if not isinstance(value, (int, float)):
                return None
            values.append(float(value))
        economy, balanced, advanced = values
        if difficulty_score <= 50:
            return economy + (balanced - economy) * (difficulty_score / 50.0)
        return balanced + (advanced - balanced) * ((difficulty_score - 50) / 50.0)

    @classmethod
    def _messages(
        cls,
        *,
        candidate_model_ids: list[str],
        routing_feature_text: str,
        rag_context: dict[str, Any] | None,
        candidate_profiles: list[dict[str, Any]] | None,
    ) -> list[dict[str, str]]:
        # 후보 모델은 Judge 응답이 아니라 호출한 코드가 카탈로그 수치로 고른다.
        # 인자를 남겨 둬 기존 호출부와의 호환성은 유지한다.
        del candidate_model_ids, candidate_profiles
        instruction = (
            "당신은 워크플로우 LLM 요청 난이도 Judge입니다. 현재 요청, 렌더된 프롬프트, "
            "출력 제약과 실제 RAG 검색량을 보고 필요한 난이도를 0~100 정수로 점수화하세요. "
            "모델을 고르거나 가격을 추정하지 마세요. 0은 짧고 단순한 변환·분류·안내이고, "
            "50은 여러 조건을 종합하는 일반 업무, 100은 높은 정확도·안전성·다단계 추론·충돌 근거 판단입니다. "
            "문장이 짧거나 JSON 출력이어도, 그 분류·추천이 되돌리기 어려운 변경, 금전·권한·법적 판단, "
            "안전 조치 또는 상충하는 근거의 다음 결정을 좌우하면 70점 이상으로 평가하세요. "
            "반대로 답이 정해진 단순 안내나 절차 설명은 30점 이하입니다. "
            "reason_short에는 판단 이유를 한국어 8~14자로만 작성하세요. "
            "반드시 JSON object 하나만 반환하세요: "
            '{"difficulty_score":58,"confidence":0.0,'
            '"reason_short":"여러 조건 종합","reason_code":"balanced_quality"}.'
        )
        body = {
            "request_feature": str(routing_feature_text or "")[: cls.MAX_FEATURE_CHARS],
            "rag_context": cls._safe_rag_context(rag_context),
        }
        return [
            {"role": "system", "content": instruction},
            {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
        ]

    @classmethod
    def _retry_messages(
        cls,
        *,
        routing_feature_text: str,
        rag_context: dict[str, Any] | None,
    ) -> list[dict[str, str]]:
        """응답 미완료 때만 쓰는 최소 Judge 계약이다."""

        instruction = (
            "요청 난이도를 0~100으로 평가하세요. 모델 선택 금지. "
            "JSON 하나만 반환: {\"difficulty_score\":0,\"confidence\":0.0,"
            "\"reason_code\":\"simple_response|multi_constraint|evidence_synthesis|"
            "structured_precision|high_risk_reasoning|ambiguous_request|long_context\"}."
        )
        body = {
            "request_feature": str(routing_feature_text or "")[: cls._RETRY_FEATURE_CHARS],
            "rag_context": cls._safe_rag_context(rag_context),
        }
        return [
            {"role": "system", "content": instruction},
            {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
        ]

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
            if capability_tier in {"economy", "balanced", "high"}:
                safe["capability_tier"] = capability_tier
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
            result.append(safe)
        return result

    @staticmethod
    def _compact_candidate_profiles(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """256-token Judge budget을 위해 반복 키를 제거한 호출 전용 표현이다."""

        compact: list[dict[str, Any]] = []
        for profile in profiles:
            row: dict[str, Any] = {"id": profile["model_id"]}
            input_price = profile.get("input_price_per_1k")
            output_price = profile.get("output_price_per_1k")
            if isinstance(input_price, (int, float)) and isinstance(output_price, (int, float)):
                row["cost"] = [input_price, output_price]
            quality = profile.get("quality_by_difficulty")
            if isinstance(quality, dict):
                row["quality"] = [
                    quality.get("economy"),
                    quality.get("balanced"),
                    quality.get("advanced"),
                ]
            latency = profile.get("expected_latency_ms_by_input_profile")
            if isinstance(latency, dict):
                row["latency_ms"] = [
                    latency.get("short"),
                    latency.get("medium"),
                    latency.get("long"),
                ]
            if isinstance(profile.get("fallback_rate"), (int, float)):
                row["fallback_rate"] = profile["fallback_rate"]
            if isinstance(profile.get("capability_tier"), str):
                row["tier"] = profile["capability_tier"]
            compact.append(row)
        return compact

    @staticmethod
    def _normalized_candidates(candidate_model_ids: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for model_id in candidate_model_ids:
            normalized = str(model_id or "").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result

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
