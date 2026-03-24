import sys
from pathlib import Path

from llmgrader.scripts import create_qfile


RESOURCE_DIR = Path(__file__).parent / "fixtures" / "unit_parser"


def test_create_qfile_rejects_invalid_xml(tmp_path, capsys, monkeypatch) -> None:
    output_path = tmp_path / "broken.html"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_qfile",
            "--input",
            str(RESOURCE_DIR / "unit_broken.xml"),
            "--output",
            str(output_path),
        ],
    )

    exit_code = create_qfile.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Validation errors found in input XML file:" in captured.out
    assert "line 6" in captured.out
    assert not output_path.exists()


def test_create_qfile_generates_output_for_valid_xml(tmp_path, monkeypatch) -> None:
    output_path = tmp_path / "good.html"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_qfile",
            "--input",
            str(RESOURCE_DIR / "unit_good.xml"),
            "--output",
            str(output_path),
        ],
    )

    exit_code = create_qfile.main()

    assert exit_code == 0
    assert output_path.exists()
    assert "Fixture Good Unit" in output_path.read_text(encoding="utf-8")