"""Guardrail Node 관련 엔티티 정의"""

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field

from apps.workflow_engine.workflow.nodes.base.entities import BaseNodeData


GuardrailOperation = Literal["check_text", "sanitize_text"]
GuardrailBranchCondition = Literal["keyword_match", "regex_match"]


class GuardrailVariable(BaseModel):
    """프론트 호환을 위한 참조 변수 모델."""

    name: str
    value_selector: List[str]


class GuardrailNodeData(BaseNodeData):
    """Guardrail Node 전용 데이터."""

    operation: GuardrailOperation = "check_text"
    text_to_check: str = ""
    input_selector: Optional[List[str]] = Field(default_factory=list)
    system_message: Optional[str] = None
    guardrails: List[str] = Field(default_factory=list)
    custom_keywords: str = ""
    custom_prompt: str = ""
    custom_regex: str = ""
    branching_enabled: bool = True
    branch_condition: GuardrailBranchCondition = "keyword_match"
    match_keywords: List[str] = Field(default_factory=list)
    pass_label: str = "통과"
    fail_label: str = "실패"
    pass_handle_id: str = "pass"
    fail_handle_id: str = "fail"
    referenced_variables: List[Any] = Field(default_factory=list)
