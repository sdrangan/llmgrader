"""Live smoke tests for every model in the registry.

Opt-in and not free: see ``conftest.live_enabled`` for the gating and
``pyproject.toml`` for the ``-m 'not live'`` default that keeps them out of a
bare ``pytest`` run.  Run them with::

    LLMGRADER_RUN_LIVE_TESTS=1 OPENAI_API_KEY=... pytest tests/live -m live

Parametrized over :data:`MODEL_REGISTRY`, so adding a model to the registry
adds its coverage here with no edit to this file.  What is asserted, and what
deliberately is not:

* Reachability is the point of the suite.  A retired or renamed model id is
  the failure mode that produced the slate refresh, and it is invisible
  offline -- every mocked test in ``tests/services/`` passes against a model
  that no longer exists.
* The correctness floor is coarse on purpose.  This is a smoke test, not a
  benchmark: a flaky assertion here is worse than no assertion, so the two
  questions have single agreed-on answers and the wrong answers are wrong in a
  way no rubric reading can rescue.  Whether a model grades *real* student work
  well is a question for step 9, against real submissions.
"""

from __future__ import annotations

import base64

import pytest

from llmgrader.services.grader import GradeResult
from llmgrader.services.models import MODEL_REGISTRY, get_spec


pytestmark = pytest.mark.live

MODEL_IDS = list(MODEL_REGISTRY)

#: A 1x1 transparent PNG.  The image path is what is under test, not anything
#: depicted, so the smallest valid file is the right one -- it keeps the image
#: call from costing appreciably more than a text one.
TINY_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
    "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

#: qtag, student answer, and any attached images, per scenario.  Answers are
#: written to be unarguable in both directions: the wrong ones are not weak
#: answers, they are answers to a different question.
SCENARIOS: dict[str, dict] = {
    "recall_correct": {
        "qtag": "q_recall",
        "answer": "The SI base unit of electric current is the ampere, symbol A.",
    },
    "recall_wrong": {
        "qtag": "q_recall",
        "answer": "The SI base unit of electric current is the volt, symbol V.",
    },
    "derive_correct": {
        "qtag": "q_derive",
        "answer": "By the power rule, f'(x) = 3x^2.",
    },
    "derive_wrong": {
        # The antiderivative, not the derivative: it satisfies neither rubric
        # item, so a model that reads the rubric at all must award zero.
        "qtag": "q_derive",
        "answer": "The derivative of x^3 is x^4/4 + C.",
    },
    "image": {
        "qtag": "q_recall",
        "answer": "The ampere, symbol A. My work is in the attached image.",
        "solution_images": [TINY_PNG],
    },
    "web_search": {
        "qtag": "q_web",
        "answer": (
            "The ampere is defined by fixing the elementary charge e to "
            "1.602176634e-19 coulomb, per the SI brochure."
        ),
    },
}

#: One live call per (model, scenario), reused across the tests that assert on
#: it.  Reachability and schema are two claims about the same response, and
#: paying twice for it would double the cost of the suite for nothing.
_GRADE_CACHE: dict[tuple[str, str], dict] = {}


def graded(run_grade, model_id: str, scenario: str) -> dict:
    """Return the grade for ``scenario``, calling the API at most once."""
    key = (model_id, scenario)
    if key not in _GRADE_CACHE:
        spec = SCENARIOS[scenario]
        _GRADE_CACHE[key] = run_grade(
            model_id,
            spec["qtag"],
            spec["answer"],
            scenario,
            solution_images=spec.get("solution_images"),
        )
    return _GRADE_CACHE[key]


def assert_no_api_error(grade: dict, model_id: str, scenario: str) -> None:
    """Fail with the grader's own explanation, which carries the API message.

    ``Grader.grade`` catches provider exceptions and returns
    ``result="error"`` rather than raising, so an unreachable model looks like
    a graded submission unless the explanation is surfaced.
    """
    assert grade.get("result") != "error", (
        f"{model_id} returned an error for scenario {scenario!r}: "
        f"{grade.get('full_explanation')}"
    )


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_model_is_reachable(run_grade, model_id: str) -> None:
    """A trivial grading call completes without an API error.

    This is the check that catches a retired or renamed model id.
    """
    grade = graded(run_grade, model_id, "recall_correct")

    assert_no_api_error(grade, model_id, "recall_correct")
    assert grade.get("full_explanation")


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_response_satisfies_grade_result_schema(run_grade, model_id: str) -> None:
    """The response parsed as GraderRawResult and post-processed into a GradeResult.

    Reaching a non-error grade already proves the raw parse -- the caller
    raises on a GraderRawResult validation failure -- so what is left to check
    is the post-processed contract the rest of the app consumes.
    """
    grade = graded(run_grade, model_id, "recall_correct")
    assert_no_api_error(grade, model_id, "recall_correct")

    result = GradeResult.model_validate(grade)

    assert result.result in {"pass", "fail", "partial"}
    assert result.points is not None and result.max_points is not None
    assert 0 <= result.points <= result.max_points


@pytest.mark.parametrize("model_id", MODEL_IDS)
@pytest.mark.parametrize("scenario", ["recall_correct", "derive_correct"])
def test_correct_answer_scores_full_marks(run_grade, model_id: str, scenario: str) -> None:
    grade = graded(run_grade, model_id, scenario)
    assert_no_api_error(grade, model_id, scenario)

    assert grade["points"] == grade["max_points"], (
        f"{model_id} gave {grade['points']}/{grade['max_points']} to a correct "
        f"answer in {scenario!r}: {grade.get('feedback')}"
    )
    assert grade["result"] == "pass"


@pytest.mark.parametrize("model_id", MODEL_IDS)
@pytest.mark.parametrize("scenario", ["recall_wrong", "derive_wrong"])
def test_wrong_answer_scores_zero(run_grade, model_id: str, scenario: str) -> None:
    grade = graded(run_grade, model_id, scenario)
    assert_no_api_error(grade, model_id, scenario)

    assert grade["points"] == 0, (
        f"{model_id} gave {grade['points']}/{grade['max_points']} to a wrong "
        f"answer in {scenario!r}: {grade.get('feedback')}"
    )
    assert grade["result"] == "fail"


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_image_input_when_supported(run_grade, model_id: str) -> None:
    """`supports_images` is a claim about the wire, so put an image on the wire.

    Only the absence of an error is asserted: a 1x1 PNG carries no content to
    grade, and what the flag promises is that the request shape is accepted.
    """
    spec = get_spec(model_id)
    if not spec.supports_images:
        pytest.skip(f"{model_id} does not declare supports_images")

    grade = graded(run_grade, model_id, "image")

    assert_no_api_error(grade, model_id, "image")


@pytest.mark.parametrize("model_id", MODEL_IDS)
def test_web_search_when_supported(run_grade, model_id: str) -> None:
    """A tool-enabled call comes back and reports what the model did.

    The score is not asserted: enabling a tool drops the ``json_object``
    response format, so this call exercises the one path where the output shape
    is the model's own doing.
    """
    spec = get_spec(model_id)
    if not spec.supports_web_search:
        pytest.skip(f"{model_id} does not declare supports_web_search")

    grade = graded(run_grade, model_id, "web_search")

    assert_no_api_error(grade, model_id, "web_search")
    # grade_post_process folds tool_call_summary into the explanation and emits
    # the "Tool Summary:" header only when that summary is non-empty, so this
    # is the non-empty-summary assertion on the value the app actually keeps.
    assert "Tool Summary:" in grade["full_explanation"], grade["full_explanation"]
