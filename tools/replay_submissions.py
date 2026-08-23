"""Replay stored submissions against the current model slate.

Purpose: the default model was flipped from ``gpt-4.1-mini`` to
``gpt-5.6-luna``.  The live suite (``tests/live/``) proves luna is reachable
and can tell right from wrong on unambiguous fixtures; it says nothing about
rubric adherence on real student work.  This script grades work that was
actually submitted, through the real ``Grader.grade()`` path, and reports
where the new model disagrees with the old one.

**The stored grade is not ground truth.**  It is the output of the model being
replaced, and plan section 4 records that model awarding half credit to an
answer satisfying zero rubric items.  Agreement is not accuracy and
disagreement is not regression.  Where the escalation models both side with
luna against the stored grade, that is evidence the *old* grade was wrong.

Privacy: submissions are real student work.  Detailed output goes only to the
``--out-dir`` (default ``local_data/replay/``, gitignored); the terminal and
the summary identify submissions by row id.  No student text is printed.

Usage::

    python tools/replay_submissions.py --dry-run     # reconstruct + price, no API
    python tools/replay_submissions.py               # luna pass + escalations
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_DB = REPO_ROOT / "local_data" / "db" / "llmgrader.db"
DEFAULT_OUT = REPO_ROOT / "local_data" / "replay"

#: The model whose grades are being re-examined.
BASELINE_MODEL = "gpt-4.1-mini"

#: Ordered worst -> best, for comparing two grades when points are missing.
RESULT_RANK = {"fail": 0, "partial": 1, "pass": 2}


def build_question_dict(row: dict) -> dict:
    """Rebuild the grader's question dict from a stored submission row.

    Fidelity limits, both of which the report records:

    * **Rubrics are not stored.**  The submissions table keeps the rendered
      ``raw_prompt`` but no structured rubric, so a row originally graded with
      a rubric replays through the no-rubric prompt template.
    * **Points are frequently absent.**  Older rows predate the points columns;
      ``points``/``max_points`` are NULL and the original prompt did not
      mention points either, so a part with ``points=None`` reproduces the
      request shape rather than inventing a total.
    """
    max_points = row.get("max_points")
    max_point_parts = _load_json(row.get("max_point_parts_json"))

    if isinstance(max_point_parts, list) and len(max_point_parts) > 1:
        # A multi-part question graded as "all": one part per stored total.
        parts = [
            {"part_label": str(index + 1), "points": value}
            for index, value in enumerate(max_point_parts)
        ]
    else:
        parts = [{"part_label": "all", "points": max_points}]

    return {
        "qtag": row.get("qtag") or "",
        "question_text": row.get("question_text") or "",
        "solution": row.get("ref_soln") or "",
        "solution_images": [],
        "grading_notes": row.get("grading_notes") or "",
        "parts": parts,
        # NULL means the row predates the column. Mirror the app's own
        # defaults rather than guessing: required defaults True, partial_credit
        # defaults False.
        "required": True if row.get("required") is None else bool(row["required"]),
        "partial_credit": bool(row.get("partial_credit")),
        "tools": _load_json(row.get("tools_json")) or [],
        "rubrics": {},
        "rubric_total": None,
        "rubric_groups": [],
        "preferred_model": "",
    }


def _load_json(value):
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def score_of(points, max_points, result) -> float | None:
    """Normalize a grade to a 0-1 fraction, or None when it cannot be scored.

    Points win when both are present.  Otherwise a binary pass/fail still
    carries a score; a bare "partial" with no points does not, and an "error"
    is not a grade at all.
    """
    if points is not None and max_points not in (None, 0):
        try:
            return max(0.0, min(1.0, float(points) / float(max_points)))
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    if result == "pass":
        return 1.0
    if result == "fail":
        return 0.0
    return None


def compare(old: dict, new: dict) -> str:
    """Classify the replayed grade against the stored one."""
    if old.get("result") == "error":
        return "old_error"
    if new.get("result") == "error":
        return "replay_error"

    old_score = score_of(old.get("points"), old.get("max_points"), old.get("result"))
    new_score = score_of(new.get("points"), new.get("max_points"), new.get("result"))

    if old_score is not None and new_score is not None:
        if abs(old_score - new_score) < 1e-9:
            return "agree"
        return "stricter" if new_score < old_score else "more_lenient"

    old_rank = RESULT_RANK.get(old.get("result"))
    new_rank = RESULT_RANK.get(new.get("result"))
    if old_rank is None or new_rank is None:
        return "uncomparable"
    if old_rank == new_rank:
        return "agree"
    return "stricter" if new_rank < old_rank else "more_lenient"


def price(spec, tokens_in: int, tokens_out: int) -> float:
    """USD for one call, from the ModelSpec rates (short-context here)."""
    if spec is None:
        return 0.0
    long_rate = (
        spec.long_context_threshold is not None
        and tokens_in > spec.long_context_threshold
        and spec.usd_per_mtok_in_long is not None
    )
    rate_in = spec.usd_per_mtok_in_long if long_rate else spec.usd_per_mtok_in
    rate_out = spec.usd_per_mtok_out_long if long_rate else spec.usd_per_mtok_out
    return (tokens_in * rate_in + tokens_out * rate_out) / 1_000_000


class Replayer:
    """Runs grades through the app and reads usage back out of its own DB."""

    def __init__(self, out_dir: Path, timeout: float) -> None:
        from llmgrader.services.grader import Grader

        # Redirect app storage: grade() inserts a submission row, and that must
        # not land in the database being replayed.
        self.storage = out_dir / "storage"
        os.environ["LLMGRADER_STORAGE_PATH"] = str(self.storage)

        self.timeout = timeout
        self.tmp = tempfile.TemporaryDirectory(prefix="replay-")
        pkg = Path(self.tmp.name) / "pkg"
        pkg.mkdir(parents=True, exist_ok=True)
        # The question dicts are rebuilt from the DB, so the grader needs no
        # course package; an empty one keeps the constructor happy.
        self.grader = Grader(scratch_dir=str(Path(self.tmp.name) / "scratch"),
                             soln_pkg=str(pkg))
        self.api_key = os.environ["OPENAI_API_KEY"]

    def grade(self, row: dict, model: str) -> dict:
        question = build_question_dict(row)
        started = time.time()
        grade = self.grader.grade(
            question,
            row.get("student_soln") or "",
            part_label="all",
            unit_name=row.get("unit_name") or "",
            qtag=row.get("qtag") or "",
            model=model,
            api_key=self.api_key,
            timeout=self.timeout,
        )
        usage = self._last_usage()
        return {
            "model": model,
            "result": grade.get("result"),
            "points": grade.get("points"),
            "max_points": grade.get("max_points"),
            "feedback": grade.get("feedback"),
            "full_explanation": grade.get("full_explanation"),
            "tokens_in": usage.get("tokens_in") or 0,
            "tokens_out": usage.get("tokens_out") or 0,
            "seconds": round(time.time() - started, 2),
        }

    def _last_usage(self) -> dict:
        conn = sqlite3.connect(self.grader.db_path)
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT tokens_in, tokens_out FROM submissions "
                "ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        return dict(row) if row else {}


def load_rows(db_path: Path, model: str, limit: int | None) -> list[dict]:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM submissions WHERE model = ? ORDER BY id", (model,)
        )]
    finally:
        conn.close()
    return rows[:limit] if limit else rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--baseline-model", default=BASELINE_MODEL)
    parser.add_argument("--model", default=None,
                        help="Replay model (default: the registry's simple tier)")
    parser.add_argument("--escalate", nargs="*", default=None,
                        help="Models to run on disagreements (default: standard + complex)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--dry-run", action="store_true",
                        help="Rebuild and price every row without calling the API")
    parser.add_argument("--rebuild-from", type=Path, default=None,
                        help="Rewrite the outputs from an existing report.json, "
                             "re-deriving the analysis without calling the API")
    parser.add_argument("--max-usd", type=float, default=3.0,
                        help="Refuse to start if the projected spend exceeds this")
    args = parser.parse_args()

    from llmgrader.services.models import (
        DEFAULT_MODEL_COMPLEX,
        DEFAULT_MODEL_SIMPLE,
        DEFAULT_MODEL_STANDARD,
        get_spec,
    )

    replay_model = args.model or DEFAULT_MODEL_SIMPLE
    escalation = args.escalate if args.escalate is not None else [
        DEFAULT_MODEL_STANDARD, DEFAULT_MODEL_COMPLEX
    ]

    if args.rebuild_from:
        return rebuild(args.rebuild_from, args.out_dir)

    rows = load_rows(args.db, args.baseline_model, args.limit)
    if not rows:
        print(f"No rows for model {args.baseline_model!r} in {args.db}")
        return 1
    print(f"{len(rows)} submissions graded by {args.baseline_model}")

    args.out_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        return dry_run(rows, replay_model, escalation, get_spec)

    projected = project_cost(rows, replay_model, escalation, get_spec)
    print(f"projected spend: ${projected:.3f} (ceiling ${args.max_usd:.2f})")
    if projected > args.max_usd:
        print("ABORT: projected spend exceeds the ceiling; raise --max-usd to proceed")
        return 2

    replayer = Replayer(args.out_dir, args.timeout)
    records: list[dict] = []
    spend = 0.0

    for index, row in enumerate(rows, start=1):
        old = {
            "model": row["model"],
            "result": row["result"],
            "points": row["points"],
            "max_points": row["max_points"],
        }
        new = replayer.grade(row, replay_model)
        spend += price(get_spec(replay_model), new["tokens_in"], new["tokens_out"])
        verdict = compare(old, new)
        records.append({
            "id": row["id"],
            "unit_name": row["unit_name"],
            "qtag": row["qtag"],
            "partial_credit": bool(row["partial_credit"]),
            "had_rubric_in_prompt": "rubric" in (row["raw_prompt"] or "").lower(),
            "old": old,
            "replay": new,
            "verdict": verdict,
            "escalation": {},
        })
        print(f"  [{index}/{len(rows)}] id={row['id']:<4} {verdict}")

    disagreements = [r for r in records if r["verdict"] in ("stricter", "more_lenient")]
    print(f"\n{len(disagreements)} disagreements; escalating to {', '.join(escalation)}")

    for index, record in enumerate(disagreements, start=1):
        row = next(r for r in rows if r["id"] == record["id"])
        for model in escalation:
            result = replayer.grade(row, model)
            spend += price(get_spec(model), result["tokens_in"], result["tokens_out"])
            record["escalation"][model] = result
        record["escalation_verdict"] = escalation_verdict(record, escalation)
        record["direction_votes"] = direction_votes(record, escalation)
        print(f"  [{index}/{len(disagreements)}] id={record['id']:<4} "
              f"{record['escalation_verdict']}")

    write_outputs(args.out_dir, records, args.baseline_model, replay_model,
                  escalation, spend)
    print(f"\nactual spend: ${spend:.4f}")
    print(f"wrote {args.out_dir / 'report.json'} and {args.out_dir / 'summary.md'}")
    return 0


def rebuild(report_path: Path, out_dir: Path) -> int:
    """Re-derive the analysis from a completed run and rewrite the outputs.

    Every per-row grade is already recorded, so refining how the results are
    summarized costs nothing and must not re-bill the API.
    """
    data = json.loads(report_path.read_text(encoding="utf-8"))
    escalation = data["escalation_models"]
    for record in data["records"]:
        if record["verdict"] in ("stricter", "more_lenient"):
            record["direction_votes"] = direction_votes(record, escalation)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_outputs(out_dir, data["records"], data["baseline_model"],
                  data["replay_model"], escalation, data["usd_spent"])
    print(f"rebuilt {out_dir / 'report.json'} and {out_dir / 'summary.md'} "
          f"from {report_path} (no API calls)")
    return 0


def escalation_verdict(record: dict, escalation: list[str]) -> str:
    """Do the stronger models side with the replay model or the stored grade?"""
    replay_score = score_of(record["replay"]["points"],
                            record["replay"]["max_points"],
                            record["replay"]["result"])
    old_score = score_of(record["old"]["points"],
                         record["old"]["max_points"],
                         record["old"]["result"])

    with_replay = 0
    with_old = 0
    other = 0
    for model in escalation:
        result = record["escalation"].get(model) or {}
        this = score_of(result.get("points"), result.get("max_points"), result.get("result"))
        if this is None:
            other += 1
        elif replay_score is not None and abs(this - replay_score) < 1e-9:
            with_replay += 1
        elif old_score is not None and abs(this - old_score) < 1e-9:
            with_old += 1
        else:
            other += 1

    if with_replay and not with_old:
        return "both_side_with_replay" if with_replay > 1 else "sides_with_replay"
    if with_old and not with_replay:
        return "both_side_with_old" if with_old > 1 else "sides_with_old"
    if with_replay and with_old:
        return "split"
    return "neither"


def direction_votes(record: dict, escalation: list[str]) -> dict:
    """Which way each stronger model moved, relative to the stored grade.

    Coarser than :func:`escalation_verdict` and more useful: two models can
    both judge an answer far below the stored grade without landing on the
    same score.  What matters for "was the old grade wrong?" is the direction
    they moved, not whether they matched the replay to the decimal.
    """
    old = score_of(record["old"]["points"], record["old"]["max_points"],
                   record["old"]["result"])
    replay = score_of(record["replay"]["points"], record["replay"]["max_points"],
                      record["replay"]["result"])
    if old is None or replay is None:
        return {}

    direction = -1 if replay < old else 1
    votes = {}
    for model in escalation:
        this = score_of(*(record["escalation"].get(model, {}).get(k)
                          for k in ("points", "max_points", "result")))
        if this is None:
            votes[model] = "unscored"
        elif abs(this - old) < 1e-9:
            votes[model] = "old"
        elif (this - old) * direction > 0:
            votes[model] = "replay"
        else:
            votes[model] = "opposite"
    return votes


def review_rank(record: dict) -> tuple:
    """Sort key for "most worth a human look", most urgent first.

    Band 0: no stronger model moved the way the replay did -- the replay is
            the outlier and is the thing to check.
    Band 1: the stronger models split.
    Band 2: unanimous backing, ranked by how much the grade would move.
    """
    votes = list(record.get("direction_votes", {}).values())
    backing = votes.count("replay")
    old = score_of(record["old"]["points"], record["old"]["max_points"],
                   record["old"]["result"])
    replay = score_of(record["replay"]["points"], record["replay"]["max_points"],
                      record["replay"]["result"])
    gap = abs((replay or 0) - (old or 0))

    if votes and backing == 0:
        band = 0
    elif votes and backing < len(votes):
        band = 1
    else:
        band = 2
    return (band, -gap, record["id"])


def project_cost(rows, replay_model, escalation, get_spec) -> float:
    """Rough projection: measured ~1.4k in / ~250 out per graded question."""
    tokens_in, tokens_out = 1400, 250
    per_row = price(get_spec(replay_model), tokens_in, tokens_out)
    # Assume a pessimistic half of the rows disagree and need escalating.
    per_escalation = sum(price(get_spec(m), tokens_in, tokens_out) for m in escalation)
    return len(rows) * per_row + 0.5 * len(rows) * per_escalation


def dry_run(rows, replay_model, escalation, get_spec) -> int:
    """Rebuild every question dict and render every prompt, without the API."""
    from llmgrader.services.prompt import PromptBuilder

    builder = PromptBuilder()
    failures = []
    for row in rows:
        try:
            builder.build_task_prompt(build_question_dict(row),
                                      row.get("student_soln") or "", "all")
        except Exception as exc:                      # noqa: BLE001 - reporting
            failures.append((row["id"], f"{type(exc).__name__}: {exc}"))

    print(f"reconstructed {len(rows) - len(failures)}/{len(rows)} prompts")
    for row_id, message in failures:
        print(f"  id={row_id}: {message}")
    print(f"projected spend: ${project_cost(rows, replay_model, escalation, get_spec):.3f}")
    return 1 if failures else 0


def _agreement_split(records) -> dict:
    """Agreement rate on rows whose original prompt carried a rubric, and not.

    The split matters: a rubric row's original grade was produced *with* a
    rubric the replay cannot reconstruct, so its disagreements are confounded.
    Comparisons among the replayed models are not -- they all ran without it.
    """
    from collections import Counter

    split = {}
    for flag in (False, True):
        subset = [r for r in records
                  if r["had_rubric_in_prompt"] == flag
                  and r["verdict"] in ("agree", "stricter", "more_lenient")]
        counts = Counter(r["verdict"] for r in subset)
        split["with_rubric" if flag else "without_rubric"] = {
            "comparable": len(subset),
            "agree": counts["agree"],
            "stricter": counts["stricter"],
            "more_lenient": counts["more_lenient"],
            "agreement_rate": counts["agree"] / len(subset) if subset else None,
        }
    return split


def write_outputs(out_dir: Path, records, baseline_model, replay_model, escalation, spend) -> None:
    from collections import Counter

    verdicts = Counter(r["verdict"] for r in records)
    comparable = sum(v for k, v in verdicts.items()
                     if k in ("agree", "stricter", "more_lenient"))
    agreement = verdicts["agree"] / comparable if comparable else 0.0
    escalations = Counter(r.get("escalation_verdict") for r in records
                          if r.get("escalation_verdict"))
    disagreements = [r for r in records if r["verdict"] in ("stricter", "more_lenient")]
    backing = Counter()
    for record in disagreements:
        votes = list(record.get("direction_votes", {}).values())
        if not votes:
            backing["unscored"] += 1
        elif votes.count("replay") == len(votes):
            backing["all_stronger_models_agree_with_replay"] += 1
        elif votes.count("replay") == 0:
            backing["no_stronger_model_agrees_with_replay"] += 1
        else:
            backing["split"] += 1
    shortlist = sorted(disagreements, key=review_rank)[:10]

    (out_dir / "report.json").write_text(json.dumps({
        "baseline_model": baseline_model,
        "replay_model": replay_model,
        "escalation_models": escalation,
        "rows": len(records),
        "verdicts": dict(verdicts),
        "agreement_rate_over_comparable": agreement,
        "agreement_split_by_rubric": _agreement_split(records),
        "escalation_verdicts": dict(escalations),
        "disagreement_direction_backing": dict(backing),
        "review_shortlist_ids": [r["id"] for r in shortlist],
        "usd_spent": spend,
        "caveats": [
            "The stored grade is the output of the model being replaced, not "
            "ground truth. Agreement is not accuracy.",
            "Rubrics are not stored in the submissions table, so rows "
            "originally graded with a rubric replay through the no-rubric "
            "prompt template (see had_rubric_in_prompt).",
            "Rows with NULL points replay with a part carrying no point total, "
            "matching the original request shape.",
        ],
        "records": records,
    }, indent=2), encoding="utf-8")

    lines = [
        "# Replay of stored submissions against the current slate",
        "",
        f"- baseline (stored): `{baseline_model}`",
        f"- replay: `{replay_model}`",
        f"- escalation: {', '.join(f'`{m}`' for m in escalation)}",
        f"- rows: {len(records)}",
        f"- spend: ${spend:.4f}",
        "",
        "## Verdicts",
        "",
        "| verdict | n |",
        "|---|---|",
    ]
    for verdict, count in verdicts.most_common():
        lines.append(f"| {verdict} | {count} |")
    split = _agreement_split(records)
    lines += [
        "",
        f"Agreement over comparable rows: {agreement:.1%} ({verdicts['agree']}/{comparable})",
        "",
        "The stored grade is **not ground truth** -- it is the output of the "
        "model being replaced. Agreement is not accuracy, and disagreement is "
        "not regression.",
        "",
        "### Split by whether the original prompt carried a rubric",
        "",
        "| rows | comparable | agree | rate |",
        "|---|---|---|---|",
    ]
    for key, entry in split.items():
        rate = "-" if entry["agreement_rate"] is None else f"{entry['agreement_rate']:.0%}"
        lines.append(f"| {key} | {entry['comparable']} | {entry['agree']} | {rate} |")
    lines += [
        "",
        "Rubrics are not stored in the submissions table, so a row originally "
        "graded with one replays through the no-rubric template. Its "
        "disagreement with the stored grade is confounded; its agreement with "
        "the other replayed models is not, since all of them ran without it.",
        "",
        "## Escalation (disagreements only)",
        "",
        "Exact-score agreement:",
        "",
        "| outcome | n |",
        "|---|---|",
    ]
    for verdict, count in escalations.most_common():
        lines.append(f"| {verdict} | {count} |")
    lines += [
        "",
        "Directional agreement -- did the stronger models move the same way "
        "the replay did, relative to the stored grade?",
        "",
        "| outcome | n |",
        "|---|---|",
    ]
    for outcome, count in backing.most_common():
        lines.append(f"| {outcome} | {count} |")
    lines += [
        "",
        "## Ranked for human review",
        "",
        "Most urgent first: rows where no stronger model backed the replay, "
        "then splits, then unanimous disagreements ranked by how far the grade "
        "would move.",
        "",
        "| # | id | qtag | old | replay | terra | sol |",
        "|---|---|---|---|---|---|---|",
    ]
    for position, record in enumerate(shortlist, start=1):
        esc = record.get("escalation", {})
        lines.append(
            f"| {position} | {record['id']} | {record['qtag']} | "
            f"{_grade(record['old'])} | {_grade(record['replay'])} | "
            f"{_grade(esc.get(escalation[0], {}))} | "
            f"{_grade(esc.get(escalation[1], {})) if len(escalation) > 1 else '-'} |"
        )
    lines += [
        "",
        "## All disagreements",
        "",
        "Look a row up with:",
        "",
        "```sql",
        "SELECT question_text, student_soln, feedback FROM submissions WHERE id = ?;",
        "```",
        "",
        "| id | qtag | rubric | old | replay | terra | sol | escalation |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for record in disagreements:
        esc = record.get("escalation", {})
        lines.append(
            f"| {record['id']} | {record['qtag']} | "
            f"{'yes' if record['had_rubric_in_prompt'] else 'no'} | "
            f"{_grade(record['old'])} | {_grade(record['replay'])} | "
            f"{_grade(esc.get(escalation[0], {}))} | "
            f"{_grade(esc.get(escalation[1], {})) if len(escalation) > 1 else '-'} | "
            f"{record.get('escalation_verdict', '-')} |"
        )
    lines.append("")
    lines.append("Student work is not reproduced here; rows are identified by id.")
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def _grade(grade: dict) -> str:
    """Render one grade as `result n/max`, omitting points when absent."""
    if not grade:
        return "-"
    result = grade.get("result") or "-"
    if grade.get("points") is None or grade.get("max_points") is None:
        return result
    return f"{result} {grade['points']:g}/{grade['max_points']:g}"


if __name__ == "__main__":
    raise SystemExit(main())
