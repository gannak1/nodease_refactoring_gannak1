"""Mail 노드 데이터 스키마"""

from enum import Enum
from typing import List, Literal, Optional

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from apps.workflow_engine.workflow.nodes.base.entities import BaseNodeData


class EmailProvider(str, Enum):
    """이메일 서비스 제공자"""

    GMAIL = "gmail"
    NAVER = "naver"
    DAUM = "daum"
    OUTLOOK = "outlook"
    CUSTOM = "custom"


class MailVariable(BaseModel):
    """Mail 노드 변수 매핑"""

    name: str = Field("", description="변수 이름")
    value_selector: List[str] = Field(
        default_factory=list, description="값 선택자 [node_id, output_key]"
    )


class MailNodeData(BaseNodeData):
    """Mail Node 설정 데이터"""

    model_config = ConfigDict(extra="forbid")

    credential_id: Optional[UUID] = Field(None, description="Mail credential reference")
    configuration_state: Optional[Literal["resolved", "unresolved"]] = None

    # Search Criteria
    keyword: Optional[str] = Field(None, description="검색 키워드")
    sender: Optional[str] = Field(None, description="발신자 필터")
    subject: Optional[str] = Field(None, description="제목 필터")
    start_date: Optional[str] = Field(None, description="시작일 (YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="종료일 (YYYY-MM-DD)")

    # Options
    folder: Literal["INBOX", "SENT", "DRAFTS", "SPAM", "TRASH"] = Field(
        "INBOX", description="검색할 폴더"
    )
    max_results: Optional[int] = Field(
        None, description="최대 결과 개수 (기본값: 5)", ge=1, le=100
    )
    unread_only: bool = Field(False, description="읽지 않은 메일만")
    mark_as_read: bool = Field(False, description="검색 후 읽음 표시")

    # Variables
    referenced_variables: List[MailVariable] = Field(
        default_factory=list, description="참조된 변수 목록"
    )
