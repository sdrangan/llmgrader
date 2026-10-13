"""Course materials from the package: ``plans/unified_materials.md``.

The model (kinds, units, items, policies), the package source -- slides, PDFs
read page by page, text files -- and the four material tools over it.  The
mirror source is ``test_course_code.py``'s.

Serving needs nothing but JSON, text and images in the package, so those
tests write them by hand and always run.  The build tests make a real .pptx
and PDF and are skipped where python-pptx / PyMuPDF (the mcp-build extra)
are not installed.

The properties that would fail silently:

* a stale PDF -- page count differs from the deck -- must not be used, or each
  slide's image would sit beside another slide's text;
* only listed files are published, and the package source takes no patterns;
* a private item is listed and never read, searched or even packaged;
* a tutor item's content always comes with the tutoring instruction;
* search must not log the query: it is the student's own words.
"""

import json
from pathlib import Path

import pytest

from llmgrader.coursemcp.content import TUTOR_INSTRUCTION
from llmgrader.coursemcp.materials import (
    MaterialsError,
    TermIndex,
    build_materials,
    load_materials,
    read_materials,
)

from test_course_content import TOKEN, UNIT, build_app, call, payload  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"slide-image"
NOTES_MD = "# Lab notes\n\nUse a FIFO_DEPTH of 16.\n" + "".join(f"line {n}\n" for n in range(4, 501))


def write_materials(package: Path) -> None:
    """A hand-written mcp_materials tree: two decks (one with images), a
    text item, a material-only unit, a tutor item and a private one."""
    root = package / "mcp_materials"
    fsm = root / "slides" / "fsm"
    fifo = root / "slides" / "fifo"
    fsm.mkdir(parents=True)
    fifo.mkdir(parents=True)
    (fsm / "slide-001.jpg").write_bytes(JPEG)
    (fsm / "deck.json").write_text(json.dumps({
        "id": "fsm", "item": "fsm", "unit": UNIT, "title": "Sequential Logic",
        "format": "slides", "source": "fsm.pptx",
        "slides": [
            {"n": 1, "title": "Finite State Machines", "text": "Moore and Mealy machines",
             "notes": "", "image": "slide-001.jpg"},
            {"n": 2, "title": "Next-state logic", "text": "always_comb computes the next state",
             "notes": "Stress non-blocking assignment here.", "image": "../../../secret.jpg"},
        ]}), encoding="utf-8")
    (fifo / "deck.json").write_text(json.dumps({
        "id": "fifo", "item": "fifo", "unit": "Unit 5: Streams", "title": "FIFOs",
        "format": "slides", "source": "fifo.pptx",
        "slides": [{"n": 1, "title": "FIFO full and empty", "text": "A FIFO with depth N",
                    "notes": "", "image": None}]}), encoding="utf-8")
    files = root / "files"
    (files / "setup-guide" / "setup").mkdir(parents=True)
    (files / "setup-guide" / "setup" / "install.md").write_text(NOTES_MD, encoding="utf-8")
    (files / "lab1-soln" / "soln").mkdir(parents=True)
    (files / "lab1-soln" / "soln" / "fifo.sv").write_text(
        "module fifo;\n  // SOLUTION_MARKER: the full flag\nendmodule\n", encoding="utf-8")

    def deck_item(item_id, unit, title):
        return {"id": item_id, "kind": "slides", "title": title, "description": "",
                "units": [unit], "slides": [], "not_slides": [],
                "parts": [{"path": f"units/{item_id}.pptx", "format": "slides", "deck": item_id}]}

    def text_item(item_id, kind, unit, path, lines):
        return {"id": item_id, "kind": kind, "title": item_id.replace("-", " "),
                "description": "", "units": [unit], "slides": [], "not_slides": [],
                "parts": [{"path": path, "format": "text", "language": "markdown",
                           "file": f"files/{item_id}/{path}", "lines": lines}]}

    (root / "manifest.json").write_text(json.dumps({
        "version": 2,
        "kinds": [{"id": "slides", "description": "Lecture slides", "policy": "open"},
                  {"id": "handout", "description": "Handouts", "policy": "open"},
                  {"id": "lab-solution", "description": "Worked lab solutions", "policy": "tutor"},
                  {"id": "answer-key", "description": "Exam keys", "policy": "private"}],
        "material_units": [{"id": "setup", "name": "Course setup",
                            "description": "Installing the tools"}],
        "items": [
            deck_item("fsm", UNIT, "Sequential Logic"),
            deck_item("fifo", "Unit 5: Streams", "FIFOs"),
            text_item("setup-guide", "handout", "Course setup", "setup/install.md", 500),
            text_item("lab1-soln", "lab-solution", UNIT, "soln/fifo.sv", 3),
            {"id": "midterm-key", "kind": "answer-key", "title": "Midterm key",
             "description": "", "units": [UNIT], "slides": [], "not_slides": [],
             "parts": [{"path": "exams/key.pdf"}]},
        ],
        "mirror_items": [], "patterns": [], "refinements": [],
        "decks": [
            {"id": "fsm", "item": "fsm", "unit": UNIT, "title": "Sequential Logic",
             "format": "slides", "path": "units/fsm.pptx", "slides": 2, "images": True,
             "warning": ""},
            {"id": "fifo", "item": "fifo", "unit": "Unit 5: Streams", "title": "FIFOs",
             "format": "slides", "path": "units/fifo.pptx", "slides": 1, "images": False,
             "warning": "no PDF given"},
        ],
        "units": [], "unit_types": [],
    }), encoding="utf-8")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    app = build_app(tmp_path, monkeypatch, token=TOKEN)
    write_materials(tmp_path / "storage" / "courses" / "alpha" / "soln_pkg")
    return app.test_client()


def ok(result: dict) -> dict:
    assert result.get("isError") is not True, result
    return payload(result)


def error(result: dict) -> str:
    assert result.get("isError") is True, result
    return result["content"][0]["text"]


def tool(client, name, **args) -> dict:
    return call(client, name, {"course_id": "alpha", **args})


def ids(client, **args) -> list[str]:
    return [i["id"] for i in ok(tool(client, "list_materials", **args))["items"]]


# ---------------------------------------------------------------------------
# Listing and opening
# ---------------------------------------------------------------------------


def test_list_materials_gives_kinds_units_and_items(client) -> None:
    listed = ok(tool(client, "list_materials"))
    assert {k["kind"]: k.get("policy", "open") for k in listed["kinds"]} == {
        "slides": "open", "handout": "open", "lab-solution": "tutor", "answer-key": "private"}
    assert ids(client) == ["fsm", "fifo", "setup-guide", "lab1-soln", "midterm-key"]
    fsm = listed["items"][0]
    assert fsm == {"id": "fsm", "title": "Sequential Logic", "kind": "slides",
                   "units": [UNIT], "parts": 1}
    assert {"unit": "Course setup", "material_only": True,
            "description": "Installing the tools"} in listed["units"]


def test_list_materials_filters_by_unit_and_kind(client) -> None:
    assert ids(client, unit="unit 1: basics") == ["fsm", "lab1-soln", "midterm-key"]
    assert ids(client, unit="setup") == ["setup-guide"]          # a material unit, by id
    assert ids(client, kind="slides") == ["fsm", "fifo"]
    assert "Unknown kind" in error(tool(client, "list_materials", kind="video"))


def test_a_material_unit_is_listed_with_no_questions(client) -> None:
    units = {u["name"]: u for u in json.loads(
        json.dumps([json.loads(b["text"]) for b in tool(client, "list_units")["content"]]))
        if u["type"] == "unit"}
    assert units["Course setup"]["questions"] == 0
    assert units["Course setup"]["unit_type"] == "material"
    types = {t["unit_type"] for t in json.loads(
        json.dumps([json.loads(b["text"]) for b in tool(client, "list_unit_types")["content"]]))}
    assert "material" not in types


def test_get_material_gives_a_decks_outline(client) -> None:
    deck = ok(tool(client, "get_material", id="fsm"))
    [part] = deck["parts"]
    assert (part["format"], part["pages"], part["images"]) == ("slides", 2, True)
    assert [(p["page"], p["title"]) for p in part["outline"]] == [
        (1, "Finite State Machines"), (2, "Next-state logic")]
    assert deck["units"] == [{"unit": UNIT, "via": "config"}]


def test_get_material_lists_a_text_part_without_a_public_address(client) -> None:
    guide = ok(tool(client, "get_material", id="setup-guide"))
    assert guide["parts"] == [{"path": "setup/install.md", "format": "text",
                               "language": "markdown", "lines": 500}]


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_read_material_returns_a_slides_image_and_notes(client) -> None:
    result = tool(client, "read_material", id="fsm", page=1)
    body = ok(result)
    assert (body["title"], body["page"], body["of"]) == ("Finite State Machines", 1, 2)
    assert (body["document"], body["path"], body["format"]) == ("Sequential Logic",
                                                                "units/fsm.pptx", "slides")
    image = [b for b in result["content"] if b["type"] == "image"]
    assert len(image) == 1 and image[0]["mimeType"] == "image/jpeg"


def test_a_slides_content_is_its_deck_entry(tmp_path, client) -> None:
    """What get_slide returned, read_material returns: the deck's own entry."""
    deck = json.loads((tmp_path / "storage/courses/alpha/soln_pkg/mcp_materials/slides/fsm/"
                       "deck.json").read_text())
    body = ok(tool(client, "read_material", id="fsm", path="units/fsm.pptx", page=2))
    entry = deck["slides"][1]
    assert (body["title"], body["text"], body["notes"]) == (entry["title"], entry["text"],
                                                            entry["notes"])


def test_slide_image_path_cannot_leave_the_deck(client) -> None:
    result = tool(client, "read_material", id="fsm", page=2)
    assert not [b for b in result["content"] if b["type"] == "image"]
    assert ok(result)["notes"] == "Stress non-blocking assignment here."


def test_text_only_deck_says_so(client) -> None:
    body = ok(tool(client, "read_material", id="fifo", page=1))
    assert body["image"].startswith("not available")
    assert "view_url" not in body


def test_a_package_text_file_reads_in_windows(client) -> None:
    first = ok(tool(client, "read_material", id="setup-guide"))
    assert (first["start_line"], first["end_line"], first["truncated"]) == (1, 400, True)
    assert "FIFO_DEPTH" in first["text"] and "source_url" not in first
    rest = ok(tool(client, "read_material", id="setup-guide", start_line=401))
    assert (rest["end_line"], rest["truncated"]) == (500, False)


@pytest.mark.parametrize("args, expected", [
    ({"id": "nope", "page": 1}, "Valid ids"),
    ({"id": "fsm", "page": 9}, "pages 1 to 2"),
    ({"id": "fsm"}, "pass page"),
    ({"id": "fsm", "path": "../../manifest.json"}, "contains '..'"),
    ({"id": "fsm", "path": "units/other.pptx"}, "has no part"),
    ({"id": "setup-guide", "path": "/etc/passwd"}, "absolute path"),
])
def test_bad_requests_are_readable_errors(client, args, expected) -> None:
    assert expected in error(tool(client, "read_material", **args))


def test_course_without_materials_says_so(tmp_path, monkeypatch) -> None:
    client = build_app(tmp_path, monkeypatch, token=TOKEN).test_client()
    assert "not published any materials" in error(tool(client, "list_materials"))


def test_materials_reload_when_the_manifest_changes(tmp_path) -> None:
    write_materials(tmp_path)
    assert len(load_materials(str(tmp_path)).items) == 5
    manifest = tmp_path / "mcp_materials" / "manifest.json"
    data = json.loads(manifest.read_text())
    data["items"] = data["items"][:1]
    manifest.write_text(json.dumps(data))
    import os, time
    later = time.time() + 5
    os.utime(manifest, (later, later))
    assert len(load_materials(str(tmp_path)).items) == 1


def test_a_package_built_before_materials_serves_none(tmp_path) -> None:
    (tmp_path / "mcp_materials").mkdir()
    (tmp_path / "mcp_materials" / "manifest.json").write_text(json.dumps({
        "version": 1, "decks": [{"id": "fsm", "unit": "U", "title": "T", "slides": 1}],
        "units": [], "unit_types": []}))
    loaded = load_materials(str(tmp_path))
    assert loaded.items == [] and loaded.decks == []


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


def test_a_private_item_is_listed_and_never_read(client) -> None:
    listed = {i["id"]: i for i in ok(tool(client, "list_materials"))["items"]}
    assert listed["midterm-key"]["readable"] is False
    assert listed["midterm-key"]["parts"] == 1
    assert "not made it available" in error(tool(client, "get_material", id="midterm-key"))
    assert "not made it available" in error(tool(client, "read_material", id="midterm-key"))
    assert all(h["id"] != "midterm-key"
               for h in ok(tool(client, "search_materials", query="midterm key"))["hits"])


def test_a_tutor_items_content_carries_the_instruction(client) -> None:
    assert ok(tool(client, "get_material", id="lab1-soln"))["instruction"] == TUTOR_INSTRUCTION
    assert ok(tool(client, "read_material", id="lab1-soln"))["instruction"] == TUTOR_INSTRUCTION
    found = ok(tool(client, "search_materials", query="SOLUTION_MARKER"))
    assert found["hits"][0]["policy"] == "tutor"
    assert found["instruction"] == TUTOR_INSTRUCTION
    assert "instruction" not in ok(tool(client, "get_material", id="fsm"))
    assert "instruction" not in ok(tool(client, "search_materials", query="mealy"))


def test_get_solution_carries_the_same_instruction(client) -> None:
    body = ok(tool(client, "get_solution", unit=UNIT, qtag="Bouncing ball"))
    assert body["instruction"] == TUTOR_INSTRUCTION
    tools = {t["name"]: t for t in __import__("test_course_content").rpc(
        client, "tools/list").get_json()["result"]["tools"]}
    assert TUTOR_INSTRUCTION in tools["get_solution"]["description"]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def hits(client, query, **args) -> list[dict]:
    return ok(tool(client, "search_materials", query=query, **args))["hits"]


def test_search_ranks_the_matching_slide_first(client) -> None:
    first = hits(client, "mealy machine")[0]
    assert (first["id"], first["page"], first["kind"]) == ("fsm", 1, "slides")
    notes_hit = hits(client, "non-blocking")[0]
    assert (notes_hit["id"], notes_hit["page"]) == ("fsm", 2)


def test_search_can_be_limited_to_a_unit_kind_or_format(client) -> None:
    assert {h["id"] for h in hits(client, "fifo state", unit="Unit 5: Streams")} == {"fifo"}
    # The identifier's part "fifo" also finds the FIFO slides; the line is the guide's.
    assert {h["id"] for h in hits(client, "FIFO_DEPTH", format="text")} == {"setup-guide"}
    assert hits(client, "install", format="slides") == []
    assert hits(client, "FIFO_DEPTH", kind="slides", format="text") == []


def test_search_hits_carry_the_link(client) -> None:
    assert hits(client, "mealy")[0]["view_url"] == "http://localhost/c/alpha/slides/fsm/1"


def test_search_does_not_log_the_query(client, capsys) -> None:
    tool(client, "search_materials", query="my-private-question-words")
    assert "my-private-question-words" not in capsys.readouterr().out


@pytest.mark.parametrize("text, expected", [
    ("s_axilite", ["s_axilite", "axilite"]),          # the "s" alone is not a term
    ("ap_ctrl_none", ["ap_ctrl_none", "ap", "ctrl", "none"]),
    ("readBuffer", ["readbuffer", "read", "buffer"]),
    ("FIFOs and AXI4-Lite", ["fifos", "and", "axi4", "lite"]),   # prose: as before
    ("it's _private_", ["it", "s", "private"]),
])
def test_identifiers_are_terms_whole_and_by_part(text, expected) -> None:
    from llmgrader.coursemcp.materials import tokenize

    assert tokenize(text) == expected


def ranked(slides: list[tuple[str, str]], query: str) -> list[int]:
    index = TermIndex([(title, [text], n) for n, (title, text) in enumerate(slides, start=1)])
    return [n for _, n in index.search(query)]


def test_search_finds_an_identifier_and_not_its_fragments() -> None:
    slides = [
        ("Kernel types", "#pragma HLS INTERFACE s_axilite port=return"),
        ("Bus roles", "The AXI-Lite subordinate's registers, and the manager's writes"),
        ("Signed numbers", "It's two's complement: the sign bit's weight is negative"),
        ("Register map", "Each axilite register sits at a fixed offset"),
    ]
    found = ranked(slides, "s_axilite")
    assert found[0] == 1                 # the exact identifier first
    assert 3 not in found                # "it's", "two's": the "s" is not a match
    # A part still finds the whole identifier, as well as the bare word.
    assert set(ranked(slides, "axilite")) == {1, 4}


def test_an_exact_identifier_outranks_a_slide_that_only_shares_its_parts() -> None:
    assert ranked([("Control", "ap ctrl ap ctrl none of these ap ctrl handshakes ap ctrl"),
                   ("Free running", "ap_ctrl_none")], "ap_ctrl_none")[0] == 2


def test_weak_hits_are_cut() -> None:
    assert ranked([("Mealy machine", "A Mealy machine: outputs depend on state and inputs. Mealy Mealy."),
                   ("Machines", "Every machine in the lab")], "mealy machine") == [1]


# ---------------------------------------------------------------------------
# Showing a slide to the student
# ---------------------------------------------------------------------------


def test_read_material_gives_a_link_the_student_can_open(client) -> None:
    """A tool's image reaches the model only; the student needs a link."""
    body = ok(tool(client, "read_material", id="fsm", page=1))
    assert body["view_url"] == "http://localhost/c/alpha/slides/fsm/1"
    image = client.get("/c/alpha/slides/fsm/1")
    assert image.status_code == 200
    assert image.mimetype == "image/jpeg" and image.data == JPEG
    assert client.get("/c/alpha/slides/fifo/1").status_code == 404


@pytest.mark.parametrize("path", ["/c/alpha/slides/fsm/2", "/c/alpha/slides/fsm/9",
                                  "/c/alpha/slides/nope/1"])
def test_slide_route_refuses_what_it_should(client, path) -> None:
    # fsm/2's image path climbs out of the deck; 9 is out of range.
    assert client.get(path).status_code == 404


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


PORTAL_CONFIG = """<llmgrader>
  <course><course_id>alpha</course_id><name>A</name><semester>S</semester></course>
  <units><unit><name>U</name><source>u.xml</source><destination>u.xml</destination></unit></units>
</llmgrader>"""

UNIT_FILE = """<unit id="u" title="U" version="1.0">
  <question qtag="Q">
    <question_text>Q?</question_text><solution>A.</solution>
    <parts><part><part_label>all</part_label><points>1</points></part></parts>
  </question>
</unit>"""

CONFIG = """<llmgrader_mcp>
  <roots><root id="pub" path="pub"/></roots>
  <materials>
    <kind id="slides" description="Slides"/>
    <kind id="handout" description="Handouts"/>
    <kind id="lab-solution" description="Lab solutions" policy="tutor"/>
    <kind id="answer-key" description="Keys" policy="private"/>
    <unit id="setup" name="Course setup"/>
    {items}
  </materials>
</llmgrader_mcp>"""


def write_config(tmp_path: Path, items: str, *, extra: str = "") -> Path:
    (tmp_path / "pub").mkdir(exist_ok=True)
    (tmp_path / "llmgrader_config.xml").write_text(PORTAL_CONFIG, encoding="utf-8")
    path = tmp_path / "llmgrader_mcp_config.xml"
    path.write_text(CONFIG.format(items=items).replace("<materials>", extra + "<materials>"),
                    encoding="utf-8")
    return path


def test_config_rejects_a_missing_file(tmp_path) -> None:
    config = write_config(tmp_path, '<item id="a" kind="slides" root="pub" unit="U" path="nope.pptx"/>')
    with pytest.raises(MaterialsError, match="nope.pptx not found"):
        read_materials(config)


def test_config_rejects_an_unsafe_id(tmp_path) -> None:
    config = write_config(tmp_path, '<item id="../x" kind="slides" root="pub" unit="U" path="a.pptx"/>')
    with pytest.raises(MaterialsError, match="not valid"):
        read_materials(config)


def test_root_override(tmp_path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "a.pptx").write_bytes(b"x")
    config = write_config(tmp_path, '<item id="a" kind="slides" root="pub" unit="U" path="a.pptx"/>')
    spec = read_materials(config, {"pub": str(elsewhere)})
    assert spec.decks[0].pptx == (elsewhere / "a.pptx").resolve()


def test_units_resolve_by_name_whatever_the_spacing_or_a_material_unit_id(tmp_path) -> None:
    (tmp_path / "pub").mkdir()
    (tmp_path / "pub" / "a.md").write_text("# A\n", encoding="utf-8")
    config = write_config(tmp_path, '<item id="a" kind="handout" root="pub" path="a.md" '
                                    'unit="  u " also="setup"/>')
    assert read_materials(config).items[0].units == ["U", "Course setup"]


@pytest.mark.parametrize("items, message", [
    ('<item id="a" kind="slides" root="pub" path="a.pptx"/>', "these have none: a"),
    ('<item id="a" kind="video" root="pub" unit="U" path="a.pptx"/>', "unknown kind 'video'"),
    ('<item id="a" kind="slides" root="pub" unit="Unit 99" path="a.pptx"/>', "unknown unit 'Unit 99'"),
    ('<item id="ghost" unit="U"/>', "matches no item"),
    ('<item id="a" kind="slides" root="pub" unit="U" path="a.pptx"/>'
     '<item id="a" kind="slides" root="pub" unit="U" path="a.pptx"/>', "two items have the id 'a'"),
    ('<item id="a" kind="handout" root="pub" unit="U" path="*.md"/>', "package paths are explicit"),
    ('<item id="a" kind="handout" source="mirror" unit="U" path="labs"/>', "needs <code"),
])
def test_config_mistakes_fail_the_build(tmp_path, items, message) -> None:
    (tmp_path / "pub").mkdir()
    (tmp_path / "pub" / "a.pptx").write_bytes(b"x")
    with pytest.raises(MaterialsError, match=message.replace("(", r"\(").replace("*", r"\*")):
        read_materials(write_config(tmp_path, items))


def test_items_from_the_package_is_a_schema_error(tmp_path) -> None:
    config = write_config(tmp_path, '<items kind="handout" source="package" path="labs/*"/>')
    with pytest.raises(MaterialsError, match="not valid"):
        read_materials(config)


def test_a_refinement_applies_to_an_explicit_item(tmp_path) -> None:
    (tmp_path / "pub").mkdir()
    (tmp_path / "pub" / "a.md").write_text("# A\n", encoding="utf-8")
    config = write_config(tmp_path, '<item id="a" kind="handout" root="pub" path="a.md"/>'
                                    '<item id="a" title="Better" unit="U"><description>'
                                    'Says  what.</description></item>')
    [item] = read_materials(config).items
    assert (item.title, item.description, item.units) == ("Better", "Says what.", ["U"])


def write_package_course(tmp_path) -> Path:
    pub = tmp_path / "pub"
    (pub / "soln").mkdir(parents=True)
    (pub / "soln" / "fifo.sv").write_text("module fifo;\n  // TUTOR_ME\nendmodule\n", encoding="utf-8")
    (pub / "soln" / "build" / ".Xil").mkdir(parents=True)
    (pub / "soln" / "build" / ".Xil" / "junk.tcl").write_text("x", encoding="utf-8")
    (pub / "soln" / "wave.bin").write_bytes(b"\x00\x01")
    (pub / "key.md").write_text("# The key\n\nSECRET_ANSWER\n", encoding="utf-8")
    return write_config(tmp_path, """
    <item id="lab1-soln" kind="lab-solution" root="pub" unit="U" path="soln"/>
    <item id="midterm-key" kind="answer-key" root="pub" unit="U" path="key.md"/>""")


def test_tutor_and_private_round_trip_through_the_build(tmp_path) -> None:
    config = write_package_course(tmp_path)
    package = tmp_path / "pkg"
    manifest = build_materials(read_materials(config), package, log=lambda *_: None)
    kinds = {k["id"]: k["policy"] for k in manifest["kinds"]}
    assert (kinds["lab-solution"], kinds["answer-key"]) == ("tutor", "private")
    items = {i["id"]: i for i in manifest["items"]}
    # A folder is copied file by file, without build output or binaries.
    assert [p["path"] for p in items["lab1-soln"]["parts"]] == ["soln/fifo.sv"]
    assert (package / "mcp_materials" / "files" / "lab1-soln" / "soln" / "fifo.sv").is_file()
    # A private item is listed, and nothing of it is built into the package.
    assert items["midterm-key"]["parts"] == [{"path": "key.md"}]
    assert not any("SECRET_ANSWER" in p.read_text(errors="ignore")
                   for p in (package / "mcp_materials").rglob("*") if p.is_file())


# ---------------------------------------------------------------------------
# Build: slides and PDFs
# ---------------------------------------------------------------------------


def make_deck(path: Path, titles: list[str]) -> None:
    pptx = pytest.importorskip("pptx")
    prs = pptx.Presentation()
    for title in titles:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = title
        slide.placeholders[1].text = f"Body of {title}"
        slide.notes_slide.notes_text_frame.text = f"Notes for {title}"
    prs.save(str(path))


def make_pdf(path: Path, pages: int, *, label: str = "Page") -> None:
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    for number in range(1, pages + 1):
        # Distinct content per page: identical images share a description key.
        doc.new_page(width=720, height=405).insert_text((72, 72), f"{label} {number}", fontsize=40)
    doc.save(str(path))


def deck_config(tmp_path, pdf: bool = True) -> Path:
    return write_config(tmp_path, '<item id="d" kind="slides" root="pub" unit="U" path="deck.pptx"'
                                  + (' pdf="deck.pdf"' if pdf else "") + "/>")


@pytest.mark.parametrize("pages, expect_images", [(2, True), (3, False)])
def test_build_uses_the_pdf_only_when_it_matches_the_deck(tmp_path, pages, expect_images) -> None:
    pub = tmp_path / "pub"
    pub.mkdir()
    make_deck(pub / "deck.pptx", ["First\x0bTitle", "Second"])
    make_pdf(pub / "deck.pdf", pages)
    package = tmp_path / "pkg"
    manifest = build_materials(read_materials(deck_config(tmp_path)), package, log=lambda *_: None)

    entry = manifest["decks"][0]
    assert entry["images"] is expect_images
    assert ("re-export the PDF" in entry["warning"]) is (not expect_images)
    assert manifest["items"][0]["parts"] == [{"path": "deck.pptx", "format": "slides", "deck": "d"}]
    deck = json.loads((package / "mcp_materials" / "slides" / "d" / "deck.json").read_text())
    assert deck["title"] == "First Title"  # from the title slide, soft break removed
    assert deck["slides"][1] == {"n": 2, "title": "Second", "text": "Body of Second",
                                 "notes": "Notes for Second", "links": [],
                                 "image": "slide-002.jpg" if expect_images else None,
                                 "description": ""}
    jpgs = sorted(p.name for p in (package / "mcp_materials" / "slides" / "d").glob("*.jpg"))
    assert jpgs == (["slide-001.jpg", "slide-002.jpg"] if expect_images else [])


def test_a_pdf_reads_page_by_page(tmp_path, monkeypatch) -> None:
    """The pdf format (phase 3): a handout is served a page at a time,
    with its text and image, and searched like slides."""
    app = build_app(tmp_path, monkeypatch, token=TOKEN)
    pub = tmp_path / "pub"
    pub.mkdir()
    make_pdf(pub / "handout.pdf", 2, label="Karnaugh map")
    config = write_config(tmp_path, '<item id="kmap" kind="handout" root="pub" unit="U" '
                                    'path="handout.pdf"/>')
    package = tmp_path / "storage" / "courses" / "alpha" / "soln_pkg"
    build_materials(read_materials(config), package, log=lambda *_: None)
    client = app.test_client()

    part = ok(tool(client, "get_material", id="kmap"))["parts"][0]
    assert (part["format"], part["pages"], part["images"]) == ("pdf", 2, True)
    page = tool(client, "read_material", id="kmap", page=2)
    body = ok(page)
    assert (body["page"], body["of"], body["title"]) == (2, 2, "Karnaugh map 2")
    assert "Karnaugh map 2" in body["text"]
    assert [b for b in page["content"] if b["type"] == "image"]
    assert body["view_url"] == "http://localhost/c/alpha/slides/kmap/2"
    found = hits(client, "karnaugh", format="pdf")
    assert {(h["id"], h["page"]) for h in found} == {("kmap", 1), ("kmap", 2)}


def test_a_pdf_renders_once_per_content(tmp_path, monkeypatch) -> None:
    """A mirrored PDF is rendered on sync and cached by content hash: an
    unchanged one is not rendered again, a changed one is."""
    from llmgrader.coursemcp import materials

    make_pdf(tmp_path / "a.pdf", 2)
    make_pdf(tmp_path / "b.pdf", 3)
    renders = []
    real = materials.pdf_pages
    monkeypatch.setattr(materials, "pdf_pages", lambda *a: renders.append(1) or real(*a))
    import hashlib

    def render(name):
        data = (tmp_path / name).read_bytes()
        return materials.render_pdf_cached(data, tmp_path / "cache" / hashlib.sha256(data).hexdigest())

    out, first = render("a.pdf")
    assert len(first["pages"]) == 2 and (out / "page-001.jpg").is_file()
    assert render("a.pdf")[1] == first and len(renders) == 1
    assert len(render("b.pdf")[1]["pages"]) == 3 and len(renders) == 2


def test_a_mirrored_pdf_is_served_from_the_snapshot(tmp_path) -> None:
    from llmgrader.coursemcp.catalog import build_catalog
    from llmgrader.coursemcp.code import CodeConfig, attach_pdfs, build_snapshot
    from llmgrader.coursemcp.materials import Materials, UnitResolver

    tree = tmp_path / "tree"
    (tree / "handouts" / "kmap").mkdir(parents=True)
    make_pdf(tree / "handouts" / "kmap" / "kmap.pdf", 2, label="Karnaugh")
    config = CodeConfig.from_dict({"repo": "https://github.com/t/r",
                                   "includes": [{"path": "handouts"}]})
    snapshot = build_snapshot(tree, config, "abc")
    attach_pdfs(snapshot, tree, tmp_path / "cache")
    materials = Materials(root=tmp_path / "pkg", kinds=[{"id": "handout", "description": "H",
                                                         "policy": "open"}],
                          patterns=[{"kind": "handout", "path": "handouts/*", "docs": None,
                                     "units": ["U"]}], code=config.to_dict())
    catalog = build_catalog(materials, snapshot, UnitResolver(["U"]))
    part = catalog.get("kmap").parts[0]
    assert (part.path, part.format) == ("handouts/kmap/kmap.pdf", "pdf")
    paged = catalog.paged(part)
    assert len(paged.pages) == 2 and paged.image_path(paged.pages[0]["image"]).is_file()
    found = catalog.search("karnaugh", items=list(catalog.items.values()))
    assert {h["page"] for h in found["hits"]} == {1, 2}


def test_create_soln_pkg_builds_materials_into_the_zip(tmp_path, monkeypatch) -> None:
    """One upload carries everything: the slides travel inside soln_package.zip."""
    import sys
    import zipfile

    from llmgrader.scripts import create_soln_pkg

    src = tmp_path / "course"
    (src / "pub").mkdir(parents=True)
    make_deck(src / "pub" / "deck.pptx", ["Only slide"])
    (src / "llmgrader_config.xml").write_text(PORTAL_CONFIG, encoding="utf-8")
    (src / "u.xml").write_text(UNIT_FILE, encoding="utf-8")
    (src / "llmgrader_mcp_config.xml").write_text(CONFIG.format(
        items='<item id="d" kind="slides" root="pub" unit="U" path="deck.pptx"/>'), encoding="utf-8")

    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.chdir(out)
    monkeypatch.setattr(sys, "argv", ["create_soln_pkg", "--config", str(src / "llmgrader_config.xml")])
    assert create_soln_pkg.main() == 0

    names = set(zipfile.ZipFile(out / "soln_package.zip").namelist())
    assert "mcp_materials/manifest.json" in names
    assert "mcp_materials/slides/d/deck.json" in names


def test_materials_report_prints_each_item_and_its_units(tmp_path, capsys) -> None:
    from llmgrader.scripts import llmgrader_mcp_build

    config = write_package_course(tmp_path)
    assert llmgrader_mcp_build.main(["--config", str(config), "--package",
                                     str(tmp_path / "none"), "--materials"]) == 0
    out = capsys.readouterr().out
    assert "[lab1-soln]" in out and "unit  U    <- config" in out
    assert "lab-solution (1), tutor" in out and "1 listed, not built" in out


# ---------------------------------------------------------------------------
# Describe: the paid step, exercised with a fake model
# ---------------------------------------------------------------------------


def fake_caller(replies: dict, calls: list):
    """Stands in for answers.make_openai_answer_caller; replies keyed by slide number."""
    def make(*, model, api_key, prompt, timeout, images):
        number = int(prompt.split("This is slide ", 1)[1].split(" ", 1)[0])
        calls.append(number)

        def call():
            reply = replies[number]
            if isinstance(reply, Exception):
                raise reply
            return reply, 1000, 100
        return call
    return make


def described_deck(tmp_path, monkeypatch, replies):
    from llmgrader.coursemcp import materials
    from llmgrader.services import answers, models

    pub = tmp_path / "pub"
    pub.mkdir()
    make_deck(pub / "deck.pptx", ["Waveforms", "Summary"])
    make_pdf(pub / "deck.pdf", 2)
    config = deck_config(tmp_path)
    specs = read_materials(config).decks
    cache = materials.descriptions_dir(config)
    calls = []
    monkeypatch.setattr(answers, "make_openai_answer_caller", fake_caller(replies, calls))
    model = models.default_for_tier("simple")
    return materials, specs, cache, model, calls


def test_describe_caches_by_image_and_is_paid_once(tmp_path, monkeypatch) -> None:
    materials, specs, cache, model, calls = described_deck(tmp_path, monkeypatch, {
        1: "A timing diagram of a valid/ready handshake.", 2: "TEXT ONLY"})

    plan = materials.plan_descriptions(specs, materials.load_descriptions(cache), tmp_path / "w1")
    assert (len(plan.todo), plan.cached) == (2, 0)
    described, spent = materials.describe_slides(plan, cache, model_spec=model, api_key="k",
                                                 log=lambda *_: None)
    assert described == 2 and spent > 0

    saved = materials.load_descriptions(cache)
    assert sorted(v["description"] for v in saved.values()) == [
        "", "A timing diagram of a valid/ready handshake."]  # TEXT ONLY stores nothing

    again = materials.plan_descriptions(specs, saved, tmp_path / "w2")
    assert (len(again.todo), again.cached) == (0, 2)
    assert sorted(calls) == [1, 2]  # never asked twice


def test_a_pdf_page_is_described_as_a_page(tmp_path, monkeypatch) -> None:
    from llmgrader.coursemcp import materials
    from llmgrader.services import answers, models

    (tmp_path / "pub").mkdir()
    make_pdf(tmp_path / "pub" / "h.pdf", 1)
    config = write_config(tmp_path, '<item id="h" kind="handout" root="pub" unit="U" path="h.pdf"/>')
    prompts = []

    def make(*, model, api_key, prompt, timeout, images):
        prompts.append(prompt)
        return lambda: ("A figure.", 10, 10)

    monkeypatch.setattr(answers, "make_openai_answer_caller", make)
    specs = read_materials(config).decks
    plan = materials.plan_descriptions(specs, {}, tmp_path / "w")
    materials.describe_slides(plan, materials.descriptions_dir(config),
                              model_spec=models.default_for_tier("simple"), api_key="k",
                              log=lambda *_: None)
    assert prompts[0].startswith('This is page 1 of the document "Page 1"')


def test_one_failed_call_keeps_the_others(tmp_path, monkeypatch) -> None:
    materials, specs, cache, model, _ = described_deck(tmp_path, monkeypatch, {
        1: RuntimeError("rate limited"), 2: "A block diagram."})
    plan = materials.plan_descriptions(specs, {}, tmp_path / "w")
    materials.describe_slides(plan, cache, model_spec=model, api_key="k", log=lambda *_: None)
    assert [v["description"] for v in materials.load_descriptions(cache).values()] == ["A block diagram."]


def test_build_includes_descriptions_and_search_finds_them(tmp_path, monkeypatch) -> None:
    from llmgrader.coursemcp.catalog import build_catalog
    from llmgrader.coursemcp.materials import UnitResolver

    materials, specs, cache, model, _ = described_deck(tmp_path, monkeypatch, {
        1: "A Moore machine state diagram with three states.", 2: "TEXT ONLY"})
    plan = materials.plan_descriptions(specs, {}, tmp_path / "w")
    materials.describe_slides(plan, cache, model_spec=model, api_key="k", log=lambda *_: None)

    package = tmp_path / "pkg"
    build_materials(read_materials(deck_config(tmp_path)), package, log=lambda *_: None,
                    descriptions=materials.load_descriptions(cache))
    catalog = build_catalog(load_materials(str(package)), None, UnitResolver(["U"]))
    found = catalog.search("moore", items=list(catalog.items.values()))
    # The word is in no slide's text, only the description.
    assert [(h["id"], h["page"]) for h in found["hits"]] == [("d", 1)]


def test_describe_dry_run_spends_nothing(tmp_path, monkeypatch, capsys) -> None:
    from llmgrader.scripts import llmgrader_mcp_build

    materials, specs, cache, model, calls = described_deck(tmp_path, monkeypatch, {})
    config = tmp_path / "llmgrader_mcp_config.xml"
    assert llmgrader_mcp_build.main(["--config", str(config), "--describe", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "2 slide(s) to describe" in out and "estimated $" in out
    assert calls == [] and not cache.exists()


def test_missing_config_is_a_short_message(tmp_path, monkeypatch, capsys) -> None:
    """Run from the wrong folder: one line saying so, not a urllib traceback."""
    from llmgrader.scripts import llmgrader_mcp_build

    monkeypatch.chdir(tmp_path)
    assert llmgrader_mcp_build.main(["--dry-run"]) == 1
    err = capsys.readouterr().err
    assert "No llmgrader_mcp_config.xml in" in err
    assert "Traceback" not in err


def test_malformed_config_is_a_short_message(tmp_path) -> None:
    path = tmp_path / "llmgrader_mcp_config.xml"
    path.write_text("<llmgrader_mcp><materials>", encoding="utf-8")
    with pytest.raises(MaterialsError, match="not well-formed XML"):
        read_materials(path)


def test_force_redoes_described_slides(tmp_path, monkeypatch) -> None:
    materials, specs, cache, model, calls = described_deck(tmp_path, monkeypatch, {
        1: "First.", 2: "Second."})
    plan = materials.plan_descriptions(specs, {}, tmp_path / "w1")
    materials.describe_slides(plan, cache, model_spec=model, api_key="k", log=lambda *_: None)

    saved = materials.load_descriptions(cache)
    plain = materials.plan_descriptions(specs, saved, tmp_path / "w2")
    forced = materials.plan_descriptions(specs, saved, tmp_path / "w3", force=True)
    assert (len(plain.todo), plain.replacing) == (0, 0)
    assert (len(forced.todo), forced.replacing, forced.cached) == (2, 2, 0)


def test_identical_slides_are_sent_once(tmp_path, monkeypatch) -> None:
    from llmgrader.coursemcp import materials

    pub = tmp_path / "pub"
    pub.mkdir()
    make_deck(pub / "deck.pptx", ["Divider", "Divider"])
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    for _ in range(2):  # two pages drawn identically
        doc.new_page(width=720, height=405).insert_text((72, 72), "Same", fontsize=40)
    doc.save(str(pub / "deck.pdf"))
    plan = materials.plan_descriptions(read_materials(deck_config(tmp_path)).decks, {},
                                       tmp_path / "w")
    assert len(plan.todo) == 1


def test_deck_and_force_need_describe(tmp_path, monkeypatch, capsys) -> None:
    from llmgrader.scripts import llmgrader_mcp_build

    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "deck.pptx").write_bytes(b"x")
    config = deck_config(tmp_path, pdf=False)
    assert llmgrader_mcp_build.main(["--config", str(config), "--force"]) == 1
    assert "go with --describe" in capsys.readouterr().err
    assert llmgrader_mcp_build.main(["--config", str(config), "--describe", "--dry-run",
                                     "--deck", "nope"]) == 1
    assert "unknown deck(s) nope" in capsys.readouterr().err


def test_save_waits_out_a_briefly_locked_file(tmp_path, monkeypatch) -> None:
    """Windows refuses the replace while another program has the file open."""
    from llmgrader.coursemcp import materials

    real_replace = Path.replace
    failures = iter([PermissionError("locked"), PermissionError("locked")])

    def flaky_replace(self, target):
        error = next(failures, None)
        if error:
            raise error
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    directory = tmp_path / "llmgrader_mcp_descriptions"
    materials.write_deck_descriptions(directory, "d", [(1, "Title", "k")],
                                      {"k": {"description": "d", "model": "m"}})
    assert materials.load_descriptions(directory)["k"]["description"] == "d"


def test_descriptions_are_one_file_per_deck_in_slide_order(tmp_path, monkeypatch) -> None:
    """Readable top to bottom: a lecture's descriptions, numbered and titled."""
    materials, specs, directory, model, _ = described_deck(tmp_path, monkeypatch, {
        1: "First figure.", 2: "Second figure."})
    plan = materials.plan_descriptions(specs, {}, tmp_path / "w")
    materials.describe_slides(plan, directory, model_spec=model, api_key="k", log=lambda *_: None)

    assert directory == tmp_path / "llmgrader_mcp_descriptions"
    assert [p.name for p in directory.iterdir()] == ["d.json"]
    data = json.loads((directory / "d.json").read_text(encoding="utf-8"))
    assert data["deck"] == "d"
    assert [(e["slide"], e["title"], e["description"]) for e in data["slides"]] == [
        (1, "Waveforms", "First figure."), (2, "Summary", "Second figure.")]


def test_legacy_single_file_is_split_without_paying(tmp_path, monkeypatch) -> None:
    """The first release wrote one file; its descriptions carry over for free."""
    materials, specs, directory, model, calls = described_deck(tmp_path, monkeypatch, {})
    plan = materials.plan_descriptions(specs, {}, tmp_path / "w1")
    keys = [key for _, _, key in plan.decks["d"]]
    legacy = tmp_path / "llmgrader_mcp_descriptions.json"
    legacy.write_text(json.dumps({"version": 1, "slides": {
        keys[0]: {"description": "Old one.", "model": "m", "deck": "d", "slide": 1},
        keys[1]: {"description": "Old two.", "model": "m", "deck": "d", "slide": 2},
    }}), encoding="utf-8")

    cache = materials.load_descriptions(directory)
    again = materials.plan_descriptions(specs, cache, tmp_path / "w2")
    assert len(again.todo) == 0  # nothing to buy: the legacy file counts
    materials.sync_descriptions(again, directory, cache, log=lambda *_: None)

    assert not legacy.exists()
    assert (tmp_path / "llmgrader_mcp_descriptions.json.bak").exists()
    data = json.loads((directory / "d.json").read_text(encoding="utf-8"))
    assert [e["description"] for e in data["slides"]] == ["Old one.", "Old two."]
    assert calls == []


def test_descriptions_path_can_be_set_in_the_config(tmp_path) -> None:
    from llmgrader.coursemcp import materials

    config = tmp_path / "llmgrader_mcp_config.xml"
    config.write_text("""<llmgrader_mcp>
  <descriptions path="notes/slide_descriptions"/>
</llmgrader_mcp>""", encoding="utf-8")
    assert materials.descriptions_dir(config) == (tmp_path / "notes" / "slide_descriptions").resolve()
    read_materials(config)  # and the schema accepts it


def test_slide_number_and_footer_boxes_are_not_slide_text() -> None:
    """A figure-only slide's "text" was its slide number, "35"."""
    from types import SimpleNamespace

    from llmgrader.coursemcp.materials import _shape_texts

    def box(text, placeholder_type=None):
        return SimpleNamespace(
            shape_type=1, has_text_frame=True, has_table=False,
            text_frame=SimpleNamespace(text=text),
            is_placeholder=placeholder_type is not None,
            placeholder_format=SimpleNamespace(type=placeholder_type))

    assert _shape_texts(box("35", 13)) == []          # slide number
    assert _shape_texts(box("Fall 2026", 16)) == []   # date
    assert _shape_texts(box("NYU", 15)) == []         # footer
    assert _shape_texts(box("Real content", 2)) == ["Real content"]
    assert _shape_texts(box("Free text box")) == ["Free text box"]


def test_a_slide_with_little_text_is_always_described() -> None:
    from llmgrader.coursemcp.materials import TEXT_ONLY, text_only_rule

    assert TEXT_ONLY not in text_only_rule("")
    assert TEXT_ONLY not in text_only_rule("A short caption")
    assert TEXT_ONLY in text_only_rule("A long paragraph of slide text. " * 10)


def test_redo_empty_requeues_only_empty_descriptions(tmp_path, monkeypatch) -> None:
    materials, specs, directory, model, _ = described_deck(tmp_path, monkeypatch, {
        1: "A real description.", 2: "TEXT ONLY"})
    plan = materials.plan_descriptions(specs, {}, tmp_path / "w1")
    materials.describe_slides(plan, directory, model_spec=model, api_key="k", log=lambda *_: None)

    cache = materials.load_descriptions(directory)
    plain = materials.plan_descriptions(specs, cache, tmp_path / "w2")
    redo = materials.plan_descriptions(specs, cache, tmp_path / "w3", redo_empty=True)
    assert len(plain.todo) == 0
    assert [slide["n"] for _, slide, _, _ in redo.todo] == [2]
