from pathlib import Path
from types import SimpleNamespace

import pytest

from llmgrader.scripts.llmgrader_mcp_setup import render_mcp_config
from llmgrader.scripts.llmgrader_mcp_setup import validate_python_interpreter
from llmgrader.scripts.llmgrader_mcp_setup import write_mcp_config


def test_render_mcp_config_embeds_python_path():
    rendered = render_mcp_config(python_path="/tmp/venv/bin/python")

    assert '"command": "/tmp/venv/bin/python"' in rendered
    assert '"args": [' in rendered
    assert '"llmgrader.mcp.server"' in rendered


def test_validate_python_interpreter_rejects_missing_llmgrader(monkeypatch):
    monkeypatch.setattr(
        "llmgrader.scripts.llmgrader_mcp_setup.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stderr="ModuleNotFoundError: No module named 'llmgrader'",
            stdout="",
        ),
    )

    with pytest.raises(RuntimeError) as excinfo:
        validate_python_interpreter("/tmp/missing-python")

    assert "cannot import llmgrader.mcp.server" in str(excinfo.value)


def test_write_mcp_config_creates_workspace_file(tmp_path):
    output_path = write_mcp_config(
        workspace=tmp_path,
        python_path="/tmp/venv/bin/python",
    )

    assert output_path == tmp_path / ".vscode" / "mcp.json"
    assert output_path.exists()
    assert '"command": "/tmp/venv/bin/python"' in output_path.read_text(encoding="utf-8")


def test_write_mcp_config_requires_force_when_file_exists(tmp_path):
    existing_path = tmp_path / ".vscode" / "mcp.json"
    existing_path.parent.mkdir(parents=True)
    existing_path.write_text("{}", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_mcp_config(workspace=tmp_path, python_path="/tmp/venv/bin/python")