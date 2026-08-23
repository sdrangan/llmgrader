"""Symbolic preferred_model: resolution, precedence and wiring.

Before this, `preferred_model` was parsed, carried in the question dict, and
consumed by nothing at all -- the model was whatever the client sent.
"""

import logging
from pathlib import Path

import pytest

from llmgrader.app import create_app
from llmgrader.services.grader import Grader, preferred_model_for
from llmgrader.services.models import (
    DEFAULT_MODEL_COMPLEX,
    DEFAULT_MODEL_SIMPLE,
    LEGACY_TIER_ALIASES,
    TIERS,
    default_for_tier,
    resolve_preferred_model,
)


# ---------------------------------------------------------------------------
#  C1: resolution
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tier", TIERS)
def test_a_tier_name_resolves_to_that_tiers_default(tier: str) -> None:
    spec = resolve_preferred_model(tier)

    assert spec is not None
    assert spec.id == default_for_tier(tier).id
    assert spec.tier_default


def test_the_symbolic_names_are_the_tier_names() -> None:
    assert resolve_preferred_model("simple").id == DEFAULT_MODEL_SIMPLE
    assert resolve_preferred_model("complex").id == DEFAULT_MODEL_COMPLEX


@pytest.mark.parametrize("legacy,tier", sorted(LEGACY_TIER_ALIASES.items()))
def test_a_legacy_tier_name_resolves_forward_and_warns(legacy, tier, caplog) -> None:
    """`cheap`/`mid`/`strong` shipped, so course XML we do not control has them.

    Treated exactly like a retired model id: it resolves to what replaced it
    and logs a deprecation, rather than degrading to the app-wide default.
    """
    with caplog.at_level(logging.WARNING, logger="llmgrader.services.models"):
        spec = resolve_preferred_model(legacy, qtag="q1")

    assert spec is not None
    assert spec.id == default_for_tier(tier).id
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert legacy in logged and tier in logged


def test_a_concrete_live_id_resolves_to_itself() -> None:
    assert resolve_preferred_model("gpt-5.6-terra").id == "gpt-5.6-terra"


def test_a_retired_id_resolves_forward_to_its_replacement(caplog) -> None:
    """A preference names a model to select, so it must land on a live one."""
    with caplog.at_level(logging.WARNING, logger="llmgrader.services.models"):
        spec = resolve_preferred_model("gpt-5.4", qtag="q1")

    assert spec.id == "gpt-5.6-terra"
    assert any("gpt-5.4" in r.getMessage() for r in caplog.records)


def test_surrounding_whitespace_is_tolerated() -> None:
    assert resolve_preferred_model("  complex  ").id == DEFAULT_MODEL_COMPLEX


def test_an_unresolvable_value_returns_none_and_names_it(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="llmgrader.services.models"):
        assert resolve_preferred_model("gpt-turbo-9000", qtag="q_chain_rule") is None

    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "gpt-turbo-9000" in logged
    assert "q_chain_rule" in logged


@pytest.mark.parametrize("value", [None, "", "   "])
def test_an_absent_preference_is_silent(value, caplog) -> None:
    """The common case: warning here would fire on every grading request."""
    with caplog.at_level(logging.WARNING, logger="llmgrader.services.models"):
        assert resolve_preferred_model(value) is None

    assert not caplog.records


def test_preferred_model_for_reads_the_question_dict() -> None:
    assert preferred_model_for({"preferred_model": "complex"}) == DEFAULT_MODEL_COMPLEX
    assert preferred_model_for({"preferred_model": "nope"}) is None
    assert preferred_model_for({}) is None
    assert preferred_model_for(None) is None


# ---------------------------------------------------------------------------
#  C2: precedence, through the grade endpoint
# ---------------------------------------------------------------------------

UNIT_XML = """<unit id="preferred_model_unit" title="Preferred Model Unit" version="1.0">
  <question qtag="q_complex" preferred_model="complex">
    <question_text><![CDATA[<p>What is 2+2? Show your work.</p>]]></question_text>
    <solution><![CDATA[<p>4</p>]]></solution>
    <grading_notes><![CDATA[Accept the value.]]></grading_notes>
    <parts>
      <part>
        <part_label>all</part_label>
        <points>1</points>
      </part>
    </parts>
  </question>
  <question qtag="q_terra" preferred_model="gpt-5.6-terra">
    <question_text><![CDATA[<p>What is 3+3? Show your work.</p>]]></question_text>
    <solution><![CDATA[<p>6</p>]]></solution>
    <grading_notes><![CDATA[Accept the value.]]></grading_notes>
    <parts>
      <part>
        <part_label>all</part_label>
        <points>1</points>
      </part>
    </parts>
  </question>
  <question qtag="q_none">
    <question_text><![CDATA[<p>What is 4+4? Show your work.</p>]]></question_text>
    <solution><![CDATA[<p>8</p>]]></solution>
    <grading_notes><![CDATA[Accept the value.]]></grading_notes>
    <parts>
      <part>
        <part_label>all</part_label>
        <points>1</points>
      </part>
    </parts>
  </question>
  <question qtag="q_typo" preferred_model="gpt-turbo-9000">
    <question_text><![CDATA[<p>What is 5+5? Show your work.</p>]]></question_text>
    <solution><![CDATA[<p>10</p>]]></solution>
    <grading_notes><![CDATA[Accept the value.]]></grading_notes>
    <parts>
      <part>
        <part_label>all</part_label>
        <points>1</points>
      </part>
    </parts>
  </question>
</unit>
"""

CONFIG_XML = """<llmgrader>
  <course>
    <name>Preferred Model Course</name>
    <term>Fall 2026</term>
  </course>
  <units>
    <unit>
      <name>Preferred Model Unit</name>
      <source>preferred_unit.xml</source>
      <destination>preferred_unit.xml</destination>
    </unit>
  </units>
</llmgrader>
"""


@pytest.fixture()
def pkg_dir(tmp_path: Path) -> Path:
    pkg = tmp_path / "soln_pkg"
    pkg.mkdir()
    (pkg / "llmgrader_config.xml").write_text(CONFIG_XML, encoding="utf-8")
    (pkg / "preferred_unit.xml").write_text(UNIT_XML, encoding="utf-8")
    return pkg


@pytest.fixture()
def grader(tmp_path: Path, pkg_dir: Path, monkeypatch) -> Grader:
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return Grader(scratch_dir=str(scratch), soln_pkg=str(pkg_dir))


@pytest.fixture()
def client(tmp_path: Path, pkg_dir: Path, monkeypatch):
    monkeypatch.setenv("LLMGRADER_STORAGE_PATH", str(tmp_path / "storage"))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    app = create_app(scratch_dir=str(scratch), soln_pkg=str(pkg_dir))
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


UNIT = "Preferred Model Unit"


def _questions(grader: Grader) -> dict:
    return grader.units[UNIT]


def test_the_fixture_unit_loads(grader: Grader) -> None:
    assert set(_questions(grader)) == {"q_complex", "q_terra", "q_none", "q_typo"}


def test_a_symbolic_preference_resolves_per_question(grader: Grader) -> None:
    questions = _questions(grader)

    assert preferred_model_for(questions["q_complex"], "q_complex") == DEFAULT_MODEL_COMPLEX
    assert preferred_model_for(questions["q_terra"], "q_terra") == "gpt-5.6-terra"
    assert preferred_model_for(questions["q_none"], "q_none") is None
    assert preferred_model_for(questions["q_typo"], "q_typo") is None


def _model_used(client, monkeypatch, qtag, **overrides):
    """Post a grade job and capture the model the job was created with."""
    captured = {}

    from llmgrader.routes import api as api_module

    original = api_module.APIController.run_grade_job

    def fake_run(self, job_id):
        captured["model"] = self.grade_jobs[job_id]["model"]
        job = self.grade_jobs[job_id]
        job["status"] = "completed"
        job["result"] = {"result": "pass"}
        self.active_grade_job_id = None

    monkeypatch.setattr(api_module.APIController, "run_grade_job", fake_run)
    try:
        body = {"unit": UNIT, "qtag": qtag, "student_solution": "4"}
        body.update(overrides)
        resp = client.post("/grade", json=body)
        assert resp.status_code == 202, resp.get_json()
    finally:
        monkeypatch.setattr(api_module.APIController, "run_grade_job", original)

    return captured.get("model")


def test_preferred_model_is_used_when_the_client_sends_none(client, monkeypatch) -> None:
    assert _model_used(client, monkeypatch, "q_complex") == DEFAULT_MODEL_COMPLEX


def test_a_concrete_preference_is_used_too(client, monkeypatch) -> None:
    assert _model_used(client, monkeypatch, "q_terra") == "gpt-5.6-terra"


def test_an_explicit_client_model_wins(client, monkeypatch) -> None:
    """A student who picked a model in the dropdown keeps it."""
    used = _model_used(client, monkeypatch, "q_complex", model=DEFAULT_MODEL_SIMPLE)

    assert used == DEFAULT_MODEL_SIMPLE


def test_no_preference_falls_back_to_the_default(client, monkeypatch) -> None:
    assert _model_used(client, monkeypatch, "q_none") == DEFAULT_MODEL_SIMPLE


def test_an_unresolvable_preference_falls_back_and_does_not_raise(client, monkeypatch) -> None:
    assert _model_used(client, monkeypatch, "q_typo") == DEFAULT_MODEL_SIMPLE


def test_an_unknown_client_model_is_still_rejected(client) -> None:
    resp = client.post(
        "/grade",
        json={
            "unit": UNIT,
            "qtag": "q_complex",
            "student_solution": "4",
            "model": "gpt-9000-imaginary",
        },
    )

    assert resp.status_code == 400
    assert "gpt-9000-imaginary" in resp.get_json()["error"]


# ---------------------------------------------------------------------------
#  C2: the unit payload the front end reads
# ---------------------------------------------------------------------------

def test_the_unit_payload_carries_raw_and_resolved_preferences(client) -> None:
    items = client.get(f"/unit/{UNIT}").get_json()["items"]

    assert items["q_complex"]["preferred_model"] == "complex"
    assert items["q_complex"]["preferred_model_resolved"] == DEFAULT_MODEL_COMPLEX
    assert items["q_none"]["preferred_model_resolved"] is None
    assert items["q_typo"]["preferred_model_resolved"] is None


def test_the_unit_payload_still_hides_the_solution(client) -> None:
    items = client.get(f"/unit/{UNIT}").get_json()["items"]

    assert "solution" not in items["q_complex"]
    assert "grading_notes" not in items["q_complex"]


# ---------------------------------------------------------------------------
#  C3: the parser warns rather than failing
# ---------------------------------------------------------------------------

def test_a_typo_warns_but_still_loads_the_unit(grader: Grader) -> None:
    assert "q_typo" in _questions(grader)
    assert not grader.unit_validation_errors

    log_text = Path(grader.scratch_dir, "load_unit_pkg_log.txt").read_text(encoding="utf-8")
    assert "gpt-turbo-9000" in log_text
    assert "q_typo" in log_text
