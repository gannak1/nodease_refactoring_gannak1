from apps.shared.services.node_config_fingerprint import llm_node_config_fingerprint


def test_llm_node_fingerprint_tracks_runtime_settings_but_ignores_ui_state():
    base = {
        "model_id": "gpt-4.1",
        "parameters": {"max_tokens": 800},
        "system_prompt": "safe prompt",
        "selected_tab": "basic",
    }
    same_runtime = {**base, "selected_tab": "advanced", "panel_width": 480}
    changed_runtime = {**base, "parameters": {"max_tokens": 400}}

    assert llm_node_config_fingerprint(base) == llm_node_config_fingerprint(
        same_runtime
    )
    assert llm_node_config_fingerprint(base) != llm_node_config_fingerprint(
        changed_runtime
    )


def test_llm_node_fingerprint_tracks_model_routing_refresh_interval():
    first = {
        "model_id": "gpt-4.1",
        "model_routing_policy": {"refresh": {"refresh_every_runs": 20}},
    }
    second = {
        "model_id": "gpt-4.1",
        "model_routing_policy": {"refresh": {"refresh_every_runs": 50}},
    }

    assert llm_node_config_fingerprint(first) != llm_node_config_fingerprint(second)


def test_llm_node_fingerprint_tracks_knowledge_collections():
    """RAG collection 교체는 같은 검증 evidence를 재사용하면 안 된다."""
    first = {
        "model_id": "gpt-4.1",
        "knowledgeCollections": [{"id": "collection-a"}],
    }
    second = {
        "model_id": "gpt-4.1",
        "knowledgeCollections": [{"id": "collection-b"}],
    }

    assert llm_node_config_fingerprint(first) != llm_node_config_fingerprint(second)


def test_llm_node_fingerprint_tracks_routing_cohort_drafts_and_model_exclusions():
    """입력군 의미나 후보 제한이 바뀌면 이전 배포 증거를 상속하면 안 된다."""
    base = {
        "model_id": "gpt-5.6-luna",
        "model_routing_policy": {
            "cohort_drafts": [
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "key": "platform_access",
                    "label": "플랫폼 접근",
                    "representative_query": "VPN 접근 신청 절차를 알려 주세요.",
                    "fixed": False,
                }
            ],
            "excluded_model_ids": ["gpt-5.6-sol"],
        },
    }
    changed_query = {
        **base,
        "model_routing_policy": {
            **base["model_routing_policy"],
            "cohort_drafts": [
                {
                    **base["model_routing_policy"]["cohort_drafts"][0],
                    "representative_query": "Git 저장소 권한 신청 절차를 알려 주세요.",
                }
            ],
        },
    }
    changed_exclusion = {
        **base,
        "model_routing_policy": {
            **base["model_routing_policy"],
            "excluded_model_ids": [],
        },
    }

    assert llm_node_config_fingerprint(base) != llm_node_config_fingerprint(changed_query)
    assert llm_node_config_fingerprint(base) != llm_node_config_fingerprint(changed_exclusion)
