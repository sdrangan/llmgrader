---
title: Selecting an IDE
parent: Setting Up LLM Grader
nav_order: 3
has_children: false
---

# Selecting an IDE

To build a course package, you will spend most of your time editing XML files,
HTML fragments inside CDATA blocks, and a few configuration files.

So while you do not need a heavyweight IDE, you do want an editor that makes it
easy to:

- edit XML without fighting indentation
- spot mismatched tags quickly
- search across multiple course files
- work with folders such as `example_repo/`, `soln_package/`, and your own
	course package source tree

## Recommended Choice: Visual Studio Code

For this project, the recommended editor is **Visual Studio Code**.

VS Code is a good fit because it gives you:

- solid XML and Markdown editing
- easy folder-based project navigation
- integrated terminal support
- search across the full repository
- Git integration
- a good path for future AI-assisted authoring workflows

It is also the editor used most often in the surrounding project workflow, so
the documentation and examples fit naturally with it.

## What You Need from an Editor

Whatever editor you choose, make sure it handles these tasks well:

### XML editing

Your course content is defined in XML files such as:

- `llmgrader_config.xml`
- unit XML files containing questions, solutions, parts, grading notes, and rubrics

The editor should make it easy to:

- indent nested XML cleanly
- collapse and expand sections
- highlight matching tags
- avoid accidental malformed XML

### Markdown editing

The documentation pages in `docs/` are written in Markdown. If you plan to edit
the admin or student docs, Markdown preview is useful.

### Terminal access

You will often want to run commands such as:

```bash
create_soln_pkg --config llmgrader_config.xml
python run.py --soln_pkg example_repo/soln_package
```

An integrated terminal makes this much easier.

### Search across files

Course packages often span multiple units and assets. Good project-wide search
is very helpful when you are tracking down:

- a question tag
- a rubric id
- an image reference
- a unit source or destination path

## Suggested VS Code Workflow: Open Both Folders

Your course content and the `llmgrader` application live in
[two separate repositories](../buildcourse/pkgconfig.md).  VS Code can show both
at once in a single window, which is the setup we recommend:

1. Open your course folder (for example `hwdesign-soln`).
2. Choose **File → Add Folder to Workspace...** and add the `llmgrader` folder.
3. Optionally **File → Save Workspace As...** so the pair reopens together next
	 time.

The Explorer then shows both trees side by side, global search covers both, and
the integrated terminal can `cd` between them.

### Why Add `llmgrader` Even If You Never Edit It

It is tempting to open only your course repo, since that is the only folder you
will change.  Having `llmgrader` in the workspace is worth it anyway, especially
if you use an AI agent:

- **The agent can read real examples.**  `example_repo/` contains complete,
	working unit XML -- multi-part questions, rubric groups, images, binary and
	partial-credit grading.  An agent that can see those writes far better XML than
	one working from a description of the format.
- **The schemas are the ground truth.**  `llmgrader/schemas/unit.xsd` and
	`llmgrader_config.xsd` define exactly what is valid.  An agent that reads them
	will not invent elements that fail validation.
- **The docs are in the same tree.**  Everything under `docs/` is searchable
	alongside your content.

The [MCP authoring server](./mcp_setup.md) covers much of this ground directly,
and the two work well together: MCP tells the agent what the format *is*, while
the repository shows it what good course content actually looks like.

> **Treat `llmgrader` as read-only.** With both folders open, an agent may offer
> to edit application source when it was only asked to fix your course content.
> Unless you are working on the grader itself, keep your changes inside the course
> folder -- it keeps `git pull` on `llmgrader` painless.

If you *are* modifying the grader, the same two-folder workspace is what you
want; the only difference is that edits to `llmgrader` are then intentional.

Beyond the folder setup:

- Keep the Explorer visible so you can move between your units, `example_repo/`,
	and `docs/`.
- Use the integrated terminal to build the solution package and run the app.
- Use global search when editing qtags, rubric ids, or asset paths.

## Optional VS Code Extensions

You can work without extra extensions, but these categories are often helpful:

- XML support and formatting
- Markdown preview tools
- Python support
- Git history or diff tools

If you prefer another editor, that is fine. The main requirement is that it be
comfortable for XML-heavy authoring.

## Other Editors Are Fine

You do not have to use VS Code.

Any editor or IDE is acceptable if it gives you:

- reliable XML editing
- reasonable search/navigation
- easy access to a terminal or command runner

Examples include PyCharm, Sublime Text, Notepad++, or a terminal-based editor
such as Vim or Neovim.

## Looking Ahead

In future versions, we expect to add more editor-assisted and agent-assisted
workflows for creating XML questions, grading notes, and rubrics. For now, the
main goal is simply to use an editor that makes structured text editing easy and
safe.