# llmgrader MCP server (prototype)

This repository includes a minimal MCP server for `llmgrader_config.xml` authoring.

## What it provides

- `llmgrader_explain_config`: quick authoring guidance
- `llmgrader_create_config_skeleton`: generate a skeleton XML from structured inputs
- `llmgrader_validate_config_xml`: validate XML shape and destination-path rules
- `llmgrader_scan_repo_for_config_inputs`: scan a workspace for likely unit XML / asset dirs

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
