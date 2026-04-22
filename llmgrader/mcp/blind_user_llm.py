from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from openai import OpenAI

from llmgrader.mcp.config_xml_tools import (
    create_config_skeleton,
    get_llmgrader_config_structure,
    scan_repo_for_config_inputs,
    validate_config_xml,
)
from llmgrader.mcp.unit_xml_tools import (
    create_unit_xml_skeleton,
    explain_rubric_rules,
    get_unit_xml_structure,
    scan_repo_for_unit_inputs,
    validate_unit_xml,
)


DEFAULT_MODEL = "gpt-4.1"


def build_tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": "get_llmgrader_config_structure",
            "description": (
                "Return a nested schema object for llmgrader_config.xml, including the "
                "XML hierarchy, child elements, semantic rules, and example documents."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "create_config_skeleton",
            "description": (
                "Create a draft llmgrader_config.xml from explicit course metadata, unit XML "
                "sources, and optional asset mappings."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "course_name": {
                        "type": "string",
                        "description": "Course name to place in <course><name>.",
                    },
                    "term": {
                        "type": "string",
                        "description": "Academic term to place in <course><term>.",
                    },
                    "units": {
                        "type": "array",
                        "description": "Unit XML entries to include in <units>.",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "source": {"type": "string"},
                                "destination": {"type": "string"},
                            },
                            "required": ["name", "source", "destination"],
                            "additionalProperties": False,
                        },
                    },
                    "assets": {
                        "type": ["array", "null"],
                        "description": "Optional asset mappings for <assets>.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "source": {"type": "string"},
                                "destination": {"type": "string"},
                            },
                            "required": ["source", "destination"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["course_name", "term", "units", "assets"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "validate_config_xml",
            "description": (
                "Validate llmgrader_config.xml content and report structural errors, path-rule "
                "errors, and workspace-relative missing-source warnings."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "config_xml": {
                        "type": "string",
                        "description": "Full llmgrader_config.xml text to validate.",
                    },
                    "workspace_root": {
                        "type": ["string", "null"],
                        "description": "Optional workspace root used for relative source existence checks.",
                    },
                },
                "required": ["config_xml", "workspace_root"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "scan_repo_for_config_inputs",
            "description": (
                "Scan a workspace root for likely unit XML files and asset directories before "
                "drafting llmgrader_config.xml. Prefer this before inventing file paths."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace_root": {
                        "type": "string",
                        "description": "Absolute or relative workspace root path to scan.",
                    }
                },
                "required": ["workspace_root"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "get_unit_xml_structure",
            "description": (
                "Return a nested schema object for the unit XML hierarchy, including element metadata, "
                "attributes, child elements, text content, semantic rules, and examples."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "explain_rubric_rules",
            "description": (
                "Explain binary and partial-credit rubric rules, including rubric_total behavior, common mistakes, and group semantics."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "create_unit_xml_skeleton",
            "description": (
                "Create a starter unit XML draft from a unit id, optional title/version, and structured question definitions."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "unit_id": {
                        "type": "string",
                        "description": "Identifier for the root <unit id=...> attribute.",
                    },
                    "title": {
                        "type": ["string", "null"],
                        "description": "Optional unit title attribute.",
                    },
                    "version": {
                        "type": ["string", "null"],
                        "description": "Optional unit version attribute.",
                    },
                    "questions": {
                        "type": ["array", "null"],
                        "description": "Optional structured question list for the starter unit.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "qtag": {"type": "string"},
                                "question_text": {"type": "string"},
                                "solution": {"type": "string"},
                                "grading_notes": {"type": ["string", "null"]},
                                "preferred_model": {"type": ["string", "null"]},
                                "required": {"type": "boolean"},
                                "partial_credit": {"type": "boolean"},
                                "tools": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "parts": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "part_label": {"type": "string"},
                                            "points": {"type": ["number", "integer"]},
                                        },
                                        "required": ["part_label", "points"],
                                        "additionalProperties": False,
                                    },
                                },
                                "rubrics": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "part": {"type": ["string", "null"]},
                                            "condition_type": {"type": ["string", "null"]},
                                            "action": {"type": ["string", "null"]},
                                            "point_adjustment": {"type": ["string", "number", "integer", "null"]},
                                            "display_text": {"type": "string"},
                                            "condition": {"type": "string"},
                                            "notes": {"type": ["string", "null"]},
                                        },
                                        "required": [
                                            "id",
                                            "part",
                                            "condition_type",
                                            "action",
                                            "point_adjustment",
                                            "display_text",
                                            "condition",
                                            "notes",
                                        ],
                                        "additionalProperties": False,
                                    },
                                },
                                "rubric_groups": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "type": {"type": "string"},
                                            "ids": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                            },
                                        },
                                        "required": ["type", "ids"],
                                        "additionalProperties": False,
                                    },
                                },
                                "rubric_total": {"type": ["string", "null"]},
                            },
                            "required": [
                                "qtag",
                                "question_text",
                                "solution",
                                "grading_notes",
                                "preferred_model",
                                "required",
                                "partial_credit",
                                "tools",
                                "parts",
                                "rubrics",
                                "rubric_groups",
                                "rubric_total",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["unit_id", "title", "version", "questions"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "validate_unit_xml",
            "description": (
                "Validate a unit XML draft using schema checks, existing parser semantic checks, and high-confidence authoring checks for questions and rubrics."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "unit_xml": {
                        "type": "string",
                        "description": "Full unit XML text to validate.",
                    },
                    "workspace_root": {
                        "type": ["string", "null"],
                        "description": "Optional workspace root used for warnings about /pkg_assets references and nearby config context.",
                    },
                },
                "required": ["unit_xml", "workspace_root"],
                "additionalProperties": False,
            },
        },
        {
            "type": "function",
            "name": "scan_repo_for_unit_inputs",
            "description": (
                "Scan a workspace root for likely unit XML files, rubric examples, asset directories, and nearby authoring files before drafting a new unit."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "workspace_root": {
                        "type": "string",
                        "description": "Absolute or relative workspace root path to scan.",
                    }
                },
                "required": ["workspace_root"],
                "additionalProperties": False,
            },
        },
    ]


def resolve_openai_api_key(api_key: str | None = None) -> str:
    resolved = api_key or os.getenv("OPENAI_API_KEY")
    if not resolved:
        raise ValueError(
            "OPENAI_API_KEY is required. Pass api_key explicitly or set OPENAI_API_KEY in the environment."
        )
    return resolved


def execute_tool_call(name: str, arguments: dict[str, Any]) -> Any:
    if name == "get_llmgrader_config_structure":
        return get_llmgrader_config_structure()
    if name == "get_unit_xml_structure":
        return get_unit_xml_structure()
    if name == "explain_rubric_rules":
        return explain_rubric_rules()
    if name == "create_config_skeleton":
        return create_config_skeleton(
            course_name=arguments["course_name"],
            term=arguments["term"],
            units=arguments["units"],
            assets=arguments.get("assets"),
        )
    if name == "create_unit_xml_skeleton":
        return create_unit_xml_skeleton(
            unit_id=arguments["unit_id"],
            title=arguments.get("title"),
            version=arguments.get("version"),
            questions=arguments.get("questions"),
        )
    if name == "validate_config_xml":
        return validate_config_xml(
            config_xml=arguments["config_xml"],
            workspace_root=arguments.get("workspace_root"),
        )
    if name == "validate_unit_xml":
        return validate_unit_xml(
            unit_xml=arguments["unit_xml"],
            workspace_root=arguments.get("workspace_root"),
        )
    if name == "scan_repo_for_config_inputs":
        return scan_repo_for_config_inputs(workspace_root=arguments["workspace_root"])
    if name == "scan_repo_for_unit_inputs":
        return scan_repo_for_unit_inputs(workspace_root=arguments["workspace_root"])
    raise ValueError(f"Unknown blind-user tool: {name}")


def _build_system_instruction(workspace_root: str) -> str:
    return (
        "You are helping a first-time user author or validate llmgrader_config.xml and unit XML files. "
        "You have no prior conversation context beyond the current user prompt. "
        f"The current workspace root is: {workspace_root}. "
        "Prefer inspecting the workspace with repo-scan tools before inventing file paths or question structure. "
        "If enough information exists in the workspace, create a reasonable draft config or unit XML. "
        "If key information is missing, ask concise follow-up questions instead of guessing. "
        "After generating XML, validate it before presenting it when practical. "
        "For unit XML, pay attention to parts, partial-credit mode, and rubric rules. "
        "Keep responses concise, practical, and focused on the user request."
    )


def _response_output_items(response: Any) -> list[Any]:
    return list(getattr(response, "output", []) or [])


def _response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text

    text_parts: list[str] = []
    for item in _response_output_items(response):
        if _get_attr(item, "type") != "message":
            continue
        for content_item in _get_attr(item, "content", []) or []:
            if _get_attr(content_item, "type") in {"output_text", "text"}:
                text_value = _get_attr(content_item, "text")
                if text_value:
                    text_parts.append(text_value)
    return "\n".join(text_parts).strip()


def _response_summary(response: Any, round_trip: int) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    return {
        "round_trip": round_trip,
        "response_id": getattr(response, "id", None),
        "output_types": [_get_attr(item, "type") for item in _response_output_items(response)],
        "output_text": _response_text(response),
        "usage": {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        },
    }


def _extract_function_calls(response: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for item in _response_output_items(response):
        if _get_attr(item, "type") != "function_call":
            continue
        raw_arguments = _get_attr(item, "arguments") or "{}"
        calls.append(
            {
                "call_id": _get_attr(item, "call_id") or _get_attr(item, "id"),
                "name": _get_attr(item, "name"),
                "arguments_json": raw_arguments,
                "arguments": json.loads(raw_arguments),
            }
        )
    return calls


def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _serialize_tool_output(output: Any) -> str:
    if isinstance(output, str):
        return output
    return json.dumps(output, indent=2, sort_keys=True)


def _print_verbose(label: str, payload: Any) -> None:
    print(label, flush=True)
    if isinstance(payload, str):
        print(payload, flush=True)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True), flush=True)
    print(flush=True)


def run_blind_user_llm(
    prompt: str,
    workspace_root: str,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    max_round_trips: int = 8,
    verbose: bool = True,
) -> dict[str, Any]:
    resolved_api_key = resolve_openai_api_key(api_key)
    client = OpenAI(api_key=resolved_api_key)
    tools = build_tool_schemas()
    instructions = _build_system_instruction(workspace_root)

    if verbose:
        _print_verbose("Prompt", prompt)

    tool_calls_log: list[dict[str, Any]] = []
    raw_response_summary: list[dict[str, Any]] = []
    pending_input: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [{"type": "input_text", "text": prompt}],
        }
    ]
    previous_response_id: str | None = None
    final_text = ""

    for round_trip in range(1, max_round_trips + 1):
        request_kwargs: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "tools": tools,
            "input": pending_input,
        }
        if previous_response_id is not None:
            request_kwargs["previous_response_id"] = previous_response_id

        response = client.responses.create(**request_kwargs)
        previous_response_id = getattr(response, "id", None)
        raw_response_summary.append(_response_summary(response, round_trip))

        function_calls = _extract_function_calls(response)
        if not function_calls:
            final_text = _response_text(response)
            break

        pending_input = []
        for function_call in function_calls:
            tool_output = execute_tool_call(function_call["name"], function_call["arguments"])
            logged_call = {
                "round_trip": round_trip,
                "name": function_call["name"],
                "arguments": function_call["arguments"],
                "output": tool_output,
            }
            tool_calls_log.append(logged_call)

            if verbose:
                _print_verbose(f"Tool Call: {function_call['name']}", function_call["arguments"])
                _print_verbose(f"Tool Output: {function_call['name']}", tool_output)

            pending_input.append(
                {
                    "type": "function_call_output",
                    "call_id": function_call["call_id"],
                    "output": _serialize_tool_output(tool_output),
                }
            )
    else:
        final_text = f"Stopped after reaching max_round_trips={max_round_trips} before the model returned a final answer."

    if verbose:
        _print_verbose("Final Assistant Response", final_text)

    return {
        "prompt": prompt,
        "workspace_root": workspace_root,
        "model": model,
        "tool_calls": tool_calls_log,
        "final_text": final_text,
        "raw_response_summary": raw_response_summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a blind-user LLM harness for llmgrader MCP config authoring.")
    parser.add_argument("--workspace-root", required=True, help="Workspace root to expose to the harness.")
    parser.add_argument("--prompt", required=True, help="Blind user prompt to send to the model.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="OpenAI Responses API model name.")
    parser.add_argument("--api-key", default=None, help="OpenAI API key. Defaults to OPENAI_API_KEY.")
    parser.add_argument("--max-round-trips", type=int, default=8, help="Maximum tool-calling round trips.")
    parser.add_argument("--quiet", action="store_true", help="Suppress step-by-step printing.")
    args = parser.parse_args(argv)

    try:
        run_blind_user_llm(
            prompt=args.prompt,
            workspace_root=args.workspace_root,
            model=args.model,
            api_key=args.api_key,
            max_round_trips=args.max_round_trips,
            verbose=not args.quiet,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
