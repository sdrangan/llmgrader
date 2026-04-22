from __future__ import annotations


def make_attribute_description(
    description: str,
    *,
    required: bool,
    type: str,
    example: str | None = None,
    allowed_values: list[str] | None = None,
) -> dict:
    result = {
        "description": description,
        "required": required,
        "type": type,
    }
    if example is not None:
        result["example"] = example
    if allowed_values is not None:
        result["allowed_values"] = allowed_values
    return result


def make_text_content_description(
    description: str,
    *,
    required: bool,
    type: str,
    example: str | None = None,
    allowed_values: list[str] | None = None,
) -> dict:
    result = {
        "description": description,
        "required": required,
        "type": type,
    }
    if example is not None:
        result["example"] = example
    if allowed_values is not None:
        result["allowed_values"] = allowed_values
    return result


def make_related_tool_description(name: str, *, when_to_use: str) -> dict:
    return {
        "name": name,
        "when_to_use": when_to_use,
    }


def make_element_description(
    description: str,
    *,
    required: bool,
    multiple: bool,
    attributes: dict | None = None,
    children: dict | None = None,
    text_content: dict | None = None,
    related_tools: list[dict] | None = None,
    example: str | None = None,
) -> dict:
    result = {
        "description": description,
        "required": required,
        "multiple": multiple,
        "attributes": attributes or {},
        "children": children or {},
    }
    if text_content is not None:
        result["text_content"] = text_content
    if related_tools is not None:
        result["related_tools"] = related_tools
    if example is not None:
        result["example"] = example
    return result