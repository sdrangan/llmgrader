# llmgrader MCP server (prototype)

This repository includes a minimal MCP server for `llmgrader_config.xml` and unit XML authoring.

## What it provides

- `llmgrader_get_llmgrader_config_structure`: nested guidance for the llmgrader_config.xml element tree and authoring constraints
- `llmgrader_create_config_skeleton`: generate a skeleton XML from structured inputs
- `llmgrader_validate_config_xml`: validate XML shape and destination-path rules
- `llmgrader_scan_repo_for_config_inputs`: scan a workspace for likely unit XML / asset dirs
- `llmgrader_get_unit_xml_structure`: nested guidance for the unit XML element tree and authoring constraints
- `llmgrader_explain_rubric_rules`: quick guidance for binary and partial-credit rubrics
- `llmgrader_create_unit_xml_skeleton`: generate a starter unit XML from structured inputs
- `llmgrader_validate_unit_xml`: validate unit XML structure and common rubric issues
- `llmgrader_scan_repo_for_unit_inputs`: scan a workspace for unit XMLs, rubric examples, assets, and nearby authoring files

## Local setup

```bash
cd /path/to/llmgrader
pip install -e .
```

Then run the MCP server over stdio:

```bash
llmgrader_mcp_server
```

## VS Code MCP wiring

An example workspace config is provided at:

- `.vscode/mcp.json`

The checked-in workspace config uses a repo-local launcher script on Windows instead of hardcoding a machine-specific Python path. The launcher tries, in order:

- `LLMGRADER_MCP_PYTHON` if it points to a `python.exe`
- `LLMGRADER_MCP_VENV` if it points to a virtual environment directory
- the currently activated virtual environment via `VIRTUAL_ENV`
- `.venv\\Scripts\\python.exe` under the workspace root
- `venv\\Scripts\\python.exe` under the workspace root
- `py -3`
- `python`

If your virtual environment is outside the repo, set one of these Windows environment variables before starting VS Code:

```powershell
$env:LLMGRADER_MCP_PYTHON = 'C:\path\to\python.exe'
```

or

```powershell
$env:LLMGRADER_MCP_VENV = 'C:\path\to\your-venv'
```

If you set the variable outside VS Code after VS Code is already open, fully restart VS Code so the MCP host picks up the new environment.

For the most predictable setup, create a repo-local virtual environment and install the project into it:

```bash
cd /path/to/llmgrader
python -m venv .venv
.venv\\Scripts\\pip install -e .
```

Then open this repo as a workspace, start Copilot Chat with MCP enabled, and call the `llmgrader_*` tools.

Useful prompts now include:

- Explain how to create `llmgrader_config.xml`
- Scan this repo for likely config inputs
- Create a skeleton `llmgrader_config.xml` for this course
- Explain how to create a unit XML file
- Explain rubric rules for a partial-credit question
- Create a starter unit XML for a binary or partial-credit question
- Validate this unit XML against the documented authoring rules
