---
title: Set-Up
parent: Developer Guide
nav_order: 1
has_children: false
---

# Set-up for Developers

Most of the set-up instructions are identical to general users -- see the [instructor setup instructions](../admin/setup/).  We point out a few minor differences.


## Python installation

Similar to general developers, you should  [fork and clone](../admin/setup/python.md) the python package.
Then, you can follow all the remaining installation instructions.
The one key difference is that you should install the python package in editable mode:  Specifically, use


```bash
pip install -e .
```

The `-e` flag means editable mode. Your environment points at the working copy
of the repository, so Python sees your local code changes immediately.

## MCP Setup

MCP setup for developers is installed the same way as it is for regular users;
see the [instructor-facing guide for MCP setup](../admin/setup/mcp_instructor.md).

In practice, that means you should install `llmgrader` into the environment you
want VS Code to use for MCP and then run:

```bash
llmgrader_mcp_setup --workspace .
```

If you are working inside this source repository, the generated `.vscode/mcp.json`
will contain an interpreter-specific absolute path, so treat it as a local
workspace override rather than something to commit.

