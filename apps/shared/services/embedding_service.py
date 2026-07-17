import logging
from typing import List
from uuid import UUID

import openai
from apps.shared.db.models.llm import LLMCredential, LLMProvider
from apps.shared.services.llm_credential_config import (
    LLMCredentialConfigError,
    load_llm_credential_config,
)
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    [Shared] 임베딩 전용 서비스
    Gateway LLMService에 의존하지 않고, 직접 OpenAI 임베딩을 수행합니다.
    """

    def __init__(self, db: Session, user_id: UUID):
        self.db = db
        self.user_id = user_id
        self._client = None
        self._model = "text-embedding-3-small"  # Default

    def _get_client(self):
        if self._client:
            return self._client

        # 1. 사용자의 OpenAI 크리덴셜 조회 (우선순위: Provider Name = 'openai')
        credential = (
            self.db.query(LLMCredential)
            .join(LLMProvider)
            .filter(
                LLMCredential.user_id == self.user_id,
                LLMCredential.is_valid,
                LLMProvider.name == "openai",
            )
            .first()
        )

        if not credential:
            # Fallback: 아무 유효한 크리덴셜이나 사용 (개발/테스트용)
            credential = (
                self.db.query(LLMCredential)
                .filter(
                    LLMCredential.user_id == self.user_id,
                    LLMCredential.is_valid,
                )
                .first()
            )

        if not credential:
            raise ValueError(f"No valid LLM credential found for user {self.user_id}")

        # 2. API Key 복호화
        try:
            config = load_llm_credential_config(credential)
        except LLMCredentialConfigError as exc:
            raise ValueError("Failed to initialize OpenAI client") from exc

        try:
            api_key = config["apiKey"]
            self._client = openai.OpenAI(api_key=api_key)
            return self._client
        except Exception:
            raise ValueError("Failed to initialize OpenAI client") from None

    def embed_batch(self, texts: List[str], model: str = None) -> List[List[float]]:
        """
        텍스트 배치를 임베딩 벡터로 변환 (OpenAI)
        """
        client = self._get_client()
        target_model = model or self._model

        # 빈 텍스트 처리 (OpenAI 에러 방지)
        clean_texts = [t if t and t.strip() else " " for t in texts]

        try:
            response = client.embeddings.create(input=clean_texts, model=target_model)
            # 순서 보장
            embeddings = [data.embedding for data in response.data]
            return embeddings
        except Exception as exc:
            logger.error(
                "[EmbeddingService] Provider call failed: error_type=%s",
                type(exc).__name__,
            )
            # 실패 시 더미 벡터 (0.0) 반환 or Raise
            # 여기서는 Workflow가 멈추지 않도록 Raise하되 상위에서 처리
            raise
