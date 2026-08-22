"""Checks on the provider seam: the PROVIDER_CALLERS table and its inputs.

These are the three assertions §6a deferred until the table existed.
"""

from pathlib import Path

import pytest

from llmgrader.services.grader import (
    PROVIDER_CALLERS,
    Grader,
    _build_message_content,
)
from llmgrader.services.models import DEPRECATED_MODEL_REGISTRY, MODEL_REGISTRY

REF_IMAGES = ["data:image/png;base64,reference-a", "data:image/png;base64,reference-b"]
STUDENT_IMAGES = ["data:image/png;base64,student"]


class _FakeUsage:
    input_tokens = 12
    output_tokens = 5


class _FakeResponse:
    def __init__(self) -> None:
        self.output_text = '{"result":"pass","full_explanation":"ok","feedback":"fine"}'
        self.usage = _FakeUsage()
        self.output = []


class _FakeResponses:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse()


class _FakeOpenAI:
    last_instance = None

    def __init__(self, *args, **kwargs) -> None:
        self.responses = _FakeResponses()
        _FakeOpenAI.last_instance = self


@pytest.fixture()
def grader(tmp_path: Path, monkeypatch) -> Grader:
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setattr("llmgrader.services.grader.OpenAI", _FakeOpenAI)
    monkeypatch.setattr(Grader, "load_unit_pkg", lambda self: None)
    return Grader(scratch_dir=str(tmp_path / "scratch"), soln_pkg=str(tmp_path / "pkg"))


def test_every_registry_provider_has_a_caller() -> None:
    """Keeps the seam honest: a model cannot ship before its caller exists."""
    providers = {
        spec.provider
        for registry in (MODEL_REGISTRY, DEPRECATED_MODEL_REGISTRY)
        for spec in registry.values()
    }

    assert providers
    assert providers <= set(PROVIDER_CALLERS)


def test_unknown_provider_raises_value_error(grader: Grader) -> None:
    with pytest.raises(ValueError, match="Unknown provider 'gemini'"):
        grader._make_llm_caller(
            provider="gemini",
            model="gemini-3.7-flash",
            api_key="test-key",
            task="Grade this solution.",
            timeout=20,
        )


def test_message_content_is_shared_not_rebuilt_per_caller(grader: Grader) -> None:
    """The caller must send exactly what the shared builder produced.

    Rebuilding the annotation or the image ordering inside a provider factory
    is how the paths diverged before, so this pins the payload to the builder.
    """
    task = "Grade this solution."
    text, image_uris = _build_message_content(task, REF_IMAGES, STUDENT_IMAGES)

    call_llm = grader._make_llm_caller(
        provider="openai",
        model="gpt-5.6-luna",
        api_key="test-key",
        task=task,
        timeout=20,
        solution_images=STUDENT_IMAGES,
        ref_solution_images=REF_IMAGES,
    )
    call_llm()

    content = _FakeOpenAI.last_instance.responses.calls[0]["input"][0]["content"]
    assert content[0]["text"] == text
    assert [part["image_url"] for part in content[1:]] == image_uris


def test_builder_is_deterministic_for_identical_inputs() -> None:
    first = _build_message_content("Grade this.", REF_IMAGES, STUDENT_IMAGES)
    second = _build_message_content("Grade this.", list(REF_IMAGES), list(STUDENT_IMAGES))

    assert first == second


def test_builder_orders_reference_images_before_student_images() -> None:
    _, image_uris = _build_message_content("Grade this.", REF_IMAGES, STUDENT_IMAGES)

    assert image_uris == [*REF_IMAGES, *STUDENT_IMAGES]


def test_builder_returns_the_bare_task_when_there_are_no_images() -> None:
    assert _build_message_content("Grade this.", [], []) == ("Grade this.", [])
    assert _build_message_content("Grade this.", None, None) == ("Grade this.", [])


def test_builder_annotates_only_the_image_sets_present() -> None:
    ref_only, _ = _build_message_content("Grade this.", REF_IMAGES, [])
    student_only, _ = _build_message_content("Grade this.", [], STUDENT_IMAGES)

    assert "REFERENCE SOLUTION IMAGES" in ref_only
    assert "STUDENT SOLUTION IMAGES" not in ref_only
    assert "STUDENT SOLUTION IMAGES" in student_only
    assert "REFERENCE SOLUTION IMAGES" not in student_only
