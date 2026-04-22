---
title:  Using the LLM Course Builder Agent
parent: Building a Course Package
nav_order: 6
has_children: false
---


# Using an Agent for Course Authoring

## LLM Grader's MCP Server

LLM grader is being designed with agentic assistance to help instructors build course content. The goal is not to replace hand authoring, but to make it faster to create a correct first draft and then validate it before packaging. Over time, this workflow should help with tasks such as:

- creating course package configuration files
- drafting unit XML files
- sketching solutions and grading rubrics
- checking authoring mistakes before packaging

The current agent functionality is exposed through a **Model Context Protocol** (MCP) server. An MCP server is a small tool server that an LLM client, such as GitHub Copilot in Visual Studio Code, can call while answering your prompt. In practice, that means the model can do more than generate text: it can inspect your workspace, create a starter XML file, and run validation tools before replying.

This is useful for course authoring because the model does not need to guess the format from your prompt alone. It can use the same helper functions and validation logic that the repository uses during development.

## Initial Functionality

The current MCP prototype can help with both course configuration files and unit XML authoring inside Visual Studio Code.

For `llmgrader_config.xml`, it can:

- scan your workspace for likely unit XML files and asset folders
- generate a starter `llmgrader_config.xml`
- validate the config before packaging

For unit XML authoring, it can:

- explain the expected unit XML structure
- explain rubric conventions for binary and partial-credit questions
- generate a starter unit XML file
- validate a unit XML draft for common schema and rubric mistakes
- scan the workspace for nearby examples and likely assets

The current tools are:

- `llmgrader_get_llmgrader_config_structure`
- `llmgrader_create_config_skeleton`
- `llmgrader_validate_config_xml`
- `llmgrader_scan_repo_for_config_inputs`
- `llmgrader_get_unit_xml_structure`
- `llmgrader_explain_rubric_rules`
- `llmgrader_create_unit_xml_skeleton`
- `llmgrader_validate_unit_xml`
- `llmgrader_scan_repo_for_unit_inputs`

## How to Use the Agent

The easiest way to use the agent today is through GitHub Copilot Chat in Visual Studio Code.

### 1. Install the project in a Python environment

From the repository root, install the package into the Python environment that VS Code should use for the MCP server:

```powershell
pip install -e .
```

If you prefer a repo-local environment, create one first:

```powershell
python -m venv .venv
.venv\Scripts\pip install -e .
```

### 2. Make sure VS Code can find the Python interpreter

This repository includes a workspace MCP configuration in `.vscode/mcp.json`. If your Python environment is not in `.venv`, set one of the following environment variables before starting VS Code:

```powershell
$env:LLMGRADER_MCP_PYTHON = 'C:\path\to\python.exe'
```

or

```powershell
$env:LLMGRADER_MCP_VENV = 'C:\path\to\your-venv'
```

If you set these after VS Code is already open, restart VS Code so the MCP host picks them up.

### 3. Open the repository in VS Code and use Copilot Chat

Once the workspace is open, start Copilot Chat with MCP enabled and ask for one of the tasks below. The agent can inspect the current workspace and call the `llmgrader_*` tools as needed.

## Starting Prompt Examples

These prompts are intended as starting points. In practice, the best workflow is often:

1. ask the agent to scan the workspace
2. ask it to draft a file
3. ask it to validate the result
4. revise the XML manually if needed

### Example: start a course config

```text
Scan this workspace for likely unit XML files and asset folders, then create a starter llmgrader_config.xml for a probability course for Fall 2026.
```

### Example: validate a config draft

```text
Validate this llmgrader_config.xml and tell me what I still need to fix before packaging.
```

### Example: draft a binary-graded probability question

```text
Create a starter unit XML for a probability unit with one binary-graded question.
The question should ask students to list the sample space for two fair coin tosses.
Include a simple binary rubric and validate the XML before presenting it.
```

### Example: draft a partial-credit probability question

```text
Create a starter unit XML for a probability unit with one partial-credit question about computing P(A union B) from P(A), P(B), and P(A intersection B).
Break the question into parts, include a partial-credit rubric, and validate the XML before presenting it.
```

### Example: ask only for rubric help

```text
Explain the rubric rules for a partial-credit probability question and show a minimal rubric example for a problem about expected value.
```

### Example: improve an existing unit XML file

```text
Scan this workspace for unit authoring inputs, then review my current unit XML draft and point out missing question_text, solution, parts, or rubric issues.
```

## What to Expect from the Agent

The current MCP tools are best viewed as authoring helpers, not a one-shot course builder. They are good at:

- producing a valid initial XML skeleton
- reflecting the structure already documented in this repository
- catching missing required fields and common rubric mistakes

They are not yet a substitute for instructor review. You should still check that:

- the mathematics or course content is correct
- the rubric matches the learning objective
- the solution is complete enough for grading
- asset paths and packaging destinations are what you intended

## Recommended Workflow

For new content, a practical workflow is:

1. Create or collect your source materials in the workspace.
2. Ask the agent to scan the repo for likely config or unit inputs.
3. Ask it to create a starter XML file.
4. Edit the draft manually to reflect your exact wording and scoring policy.
5. Ask the agent to validate the revised XML.
6. Package and upload only after the XML passes validation and you have reviewed the result.

