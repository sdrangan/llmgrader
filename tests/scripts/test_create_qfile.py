import sys
from pathlib import Path

from llmgrader.scripts import create_qfile


RESOURCE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "unit_parser"


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


def _write_asset_unit_xml(unit_path: Path, image_url: str) -> None:
        unit_path.write_text(
                f"""<unit id="fixture_good" title="Fixture Good Unit" version="1.0">
    <question qtag="q_partial" preferred_model="gpt-4.1-mini">
        <question_text><![CDATA[
        <p>Inspect the figure.</p>
        <img src="{image_url}" alt="Fixture image" />
        ]]></question_text>
        <solution><![CDATA[
        <p>Use the plotted figure.</p>
        ]]></solution>
        <grading_notes><![CDATA[
        Accept equivalent implementations.
        ]]></grading_notes>
        <required>false</required>
        <partial_credit>true</partial_credit>
        <rubrics>
            <item id="correct_update" point_adjustment="2.5">
                <display_text>Correct update</display_text>
                <condition>Student uses the correct update equation.</condition>
            </item>
        </rubrics>
        <parts>
            <part>
                <part_label>all</part_label>
                <points>2.5</points>
            </part>
        </parts>
    </question>
</unit>
""",
                encoding="utf-8",
        )


def test_create_qfile_rewrites_pkg_assets_with_explicit_config(tmp_path, monkeypatch) -> None:
        course_root = tmp_path / "course"
        unit_dir = course_root / "unit2"
        image_dir = unit_dir / "images"
        image_dir.mkdir(parents=True)
        (image_dir / "func.png").write_bytes(b"\x89PNG\r\n")

        unit_path = unit_dir / "python.xml"
        _write_asset_unit_xml(unit_path, "/pkg_assets/unit2_images/func.png")

        config_path = course_root / "llmgrader_config.xml"
        config_path.write_text(
                """<llmgrader>
    <course>
        <name>Fixture Course</name>
        <term>Fall 2026</term>
    </course>
    <units>
        <unit>
            <name>Unit 2</name>
            <source>unit2/python.xml</source>
            <destination>unit2_python.xml</destination>
        </unit>
    </units>
    <assets>
        <asset>
            <source>unit2/images</source>
            <destination>unit2_images</destination>
        </asset>
    </assets>
</llmgrader>
""",
                encoding="utf-8",
        )

        output_path = unit_dir / "python.html"
        monkeypatch.setattr(
                sys,
                "argv",
                [
                        "create_qfile",
                        "--input",
                        str(unit_path),
                        "--config",
                        str(config_path),
                        "--output",
                        str(output_path),
                ],
        )

        exit_code = create_qfile.main()

        assert exit_code == 0
        assert 'src="images/func.png"' in output_path.read_text(encoding="utf-8")


def test_create_qfile_auto_discovers_config_for_pkg_assets(tmp_path, monkeypatch) -> None:
        course_root = tmp_path / "course"
        unit_dir = course_root / "unit2"
        image_dir = unit_dir / "images"
        image_dir.mkdir(parents=True)
        (image_dir / "func.png").write_bytes(b"\x89PNG\r\n")

        unit_path = unit_dir / "python.xml"
        _write_asset_unit_xml(unit_path, "/pkg_assets/unit2_images/func.png")

        (course_root / "llmgrader_config.xml").write_text(
                """<llmgrader>
    <course>
        <name>Fixture Course</name>
        <term>Fall 2026</term>
    </course>
    <units>
        <unit>
            <name>Unit 2</name>
            <source>unit2/python.xml</source>
            <destination>unit2_python.xml</destination>
        </unit>
    </units>
    <assets>
        <asset>
            <source>unit2/images</source>
            <destination>unit2_images</destination>
        </asset>
    </assets>
</llmgrader>
""",
                encoding="utf-8",
        )

        output_path = unit_dir / "python.html"
        monkeypatch.setattr(
                sys,
                "argv",
                [
                        "create_qfile",
                        "--input",
                        str(unit_path),
                        "--output",
                        str(output_path),
                ],
        )

        exit_code = create_qfile.main()

        assert exit_code == 0
        assert 'src="images/func.png"' in output_path.read_text(encoding="utf-8")


def test_create_qfile_rewrites_legacy_namespaced_images(tmp_path, monkeypatch) -> None:
        course_root = tmp_path / "course"
        unit_dir = course_root / "unit2"
        image_dir = unit_dir / "images"
        image_dir.mkdir(parents=True)
        (image_dir / "func.png").write_bytes(b"\x89PNG\r\n")

        unit_path = unit_dir / "python.xml"
        _write_asset_unit_xml(unit_path, "/pkg_assets/unit2_python_images/func.png")

        (course_root / "llmgrader_config.xml").write_text(
                """<llmgrader>
    <course>
        <name>Fixture Course</name>
        <term>Fall 2026</term>
    </course>
    <units>
        <unit>
            <name>Unit 2</name>
            <source>unit2/python.xml</source>
            <destination>unit2_python.xml</destination>
        </unit>
    </units>
</llmgrader>
""",
                encoding="utf-8",
        )

        output_path = unit_dir / "python.html"
        monkeypatch.setattr(
                sys,
                "argv",
                [
                        "create_qfile",
                        "--input",
                        str(unit_path),
                        "--output",
                        str(output_path),
                ],
        )

        exit_code = create_qfile.main()

        assert exit_code == 0
        assert 'src="images/func.png"' in output_path.read_text(encoding="utf-8")


def test_create_qfile_errors_when_asset_destination_not_in_config(
    tmp_path, monkeypatch, capsys
) -> None:
    course_root = tmp_path / "course"
    unit_dir = course_root / "unit2"
    image_dir = unit_dir / "images"
    image_dir.mkdir(parents=True)
    (image_dir / "func.png").write_bytes(b"\x89PNG\r\n")

    unit_path = unit_dir / "python.xml"
    _write_asset_unit_xml(unit_path, "/pkg_assets/unit2_images/func.png")

    config_path = course_root / "llmgrader_config.xml"
    config_path.write_text(
        """<llmgrader>
    <course>
    <name>Fixture Course</name>
    <term>Fall 2026</term>
    </course>
    <units>
    <unit>
        <name>Unit 2</name>
        <source>unit2/python.xml</source>
        <destination>unit2_python.xml</destination>
    </unit>
    </units>
</llmgrader>
""",
        encoding="utf-8",
    )

    output_path = unit_dir / "python.html"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_qfile",
            "--input",
            str(unit_path),
            "--config",
            str(config_path),
            "--output",
            str(output_path),
        ],
    )

    exit_code = create_qfile.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "destination path /pkg_assets/unit2_images/func.png was not found" in captured.out
    assert not output_path.exists()


def test_create_qfile_errors_when_asset_source_missing(
    tmp_path, monkeypatch, capsys
) -> None:
    course_root = tmp_path / "course"
    unit_dir = course_root / "unit2"
    unit_dir.mkdir(parents=True)

    unit_path = unit_dir / "python.xml"
    _write_asset_unit_xml(unit_path, "/pkg_assets/unit2_images/func.png")

    config_path = course_root / "llmgrader_config.xml"
    config_path.write_text(
        """<llmgrader>
    <course>
    <name>Fixture Course</name>
    <term>Fall 2026</term>
    </course>
    <units>
    <unit>
        <name>Unit 2</name>
        <source>unit2/python.xml</source>
        <destination>unit2_python.xml</destination>
    </unit>
    </units>
    <assets>
    <asset>
        <source>unit2/images</source>
        <destination>unit2_images</destination>
    </asset>
    </assets>
</llmgrader>
""",
        encoding="utf-8",
    )

    output_path = unit_dir / "python.html"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_qfile",
            "--input",
            str(unit_path),
            "--config",
            str(config_path),
            "--output",
            str(output_path),
        ],
    )

    exit_code = create_qfile.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "source asset for /pkg_assets/unit2_images/func.png was not found" in captured.out
    assert not output_path.exists()


def test_create_qfile_errors_when_config_missing_for_pkg_assets(
    tmp_path, monkeypatch, capsys
) -> None:
    unit_dir = tmp_path / "unit2"
    unit_dir.mkdir(parents=True)
    unit_path = unit_dir / "python.xml"
    _write_asset_unit_xml(unit_path, "/pkg_assets/unit2_images/func.png")

    output_path = unit_dir / "python.html"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create_qfile",
            "--input",
            str(unit_path),
            "--output",
            str(output_path),
        ],
    )

    exit_code = create_qfile.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "no llmgrader_config.xml was provided or discovered" in captured.out
    assert not output_path.exists()