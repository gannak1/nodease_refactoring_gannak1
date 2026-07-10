"""Cost Optimizer 추천 후보의 출력 품질을 안전하게 비교한다."""

from __future__ import annotations

import json
import secrets
import time
from typing import Any

from apps.gateway.services.llm_service import LLMService


class CostOptimizerOutputQualityService:
    """A/B 출력의 품질을 blind pairwise judge로 평가하는 서비스.

    baseline과 candidate라는 이름은 judge prompt에 전달하지 않는다. 평가 결과와
    usage/cost의 safe summary만 caller에게 반환하며, 원문 입력/출력은 저장하지 않는다.
    """

    PROMPT_VERSION = "cost-optimizer-output-quality-judge-v1"
    BASE_DIMENSIONS = (
        "instruction_fulfillment",
        "relevance_completeness",
        "clarity_consistency",
    )

    @classmethod
    def evaluate(
        cls,
        *,
        db: Any,
        workflow: Any,
        current_user: Any,
        node_id: str,
        candidate_row: Any,
        baseline: dict[str, Any],
        candidate_result: dict[str, Any],
        judge_client: Any | None = None,
        judge_model_id: str | None = None,
        pair_order: str | None = None,
    ) -> dict[str, Any]:
        """동일 입력에 대한 두 출력의 상대 품질을 평가한다.

        judge가 없거나 호출에 실패해도 candidate 실행 결과는 유효하므로 unavailable
        응답을 돌려준다. 이 경우 caller는 verification_status를 partial로 결정한다.
        """
        try:
            if judge_client is not None:
                selected_model_id = judge_model_id or cls._select_judge_model(
                    db=db,
                    user_id=current_user.id,
                )
                client = judge_client
            else:
                selected_model_id, client = cls._select_judge_runtime(
                    db=db,
                    user_id=current_user.id,
                    organization_id=getattr(workflow, "organization_id", None),
                    preferred_model_id=judge_model_id,
                )
            if not selected_model_id or client is None:
                return cls._unavailable("품질 평가에 사용할 수 있는 LLM credential/model이 없습니다.")
            order = pair_order or cls._pair_order(baseline, candidate_result)
            messages = cls._build_messages(
                baseline=baseline,
                candidate_result=candidate_result,
                pair_order=order,
            )
            started = time.perf_counter()
            response = client.invoke_sync(messages, temperature=0.0, max_tokens=700)
            latency_ms = int((time.perf_counter() - started) * 1000)
            usage = cls._usage_from_response(response)
            usage["latency_ms"] = latency_ms
            parsed = cls._parse_response(cls._content_from_response(response))
            quality = cls._normalize_result(parsed, pair_order=order)

            cost = LLMService.calculate_cost(
                db,
                selected_model_id,
                int(usage.get("prompt_tokens") or 0),
                int(usage.get("completion_tokens") or 0),
            )
            usage_log = LLMService.log_usage(
                db,
                user_id=current_user.id,
                model_id=selected_model_id,
                usage=usage,
                cost=cost,
                organization_id=getattr(workflow, "organization_id", None),
                workflow_id=getattr(workflow, "id", None),
                node_id=f"{node_id}:quality-judge",
                cost_optimizer_candidate_id=getattr(candidate_row, "id", None),
            )
            quality["judge_cost"] = float(cost) if cost is not None else None
            quality["judge_usage_log_id"] = (
                str(usage_log.id) if usage_log is not None else None
            )
            quality["judge"] = {
                "role": "quality_judge",
                "model_id": selected_model_id,
                "prompt_version": cls.PROMPT_VERSION,
                "usage": {
                    "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                    "completion_tokens": int(usage.get("completion_tokens") or 0),
                    "total_tokens": int(usage.get("total_tokens") or 0),
                },
            }
            return quality
        except Exception:
            # provider/credential 오류의 원문을 response, audit, 일반 trace에 전파하지 않는다.
            return cls._unavailable("품질 평가를 완료하지 못했습니다.")

    @classmethod
    def _select_judge_model(cls, *, db: Any, user_id: Any) -> str | None:
        models = LLMService.get_my_available_models(db, user_id)
        chat_models = [
            model
            for model in models
            if str(getattr(model, "type", "") or "").lower() == "chat"
        ]
        if not chat_models:
            return None
        return str(getattr(chat_models[0], "model_id_for_api_call", "") or "") or None

    @classmethod
    def _select_judge_runtime(
        cls,
        *,
        db: Any,
        user_id: Any,
        organization_id: Any,
        preferred_model_id: str | None,
    ) -> tuple[str | None, Any | None]:
        models = LLMService.get_my_available_models(db, user_id)
        candidate_ids = [
            str(getattr(model, "model_id_for_api_call", "") or "")
            for model in models
            if str(getattr(model, "type", "") or "").lower() == "chat"
        ]
        candidate_ids = [model_id for model_id in candidate_ids if model_id]
        if preferred_model_id:
            candidate_ids = [preferred_model_id]
        for model_id in candidate_ids:
            try:
                return model_id, LLMService.get_client_for_user(
                    db,
                    user_id,
                    model_id,
                    organization_id,
                )
            except Exception:
                continue
        return None, None

    @classmethod
    def _build_messages(
        cls,
        *,
        baseline: dict[str, Any],
        candidate_result: dict[str, Any],
        pair_order: str,
    ) -> list[dict[str, str]]:
        baseline_variant = cls._variant_from_result(baseline)
        candidate_variant = cls._variant_from_result(candidate_result)
        left, right = (
            (baseline_variant, candidate_variant)
            if pair_order == "baseline_left"
            else (candidate_variant, baseline_variant)
        )
        dimensions = list(cls.BASE_DIMENSIONS)
        if left.get("rag_enabled") or right.get("rag_enabled"):
            dimensions.append("groundedness")

        payload = {
            "task": "Evaluate two anonymized LLM outputs for the same input.",
            "dimensions": dimensions,
            "scoring": "Score each dimension from 0 to 100. Do not assume either variant is correct.",
            "response_schema": {
                "variant_left": {dimension: "0..100" for dimension in dimensions},
                "variant_right": {dimension: "0..100" for dimension in dimensions},
                "confidence": "0..1",
            },
            "variant_left": left,
            "variant_right": right,
        }
        return [
            {
                "role": "system",
                "content": (
                    "Return JSON only. Evaluate each anonymized variant independently and fairly. "
                    "Do not identify a baseline, a candidate, or a ground-truth answer. "
                    "Do not quote sensitive source content in the response."
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]

    @classmethod
    def _variant_from_result(cls, result: dict[str, Any]) -> dict[str, Any]:
        output = result.get("output") if isinstance(result, dict) else {}
        output = output if isinstance(output, dict) else {"text": output}
        trace = result.get("trace") if isinstance(result, dict) else {}
        trace = trace if isinstance(trace, dict) else {}
        rag_summary = trace.get("rag_summary")
        return {
            "input": cls._bounded_value(result.get("input") if isinstance(result, dict) else None),
            "output": cls._bounded_value(output),
            "rag_enabled": bool(rag_summary),
            "rag_summary": cls._safe_rag_summary(rag_summary),
        }

    @staticmethod
    def _bounded_value(value: Any, *, max_chars: int = 12000) -> Any:
        if isinstance(value, str):
            return value[:max_chars]
        if isinstance(value, dict):
            return {
                str(key): CostOptimizerOutputQualityService._bounded_value(item, max_chars=max_chars)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                CostOptimizerOutputQualityService._bounded_value(item, max_chars=max_chars)
                for item in value[:20]
            ]
        return value

    @staticmethod
    def _safe_rag_summary(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        allowed = ("retrieved_chunk_count", "context_token_estimate", "evidence_sufficient")
        return {key: value.get(key) for key in allowed if key in value}

    @staticmethod
    def _pair_order(baseline: dict[str, Any], candidate_result: dict[str, Any]) -> str:
        # 호출마다 baseline이 항상 왼쪽에 놓이는 위치 편향을 피한다.
        del baseline, candidate_result
        return "baseline_left" if secrets.randbelow(2) == 0 else "candidate_left"

    @staticmethod
    def _content_from_response(response: Any) -> str:
        if isinstance(response, dict):
            choices = response.get("choices") or []
            if choices and isinstance(choices[0], dict):
                message = choices[0].get("message") or {}
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return message["content"]
        return ""

    @staticmethod
    def _usage_from_response(response: Any) -> dict[str, int]:
        usage = response.get("usage") if isinstance(response, dict) else {}
        usage = usage if isinstance(usage, dict) else {}
        prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion_tokens = int(
            usage.get("completion_tokens") or usage.get("output_tokens") or 0
        )
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": int(usage.get("total_tokens") or prompt_tokens + completion_tokens),
        }

    @staticmethod
    def _parse_response(content: str) -> dict[str, Any]:
        normalized = content.strip()
        if normalized.startswith("```"):
            normalized = normalized.split("\n", 1)[-1]
            if normalized.endswith("```"):
                normalized = normalized[:-3]
        parsed = json.loads(normalized)
        if not isinstance(parsed, dict):
            raise ValueError("judge response must be a JSON object")
        return parsed

    @classmethod
    def _normalize_result(
        cls,
        parsed: dict[str, Any],
        *,
        pair_order: str,
    ) -> dict[str, Any]:
        left = cls._dimension_scores(parsed.get("variant_left"))
        right = cls._dimension_scores(parsed.get("variant_right"))
        baseline_dimensions, candidate_dimensions = (
            (left, right) if pair_order == "baseline_left" else (right, left)
        )
        dimensions = {
            name: {
                "baseline": baseline_dimensions.get(name),
                "candidate": candidate_dimensions.get(name),
                "delta": cls._delta(
                    baseline_dimensions.get(name), candidate_dimensions.get(name)
                ),
            }
            for name in sorted(set(baseline_dimensions) | set(candidate_dimensions))
        }
        baseline_score = cls._average(baseline_dimensions.values())
        candidate_score = cls._average(candidate_dimensions.values())
        confidence_score = cls._score(parsed.get("confidence"), lower=0, upper=1)
        return {
            "status": "completed",
            "baseline": {"score": baseline_score},
            "candidate": {"score": candidate_score},
            "delta": cls._delta(baseline_score, candidate_score),
            "dimensions": dimensions,
            "confidence": cls._confidence_label(confidence_score),
            "confidence_score": confidence_score,
            "safe_summary": cls._safe_summary(baseline_score, candidate_score),
        }

    @staticmethod
    def _dimension_scores(value: Any) -> dict[str, int]:
        if not isinstance(value, dict):
            raise ValueError("judge dimension scores are missing")
        scores: dict[str, int] = {}
        for key, item in value.items():
            score = CostOptimizerOutputQualityService._score(item, lower=0, upper=100)
            if score is not None:
                scores[str(key)] = int(round(score))
        if not scores:
            raise ValueError("judge dimension scores are empty")
        return scores

    @staticmethod
    def _score(value: Any, *, lower: float, upper: float) -> float | None:
        try:
            return max(lower, min(upper, float(value)))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _average(values: Any) -> int | None:
        numbers = [float(value) for value in values if isinstance(value, (int, float))]
        return int(round(sum(numbers) / len(numbers))) if numbers else None

    @staticmethod
    def _delta(baseline: int | None, candidate: int | None) -> int | None:
        if baseline is None or candidate is None:
            return None
        return candidate - baseline

    @staticmethod
    def _confidence_label(value: float | None) -> str:
        if value is None:
            return "low"
        if value >= 0.8:
            return "high"
        if value >= 0.6:
            return "medium"
        return "low"

    @staticmethod
    def _safe_summary(baseline_score: int | None, candidate_score: int | None) -> str:
        if baseline_score is None or candidate_score is None:
            return "출력 품질 점수를 계산하지 못했습니다."
        if candidate_score > baseline_score:
            return "후보 출력의 품질 점수가 기준 출력보다 높게 평가되었습니다."
        if candidate_score < baseline_score:
            return "후보 출력의 품질 점수가 기준 출력보다 낮게 평가되었습니다."
        return "두 출력의 품질 점수가 동일하게 평가되었습니다."

    @staticmethod
    def _unavailable(summary: str) -> dict[str, Any]:
        return {
            "status": "unavailable",
            "baseline": {"score": None},
            "candidate": {"score": None},
            "delta": None,
            "dimensions": {},
            "confidence": "unavailable",
            "safe_summary": summary,
            "judge_cost": None,
            "judge_usage_log_id": None,
        }
