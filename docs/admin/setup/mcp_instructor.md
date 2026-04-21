---
title: Using Agent for Course Authoring
parent: Setting Up LLM Grader
nav_order: 5
has_children: false
---

# Using an Agent for Course Authoring

## LLM Grader's MCP Server

LLM grader is being designed with agentic assitance to help instructors build course content.  Eventually, this agent will help tasks including creating course packages, questions, solutions, and grading rubrics.

The agent functionality is exposed as **model context protocol** or MCP server.  [Describe what is an MCP server and why it is good].

## Initial Functionality

The initial MCP server for LLM grader is just for authoring the configuration file, `llmgrader_config.xml`, inside Visual Studio Code.  If successful, the functionality will expand.  For now, the current MCP server can help you:

- scan your workspace for likely unit XML files and asset folders
- generate a starter `llmgrader_config.xml`
- validate the config before packaging

The current tools are:

- `llmgrader_explain_config`
- `llmgrader_create_config_skeleton`
- `llmgrader_validate_config_xml`
- `llmgrader_scan_repo_for_config_inputs`

## Recommended Instructor Setup

The simplest setup is:

- Follow the instructions for installing the LLM grader python package and [create a virtual environment](./python.md)
- Start VS Code from that activated environment.
As mentioned in the [editor section](./editor.md), VS Code is the currently the preferred IDE for LLM grader, although other platforms may be considered in the future.

After VS Code is open, you will need to configure the `.vscode/mcp.json` in your course repo to run `llmgrader_mcp_server`.  The configuration depends on the OS:

## Windows Setup

From PowerShell in your course repository:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install llmgrader
code .
```

Then create `.vscode/mcp.json` with:

```json
{
  "servers": {
    "llmgrader": {
      "type": "stdio",
      "command": "llmgrader_mcp_server"
    }
  }
}
```

If you are testing changes from a local clone of `llmgrader`, install from that
clone instead:

```powershell
pip install -e <path-to-llmgrader>
```

## Linux or macOS Setup

From a shell in your course repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install llmgrader
code .
```

Then create `.vscode/mcp.json` with:

```json
{
  "servers": {
    "llmgrader": {
      "type": "stdio",
      "command": "llmgrader_mcp_server"
    }
  }
}
```

If `llmgrader_mcp_server` is not found, VS Code probably did not inherit the
virtual environment `PATH`. In that case, close VS Code, activate the
environment in a fresh shell, and start VS Code again from that shell with
`code .`.

## Optional Windows Environment Variable Override

If the virtual environment is in the folder as the repo you are working on, the path to python with `llmgrader` and the other dependencies installed should be found.  However, if you prefer to keep your virtual environment outside the course repo
and want an explicit local override, you can set one of these Windows
environment variables before starting VS Code:

```powershell
$env:LLMGRADER_MCP_PYTHON = "C:\path\to\python.exe"
```

or:

```powershell
$env:LLMGRADER_MCP_VENV = "C:\path\to\your-venv"
```


These variables are useful only if your local MCP launch path actually uses a
wrapper that reads them. They do not affect the plain
`"command": "llmgrader_mcp_server"` setup by themselves.

If you set one of these variables in a PowerShell session, start VS Code from
that same session:

```powershell
code .
```

If you persist the variable with Windows system settings or `setx`.  For example,

```powershell
setx LLMGRADER_MCP_PYTHON "C:\path\to\python.exe"
```

Then, fully close and reopen VS Code so the MCP host inherits the new environment.

## When `llmgrader_mcp_server` Works

This command-based setup works when all of the following are true:

- `llmgrader` is installed in the environment you want to use
- the environment also contains the `mcp` dependency
- VS Code inherited the `PATH` from that environment

For most users, starting VS Code from the activated virtual environment is the
important step.

## Restarting the MCP Server

After changing `mcp.json` or reinstalling packages, restart the server in VS
Code:

1. Open the Command Palette.
2. Run `MCP: List Servers`.
3. Select `llmgrader`.
4. Choose `Restart`, or `Stop` and then `Start`.

You usually do not need to close and reopen VS Code unless you changed the
environment after VS Code was already open.

## Troubleshooting

- If you see `No module named mcp`, the interpreter used by VS Code does not
  have the `mcp` package installed.
- If you see `llmgrader_mcp_server` not found, VS Code is not using the virtual
  environment where `llmgrader` was installed.
- If the server looks stuck after you start it manually in a normal terminal,
  that is expected for a stdio MCP server waiting for VS Code to connect.

## Typical Copilot Usage

Once the server is running, useful prompts include:

- Explain how to create `llmgrader_config.xml`
- Scan this repo for likely config inputs
- Create a skeleton `llmgrader_config.xml` for this course
- Validate this `llmgrader_config.xml` against the workspace