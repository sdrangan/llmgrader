"""The course MCP tools: what a student's own AI can ask the portal.

Read-only: the course's titles, questions, rubrics and solutions, the units
it publishes here alone, such as past exams, and its materials -- slides,
demos, labs, whatever kinds the course declares (plans/unified_materials.md),
plus practice grading with the portal's prompt and scoring, which stores
nothing and calls no model (plans/mcp_grading.md).  Who may call it -- anyone, or only holders of a course token -- is
``mount.py``'s business, not the tools'.
"""

from __future__ import annotations

import json

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from llmgrader.coursemcp import content as cc
from llmgrader.coursemcp.catalog import catalog_for, page_url
from llmgrader.coursemcp.code import (
    FIRST_FETCH_WAIT_S,
    CodeError,
    normalize_request_path,
    read_source,
)
from llmgrader.coursemcp.materials import PAGE, PAGED_FORMATS, TEXT, load_materials
from llmgrader.services.course_registry import CourseRegistry
from llmgrader.services.grader import GraderRawResult
from llmgrader.services.unit_parser import DEFAULT_UNIT_TYPE

INSTRUCTIONS = (
    "Course material from an LLM Grader portal. Call list_courses first: "
    "every other tool takes a course_id, and it must be one list_courses "
    "returned."
)

CONTENT_INSTRUCTIONS = (
    " Units come from list_units and questions from list_questions; pass "
    "their names exactly. Each unit has a unit_type: problem_set for "
    "homework, or another type such as midterm for a past exam. Before "
    "writing a practice problem or practice exam like a midterm or another "
    "type, read that type's description from list_unit_types -- it says what "
    "this term's assessments of that type are like -- and model the problem "
    "on that type's past units. The course's materials -- lecture slides, "
    "demos, labs, handouts: each course names its own kinds -- come from "
    "list_materials, which says what each kind is and which unit each item "
    "goes with. When a student asks where something is taught or shown, or "
    "how to do it, search_materials for its exact identifiers or a phrase "
    "(one search covers slides, docs pages and code), then get_material to "
    "open an item and see its parts, and read_material to read one slide, "
    "page or file. Most of a slide's content is in its figure, so look at "
    "the image. Cite a slide by item and page, and code as path:line; give "
    "the student view_url for a slide or docs page and source_url for exact "
    "lines of code. This is practice material for a student who is "
    "studying: when they are working on a problem, help them reason toward "
    "the answer -- use the rubric to see what counts, and the worked solution "
    "to check their reasoning or build a hint -- rather than reproducing the "
    "solution, unless they ask for it. A result that carries an instruction "
    "is a worked solution: follow it. When a student asks how their answer "
    "would score, get_grading_prompt gives the portal's own grading prompt "
    "and score_grade totals your grade the way the portal does: that is a "
    "practice estimate, so say so. Only answers submitted on the portal are "
    "graded for credit. The portal counts which tools are called and on "
    "which questions, materials and files, anonymously and without the "
    "student's words."
)


def log_call(tool: str, **ids) -> None:
    """One log line per tool call: the tool and the ids it was asked about.

    Never the student's question or answer -- that is student data.  Only
    score_grade is sent anything derived from it, and its grade is not
    passed here.  The ids are what show how often the answer key is
    actually pulled.
    """
    detail = " ".join(f"{k}={v!r}" for k, v in ids.items())
    print(f"[CourseMCP] {tool} {detail}".rstrip())


def build_course_mcp(registry: CourseRegistry, *, content: bool = False,
                     public_url=lambda: None, code=None) -> MCPServer:
    """An MCP server whose tools read the courses *registry* serves.

    *content* adds the question, rubric, solution and material tools;
    ``mount.py`` always passes it -- a token, if any, is checked before a
    request gets here.  *public_url* returns the portal's public address, for
    links a student can open, or None.  *code*, a ``CodeLibrary``, adds each
    course's mirrored items to its materials; ``mount.py`` passes one only
    when ``LLMGRADER_MCP_CODE`` is set.

    Only the tools are defined here.  How it is served over HTTP is
    ``mount.py``'s business: in mcp 2 those settings belong to the app, not
    the server.
    """
    mcp = MCPServer(
        "llmgrader-course",
        instructions=INSTRUCTIONS + (CONTENT_INSTRUCTIONS if content else ""),
        # No subscriptions/listen.  A listen request is a POST held open to
        # stream change notifications, and under gunicorn's sync worker an
        # open stream holds the whole portal.  Course content changes only on
        # an upload, so there is nothing to stream anyway.
        subscriptions=False,
    )

    def require_course(course_id: str):
        # An unknown or archived id is an error, never a fall back to the
        # default course -- the same rule as bind_course in routes/api.py.
        # ToolError, not ValueError: only a ToolError's message reaches the
        # model, and this one tells it what to do next.
        if registry.get(course_id) is None:
            raise ToolError(
                f"Unknown course {course_id!r}. Call list_courses for valid ids."
            )
        return registry.grader_for(course_id)

    # A list a tool returns is sent as one content block per entry, and some
    # clients (Gemini, 2026-10-13) keep only the last block: they saw one
    # course and one unit.  So every result travels as one object, its list
    # under a key.
    @mcp.tool()
    def list_courses() -> dict:
        """List the courses this portal serves: id, name, semester and the
        version of the course material being served.

        Use the id as course_id in every other tool.
        """
        # The version is here and in no other tool's result: an assistant
        # reads every result, and on any other call it would be noise.  So
        # is the mirrored repo's commit, for a course that has one.
        courses = []
        for entry in registry.courses():
            item = {"course_id": entry.id, "name": entry.name, "semester": entry.semester,
                    "package_version": registry.grader_for(entry.id).package_version}
            code_version = code.code_version(entry.id) if code is not None else None
            if code_version:
                item["code_version"] = code_version
            courses.append(item)
        return {"courses": courses}

    @mcp.tool()
    def list_units(course_id: str) -> dict:
        """List a course's units in teaching order, with section headings.

        Each item is a section heading or a unit.  A unit carries its number
        of questions and its unit_type -- problem_set for homework, or a type
        such as midterm for a past exam -- and, for past material, the
        semester it was given.  list_unit_types says what each type is like.
        A unit of type material holds material and no questions (course
        setup, say); list_materials lists what is in it.
        course_id must come from list_courses.
        """
        units = cc.course_units(require_course(course_id))
        items = []
        for item in units.order:
            if item["type"] == "unit":
                meta = units.meta.get(item["name"], {})
                entry = {"type": "unit", "name": item["name"],
                         "questions": len(units.units.get(item["name"], {})),
                         "unit_type": meta.get("unit_type", DEFAULT_UNIT_TYPE)}
                if meta.get("semester"):
                    entry["semester"] = meta["semester"]
                if meta.get("description"):
                    entry["description"] = meta["description"]
                items.append(entry)
            else:
                items.append({"type": item["type"], "name": item["name"]})
        return {"units": items}

    @mcp.tool()
    def list_unit_types(course_id: str) -> dict:
        """List the kinds of unit in a course, with what each is like.

        Each item is a unit_type -- problem_set, midterm, final, quiz, as the
        course names them -- with the instructor's title and description where
        there is one, and the units of that type.  A description of an exam
        type says what this term's exam is like: its format, length, what it
        covers.  Read it before writing a practice problem "like the midterm".
        """
        log_call("list_unit_types", course=course_id)
        grader = require_course(course_id)
        units = cc.course_units(grader)
        materials = load_materials(grader.soln_pkg)
        described = {t["id"]: t for t in (materials.unit_types if materials else [])}
        by_type: dict[str, list[str]] = {}
        for item in units.order:
            if item["type"] == "unit":
                unit_type = units.meta.get(item["name"], {}).get("unit_type", DEFAULT_UNIT_TYPE)
                if unit_type == cc.MATERIAL_UNIT_TYPE:
                    continue        # not an assessment: list_materials covers it
                by_type.setdefault(unit_type, []).append(item["name"])
        # A described type with no unit yet still says what this term's will be.
        for type_id in described:
            by_type.setdefault(type_id, [])
        result = []
        for type_id, names in by_type.items():
            entry = {"unit_type": type_id}
            if described.get(type_id, {}).get("title"):
                entry["title"] = described[type_id]["title"]
            if described.get(type_id, {}).get("description"):
                entry["description"] = described[type_id]["description"]
            entry["units"] = names
            result.append(entry)
        return {"unit_types": result}

    if content:
        _add_content_tools(mcp, require_course)
        _add_material_tools(mcp, require_course, public_url, code)

    return mcp


def _payload_last(payload: dict, images: list) -> list:
    """A result with images: the images first, the JSON payload last.

    Last, because a client that keeps only one content block keeps the last
    (Gemini did): it then still has every word of the result, and loses only
    the pictures, which ``figures_attached`` says it was sent.
    """
    if images:
        payload = {**payload, "figures_attached": sum(1 for b in images if isinstance(b, Image))}
    return [*images, json.dumps(payload, indent=2, ensure_ascii=False)]


def _with_figures(payload: dict, figures: list) -> list:
    """A tool result: each figure after its own label, then the JSON payload.

    Each image is preceded by "Figure n:", so the [Figure n] placeholders in
    the text map onto images unambiguously even when one could not be sent.
    """
    payload = dict(payload)
    notes = cc.figure_notes(figures)
    if notes:
        payload["figure_notes"] = notes
    blocks: list = []
    for number, figure in enumerate(figures, start=1):
        if figure is not None and len(figure.data) <= cc.MAX_FIGURE_BYTES:
            blocks.append(f"Figure {number}:")
            blocks.append(Image(data=figure.data, format=figure.mime.split("/", 1)[1]))
    return _payload_last(payload, blocks)


def _slide_url(public_url, course_id: str, deck: str, number: int) -> str | None:
    # The portal's /c/<course>/slides/<deck>/<n> route.  None until a
    # request has shown the server its own address.
    base = public_url()
    return f"{base}/c/{course_id}/slides/{deck}/{number}" if base else None


def _add_content_tools(mcp: MCPServer, require_course) -> None:

    @mcp.tool()
    def list_questions(course_id: str, unit: str | None = None,
                       unit_type: str | None = None) -> dict:
        """List a course's questions: unit, qtag, a short label, parts and points.

        Omit unit for every question in the course -- the whole index is small,
        so prefer this to guessing, and match the student's description against
        the labels yourself.  Pass unit (a name from list_units) for one unit,
        or unit_type (from list_units or list_unit_types) for the questions of
        every unit of that type -- unit_type="midterm" for all past midterm
        problems.  The label is the start of the question text; call
        get_question for the full text and its figures.
        """
        log_call("list_questions", course=course_id, unit=unit, unit_type=unit_type)
        grader = require_course(course_id)
        units = cc.course_units(grader)
        names = [cc.resolve_unit(grader, unit)] if unit else cc.unit_names(grader)
        if unit_type:
            wanted = unit_type.strip().lower()
            names = [n for n in names if units.meta.get(n, {}).get("unit_type") == wanted]
        index = []
        for name in names:
            for qtag, question in units.units.get(name, {}).items():
                parts = cc.parts_summary(question)
                index.append({
                    "unit": name,
                    "qtag": qtag,
                    "label": cc.question_label(question),
                    "parts": parts,
                    "points": sum(p["points"] or 0 for p in parts),
                })
        return {"questions": index}

    @mcp.tool()
    def get_question(course_id: str, unit: str, qtag: str):
        """Get one question: its full text, its parts with points, and its figures.

        unit and qtag come from list_questions.  The text is HTML; [Figure n]
        marks where the n-th attached figure belongs.  This is what the student
        sees.  Use get_rubric for what earns credit, and get_solution for the
        worked solution.

        When the instructor has written variation_guidance, it says what is
        safe to change when making a similar practice problem and what must
        stay fixed.  Follow it if the student asks for one.
        """
        log_call("get_question", course=course_id, unit=unit, qtag=qtag)
        grader = require_course(course_id)
        unit_name, tag, question = cc.resolve_question(grader, unit, qtag)
        figures = cc.figures_in(question.get("question_text", ""), grader.soln_pkg)
        payload = {
            "unit": unit_name,
            "qtag": tag,
            "question": cc.tidy_html(question.get("question_text", "")),
            "parts": cc.parts_summary(question),
            "partial_credit": bool(question.get("partial_credit")),
        }
        if question.get("variation_guidance"):
            payload["variation_guidance"] = question["variation_guidance"]
        return _with_figures(payload, figures)

    @mcp.tool()
    def get_rubric(course_id: str, unit: str, qtag: str) -> dict:
        """Get the rubric the portal grades one question against.

        Returns each rubric item -- what it checks, its part, the points it is
        worth (negative for a deduction; null for a feedback-only item, which
        the grader analyzes and reports but does not score) and the grader's
        notes on it -- plus
        the question's grading notes, which describe common mistakes and what
        is accepted.  Use it to see what counts and to aim feedback or hints at
        it; it does not contain the worked solution.
        """
        log_call("get_rubric", course=course_id, unit=unit, qtag=qtag)
        grader = require_course(course_id)
        unit_name, tag, question = cc.resolve_question(grader, unit, qtag)
        items = [
            {
                "id": item_id,
                "part": item.get("part", ""),
                "display_text": item.get("display_text", ""),
                "condition": cc.plain_text(item.get("condition", "")),
                "points": (
                    None if item.get("scored", True) is False
                    else item.get("point_adjustment", 0)
                ),
                "feedback_only": item.get("scored", True) is False,
                "notes": item.get("notes", ""),
            }
            for item_id, item in (question.get("rubrics") or {}).items()
        ]
        return {
            "unit": unit_name,
            "qtag": tag,
            "parts": cc.parts_summary(question),
            "partial_credit": bool(question.get("partial_credit")),
            "scoring": question.get("rubric_total") or "",
            "rubric": items,
            "grading_notes": question.get("grading_notes", ""),
        }

    @mcp.tool(description=(
        "Get the instructor's worked solution to one question, with its "
        "figures. unit and qtag come from list_questions.\n\n"
        + cc.TUTOR_INSTRUCTION + " The result carries this as its instruction."))
    def get_solution(course_id: str, unit: str, qtag: str):
        log_call("get_solution", course=course_id, unit=unit, qtag=qtag)
        grader = require_course(course_id)
        unit_name, tag, question = cc.resolve_question(grader, unit, qtag)
        figures = cc.solution_figures(question, grader.soln_pkg)
        return _with_figures({
            "unit": unit_name,
            "qtag": tag,
            "solution": cc.tidy_html(question.get("solution", "")),
            "instruction": cc.TUTOR_INSTRUCTION,
        }, figures)

    # Practice grading, plans/mcp_grading.md.  Neither tool calls a model:
    # the student's AI grades, and the portal's own prompt and scoring make
    # its estimate mean what the portal's grade means.
    @mcp.tool()
    def get_grading_prompt(course_id: str, unit: str, qtag: str, part: str = "all"):
        """Get the prompt the portal grades one question with, to give a
        student a practice estimate of how their answer would score.

        Call it when the student asks how their answer would be graded.  part
        is a part label from list_questions, or "all" for every part at once.
        The prompt is the portal's own -- rubric, scoring rule, worked solution
        and grading notes -- with the student's answer left out: grade the
        answer from the conversation against it, then pass the JSON it asks
        for to score_grade, which totals it the way the portal does.  The
        result is an estimate, never a grade for credit.
        """
        log_call("get_grading_prompt", course=course_id, unit=unit, qtag=qtag, part=part)
        grader = require_course(course_id)
        unit_name, tag, question = cc.resolve_question(grader, unit, qtag)
        label = cc.resolve_part(question, tag, part)
        prompt, mode, max_points = cc.grading_prompt(grader, question, label)
        figures = cc.solution_figures(question, grader.soln_pkg)
        return _with_figures({
            "unit": unit_name,
            "qtag": tag,
            "part": label,
            "grading_mode": mode,
            "max_points": max_points,
            "prompt": prompt,
            "response_schema": GraderRawResult.model_json_schema(),
            "instruction": cc.GRADING_INSTRUCTION,
        }, figures)

    @mcp.tool()
    def score_grade(course_id: str, unit: str, qtag: str, grade: dict | str,
                    part: str = "all") -> dict:
        """Score a practice grade the way the portal scores its grader's reply.

        grade is the JSON object get_grading_prompt's prompt asks for, after
        you have graded the student's answer; unit, qtag and part are the ones
        you passed there.  Returns the points, the maximum, and the feedback
        with the portal's rubric table -- show the student those, not your
        own total.  A grade that does not fit the schema is an error saying
        what to fix.  The result is a practice estimate, not a grade.
        """
        # grade is never logged: its evidence paraphrases the student's work.
        log_call("score_grade", course=course_id, unit=unit, qtag=qtag, part=part)
        grader = require_course(course_id)
        unit_name, tag, question = cc.resolve_question(grader, unit, qtag)
        label = cc.resolve_part(question, tag, part)
        if isinstance(grade, str):
            # Some clients send an object argument as its JSON text.
            try:
                grade = json.loads(grade)
            except json.JSONDecodeError as exc:
                raise ToolError(f"grade is not valid JSON: {exc}") from exc
        result = cc.score_grade(grader, question, label, grade)
        return {"unit": unit_name, "qtag": tag, "part": label, **result,
                "estimate": True, "disclaimer": cc.ESTIMATE_DISCLAIMER}



def _add_material_tools(mcp: MCPServer, require_course, public_url, code) -> None:
    """The material tools: plans/unified_materials.md.  Every result is bounded."""

    def course_catalog(course_id: str, *, wait: bool = True):
        """``(grader, catalog, note)``.  Waits for the mirror only when there
        is no copy of it at all, and then briefly; *note* says what is
        missing meanwhile."""
        grader = require_course(course_id)
        materials = load_materials(grader.soln_pkg)
        if materials is None or not (materials.items or materials.mirror_items
                                     or materials.patterns):
            raise ToolError("This course has not published any materials.")
        snapshot, note = None, None
        if materials.code and code is not None:
            sync = code.sync_for(course_id)
            snapshot = sync.ensure(wait=FIRST_FETCH_WAIT_S if wait else 0) if sync else None
            if snapshot is None:
                error = sync.last_error() if sync else None
                note = ("Some of this course's materials could not be fetched "
                        f"({error}); try again later." if error else
                        "Some of this course's materials are being fetched for the "
                        "first time; try again in a minute for the rest.")
        return grader, catalog_for(materials, snapshot, cc.unit_resolver(grader)), note

    def require_item(catalog, item_id: str, *, readable: bool = True):
        item = catalog.get(item_id)
        if item is None:
            raise ToolError(f"Unknown material {item_id!r}. Valid ids, from list_materials: "
                            + ", ".join(repr(i) for i in catalog.items))
        if readable and not item.readable:
            raise ToolError(f"{item.id!r} is listed so you know it exists, but the "
                            "instructor has not made it available to read.")
        return item

    def slide_url_for(course_id: str):
        return lambda deck, n: _slide_url(public_url, course_id, deck, n)

    def with_policy(payload: dict, item) -> dict:
        if item.policy == "tutor":
            payload["instruction"] = cc.TUTOR_INSTRUCTION
        return payload

    def filtered(catalog, unit: str | None, kind: str | None) -> list:
        if kind and kind.strip().lower() not in catalog.kinds:
            raise ToolError(f"Unknown kind {kind!r}. Kinds, from list_materials: "
                            + ", ".join(repr(k) for k in catalog.kinds))
        items = list(catalog.items.values())
        if kind:
            items = [i for i in items if i.kind == kind.strip().lower()]
        if unit:
            if not catalog.unit_names_matching(unit):
                names = list(dict.fromkeys(n for i in catalog.items.values()
                                           for n in i.unit_names))
                raise ToolError(f"No unit matches {unit!r}. Units with materials: "
                                + "; ".join(repr(n) for n in names))
            items = [i for i in items if catalog.matches_unit(i, unit)]
        return items

    @mcp.tool()
    def list_materials(course_id: str, unit: str | None = None,
                       kind: str | None = None) -> dict:
        """List the course's materials: its kinds, its units, and every item.

        Each course names its own kinds -- lecture slides, demos, labs,
        handouts -- and each kind's description says what it is.  An item is
        what a student is pointed to: a deck, a demo with its docs pages and
        code, a lab with its starting files.  It has an id, a title, a kind,
        the units it goes with and a count of its parts; get_material opens
        it.  Pass unit or kind to narrow the list.  unit is matched loosely:
        a name from list_units in any case and spacing, or the part before its
        colon ("unit 5").  units in the result are the units the listed items
        go with, not your filter echoed back.  An item with readable false
        exists but is not available to read.
        """
        log_call("list_materials", course=course_id, unit=unit, kind=kind)
        grader, catalog, note = course_catalog(course_id)
        items = filtered(catalog, unit, kind)
        material_units = {u["name"]: u for u in catalog.material_units}
        used = list(dict.fromkeys(name for item in items for name in item.unit_names))
        # Course order first; a name the course does not list (a package
        # built against another llmgrader_config.xml) after, as items give it.
        ordered = [n for n in cc.unit_names(grader) if n in used]
        units = []
        for name in ordered + [n for n in used if n not in ordered]:
            entry = {"unit": name}
            if name in material_units:
                entry["material_only"] = True
                if material_units[name].get("description"):
                    entry["description"] = material_units[name]["description"]
            units.append(entry)
        kinds = []
        for kind_id, spec in catalog.kinds.items():
            entry = {"kind": kind_id, "description": spec["description"],
                     "items": sum(1 for i in items if i.kind == kind_id)}
            if spec.get("policy", "open") != "open":
                entry["policy"] = spec["policy"]
            kinds.append(entry)
        listed = []
        for item in items:
            entry = {"id": item.id, "title": item.title, "kind": item.kind,
                     "units": item.unit_names, "parts": item.part_count()}
            if item.description:
                entry["description"] = item.description
            if not item.readable:
                entry["readable"] = False
            listed.append(entry)
        result = {"kinds": kinds, "units": units, "items": listed}
        if note:
            result["note"] = note
        return result

    def part_summary(catalog, part, course_id: str) -> dict:
        entry = {"path": part.path, "format": part.format}
        if part.format in PAGED_FORMATS:
            paged = catalog.paged(part)
            entry.update({"title": paged.title, "pages": len(paged.pages),
                          "images": paged.images})
            if paged.error:
                entry["note"] = paged.error
            outline = []
            for page in paged.pages:
                # A figure-only slide has no text; its description says what it shows.
                excerpt = " ".join((page.get("text") or page.get("description", "")).split())
                outline.append({"page": page["n"], "title": page.get("title", ""),
                                "excerpt": excerpt[:100] + ("…" if len(excerpt) > 100 else "")})
            entry["outline"] = outline
            return entry
        try:
            source = catalog.text(part)
        except CodeError as exc:
            entry["note"] = str(exc)
            return entry
        if part.format == PAGE:
            entry["title"] = source.title
        else:
            entry["language"] = source.language
        entry["lines"] = source.last_line
        links = catalog.links_for(part)
        if links is not None:
            entry.update(links(part.path))
        return entry

    @mcp.tool()
    def get_material(course_id: str, id: str) -> dict:
        """Open one item: what it is, its units, and its parts.

        id comes from list_materials or search_materials.  Each part is a
        file: a slide deck or PDF (with its outline: each page's number,
        title and an excerpt), a docs page (with view_url, the page as
        published) or a text file such as code (with source_url).  Pass a
        part's path, and a page for a deck or PDF, to read_material.  slides
        are lecture slides that cite this item; related are other items its
        docs pages point to.
        """
        log_call("get_material", course=course_id, id=id)
        _, catalog, _ = course_catalog(course_id)
        item = require_item(catalog, id)
        payload = {"id": item.id, "title": item.title, "kind": item.kind}
        if item.description:
            payload["description"] = item.description
        payload["units"] = [{"unit": u["unit"], "via": u["via"]} for u in item.units]
        payload["parts"] = [part_summary(catalog, part, course_id) for part in item.parts]
        slides = []
        for link in item.slides:
            deck_item = catalog.item_for_deck(link["deck"])
            if deck_item is None or not deck_item.readable:
                continue
            part = next(p for p in deck_item.parts if p.deck == link["deck"])
            entry = {"id": deck_item.id, "path": part.path, "page": link["slide"]}
            url = _slide_url(public_url, course_id, link["deck"], link["slide"])
            if url:
                entry["view_url"] = url
            slides.append(entry)
        if slides:
            payload["slides"] = slides
        if item.related:
            payload["related"] = [r for r in item.related
                                  if catalog.get(r) is not None and catalog.get(r).readable]
        return with_policy(payload, item)

    def choose_part(catalog, item, path: str | None, page: int | None):
        if path:
            repo_name = catalog.snapshot.config.repo_name if catalog.snapshot else None
            paths = {p.path for p in item.parts}
            try:
                wanted = normalize_request_path(path, repo_name, lambda p: p in paths)
            except CodeError as exc:
                raise ToolError(str(exc)) from exc
            found = next((p for p in item.parts if p.path == wanted), None)
            if found is not None:
                return found
            inside = [p.path for p in item.parts if p.path.startswith(wanted + "/")]
            if inside:
                raise ToolError(f"{wanted!r} is a folder; pass one of its files: "
                                + ", ".join(inside[:20]))
            raise ToolError(f"{item.id!r} has no part {wanted!r}. Its parts, from "
                            "get_material: " + ", ".join(p.path for p in item.parts[:30]))
        if len(item.parts) == 1:
            return item.parts[0]
        paged = [p for p in item.parts if p.format in PAGED_FORMATS]
        if page is not None and len(paged) == 1:
            return paged[0]
        raise ToolError(f"{item.id!r} has {len(item.parts)} parts; pass path, one of: "
                        + ", ".join(p.path for p in item.parts[:30]))

    @mcp.tool()
    def read_material(course_id: str, id: str, path: str | None = None,
                      page: int | None = None, start_line: int | None = None,
                      end_line: int | None = None):
        """Read one part of an item: a slide or PDF page, or a file's lines.

        id comes from list_materials; path is one of the item's parts, from
        get_material or search_materials (it may be left out when the item
        has one part).  For a slide deck or PDF, page is the slide or page
        number: you get its image, its text, the speaker notes and a
        description of its figures.  Look at the image: diagrams, waveforms
        and equations are usually only there.  The image comes to you, not
        into the student's chat; give them view_url to see it.

        For a docs page or a text file, at most 400 numbered lines come back
        per call: when truncated is true, call again with start_line =
        end_line + 1.  Give the student view_url (a docs page as published)
        or source_url (the exact lines on GitHub), and cite code as path:line.
        """
        log_call("read_material", course=course_id, id=id, path=path, page=page)
        _, catalog, _ = course_catalog(course_id)
        item = require_item(catalog, id)
        part = choose_part(catalog, item, path, page)
        base = {"id": item.id, "kind": item.kind, "path": part.path, "format": part.format}

        if part.format in PAGED_FORMATS:
            paged = catalog.paged(part)
            if paged.error and not paged.pages:
                raise ToolError(f"{part.path!r} cannot be read here: {paged.error}.")
            if page is None and len(paged.pages) == 1:
                page = 1
            if page is None or not 1 <= page <= len(paged.pages):
                raise ToolError(f"{part.path!r} has pages 1 to {len(paged.pages)}; pass page.")
            entry = paged.pages[page - 1]
            payload = {**base, "document": paged.title, "page": entry["n"],
                       "of": len(paged.pages), "title": entry.get("title", ""),
                       "text": entry.get("text", ""), "notes": entry.get("notes", "")}
            if entry.get("description"):
                payload["figure_description"] = entry["description"]
            cited_by = [{"id": other.id, "title": other.title}
                        for other in (catalog.items_for_slide(paged.deck, entry["n"])
                                      if paged.deck else [])]
            if cited_by:
                payload["materials"] = cited_by    # items this slide points to
            image = paged.image_path(entry.get("image")) if entry.get("image") else None
            if image is None:
                payload["image"] = "not available: this document is served as text only"
            else:
                url = page_url(catalog, part, paged, entry["n"], slide_url_for(course_id))
                if url:
                    payload["view_url"] = url
            images = [Image(data=image.read_bytes(), format="jpeg")] if image is not None else []
            return _payload_last(with_policy(payload, item), images)

        try:
            source = catalog.text(part)
            result = read_source(source, start_line, end_line, links=catalog.links_for(part))
        except CodeError as exc:
            raise ToolError(str(exc)) from exc
        payload = {**base, **{k: v for k, v in result.items() if k not in ("path", "format")}}
        if part.format == PAGE:
            payload["cites"] = catalog.doc_cites.get(part.path, [])
        return [json.dumps(with_policy(payload, item), indent=2, ensure_ascii=False)]

    @mcp.tool()
    def search_materials(course_id: str, query: str, unit: str | None = None,
                         kind: str | None = None, format: str | None = None) -> dict:
        """Find a topic, identifier or phrase across all of the course's materials.

        One search covers lecture slides, PDF pages and docs pages -- ranked
        by keyword, best first, with an identifier such as s_axilite or
        ap_ctrl_none matched whole -- and the lines of code and other text
        files, matched literally and case-insensitively.  It matches words,
        not meanings: if a search misses, try the course's own terms or
        synonyms ("FSM", "state machine"), or an exact identifier.  Each hit
        names its item (id) and kind, its part (path) and a page or lines;
        pass those to read_material.  Narrow with unit (matched loosely, as in
        list_materials: "unit 5" will do), kind, or format ("slides", "pdf",
        "page" for docs pages, "text" for code and other files).  more counts
        hits left out: narrow the search to see them.
        """
        log_call("search_materials", course=course_id, unit=unit, kind=kind,
                 format=format)     # never the query: it is the student's words
        if not (query or "").strip():
            raise ToolError("query is empty.")
        if format is not None and format not in (*PAGED_FORMATS, PAGE, TEXT):
            raise ToolError("format must be one of 'slides', 'pdf', 'page' or 'text'.")
        _, catalog, note = course_catalog(course_id)
        items = filtered(catalog, unit, kind)
        try:
            result = catalog.search(query, items=items, fmt=format,
                                    slide_url=slide_url_for(course_id))
        except CodeError as exc:
            raise ToolError(str(exc)) from exc
        if any(hit.get("policy") == "tutor" for hit in result["hits"]):
            result["instruction"] = cc.TUTOR_INSTRUCTION
        if note:
            result["note"] = note
        return result
