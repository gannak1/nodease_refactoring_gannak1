from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

_GATEWAY_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """
    pydantic-settings의 BaseSettings 클래스를 상속합니다.
    이 클래스를 상속받아 설정 모델을 정의하면, 환경 변수나 .env 파일의 값을 자동으로 읽어와서 Python 타입으로 변환 및 검증을 수행합니다.
    """

    # RAG Ingestion Mode
    STORAGE_TYPE: str = "LOCAL"

    # AWS Settings
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: Optional[str] = None
    S3_BUCKET_NAME: Optional[str] = None

    # Workflow Builder Agent
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    WORKFLOW_BUILDER_AGENT_SLACK_BOT_TOKEN: Optional[str] = None
    WORKFLOW_BUILDER_DEMO_SLACK_BOT_TOKEN: Optional[str] = None

    # Load from .env file
    model_config = SettingsConfigDict(
        env_file=(
            str(_REPO_ROOT / ".env"),
            str(_GATEWAY_DIR / ".env"),
            ".env",
        ),
        env_ignore_empty=True,
        extra="ignore",
    )


settings = Settings()
