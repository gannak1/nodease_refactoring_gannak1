"""초기 자동 모델 라우팅에서 사용할 짧은 Judge 호출 경계.

Judge는 실제 요청을 실행하기 전에 현재 실행 주체가 사용할 수 있는 후보 안에서
모델 하나를 고른다. 이 모듈은 응답을 엄격히 검증하고, trace/DB에 남길 수 있는
안전한 메타데이터만 만든다. 원문 입력이나 prompt는 반환하거나 저장하지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


class RuntimeJudgeResponseError(ValueError):
    """Judge가 계약 밖의 응답을 반환했을 때 사용하는 오류다."""


class RuntimeJudgeClient(Protocol):
    def invoke_sync(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class RuntimeJudgeDecision:
    selected_model_id: str
    confidence: float
    reason_code: str
    usage: dict[str, Any]

    def safe_metadata(self) -> dict[str, Any]:
        """원문 없이 trace에 남길 Judge 판단 요약이다."""

        return {
            "selected_model": self.selected_model_id,
            "confidence": self.confidence,
            "reason_code": self.reason_code,
            "usage": dict(self.usage),
        }


class ModelRoutingRuntimeJudge:
    """초기 표본을 만들기 위한 runtime Judge.

    모델 능력의 절대 순위를 추측하지 않는다. 현재 노드 계약과 렌더된 요청을 보고
    *지금 실행 주체가 실제로 쓸 수 있는 후보* 중 하나만 선택하게 한다.
    """

    MAX_FEATURE_CHARS = 8_000

    @classmethod
    def decide(
        cls,
        *,
        client: RuntimeJudgeClient,
        candidate_model_ids: list[str],
        default_model_id: str,
        fallback_model_id: str | None,
        routing_feature_text: str,
        node_contract: Mapping[str, Any],
    ) -> RuntimeJudgeDecision:
        candidates = cls._normalized_candidates(candidate_model_ids)
        if not candidates:
            raise RuntimeJudgeResponseError("no candidate models")

        response = client.invoke_sync(
            messages=cls._messages(
                candidate_model_ids=candidates,
                default_model_id=default_model_id,
                fallback_model_id=fallback_model_id,
                routing_feature_text=routing_feature_text,
                node_contract=node_contract,
            ),
            temperature=0,
            max_tokens=160,
        )
        content = cls._response_content(response)
        try:
            payload = json.loads(content)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeJudgeResponseError("invalid JSON response") from exc
        if not isinstance(payload, dict):
            raise RuntimeJudgeResponseError("response must be an object")

        selected_model_id = str(payload.get("selected_model_id") or "").strip()
        if selected_model_id not in candidates:
            raise RuntimeJudgeResponseError("unavailable model selected by judge")
        try:
            confidence = float(payload.get("confidence"))
        except (TypeError, ValueError) as exc:
            raise RuntimeJudgeResponseError("invalid confidence") from exc
        if not 0.0 <= confidence <= 1.0:
            raise RuntimeJudgeResponseError("confidence must be between 0 and 1")

        reason_code = str(payload.get("reason_code") or "judge_selected").strip()
        return RuntimeJudgeDecision(
            selected_model_id=selected_model_id,
            confidence=confidence,
            reason_code=reason_code[:80],
            usage=cls._safe_usage(response.get("usage") if isinstance(response, dict) else None),
        )

    @classmethod
    def _messages(
        cls,
        *,
        candidate_model_ids: list[str],
        default_model_id: str,
        fallback_model_id: str | None,
        routing_feature_text: str,
        node_contract: Mapping[str, Any],
    ) -> list[dict[str, str]]:
        safe_contract = {
            key: value
            for key, value in dict(node_contract).items()
            if key in {"output_format", "knowledge_enabled", "schema_required", "input_length_bucket"}
        }
        instruction = (
            "당신은 워크플로우 LLM 모델 라우팅 Judge입니다. 현재 요청을 성공적으로 "
            "처리할 가능성과 비용을 함께 고려해 후보 중 하나만 고르세요. "
            "사용 가능한 후보 외의 모델을 선택하지 마세요. "
            "반드시 JSON object 하나만 반환하세요: "
            '{"selected_model_id":"후보 모델 ID","confidence":0.0,"reason_code":"짧은_근거"}.'
        )
        body = {
            "candidate_model_ids": candidate_model_ids,
            "selection_constraint": "사용 가능한 후보 외의 모델을 선택하지 마세요.",
            "default_model_id": default_model_id,
            "fallback_model_id": fallback_model_id,
            "node_contract": safe_contract,
            "request_feature": str(routing_feature_text or "")[: cls.MAX_FEATURE_CHARS],
        }
        return [
            {"role": "system", "content": instruction},
            {"role": "user", "content": json.dumps(body, ensure_ascii=False)},
        ]

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
