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

## Suggested VS Code Workflow

If you use VS Code, a simple setup is:

1. Open the repository root folder.
2. Keep the Explorer visible so you can move between `docs/`, `example_repo/`,
	 and `llmgrader/`.
3. Use the integrated terminal to build the solution package and run the app.
4. Use global search when editing qtags, rubric ids, or asset paths.

This is usually enough to be productive.

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