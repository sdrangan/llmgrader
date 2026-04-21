from llmgrader.services.grader import Grader


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
        self.args = args
        self.kwargs = kwargs
        self.responses = _FakeResponses()
        _FakeOpenAI.last_instance = self


def test_openai_multimodal_payload_wraps_content_in_user_message(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setattr("llmgrader.services.grader.OpenAI", _FakeOpenAI)
    monkeypatch.setattr(Grader, "load_unit_pkg", lambda self: None)

    grader = Grader(scratch_dir=str(tmp_path / "scratch"), soln_pkg=str(tmp_path / "pkg"))

    call_llm = grader._make_llm_caller(
        provider="openai",
        model="gpt-5.4-mini",
        api_key="test-key",
        task="Grade this solution.",
        timeout=20,
        solution_images=["data:image/png;base64,student"],
        ref_solution_images=["data:image/png;base64,reference"],
    )

    result, input_tokens, output_tokens, tool_call_summary = call_llm()

    assert result.result == "pass"
    assert input_tokens == 12
    assert output_tokens == 5
    assert tool_call_summary == ""

    request_kwargs = _FakeOpenAI.last_instance.responses.calls[0]
    assert request_kwargs["input"] == [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        "Grade this solution.\n\n"
                        "--- REFERENCE SOLUTION IMAGES ---\n"
                        "See reference solution images below.\n\n"
                        "--- STUDENT SOLUTION IMAGES ---\n"
                        "See attached student images below."
                    ),
                },
                {"type": "input_image", "image_url": "data:image/png;base64,reference"},
                {"type": "input_image", "image_url": "data:image/png;base64,student"},
            ],
        }
    ]
    assert request_kwargs["model"] == "gpt-5.4-mini"
    assert request_kwargs["timeout"] == 20
    assert request_kwargs["text"] == {"format": {"type": "json_object"}}