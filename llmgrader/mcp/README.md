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

Open this repo as a workspace, start Copilot Chat with MCP enabled, and call the `llmgrader_*` tools.
