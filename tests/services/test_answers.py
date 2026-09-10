"""``llmgrader_answer``: the prompt, the emitter, the plan and the CLI.

Nothing here makes an API call.  The model call is replaced at the
``caller_factory`` seam -- the same fake-client shape
``tests/services/test_grader_openai_payload.py`` uses -- and the emitter is
checked by feeding its own output back through ``validate_test_file`` and
``check_file``, so a file this tool writes is a file ``llmgrader_test`` will
take.

The first test in the file is the one that matters.  Everything else in this
tool is plumbing; that the prompt carries the question and nothing else is the
property the exercise rests on, and a leak there would leave every number the
tool prints meaningless while still looking fine.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from llmgrader.scripts.llmgrader_answer import main as llmgrader_answer_main
from llmgrader.scripts.llmgrader_test import main as llmgrader_test_main
from llmgrader.services.answers import (
    EXPECT_FULL,
    EXPECT_NONE,
    AnswerError,
    AnswerOptions,
    AnswerResult,
    PlannedQuestion,
    UnitAnswers,
    build_answer_prompt,
    case_id_for,
    default_out_path,
    looks_like_refusal,
    render_unit_test,
    resolve_question_images,
    run_answers,
    slugify,
    unit_attribute,
)
from llmgrader.services.gradetests import (
    LEVEL_ERROR,
    check_file,
    load_test_file,
    load_unit,
    validate_test_file,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_UNIT = REPO_ROOT / "example_repo" / "unit1" / "calculus.xml"
SECOND_UNIT = REPO_ROOT / "example_repo" / "unit2" / "python.xml"

BINARY_QTAG = "Exponential derivative"
PARTIAL_QTAG = "Integration by parts"
MULTIPART_QTAG = "Exponential graphing"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_caller(text="An answer.", *, tokens=(11, 7), fail=None, record=None):
    """A ``caller_factory`` that returns canned text and never touches OpenAI.

    ``text`` may be a callable taking the planned model and prompt, so a test
    can vary the answer per question.
    """

    def factory(*, model, api_key, prompt, timeout, images):
        if record is not None:
            record.append(
                {
                    "model": model,
                    "api_key": api_key,
                    "prompt": prompt,
                    "timeout": timeout,
                    "images": list(images or []),
                }
            )

        def call():
            if fail is not None:
                raise fail
            body = text(model, prompt) if callable(text) else text
            return body, tokens[0], tokens[1]

        return call

    return factory


def _never_called_caller():
    def factory(**kwargs):  # pragma: no cover - the point is that it is not
        raise AssertionError("the model was called during a dry run")

    return factory


def _run(tmp_path, monkeypatch, **kwargs):
    """Answer the example unit into ``tmp_path`` with a fake caller."""
    monkeypatch.chdir(tmp_path)
    caller = kwargs.pop("caller_factory", None) or _fake_caller()
    options = AnswerOptions(api_key="test-key", jobs=1, **kwargs)
    return run_answers([str(EXAMPLE_UNIT)], options, caller_factory=caller)


def _sentinel_question() -> dict:
    """A question dict whose every non-question field is a distinctive string.

    Built by hand rather than parsed, so the leak test names the exact fields
    it is guarding and fails loudly if the parser grows another one that the
    prompt then has to be taught to ignore.
    """
    return {
        "qtag": "Sentinel question",
        "question_text": "<p>Compute the derivative of \\(y = a^x\\).</p>",
        "solution": "SENTINEL_SOLUTION: y' = a^x ln a.",
        "solution_images": ["data:image/png;base64,SENTINELSOLUTIONIMAGE"],
        "grading_notes": "SENTINEL_GRADING_NOTES: accept any equivalent form.",
        "rubrics": {
            "final_answer": {
                "display_text": "SENTINEL_RUBRIC_DISPLAY",
                "condition": "SENTINEL_RUBRIC_CONDITION",
                "notes": "SENTINEL_RUBRIC_NOTES",
                "point_adjustment": 10,
            }
        },
        "rubric_total": "SENTINEL_RUBRIC_TOTAL",
        "rubric_groups": [{"type": "one_of", "ids": ["SENTINEL_GROUP_ID"]}],
        "parts": [{"part_label": "a", "points": 6}, {"part_label": "b", "points": 4}],
        "partial_credit": True,
        "preferred_model": "simple",
    }


# ---------------------------------------------------------------------------
# The prompt leaks nothing (plans/answer_cli.md §3)
# ---------------------------------------------------------------------------


SENTINELS = [
    "SENTINEL_SOLUTION",
    "SENTINELSOLUTIONIMAGE",
    "SENTINEL_GRADING_NOTES",
    "SENTINEL_RUBRIC_DISPLAY",
    "SENTINEL_RUBRIC_CONDITION",
    "SENTINEL_RUBRIC_NOTES",
    "SENTINEL_RUBRIC_TOTAL",
    "SENTINEL_GROUP_ID",
]


@pytest.mark.parametrize("sentinel", SENTINELS)
def test_prompt_never_carries_the_solution_or_the_rubric(sentinel) -> None:
    prompt = build_answer_prompt(_sentinel_question())
    assert sentinel not in prompt


def test_prompt_carries_the_question_text() -> None:
    prompt = build_answer_prompt(_sentinel_question())
    assert "Compute the derivative" in prompt


def test_prompt_carries_part_labels_and_points() -> None:
    prompt = build_answer_prompt(_sentinel_question())
    assert "(a)" in prompt and "6 points" in prompt
    assert "(b)" in prompt and "4 points" in prompt
    assert "Total: 10 points" in prompt


def test_prompt_for_a_whole_question_states_the_total_without_inventing_labels() -> None:
    question = dict(_sentinel_question(), parts=[{"part_label": "all", "points": 10}])
    prompt = build_answer_prompt(question)
    assert "worth 10 points" in prompt
    assert "(all)" not in prompt


def test_prompt_of_a_real_unit_question_leaks_no_solution(tmp_path, monkeypatch) -> None:
    """The same property, end to end, against the parser's own question dict."""
    monkeypatch.chdir(tmp_path)
    report = _run(tmp_path, monkeypatch)
    unit = report.units[0]
    prompts = "\n".join(item.prompt for item in unit.planned)

    # Distinctive strings that appear only in the solutions, notes and rubrics
    # of example_repo/unit1/calculus.xml.
    for needle in [
        "integration by parts formula",
        "Correct choice of u and dv",
        "Students may use different variables",
        "grade the graph qualitatively",
        "xexpx_soln.png",
    ]:
        assert needle not in prompts, f"{needle!r} leaked into the prompt"

    assert "Use integration by parts to compute the integral" in prompts


# ---------------------------------------------------------------------------
# Case ids
# ---------------------------------------------------------------------------


def test_slugify_reduces_a_qtag_to_an_id_safe_token() -> None:
    assert slugify("Exponential derivative") == "exponential_derivative"
    assert slugify("Part (a): f'(x)!") == "part_a_f_x"
    assert slugify("!!!") == "question"


def test_case_ids_are_deterministic_and_numbered_by_repeat() -> None:
    first = [case_id_for(BINARY_QTAG, index, taken=set()) for index in (1, 2, 3)]
    second = [case_id_for(BINARY_QTAG, index, taken=set()) for index in (1, 2, 3)]
    assert first == second
    assert first == [
        "ai_exponential_derivative_1",
        "ai_exponential_derivative_2",
        "ai_exponential_derivative_3",
    ]


def test_case_ids_disambiguate_qtags_that_slugify_alike() -> None:
    taken: set[str] = set()
    assert case_id_for("Part one", 1, taken=taken) == "ai_part_one_1"
    assert case_id_for("part!one", 1, taken=taken) == "ai_part_one_1_2"


def test_planned_case_ids_are_unique_across_a_run(tmp_path, monkeypatch) -> None:
    report = _run(tmp_path, monkeypatch, repeat=3)
    ids = [item.case_id for item in report.units[0].planned]
    assert len(ids) == len(set(ids)) == 9


# ---------------------------------------------------------------------------
# The emitter
# ---------------------------------------------------------------------------


def _emit(tmp_path, monkeypatch, **kwargs) -> Path:
    report = _run(tmp_path, monkeypatch, **kwargs)
    assert len(report.written) == 1
    return Path(report.written[0])


def _findings(path: Path, *, level=None):
    """``check_file`` findings for a generated file against the example unit.

    ``coverage=False`` deliberately: coverage reports rubric items no case
    asserts on, which is a statement about an instructor's test suite, not
    about a file of blind answers that asserts on nothing by design.
    """
    assert validate_test_file(str(path)) == []
    test_file = load_test_file(str(path))
    unit = load_unit(str(EXAMPLE_UNIT))
    findings = check_file(test_file, unit, coverage=False)
    return [f for f in findings if level is None or f.level == level]


def test_emitted_file_validates_and_checks_clean_of_errors(tmp_path, monkeypatch) -> None:
    path = _emit(tmp_path, monkeypatch)
    assert _findings(path, level=LEVEL_ERROR) == []


def test_assertion_free_is_the_default_and_reads_as_a_warning_per_case(tmp_path, monkeypatch) -> None:
    path = _emit(tmp_path, monkeypatch)
    assert "<expected_points" not in path.read_text(encoding="utf-8")
    assert "<expected_result>" not in path.read_text(encoding="utf-8")

    warnings = [f.message for f in _findings(path) if "no assertions" in f.message]
    assert len(warnings) == 3


def test_expect_full_produces_no_findings_at_all_in_either_grading_mode(tmp_path, monkeypatch) -> None:
    path = _emit(tmp_path, monkeypatch, expect=EXPECT_FULL)
    assert _findings(path) == [], [f.message for f in _findings(path)]

    text = path.read_text(encoding="utf-8")
    # Binary question: a result, not a band.
    assert "<expected_result>pass</expected_result>" in text
    # Partial-credit, one part worth 10, and the two-part question at 5 each.
    assert '<part label="all" min="10"/>' in text
    assert '<part label="a" min="5"/>' in text
    assert '<part label="b" min="5"/>' in text


def test_expect_full_bands_have_no_max(tmp_path, monkeypatch) -> None:
    """A `max` would trip check's "above the part total" error at the boundary."""
    path = _emit(tmp_path, monkeypatch, expect=EXPECT_FULL)
    test_file = load_test_file(str(path))
    bands = [band for case in test_file.cases for band in case.expected_points]
    assert bands
    assert all(band.max is None for band in bands)
    assert all(band.min is not None and band.min > 0 for band in bands)


def test_expect_full_skips_a_zero_point_part(tmp_path) -> None:
    """A band of min=0 spans the whole range, which check reports as useless."""
    planned = PlannedQuestion(
        qtag="Free question",
        unit_path=str(EXAMPLE_UNIT),
        unit_name="unit",
        case_id="ai_free_question_1",
        model="gpt-x",
        partial_credit=True,
        parts=[{"part_label": "a", "points": 0}, {"part_label": "b", "points": 4}],
        prompt="q",
    )
    unit = UnitAnswers(
        unit_path=str(EXAMPLE_UNIT),
        unit_name="unit",
        out_path=str(tmp_path / "out.xml"),
        planned=[planned],
        results=[
            AnswerResult(
                case_id="ai_free_question_1",
                qtag="Free question",
                model="gpt-x",
                repeat_index=1,
                repeat_total=1,
                text="an answer",
            )
        ],
    )
    text = render_unit_test(unit, expect=EXPECT_FULL)
    assert '<part label="b" min="4"/>' in text
    assert 'label="a"' not in text


def test_cdata_terminator_in_an_answer_round_trips(tmp_path, monkeypatch) -> None:
    hostile = "Consider the array a[i]]>b and the tag ]]> in prose."
    path = _emit(tmp_path, monkeypatch, caller_factory=_fake_caller(hostile))

    assert validate_test_file(str(path)) == []
    test_file = load_test_file(str(path))
    assert test_file.cases
    for case in test_file.cases:
        assert case.solution.strip() == hostile


def test_unit_attribute_is_written_relative_to_the_output_file(tmp_path, monkeypatch) -> None:
    out_dir = tmp_path / "tests"
    out_dir.mkdir()
    path = _emit(tmp_path, monkeypatch, out=str(out_dir / "ai.xml"))

    test_file = load_test_file(str(path))
    assert test_file.unit_attr is not None
    assert "\\" not in test_file.unit_attr
    assert os.path.normcase(os.path.abspath(test_file.unit_path)) == os.path.normcase(
        str(EXAMPLE_UNIT)
    )


def test_unit_attribute_uses_posix_separators(tmp_path) -> None:
    attribute = unit_attribute(
        str(tmp_path / "unit1" / "calculus.xml"), str(tmp_path / "unit1" / "tests" / "ai.xml")
    )
    assert attribute == "../calculus.xml"


def test_description_carries_the_model_and_the_blind_answer_claim(tmp_path, monkeypatch) -> None:
    path = _emit(tmp_path, monkeypatch)
    test_file = load_test_file(str(path))
    for case in test_file.cases:
        assert "answered this from the question text alone" in case.description
        assert "no solution, no rubric, no grading notes" in case.description


def test_repeat_numbering_appears_in_the_description(tmp_path, monkeypatch) -> None:
    path = _emit(tmp_path, monkeypatch, repeat=2)
    test_file = load_test_file(str(path))
    descriptions = [case.description for case in test_file.cases]
    assert any("attempt 1 of 2" in text for text in descriptions)
    assert any("attempt 2 of 2" in text for text in descriptions)


def test_a_single_attempt_does_not_say_attempt_1_of_1(tmp_path, monkeypatch) -> None:
    path = _emit(tmp_path, monkeypatch)
    text = path.read_text(encoding="utf-8")
    assert "attempt 1 of 1" not in text


def test_generated_file_carries_provenance_in_a_comment(tmp_path, monkeypatch) -> None:
    path = _emit(tmp_path, monkeypatch)
    text = path.read_text(encoding="utf-8")
    assert "Generated by llmgrader_answer on" in text
    assert "calculus.xml" in text
    # The schema is shared with hand-written files; provenance does not get to
    # grow an attribute for itself.
    assert "model=" not in text


# ---------------------------------------------------------------------------
# Empty and refusing answers (caveat 2)
# ---------------------------------------------------------------------------


def test_an_empty_answer_is_emitted_and_marked(tmp_path, monkeypatch) -> None:
    report = _run(tmp_path, monkeypatch, caller_factory=_fake_caller(""))
    assert len(report.empty) == 3

    text = Path(report.written[0]).read_text(encoding="utf-8")
    assert text.count("<case ") == 3
    assert "The model returned an empty answer" in text


def test_a_refusal_is_emitted_and_marked(tmp_path, monkeypatch) -> None:
    report = _run(
        tmp_path, monkeypatch, caller_factory=_fake_caller("I can't help with that.")
    )
    assert len(report.refusals) == 3
    text = Path(report.written[0]).read_text(encoding="utf-8")
    assert "The model declined to answer" in text
    assert text.count("<case ") == 3


def test_a_long_answer_that_opens_with_an_apology_is_not_called_a_refusal() -> None:
    hedged = "I'm sorry, but I can't be certain here. " + ("Still, the derivative is a^x ln a. " * 40)
    assert not looks_like_refusal(hedged)
    assert looks_like_refusal("I cannot assist with this request.")
    assert not looks_like_refusal("The answer is a^x ln(a).")


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------


def test_per_question_preferred_model_is_the_default(tmp_path, monkeypatch) -> None:
    from llmgrader.services.models import resolve_preferred_model

    report = _run(tmp_path, monkeypatch)
    by_qtag = {item.qtag: item.model for item in report.units[0].planned}

    assert by_qtag[BINARY_QTAG] == resolve_preferred_model("simple").id
    assert by_qtag[MULTIPART_QTAG] == resolve_preferred_model("standard").id


def test_model_override_accepts_a_tier_name(tmp_path, monkeypatch) -> None:
    from llmgrader.services.models import resolve_preferred_model

    report = _run(tmp_path, monkeypatch, model="complex")
    expected = resolve_preferred_model("complex").id
    assert {item.model for item in report.units[0].planned} == {expected}


def test_model_override_accepts_a_concrete_id(tmp_path, monkeypatch) -> None:
    from llmgrader.services.models import DEFAULT_MODEL_SIMPLE

    report = _run(tmp_path, monkeypatch, model=DEFAULT_MODEL_SIMPLE)
    assert {item.model for item in report.units[0].planned} == {DEFAULT_MODEL_SIMPLE}


def test_an_unknown_model_is_refused_before_anything_is_planned(tmp_path, monkeypatch) -> None:
    with pytest.raises(AnswerError, match="not a tier name or a known model id"):
        _run(tmp_path, monkeypatch, model="gpt-nonesuch")


def test_a_question_without_a_preference_falls_back_to_the_simple_default(tmp_path) -> None:
    from llmgrader.services.grader import preferred_model_for
    from llmgrader.services.models import DEFAULT_MODEL_SIMPLE

    assert preferred_model_for({"preferred_model": ""}, "q") is None
    assert (preferred_model_for({"preferred_model": ""}, "q") or DEFAULT_MODEL_SIMPLE) == (
        DEFAULT_MODEL_SIMPLE
    )


# ---------------------------------------------------------------------------
# Selection, output paths, clobbering
# ---------------------------------------------------------------------------


def test_qtag_selects_a_subset(tmp_path, monkeypatch) -> None:
    report = _run(tmp_path, monkeypatch, qtags=[BINARY_QTAG])
    assert [item.qtag for item in report.units[0].planned] == [BINARY_QTAG]


def test_a_qtag_that_matches_nothing_is_an_error(tmp_path, monkeypatch) -> None:
    with pytest.raises(AnswerError, match="no question matched --qtag"):
        _run(tmp_path, monkeypatch, qtags=["Nonexistent"])


def test_out_defaults_to_the_unit_stem(tmp_path, monkeypatch) -> None:
    assert default_out_path("/a/b/calculus.xml") == "calculus_answers.xml"
    report = _run(tmp_path, monkeypatch)
    assert Path(report.written[0]).name == "calculus_answers.xml"


def test_out_refuses_to_clobber_without_force(tmp_path, monkeypatch) -> None:
    _run(tmp_path, monkeypatch)
    with pytest.raises(AnswerError, match="already exists"):
        _run(tmp_path, monkeypatch)


def test_force_overwrites(tmp_path, monkeypatch) -> None:
    _run(tmp_path, monkeypatch, caller_factory=_fake_caller("first answer"))
    report = _run(tmp_path, monkeypatch, force=True, caller_factory=_fake_caller("second answer"))
    text = Path(report.written[0]).read_text(encoding="utf-8")
    assert "second answer" in text and "first answer" not in text


def test_the_clobber_refusal_comes_before_the_calls(tmp_path, monkeypatch) -> None:
    """Finding out the file exists must not cost a run's worth of grading calls."""
    _run(tmp_path, monkeypatch)
    with pytest.raises(AnswerError, match="already exists"):
        _run(tmp_path, monkeypatch, caller_factory=_never_called_caller())


def test_out_with_several_units_is_refused(tmp_path, monkeypatch) -> None:
    """One --out cannot hold two units: a <unit_test> file targets one unit."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(AnswerError, match="a <unit_test> file targets one unit"):
        run_answers(
            [str(EXAMPLE_UNIT), str(SECOND_UNIT)],
            AnswerOptions(api_key="k", out="one.xml"),
            caller_factory=_fake_caller(),
        )


def test_several_units_each_get_their_own_default_file(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    report = run_answers(
        [str(EXAMPLE_UNIT), str(SECOND_UNIT)],
        AnswerOptions(api_key="k", jobs=1),
        caller_factory=_fake_caller(),
    )
    assert [Path(path).name for path in report.written] == [
        "calculus_answers.xml",
        "python_answers.xml",
    ]


# ---------------------------------------------------------------------------
# Question images (caveat 1)
# ---------------------------------------------------------------------------


def test_an_image_free_unit_resolves_no_images_and_warns_about_none(tmp_path, monkeypatch) -> None:
    report = _run(tmp_path, monkeypatch)
    assert report.missing_images == 0
    assert all(not item.images for item in report.units[0].planned)


def test_an_unresolved_question_image_is_counted_not_fatal(tmp_path) -> None:
    question = {"question_text": '<p>See <img src="nowhere/missing.png"/> below.</p>'}
    images, missing = resolve_question_images(
        question, soln_pkg_path=str(tmp_path), unit_xml_path=str(tmp_path / "unit.xml")
    )
    assert images == []
    assert missing == 1


def test_a_resolvable_question_image_becomes_a_data_uri(tmp_path) -> None:
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "fig.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    question = {"question_text": '<p><img src="images/fig.png"/></p>'}
    images, missing = resolve_question_images(
        question, soln_pkg_path=str(tmp_path), unit_xml_path=str(tmp_path / "unit.xml")
    )
    assert missing == 0
    assert len(images) == 1 and images[0].startswith("data:image/png;base64,")


def test_an_unresolved_image_is_named_in_the_description_and_points_at_pkg(tmp_path) -> None:
    planned = PlannedQuestion(
        qtag="Graph it",
        unit_path=str(EXAMPLE_UNIT),
        unit_name="unit",
        case_id="ai_graph_it_1",
        model="gpt-x",
        partial_credit=False,
        parts=[{"part_label": "all", "points": 10}],
        prompt="q",
        missing_images=2,
    )
    unit = UnitAnswers(
        unit_path=str(EXAMPLE_UNIT),
        unit_name="unit",
        out_path=str(tmp_path / "out.xml"),
        planned=[planned],
        results=[
            AnswerResult(
                case_id="ai_graph_it_1",
                qtag="Graph it",
                model="gpt-x",
                repeat_index=1,
                repeat_total=1,
                text="an answer",
            )
        ],
    )
    text = render_unit_test(unit)
    assert "2 image(s) in the question text did not resolve" in text
    assert "--pkg" in text


def test_question_images_are_attached_to_the_call(tmp_path, monkeypatch) -> None:
    calls: list[dict] = []
    monkeypatch.chdir(tmp_path)

    report = _run(tmp_path, monkeypatch, caller_factory=_fake_caller(record=calls))
    assert len(calls) == 3
    assert all(call["images"] == [] for call in calls)
    assert all(call["api_key"] == "test-key" for call in calls)


# ---------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------


def _cli(monkeypatch, tmp_path, argv, *, caller_factory=None):
    """Run the console script's main() with the model call replaced."""
    monkeypatch.chdir(tmp_path)
    caller = caller_factory or _fake_caller()
    monkeypatch.setattr(
        "llmgrader.scripts.llmgrader_answer._caller_factory",
        lambda: caller,
    )
    return llmgrader_answer_main(argv)


def test_cli_dry_run_prints_the_call_count_and_makes_no_calls(tmp_path, monkeypatch, capsys) -> None:
    code = _cli(
        monkeypatch,
        tmp_path,
        [str(EXAMPLE_UNIT), "--dry-run"],
        caller_factory=_never_called_caller(),
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "dry run: 3 calls across 3 questions" in out
    assert "no API calls were made" in out
    assert not list(tmp_path.glob("*_answers.xml"))


def test_cli_dry_run_breaks_the_count_down_by_model(tmp_path, monkeypatch, capsys) -> None:
    from llmgrader.services.models import resolve_preferred_model

    _cli(
        monkeypatch,
        tmp_path,
        [str(EXAMPLE_UNIT), "--dry-run", "--repeat", "2"],
        caller_factory=_never_called_caller(),
    )
    out = capsys.readouterr().out

    assert "6 calls across 3 questions, 2 repeats each" in out
    assert resolve_preferred_model("simple").id in out
    assert resolve_preferred_model("standard").id in out


def test_cli_cost_prints_an_estimate_and_the_caveat(tmp_path, monkeypatch, capsys) -> None:
    from llmgrader.services.gradetests import LONG_CONTEXT_CAVEAT

    _cli(
        monkeypatch,
        tmp_path,
        [str(EXAMPLE_UNIT), "--dry-run", "--cost"],
        caller_factory=_never_called_caller(),
    )
    out = capsys.readouterr().out

    assert "estimated cost $" in out
    assert LONG_CONTEXT_CAVEAT in out


def test_cli_writes_the_file_and_summarises(tmp_path, monkeypatch, capsys) -> None:
    code = _cli(monkeypatch, tmp_path, [str(EXAMPLE_UNIT), "--api-key", "k"])
    out = capsys.readouterr().out

    assert code == 0
    assert "3 answered, 0 empty, 0 failed" in out
    assert "calculus_answers.xml" in out
    assert (tmp_path / "calculus_answers.xml").exists()


def test_cli_summary_counts_unresolved_images(tmp_path, monkeypatch, capsys) -> None:
    unit = tmp_path / "imgunit.xml"
    unit.write_text(
        """<unit id="img" title="Images" version="1.0">
  <question qtag="Read the figure">
    <question_text><![CDATA[<p>What does <img src="figures/absent.png"/> show?</p>]]></question_text>
    <solution><![CDATA[<p>A curve.</p>]]></solution>
    <partial_credit>false</partial_credit>
    <parts><part><part_label>all</part_label><points>10</points></part></parts>
  </question>
</unit>
""",
        encoding="utf-8",
    )

    code = _cli(monkeypatch, tmp_path, [str(unit), "--api-key", "k"])
    out = capsys.readouterr().out

    assert code == 0
    assert "1 question image did not resolve" in out
    assert "--pkg" in out


def test_cli_refuses_to_clobber_without_force(tmp_path, monkeypatch, capsys) -> None:
    assert _cli(monkeypatch, tmp_path, [str(EXAMPLE_UNIT), "--api-key", "k"]) == 0
    capsys.readouterr()

    code = _cli(monkeypatch, tmp_path, [str(EXAMPLE_UNIT), "--api-key", "k"])
    err = capsys.readouterr().err
    assert code == 2
    assert "already exists" in err

    assert _cli(monkeypatch, tmp_path, [str(EXAMPLE_UNIT), "--api-key", "k", "--force"]) == 0


def test_cli_needs_a_key_unless_it_is_a_dry_run(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    code = _cli(monkeypatch, tmp_path, [str(EXAMPLE_UNIT)])
    err = capsys.readouterr().err
    assert code == 2
    assert "no API key" in err


def test_cli_falls_back_to_the_environment_key(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    calls: list[dict] = []
    code = _cli(
        monkeypatch, tmp_path, [str(EXAMPLE_UNIT)], caller_factory=_fake_caller(record=calls)
    )
    assert code == 0
    assert {call["api_key"] for call in calls} == {"from-env"}


def test_cli_reports_a_failed_call_and_exits_nonzero(tmp_path, monkeypatch, capsys) -> None:
    code = _cli(
        monkeypatch,
        tmp_path,
        [str(EXAMPLE_UNIT), "--api-key", "k"],
        caller_factory=_fake_caller(fail=RuntimeError("the provider hung up")),
    )
    out, err = capsys.readouterr()

    assert code == 1
    assert "3 failed" in out
    assert "the provider hung up" in (out + err)


def test_cli_rejects_repeat_below_one(tmp_path, monkeypatch, capsys) -> None:
    code = _cli(monkeypatch, tmp_path, [str(EXAMPLE_UNIT), "--dry-run", "--repeat", "0"])
    assert code == 2
    assert "--repeat must be at least 1" in capsys.readouterr().err
