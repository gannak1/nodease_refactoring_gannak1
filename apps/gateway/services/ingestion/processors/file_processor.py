import logging
import os
from typing import Any, Dict

from apps.gateway.services.ingestion.parsers.docx_parser import DocxParser
from apps.gateway.services.ingestion.parsers.excel_csv_parser import ExcelCsvParser
from apps.gateway.services.ingestion.parsers.pdf_parser import PdfParser
from apps.gateway.services.ingestion.parsers.txt_parser import TxtParser
from apps.gateway.services.llm_service import (
    LLMCredentialNotAvailableError,
    LLMService,
)
from apps.shared.services.egress_guard import (
    DOCUMENT_RESPONSE_CONTENT_TYPES,
    EgressGuardError,
    EgressGuardPolicy,
    download_url_to_temp_file,
)
from apps.shared.services.ingestion.processors.base import (
    BaseProcessor,
    ProcessingResult,
)

logger = logging.getLogger(__name__)


class FileProcessor(BaseProcessor):
    """
    [FileProcessor]
    로컬 파일 처리를 담당하는 프로세서입니다.
    파일 확장자에 따라 적절한 Parser를 선택하여 실행합니다.
    """

    def process(self, source_config: Dict[str, Any]) -> ProcessingResult:
        """
        source_config: {"file_path": "/path/to/file.pdf", "document_id": "...", "strategy": "llamaparse"}
        """
        file_path = source_config.get("file_path")
        if not file_path:
            raise FileNotFoundError("File path is missing")

        # [MODIFIED] S3/HTTP URL 처리
        is_remote_file = str(file_path).startswith("http") or str(file_path).startswith(
            "s3://"
        )
        temp_file_path = None

        try:
            if is_remote_file:
                # 임시 파일 다운로드
                temp_file_path = self._download_file(file_path)
                target_path = temp_file_path
            else:
                # 로컬 파일
                if not os.path.exists(file_path):
                    raise FileNotFoundError(f"File not found: {file_path}")
                target_path = file_path

            ext = os.path.splitext(target_path)[1].lower()
            parser = self._get_parser(ext)

            if not parser:
                logger.error(f"[FileProcessor] Unsupported file extension: {ext}")
                return ProcessingResult(
                    chunks=[], metadata={"error": "Unsupported extension"}
                )

            parse_kwargs = {}
            strategy = source_config.get("strategy", "general")

            if isinstance(parser, PdfParser) and strategy == "llamaparse":
                parse_kwargs["strategy"] = "llamaparse"
                try:
                    parse_kwargs["api_key"] = self._get_llamaparse_key()
                except LLMCredentialNotAvailableError:
                    return ProcessingResult(
                        chunks=[],
                        metadata={"error": "Parser credential is unavailable."},
                    )
                # Preview 시에는 일부 페이지만 파싱하여 사용자 경험 개선
                if "target_pages" in source_config:
                    parse_kwargs["target_pages"] = source_config["target_pages"]

            try:
                parsed_blocks = parser.parse(target_path, **parse_kwargs)
            except Exception as e:
                logger.error("[FileProcessor] Parsing error: %s", type(e).__name__)
                return ProcessingResult(chunks=[], metadata={"error": "Parsing failed."})

            chunks = []
            safe_source = "remote_file" if is_remote_file else file_path
            for block in parsed_blocks:
                chunks.append(
                    {
                        "content": block["text"],
                        "metadata": {"page": block["page"], "source": safe_source},
                    }
                )

            return ProcessingResult(
                chunks=chunks,
                metadata={
                    "file_path": safe_source,
                    "extension": ext,
                    "strategy": strategy,
                },
            )

        finally:
            # 임시 파일 정리
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception as exc:
                    logger.warning(
                        "Failed to remove temporary file: error_type=%s",
                        type(exc).__name__,
                    )

    def _download_file(self, url: str) -> str:
        """
        URL(S3 포함)에서 파일을 다운로드하여 임시 경로를 반환합니다.
        """
        # s3:// 포맷이 그대로 넘어온 경우 처리 (storage service를 안 거친 경우 등)
        if url.startswith("s3://"):
            # 여기서는 단순히 에러 처리하거나, 혹은 Presigned URL 발급 로직이 필요함.
            # 현재는 knowledge.py의 리다이렉트 로직과 맞추어 HTTP URL을 기대함.
            raise ValueError(
                "Raw s3:// URL is not supported for direct processing. Use HTTP URL."
            )

        from urllib.parse import urlparse

        path = urlparse(url).path
        ext = os.path.splitext(path)[1] or ".tmp"
        try:
            return download_url_to_temp_file(
                url,
                suffix=ext,
                policy=EgressGuardPolicy(
                    timeout_seconds=30.0,
                    max_response_bytes=50 * 1024 * 1024,
                    allowed_content_types=DOCUMENT_RESPONSE_CONTENT_TYPES,
                ),
            )
        except EgressGuardError as e:
            raise RuntimeError(
                f"Remote file download denied: {e.reason_code}"
            ) from e
        except Exception as e:
            raise RuntimeError("Remote file download failed.") from e

    def analyze(self, source_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        파일 분석 (비용 예측 등)
        """
        file_path = source_config.get("file_path")
        if not file_path:
            return {"error": "File path is missing"}

        is_remote_file = str(file_path).startswith("http") or str(file_path).startswith(
            "s3://"
        )
        temp_file_path = None

        try:
            if is_remote_file:
                temp_file_path = self._download_file(file_path)
                target_path = temp_file_path
            else:
                if not os.path.exists(file_path):
                    return {"error": "File not found"}
                target_path = file_path

            ext = os.path.splitext(target_path)[1].lower()
            parser = self._get_parser(ext)

            # 현재는 PdfParser만 analyze 메서드를 가짐
            if parser and hasattr(parser, "analyze"):
                return parser.analyze(target_path)

            return {}

        except Exception as e:
            logger.warning("[FileProcessor] Analyze failed: %s", type(e).__name__)
            return {"error": "Analyze failed."}

        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception as exc:
                    logger.warning(
                        "Failed to remove temporary file: error_type=%s",
                        type(exc).__name__,
                    )

    def _get_parser(self, ext: str):
        if ext == ".pdf":
            return PdfParser()
        elif ext == ".docx":
            return DocxParser()
        elif ext in [".txt", ".md"]:
            return TxtParser()
        elif ext in [".csv", ".xlsx", ".xls"]:
            return ExcelCsvParser()
        return None

    def _get_llamaparse_key(self) -> str:
        """권한이 검증된 LlamaParse credential의 secret만 resolver에서 받는다."""
        return LLMService.resolve_llamaparse_api_key(
            self.db,
            user_id=self.user_id,
            organization_id=self.organization_id,
        )
