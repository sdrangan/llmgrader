---
title: Using Agent for Course Authoring
parent: Setting Up LLM Grader
nav_order: 4
has_children: false
---

# Setting up The MCP Server

## Overview

As described in the [instructor guide](../buildcourse/agent.md), LLM grader is being designed with agentic assistance to help instructors build course content. To use this facility, you will have to set up the **model context protocol** or MCP server. For now the setup is designed for users in VS Code. The process can be adapted for other IDEs such as Claude Code.

## Instructor Set-Up

To set up the MCP server on VS Code, first follow the [instructions](./python.md) to create and activate a virtual environment, then install `llmgrader` into that environment. You can install from a cloned `llmgrader` repository or from a published package source, as long as the environment you activate contains `llmgrader`.

Independent of where the virtual environment is installed, navigate to the root folder of the repository where you wish to work:

- If you are an instructor working in a repository with your class material, say `calculus_soln`, navigate to that repository;
- If you are an LLM grader developer working on the `llmgrader` repository itself, navigate to the root of the `llmgrader` repository.

From there run:

```bash
llmgrader_mcp_setup --workspace .
```

The function will copy a file, `.vscode/mcp.json` to the repostitory root that VS Code uses a configuration file for the MCP server.  If `.vscode/mcp.json` already exists, rerun the command with `--force` to replace it:

```bash
llmgrader_mcp_setup --workspace . --force
```

The setup command discovers its own interpreter path, verifies that `llmgrader.mcp.server` can be imported from that interpreter, and then writes `.vscode/mcp.json` for the workspace.

In most cases this command only needs to be run once per workspace. If you later recreate or move the virtual environment, rerun `llmgrader_mcp_setup --workspace .` so `.vscode/mcp.json` points to the new interpreter path.

After the command is run, you can launch VS Code from the command line:

```bash
code .
```

## Testing the MCP Server is Running

The simplest way to confirm that the MCP server is running is:

1. In VS Code, Open the Command Palette.
2. Run `MCP: List Servers`.
3. Select `llmgrader`.
4. Choose `Restart`, or `Stop` and then `Start`.

After changing `mcp.json` or reinstalling packages, you can also use the above procedure to restart the server in VS Code:

You usually do not need to close and reopen VS Code unless you changed the environment after VS Code was already open.

## Troubleshooting

- If you see `No module named mcp`, the interpreter used by VS Code does not have the `mcp` package installed.
- If `llmgrader_mcp_setup` fails, make sure you activated the intended environment before running it and that `pip install llmgrader` or `pip install -e <path-to-llmgrader>` completed successfully.
- If the server looks stuck after you start it manually in a normal terminal, that is expected for a stdio MCP server waiting for VS Code to connect.

## Typical Copilot Usage

Once the server is running, useful prompts in CoPilot chat include:

- Explain how to create `llmgrader_config.xml`
- Create a unit on chain rule and write a simple problem on taking the derivative of `x*e^{-x}`.

