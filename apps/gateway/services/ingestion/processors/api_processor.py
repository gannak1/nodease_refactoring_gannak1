import logging
from typing import Any, Dict

from apps.gateway.services.ingestion.parsers.json_parser import JsonParser
from apps.shared.services.ingestion.processors.base import (
    BaseProcessor,
    ProcessingResult,
)
from apps.shared.services.egress_guard import (
    API_RESPONSE_CONTENT_TYPES,
    EgressGuardError,
    EgressGuardPolicy,
    safe_http_request,
)

logger = logging.getLogger(__name__)


class ApiProcessor(BaseProcessor):
    """
    [ApiProcessor]
    HTTP API를 호출하여 데이터를 가져오고 텍스트를 추출합니다.
    """

    def process(self, source_config: Dict[str, Any]) -> ProcessingResult:
        """
        source_config: {
            "url": "http://...",
            "method": "GET",
            "headers": {...},
            "body": {...}
        }
        """
        url = source_config.get("url")
        method = source_config.get("method", "GET")
        headers = source_config.get("headers", {})
        body = source_config.get("body")

        # headers가 JSON string일 수 있으므로 파싱
        if isinstance(headers, str):
            try:
                import json

                headers = json.loads(headers)
            except:
                headers = {}

        # body가 JSON string일 수 있으므로 파싱
        if isinstance(body, str):
            try:
                import json

                body = json.loads(body)
            except:
                body = None

        if not url:
            return ProcessingResult(chunks=[], metadata={"error": "No URL provided"})

        try:
            response = safe_http_request(
                method=method,
                url=url,
                headers=headers,
                json_body=body,
                policy=EgressGuardPolicy(
                    timeout_seconds=30.0,
                    max_response_bytes=10 * 1024 * 1024,
                    allowed_content_types=API_RESPONSE_CONTENT_TYPES,
                ),
            )
            if response.status_code >= 400:
                return ProcessingResult(
                    chunks=[],
                    metadata={
                        "error": "External API returned an error.",
                        "status_code": response.status_code,
                    },
                )

            parser = JsonParser()
            try:
                json_data = response.json()
                # 객체 직접 전달
                parsed_blocks = parser.parse("", json_object=json_data)
            except ValueError:
                # JSON이 아닌 경우 텍스트 그대로 사용
                parsed_blocks = [{"text": response.text, "page": 1}]

            chunks = []
            for block in parsed_blocks:
                chunks.append(
                    {
                        "content": block["text"],
                        "metadata": {"source": "api_response", "page": block["page"]},
                    }
                )

            return ProcessingResult(
                chunks=chunks,
                metadata={"source_type": "API", "status_code": response.status_code},
            )

        except EgressGuardError as e:
            logger.warning("[ApiProcessor] Egress guard denied request: %s", e.reason_code)
            return ProcessingResult(
                chunks=[],
                metadata={"error": "Outbound request denied.", "reason_code": e.reason_code},
            )
        except Exception as e:
            logger.error("[ApiProcessor] Request failed: %s", type(e).__name__)
            return ProcessingResult(chunks=[], metadata={"error": "Request failed."})
