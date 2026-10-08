"""The course MCP tools: what a student's own AI can ask the portal.

Read-only: the course's titles, questions, rubrics, solutions and slides,
and the units it publishes here alone, such as past exams.
Who may call it -- anyone, or only holders of a course token -- is
``mount.py``'s business, not the tools'.
"""

from __future__ import annotations

import json

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from llmgrader.coursemcp import content as cc
from llmgrader.coursemcp.code import FIRST_FETCH_WAIT_S, CodeError
from llmgrader.coursemcp.materials import load_materials
from llmgrader.services.course_registry import CourseRegistry
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
    "on that type's past units. Lecture slides: list_materials, then get_outline or "
    "search_slides to find where a topic is taught, and get_slide to see a "
    "slide -- most of a slide's content is in its figure, so look at the "
    "image, and cite slides by deck and number. This is practice material for a student who is "
    "studying: when they are working on a problem, help them reason toward "
    "the answer -- use the rubric to see what counts, and the worked solution "
    "to check their reasoning or build a hint -- rather than reproducing the "
    "solution, unless they ask for it. The portal grades their submitted "
    "answers; nothing done through these tools is graded. The portal counts "
    "which tools are called and on which questions and slides, anonymously "
    "and without the student's words."
)

# Added when the portal serves demo code (LLMGRADER_MCP_CODE).
CODE_INSTRUCTIONS = (
    " Demos: the instructor's in-class demos -- SystemVerilog, Vitis HLS C++ "
    "and Tcl, Python build scripts and notebooks -- and the docs pages that "
    "walk through them often show what the slides only describe. When a "
    "student asks where something is shown or how to do it (a pragma, an "
    "interface, a testbench, a build step), search_demos for its exact "
    "identifiers or a phrase, then get_demo_file to read the docs page or the "
    "code; list_demos says which unit and slides each demo goes with, so you "
    "can point the student to a demo to study. Give the student view_url for "
    "a docs page and source_url for exact lines of code, and cite code as "
    "path:line. Demo calls are counted the same way, by demo and file."
)


def log_call(tool: str, **ids) -> None:
    """One log line per tool call: the tool and the ids it was asked about.

    Never the student's question -- that is student data (and these tools are
    never sent it anyway).  The ids are what show how often the answer key is
    actually pulled.
    """
    detail = " ".join(f"{k}={v!r}" for k, v in ids.items())
    print(f"[CourseMCP] {tool} {detail}".rstrip())


def build_course_mcp(registry: CourseRegistry, *, content: bool = False,
                     public_url=lambda: None, code=None) -> MCPServer:
    """An MCP server whose tools read the courses *registry* serves.

    *content* adds the question, rubric, solution and slide tools; ``mount.py``
    always passes it -- a token, if any, is checked before a request gets
    here.  *public_url* returns the portal's public address, for links a
    student can open, or None.  *code*, a ``CodeLibrary``, adds the demo
    tools (``plans/demo_code_mcp.md``); ``mount.py`` passes one only when
    ``LLMGRADER_MCP_CODE`` is set.

    Only the tools are defined here.  How it is served over HTTP is
    ``mount.py``'s business: in mcp 2 those settings belong to the app, not
    the server.
    """
    mcp = MCPServer(
        "llmgrader-course",
        instructions=INSTRUCTIONS + (CONTENT_INSTRUCTIONS if content else "")
        + (CODE_INSTRUCTIONS if content and code is not None else ""),
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

    @mcp.tool()
    def list_courses() -> list[dict]:
        """List the courses this portal serves: id, name, semester and the
        version of the course material being served.

        Use the id as course_id in every other tool.
        """
        # The version is here and in no other tool's result: an assistant
        # reads every result, and on any other call it would be noise.  So
        # is the demo repo's commit, for a course that publishes demos.
        courses = []
        for entry in registry.courses():
            item = {"course_id": entry.id, "name": entry.name, "semester": entry.semester,
                    "package_version": registry.grader_for(entry.id).package_version}
            code_version = code.code_version(entry.id) if code is not None else None
            if code_version:
                item["code_version"] = code_version
            courses.append(item)
        return courses

    @mcp.tool()
    def list_units(course_id: str) -> list[dict]:
        """List a course's units in teaching order, with section headings.

        Each item is a section heading or a unit.  A unit carries its number
        of questions and its unit_type -- problem_set for homework, or a type
        such as midterm for a past exam -- and, for past material, the
        semester it was given.  list_unit_types says what each type is like.
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
                items.append(entry)
            else:
                items.append({"type": item["type"], "name": item["name"]})
        return items

    @mcp.tool()
    def list_unit_types(course_id: str) -> list[dict]:
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
        return result

    if content:
        _add_content_tools(mcp, require_course, public_url, code)
        if code is not None:
            _add_code_tools(mcp, require_course, public_url, code)

    return mcp


def _with_figures(payload: dict, figures: list) -> list:
    """A tool result: the JSON payload, then each figure after its own label.

    Each image is preceded by "Figure n:", so the [Figure n] placeholders in
    the text map onto images unambiguously even when one could not be sent.
    """
    payload = dict(payload)
    notes = cc.figure_notes(figures)
    if notes:
        payload["figure_notes"] = notes
    blocks: list = [json.dumps(payload, indent=2, ensure_ascii=False)]
    for number, figure in enumerate(figures, start=1):
        if figure is not None and len(figure.data) <= cc.MAX_FIGURE_BYTES:
            blocks.append(f"Figure {number}:")
            blocks.append(Image(data=figure.data, format=figure.mime.split("/", 1)[1]))
    return blocks


def _slide_url(public_url, course_id: str, deck: str, number: int) -> str | None:
    # The portal's /c/<course>/slides/<deck>/<n> route.  None until a
    # request has shown the server its own address.
    base = public_url()
    return f"{base}/c/{course_id}/slides/{deck}/{number}" if base else None


def _slide_demos(code, require_course, course_id: str):
    """``(deck, n) -> [{"demo", "title"}]``: the demos a slide cites.

    Never waits and never fails a slide tool: with no copy of the demos yet,
    or any problem building the links, a slide simply has no demos.
    """
    if code is None:
        return lambda deck, n: []
    try:
        sync = code.sync_for(course_id)
        snapshot = sync.ensure(wait=0) if sync is not None else None
        if snapshot is None:
            return lambda deck, n: []
        index = sync.index(snapshot, load_materials(require_course(course_id).soln_pkg))
    except Exception as exc:
        print(f"[CourseCode] {course_id}: no demo links for slides: {exc!r}")
        return lambda deck, n: []
    return lambda deck, n: [{"demo": d.id, "title": d.title}
                            for d in index.demos_for_slide(deck, n)]


def _add_content_tools(mcp: MCPServer, require_course, public_url, code=None) -> None:

    def slide_url(course_id: str, deck: str, number: int) -> str | None:
        return _slide_url(public_url, course_id, deck, number)


    @mcp.tool()
    def list_questions(course_id: str, unit: str | None = None,
                       unit_type: str | None = None) -> list[dict]:
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
        return index

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
        worth (negative for a deduction) and the grader's notes on it -- plus
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
                "points": item.get("point_adjustment", 0),
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

    @mcp.tool()
    def get_solution(course_id: str, unit: str, qtag: str):
        """Get the instructor's worked solution to one question, with its figures.

        Prefer using this to check the student's reasoning, find where it goes
        wrong, or build a hint, rather than showing it to them -- unless they
        ask to see the solution.  unit and qtag come from list_questions.
        """
        log_call("get_solution", course=course_id, unit=unit, qtag=qtag)
        grader = require_course(course_id)
        unit_name, tag, question = cc.resolve_question(grader, unit, qtag)
        figures = cc.solution_figures(question, grader.soln_pkg)
        return _with_figures({
            "unit": unit_name,
            "qtag": tag,
            "solution": cc.tidy_html(question.get("solution", "")),
        }, figures)

    def require_materials(grader):
        materials = load_materials(grader.soln_pkg)
        if materials is None or not materials.decks:
            raise ToolError("This course has not published any lecture slides.")
        return materials

    def require_deck(materials, deck: str) -> dict:
        found = materials.deck(deck.strip().lower())
        if found is None:
            raise ToolError(f"Unknown deck {deck!r}. Valid decks, from list_materials: "
                            + ", ".join(repr(d) for d in materials.deck_ids()))
        return found

    @mcp.tool()
    def list_materials(course_id: str, unit: str | None = None) -> list[dict]:
        """List the course's lecture slide decks: id, unit, title and slide count.

        Pass unit to list one unit's decks.  images is false for a deck served
        as text only.  Use the id as deck in get_outline, search_slides and
        get_slide.
        """
        log_call("list_materials", course=course_id, unit=unit)
        materials = require_materials(require_course(course_id))
        wanted = " ".join(unit.lower().split()) if unit else None
        return [
            {"deck": d["id"], "unit": d["unit"], "title": d["title"],
             "slides": d["slides"], "images": d["images"]}
            for d in materials.decks
            if wanted is None or " ".join(d["unit"].lower().split()) == wanted
        ]

    @mcp.tool()
    def get_outline(course_id: str, deck: str) -> list[dict]:
        """A deck's outline: every slide's number and title, and a short excerpt.

        Use it to see how a lecture is organised, or which slides cover a topic
        before opening them with get_slide.
        """
        log_call("get_outline", course=course_id, deck=deck)
        found = require_deck(require_materials(require_course(course_id)), deck)
        outline = []
        for slide in found["slides"]:
            # A figure-only slide has no text; its description says what it shows.
            excerpt = " ".join((slide["text"] or slide.get("description", "")).split())
            outline.append({"slide": slide["n"], "title": slide["title"],
                            "excerpt": excerpt[:100] + ("…" if len(excerpt) > 100 else "")})
        return outline

    @mcp.tool()
    def search_slides(course_id: str, query: str, unit: str | None = None) -> list[dict]:
        """Find the slides that mention a topic: deck, slide number, title, snippet.

        A keyword search over slide titles, text, speaker notes and (where the
        instructor has generated them) descriptions of each slide's figures,
        best match first.  It matches words, not meanings, so if the first
        search misses, try the course's own terms and synonyms (e.g. "FSM",
        "state machine", "next-state logic"), or browse get_outline.  An
        identifier such as s_axilite or ap_ctrl_none matches whole, and a
        slide that has it ranks first.

        A hit on a slide with an image carries view_url, a link the student
        can open to see it.
        """
        log_call("search_slides", course=course_id, unit=unit)  # not the query: student words
        materials = require_materials(require_course(course_id))
        hits = materials.search(query, unit=unit)
        demos_of = _slide_demos(code, require_course, course_id) if hits else None
        for hit in hits:
            deck = materials.deck(hit["deck"])
            if deck and deck["slides"][hit["slide"] - 1].get("image"):
                url = slide_url(course_id, hit["deck"], hit["slide"])
                if url:
                    hit["view_url"] = url
            demos = demos_of(hit["deck"], hit["slide"])
            if demos:
                hit["demos"] = demos
        return hits

    @mcp.tool()
    def get_slide(course_id: str, deck: str, slide: int):
        """One lecture slide: its image, title, text and the speaker notes.

        deck comes from list_materials or search_slides, and slide is its
        number in the deck.  Look at the image: diagrams, waveforms and
        equations are usually only there.

        The image comes to you, not into the student's chat: they cannot see
        it.  To show them the slide, give them view_url, a link that opens
        the slide's image in their browser.
        """
        log_call("get_slide", course=course_id, deck=deck, slide=slide)
        materials = require_materials(require_course(course_id))
        found = require_deck(materials, deck)
        slides = found["slides"]
        if not 1 <= slide <= len(slides):
            raise ToolError(f"Deck {found['id']!r} has slides 1 to {len(slides)}.")
        entry = slides[slide - 1]
        payload = {"deck": found["id"], "unit": found["unit"], "deck_title": found["title"],
                   "slide": entry["n"], "of": len(slides), "title": entry["title"],
                   "text": entry["text"], "notes": entry["notes"]}
        if entry.get("description"):
            payload["figure_description"] = entry["description"]
        demos = _slide_demos(code, require_course, course_id)(found["id"], entry["n"])
        if demos:
            payload["demos"] = demos    # list_demos / get_demo_file take it from here
        blocks: list = []
        image = materials.image_path(found["id"], entry["image"]) if entry.get("image") else None
        if image is None:
            payload["image"] = "not available: this deck is served as text only"
        else:
            url = slide_url(course_id, found["id"], entry["n"])
            if url:
                payload["view_url"] = url
        blocks.append(json.dumps(payload, indent=2, ensure_ascii=False))
        if image is not None:
            blocks.append(Image(data=image.read_bytes(), format="jpeg"))
        return blocks


def _add_code_tools(mcp: MCPServer, require_course, public_url, code) -> None:
    """The demo tools: plans/demo_code_mcp.md.  Every result is bounded."""

    def require_demos(course_id: str):
        grader = require_course(course_id)
        sync = code.sync_for(course_id)
        if sync is None:
            raise ToolError("This course has not published demos.")
        # Waits only when there is no copy at all, and then briefly.
        snapshot = sync.ensure(wait=FIRST_FETCH_WAIT_S)
        if snapshot is None:
            error = sync.last_error()
            if error:
                raise ToolError(f"The demos could not be fetched ({error}); try again later.")
            raise ToolError("The demos are being fetched for the first time; "
                            "try again in a minute.")
        try:
            index = sync.index(snapshot, load_materials(grader.soln_pkg))
        except Exception as exc:
            raise ToolError(f"The demo links could not be built: {exc}") from exc
        return snapshot, index

    def require_demo(index, demo: str):
        found = index.demos.get((demo or "").strip())
        if found is None or found.hidden:
            raise ToolError(f"Unknown demo {demo!r}. Valid demos, from list_demos: "
                            + ", ".join(repr(d.id) for d in index.visible()))
        return found

    def unit_matches(unit_name: str, wanted: str) -> bool:
        name = " ".join(unit_name.lower().split())
        return name == wanted or name.startswith(wanted + ":")

    @mcp.tool()
    def list_demos(course_id: str, unit: str | None = None) -> list[dict]:
        """List the course's in-class demos: each one's docs pages, code,
        slides and unit.

        A demo is a worked example the instructor builds in class --
        SystemVerilog, a Vitis HLS kernel, a Python build script or notebook --
        usually with docs pages that walk through it.  Use this to point a
        student to a demo that shows a topic, or to find the demo that goes
        with a slide or unit.  Pass unit (a name from list_units) for one
        unit's demos.  Each unit says how the link was found ("via").
        """
        log_call("list_demos", course=course_id, unit=unit)
        snapshot, index = require_demos(course_id)
        wanted = " ".join(unit.lower().split()) if unit else None
        result = []
        for demo in index.visible():
            if wanted and not any(unit_matches(u["unit"], wanted) for u in demo.units):
                continue
            slides = []
            for s in demo.slides:
                item = {"deck": s["deck"], "slide": s["slide"]}
                url = _slide_url(public_url, course_id, s["deck"], s["slide"])
                if url:
                    item["view_url"] = url
                slides.append(item)
            docs = []
            for path in demo.docs:
                page = {"path": path, "title": snapshot.files[path].title}
                view = snapshot.view_url(path)
                if view:
                    page["view_url"] = view
                docs.append(page)
            result.append({
                "demo": demo.id, "title": demo.title, "description": demo.description,
                "units": [{"unit": u["unit"], "via": u["via"]} for u in demo.units],
                "slides": slides, "docs": docs, "code": list(demo.code),
                "related": list(demo.related),
                "files": len(index.files_of(demo, snapshot)),
            })
        return result

    @mcp.tool()
    def list_demo_files(course_id: str, demo: str) -> list[dict]:
        """List one demo's files: its docs pages first, in reading order, then
        its code.

        demo comes from list_demos.  Paths are relative to the repository;
        pass them to get_demo_file as they are.  Build output, bitstreams,
        binaries and generated scripts are not served.
        """
        log_call("list_demo_files", course=course_id, demo=demo)
        snapshot, index = require_demos(course_id)
        found = require_demo(index, demo)
        files = []
        for path in index.files_of(found, snapshot):
            source = snapshot.files[path]
            item = {"path": path, "kind": source.kind, "demo": found.id}
            if source.kind == "doc":
                item["title"] = source.title
            else:
                item["language"] = source.language
            item["lines"] = source.last_line
            item.update(snapshot.links_for(path))
            files.append(item)
        return files

    @mcp.tool()
    def get_demo_file(course_id: str, path: str, start_line: int | None = None,
                      end_line: int | None = None) -> dict:
        """Read one demo file -- a docs page or code -- with line numbers.

        path comes from list_demo_files or search_demos (a leading
        "hwdesign/", as the docs write paths, is accepted).  At most 400 lines
        come back per call: when truncated is true, call again with
        start_line = end_line + 1.  A docs page lists the code it cites in
        cites; demos says which demos the file belongs to.  Give the student
        view_url (a docs page as published) or source_url (the exact lines on
        GitHub).
        """
        log_call("get_demo_file", course=course_id, path=path)
        snapshot, index = require_demos(course_id)
        try:
            result = snapshot.read(path, start_line, end_line)
        except CodeError as exc:
            raise ToolError(str(exc)) from exc
        result["demos"] = index.demos_for_path(result["path"])
        if result["kind"] == "doc":
            result["cites"] = index.doc_cites.get(result["path"], [])
        return result

    @mcp.tool()
    def search_demos(course_id: str, query: str, demo: str | None = None,
                     kind: str | None = None) -> dict:
        """Find a word, identifier or phrase in the demo code and docs pages.

        A literal, case-insensitive search -- not a regex, and not by meaning
        -- so search for exact identifiers (s_axilite, ap_ctrl_none,
        always_ff) or a short phrase, and try other terms if it misses.
        Docs pages come first, then hand-written source, scripts and
        notebooks.  Neighbouring matches come back as one hit with a line
        range.  Pass demo (from list_demos) to search one demo, or kind
        ("code" or "doc").  more counts hits left out: narrow the search to
        see them.
        """
        log_call("search_demos", course=course_id, demo=demo, kind=kind)  # not the query
        snapshot, index = require_demos(course_id)
        if kind is not None and kind not in ("code", "doc"):
            raise ToolError("kind must be 'code' or 'doc'.")
        paths = set(index.files_of(require_demo(index, demo), snapshot)) if demo else None
        try:
            return snapshot.search(query, paths=paths, kind=kind,
                                   demos_for=index.demos_for_path)
        except CodeError as exc:
            raise ToolError(str(exc)) from exc
