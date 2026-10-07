"""Lecture slides in the course MCP: the build, and the four slide tools.

Serving needs nothing but JSON and images in the package, so those tests
write them by hand and always run.  The build tests make a real .pptx and
PDF and are skipped where python-pptx / PyMuPDF (the mcp-build extra) are not
installed.

The properties that would fail silently:

* a stale PDF -- page count differs from the deck -- must not be used, or each
  slide's image would sit beside another slide's text;
* only listed files are published;
* search_slides must not log the query: it is the student's own words.
"""

import json
from pathlib import Path

import pytest

from llmgrader.coursemcp.materials import (
    MaterialsError,
    build_materials,
    load_materials,
    read_config,
)

from test_course_content import TOKEN, build_app, call, payload  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"slide-image"


def write_materials(package: Path) -> None:
    """A hand-written mcp_materials tree: one deck with images, one without."""
    root = package / "mcp_materials"
    fsm = root / "slides" / "fsm"
    fifo = root / "slides" / "fifo"
    fsm.mkdir(parents=True)
    fifo.mkdir(parents=True)
    (fsm / "slide-001.jpg").write_bytes(JPEG)
    (fsm / "deck.json").write_text(json.dumps({
        "id": "fsm", "unit": "Unit 1:  Basics", "title": "Sequential Logic", "source": "fsm.pptx",
        "slides": [
            {"n": 1, "title": "Finite State Machines", "text": "Moore and Mealy machines",
             "notes": "", "image": "slide-001.jpg"},
            {"n": 2, "title": "Next-state logic", "text": "always_comb computes the next state",
             "notes": "Stress non-blocking assignment here.", "image": "../../../secret.jpg"},
        ]}), encoding="utf-8")
    (fifo / "deck.json").write_text(json.dumps({
        "id": "fifo", "unit": "Unit 5: Streams", "title": "FIFOs", "source": "fifo.pptx",
        "slides": [{"n": 1, "title": "FIFO full and empty", "text": "A FIFO with depth N",
                    "notes": "", "image": None}]}), encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({"version": 1, "decks": [
        {"id": "fsm", "unit": "Unit 1:  Basics", "title": "Sequential Logic",
         "slides": 2, "images": True, "warning": ""},
        {"id": "fifo", "unit": "Unit 5: Streams", "title": "FIFOs",
         "slides": 1, "images": False, "warning": "no PDF given"},
    ]}), encoding="utf-8")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    app = build_app(tmp_path, monkeypatch, token=TOKEN)
    write_materials(tmp_path / "storage" / "courses" / "alpha" / "soln_pkg")
    return app.test_client()


def items(result: dict) -> list:
    assert result.get("isError") is not True, result
    return [json.loads(block["text"]) for block in result["content"]]


# ---------------------------------------------------------------------------
# Serving
# ---------------------------------------------------------------------------


def test_list_materials_filters_by_unit(client) -> None:
    all_decks = items(call(client, "list_materials", {"course_id": "alpha"}))
    assert [d["deck"] for d in all_decks] == ["fsm", "fifo"]
    unit_1 = items(call(client, "list_materials", {"course_id": "alpha", "unit": "unit 1: basics"}))
    assert [d["deck"] for d in unit_1] == ["fsm"]


def test_get_outline(client) -> None:
    outline = items(call(client, "get_outline", {"course_id": "alpha", "deck": "fsm"}))
    assert [(s["slide"], s["title"]) for s in outline] == [
        (1, "Finite State Machines"), (2, "Next-state logic")]


def test_search_ranks_the_matching_slide_first(client) -> None:
    hits = items(call(client, "search_slides", {"course_id": "alpha", "query": "mealy machine"}))
    assert (hits[0]["deck"], hits[0]["slide"]) == ("fsm", 1)
    notes_hit = items(call(client, "search_slides", {"course_id": "alpha", "query": "non-blocking"}))
    assert (notes_hit[0]["deck"], notes_hit[0]["slide"]) == ("fsm", 2)


def test_search_can_be_limited_to_a_unit(client) -> None:
    hits = items(call(client, "search_slides",
                      {"course_id": "alpha", "query": "fifo state", "unit": "Unit 5: Streams"}))
    assert {h["deck"] for h in hits} == {"fifo"}


def test_search_does_not_log_the_query(client, capsys) -> None:
    call(client, "search_slides", {"course_id": "alpha", "query": "my-private-question-words"})
    assert "my-private-question-words" not in capsys.readouterr().out


def test_get_slide_returns_image_and_notes(client) -> None:
    result = call(client, "get_slide", {"course_id": "alpha", "deck": "fsm", "slide": 1})
    body = payload(result)
    assert (body["title"], body["of"]) == ("Finite State Machines", 2)
    image = [b for b in result["content"] if b["type"] == "image"]
    assert len(image) == 1 and image[0]["mimeType"] == "image/jpeg"


def test_slide_image_path_cannot_leave_the_deck(client) -> None:
    result = call(client, "get_slide", {"course_id": "alpha", "deck": "fsm", "slide": 2})
    assert not [b for b in result["content"] if b["type"] == "image"]
    assert payload(result)["notes"] == "Stress non-blocking assignment here."


def test_text_only_deck_says_so(client) -> None:
    body = payload(call(client, "get_slide", {"course_id": "alpha", "deck": "fifo", "slide": 1}))
    assert body["image"].startswith("not available")


@pytest.mark.parametrize("args, expected", [
    ({"deck": "nope", "slide": 1}, "Valid decks"),
    ({"deck": "fsm", "slide": 9}, "slides 1 to 2"),
])
def test_bad_deck_or_slide_is_a_readable_error(client, args, expected) -> None:
    result = call(client, "get_slide", {"course_id": "alpha", **args})
    assert result["isError"] is True
    assert expected in result["content"][0]["text"]


def test_course_without_slides_says_so(tmp_path, monkeypatch) -> None:
    client = build_app(tmp_path, monkeypatch, token=TOKEN).test_client()
    result = call(client, "list_materials", {"course_id": "alpha"})
    assert result["isError"] is True
    assert "not published any lecture slides" in result["content"][0]["text"]


def test_materials_reload_when_the_manifest_changes(tmp_path) -> None:
    write_materials(tmp_path)
    assert len(load_materials(str(tmp_path)).decks) == 2
    manifest = tmp_path / "mcp_materials" / "manifest.json"
    data = json.loads(manifest.read_text())
    data["decks"] = data["decks"][:1]
    manifest.write_text(json.dumps(data))
    import os, time
    later = time.time() + 5
    os.utime(manifest, (later, later))
    assert len(load_materials(str(tmp_path)).decks) == 1


# ---------------------------------------------------------------------------
# Config and build
# ---------------------------------------------------------------------------


CONFIG = """<llmgrader_mcp>
  <roots><root id="pub" path="pub"/></roots>
  <slides>
    {decks}
  </slides>
</llmgrader_mcp>"""


def write_config(tmp_path: Path, decks: str) -> Path:
    path = tmp_path / "llmgrader_mcp_config.xml"
    path.write_text(CONFIG.format(decks=decks), encoding="utf-8")
    return path


def test_config_rejects_a_missing_file(tmp_path) -> None:
    (tmp_path / "pub").mkdir()
    config = write_config(tmp_path, '<deck id="a" root="pub" unit="U">nope.pptx</deck>')
    with pytest.raises(MaterialsError, match="nope.pptx not found"):
        read_config(config)


def test_config_rejects_an_unsafe_deck_id(tmp_path) -> None:
    config = write_config(tmp_path, '<deck id="../x" root="pub" unit="U">a.pptx</deck>')
    with pytest.raises(MaterialsError, match="not valid"):
        read_config(config)


def test_root_override(tmp_path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "a.pptx").write_bytes(b"x")
    config = write_config(tmp_path, '<deck id="a" root="pub" unit="U">a.pptx</deck>')
    specs = read_config(config, {"pub": str(elsewhere)})
    assert specs[0].pptx == (elsewhere / "a.pptx").resolve()


def make_deck(path: Path, titles: list[str]) -> None:
    pptx = pytest.importorskip("pptx")
    prs = pptx.Presentation()
    for title in titles:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = title
        slide.placeholders[1].text = f"Body of {title}"
        slide.notes_slide.notes_text_frame.text = f"Notes for {title}"
    prs.save(str(path))


def make_pdf(path: Path, pages: int) -> None:
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    for number in range(1, pages + 1):
        # Distinct content per page: identical images share a description key.
        doc.new_page(width=720, height=405).insert_text((72, 72), f"Page {number}", fontsize=40)
    doc.save(str(path))


@pytest.mark.parametrize("pages, expect_images", [(2, True), (3, False)])
def test_build_uses_the_pdf_only_when_it_matches_the_deck(tmp_path, pages, expect_images) -> None:
    pub = tmp_path / "pub"
    pub.mkdir()
    make_deck(pub / "deck.pptx", ["First\x0bTitle", "Second"])
    make_pdf(pub / "deck.pdf", pages)
    config = write_config(tmp_path, '<deck id="d" root="pub" unit="U" pdf="deck.pdf">deck.pptx</deck>')

    package = tmp_path / "pkg"
    manifest = build_materials(read_config(config), package, log=lambda *_: None)

    entry = manifest["decks"][0]
    assert entry["images"] is expect_images
    assert ("re-export the PDF" in entry["warning"]) is (not expect_images)
    deck = json.loads((package / "mcp_materials" / "slides" / "d" / "deck.json").read_text())
    assert deck["title"] == "First Title"  # from the title slide, soft break removed
    assert deck["slides"][1] == {"n": 2, "title": "Second", "text": "Body of Second",
                                 "notes": "Notes for Second",
                                 "image": "slide-002.jpg" if expect_images else None,
                                 "description": ""}
    jpgs = sorted(p.name for p in (package / "mcp_materials" / "slides" / "d").glob("*.jpg"))
    assert jpgs == (["slide-001.jpg", "slide-002.jpg"] if expect_images else [])


def test_create_soln_pkg_builds_slides_into_the_zip(tmp_path, monkeypatch) -> None:
    """One upload carries everything: the slides travel inside soln_package.zip."""
    import sys
    import zipfile

    from llmgrader.scripts import create_soln_pkg

    src = tmp_path / "course"
    (src / "pub").mkdir(parents=True)
    make_deck(src / "pub" / "deck.pptx", ["Only slide"])
    (src / "llmgrader_config.xml").write_text("""<llmgrader>
  <course><course_id>alpha</course_id><name>A</name><semester>S</semester></course>
  <units><unit><name>U</name><source>u.xml</source><destination>u.xml</destination></unit></units>
</llmgrader>""", encoding="utf-8")
    (src / "u.xml").write_text("""<unit id="u" title="U" version="1.0">
  <question qtag="Q">
    <question_text>Q?</question_text><solution>A.</solution>
    <parts><part><part_label>all</part_label><points>1</points></part></parts>
  </question>
</unit>""", encoding="utf-8")
    (src / "llmgrader_mcp_config.xml").write_text(CONFIG.format(
        decks='<deck id="d" root="pub" unit="U">deck.pptx</deck>'), encoding="utf-8")

    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.chdir(out)
    monkeypatch.setattr(sys, "argv", ["create_soln_pkg", "--config", str(src / "llmgrader_config.xml")])
    assert create_soln_pkg.main() == 0

    names = set(zipfile.ZipFile(out / "soln_package.zip").namelist())
    assert "mcp_materials/manifest.json" in names
    assert "mcp_materials/slides/d/deck.json" in names


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
    config = write_config(tmp_path, '<deck id="d" root="pub" unit="U" pdf="deck.pdf">deck.pptx</deck>')
    specs = read_config(config)
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


def test_one_failed_call_keeps_the_others(tmp_path, monkeypatch) -> None:
    materials, specs, cache, model, _ = described_deck(tmp_path, monkeypatch, {
        1: RuntimeError("rate limited"), 2: "A block diagram."})
    plan = materials.plan_descriptions(specs, {}, tmp_path / "w")
    materials.describe_slides(plan, cache, model_spec=model, api_key="k", log=lambda *_: None)
    assert [v["description"] for v in materials.load_descriptions(cache).values()] == ["A block diagram."]


def test_build_includes_descriptions_and_search_finds_them(tmp_path, monkeypatch) -> None:
    materials, specs, cache, model, _ = described_deck(tmp_path, monkeypatch, {
        1: "A Moore machine state diagram with three states.", 2: "TEXT ONLY"})
    plan = materials.plan_descriptions(specs, {}, tmp_path / "w")
    materials.describe_slides(plan, cache, model_spec=model, api_key="k", log=lambda *_: None)

    package = tmp_path / "pkg"
    build_materials(specs, package, log=lambda *_: None,
                    descriptions=materials.load_descriptions(cache))
    loaded = load_materials(str(package))
    hits = loaded.search("moore")  # the word is in no slide's text, only the description
    assert [(h["deck"], h["slide"]) for h in hits] == [("d", 1)]


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
    path.write_text("<llmgrader_mcp><slides>", encoding="utf-8")
    with pytest.raises(MaterialsError, match="not well-formed XML"):
        read_config(path)


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
    config = write_config(tmp_path, '<deck id="d" root="pub" unit="U" pdf="deck.pdf">deck.pptx</deck>')
    plan = materials.plan_descriptions(read_config(config), {}, tmp_path / "w")
    assert len(plan.todo) == 1


def test_deck_and_force_need_describe(tmp_path, monkeypatch, capsys) -> None:
    from llmgrader.scripts import llmgrader_mcp_build

    pub = tmp_path / "pub"
    pub.mkdir()
    (pub / "a.pptx").write_bytes(b"x")
    config = write_config(tmp_path, '<deck id="a" root="pub" unit="U">a.pptx</deck>')
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
    read_config(config)  # and the schema accepts it
