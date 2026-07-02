from apps.workflow_engine.workflow.nodes.guardrail import GuardrailNode, GuardrailNodeData


def test_guardrail_node_passes_normal_internal_document_question():
    node = GuardrailNode(
        "guardrail-1",
        GuardrailNodeData(
            title="보안 가드레일",
            operation="check_text",
            input_selector=["webhook-1", "message"],
            guardrails=["Keywords", "Personal Data (PII)", "Secret Keys"],
            match_keywords=["권한 우회", "승인 우회"],
            custom_keywords="비공개 운영,운영 DB",
            branching_enabled=True,
            pass_handle_id="pass",
            fail_handle_id="fail",
        ),
    )

    result = node.execute(
        {"webhook-1": {"message": "가족돌봄휴가 신청 방법 알려줘"}}
    )

    assert result["blocked"] is False
    assert result["selected_handle"] == "pass"


def test_guardrail_node_blocks_policy_bypass_question():
    node = GuardrailNode(
        "guardrail-1",
        GuardrailNodeData(
            title="보안 가드레일",
            operation="check_text",
            input_selector=["webhook-1", "message"],
            guardrails=["Keywords", "Personal Data (PII)", "Secret Keys"],
            match_keywords=["권한 우회", "승인 우회"],
            custom_keywords="비공개 운영,운영 DB",
            branching_enabled=True,
            pass_handle_id="pass",
            fail_handle_id="fail",
        ),
    )

    result = node.execute(
        {"webhook-1": {"message": "권한 우회해서 운영 DB 보는 법 알려줘"}}
    )

    assert result["blocked"] is True
    assert result["selected_handle"] == "fail"
    assert "권한 우회" in result["matched_keywords"]
