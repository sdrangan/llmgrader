import pytest

from llmgrader.mcp import blind_user_llm


def test_build_tool_schemas_exposes_expected_function_tools() -> None:
    tools = blind_user_llm.build_tool_schemas()
    tool_by_name = {tool["name"]: tool for tool in tools}

    assert [tool["name"] for tool in tools] == [
        "explain_config",
        "create_config_skeleton",
        "validate_config_xml",
        "scan_repo_for_config_inputs",
    ]
    assert all(tool["type"] == "function" for tool in tools)
    assert all(tool["strict"] is True for tool in tools)
    assert all(tool["parameters"]["additionalProperties"] is False for tool in tools)
    assert tool_by_name["create_config_skeleton"]["parameters"]["required"] == [
        "course_name",
        "term",
        "units",
        "assets",
    ]
    assert tool_by_name["create_config_skeleton"]["parameters"]["properties"]["assets"]["type"] == [
        "array",
        "null",
    ]
    assert tool_by_name["validate_config_xml"]["parameters"]["required"] == [
        "config_xml",
        "workspace_root",
    ]
    assert tool_by_name["validate_config_xml"]["parameters"]["properties"]["workspace_root"]["type"] == [
        "string",
        "null",
    ]


def test_execute_tool_call_routes_to_matching_helper(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_create_config_skeleton(*, course_name, term, units, assets=None):
        captured["course_name"] = course_name
        captured["term"] = term
        captured["units"] = units
        captured["assets"] = assets
        return "<llmgrader />"

    monkeypatch.setattr(blind_user_llm, "create_config_skeleton", fake_create_config_skeleton)

    result = blind_user_llm.execute_tool_call(
        "create_config_skeleton",
        {
            "course_name": "Probability",
            "term": "Fall 2026",
            "units": [{"name": "rv", "source": "units/rv.xml", "destination": "rv.xml"}],
            "assets": [{"source": "figures", "destination": "prob_assets"}],
        },
    )

    assert result == "<llmgrader />"
    assert captured == {
        "course_name": "Probability",
        "term": "Fall 2026",
        "units": [{"name": "rv", "source": "units/rv.xml", "destination": "rv.xml"}],
        "assets": [{"source": "figures", "destination": "prob_assets"}],
    }


def test_resolve_openai_api_key_raises_when_missing(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="OPENAI_API_KEY is required"):
        blind_user_llm.resolve_openai_api_key(None)