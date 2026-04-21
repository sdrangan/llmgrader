---
title:  Installing the Python Package
parent: Setting Up LLM Grader
nav_order: 1
has_children: false
---

# Installing the Python Package

LLM Grader is packaged as a normal Python project. The package contains:

- the Flask web application used by the grading portal
- the XML/schema assets needed by the app
- command-line utilities for course-package creation and autograder packaging

At a minimum, you can install it like any other Python package. In practice,
this repository also includes `requirements.txt` and `requirements-dev.txt` for
the broader runtime and development stacks used by the project.

## Recommended Setup Steps

1. Install Python 3.12 or a nearby compatible version.
2. Fork the repository on GitHub.
3. Clone your fork locally.
4. Create a virtual environment.
5. Activate that environment.
6. Install the package.



### Fork and Clone the Repository

The main LLM grader repo is located at:

```bash
https://github.com/sdrangan/llmgrader
```

You should fork this repository rather than only cloning the main project repo.
That gives you an independent GitHub copy that you can later connect to Render
for your own deployment.

On GitHub, use the **Fork** button to create your own copy of the repository.
Then clone your fork to your local machine:

```bash
git clone <https://github.com/<your-github-user>/llmgrader.git>
cd llmgrader
```

## Create and Activate a Virtual Environment

A virtual environment is an isolated Python workspace for one project. It lets
you install this project's packages without affecting other Python projects or
your system-wide Python installation. In this guide, the virtual environment
will live in a local `.venv` folder inside your cloned repository.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks script execution, you can either activate from `cmd.exe`
instead, or temporarily allow scripts in your user scope.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Once the environment is active, your shell prompt usually shows the venv name.

## Choose an Installation Mode

At this point you should be in the repository root with your virtual
environment activated. Now choose one of the installation methods below.

If you are not already in the directory you cloned from your fork, change into
it now:

```bash
cd llmgrader
```

### Standard Installation

Use this when you want to run the app or the packaging utilities without editing the source code itself.

```bash
pip install .
```

This copies a normal installed version of the package into your environment.
If you later change the source tree, you will need to run the install command
again.

### Editable Installation

Use this when you are actively developing or debugging LLM Grader -- see the [developer's guide](../../developer/).

```bash
pip install -e .
```

The `-e` flag means editable mode. Your environment points at the working copy
of the repository, so Python sees your local code changes immediately.

For most contributors, this is the more convenient choice.

## Install the Package

### Minimal package install

Install just the Python package metadata and its declared package dependencies:

```bash
pip install -e .
```

or, if you do not want editable mode:

```bash
pip install .
```

This is the cleanest packaging-oriented install path.


## Verifying the Installation

After installation, these quick checks are useful:

```bash
python -c "import llmgrader; print('ok')"
python run.py --help
```

If both commands work, the package is installed correctly enough to continue.

## When to Reinstall

You usually need to reinstall only in these cases:

- you used `pip install .` and then changed source files
- you changed package metadata or dependencies
- you switched to a fresh virtual environment

If you used `pip install -e .`, normal Python source edits do not require a
reinstall.

## Troubleshooting

- If `python` points to the wrong interpreter, verify the virtual environment is
	activated.
- If an import fails even after `pip install -e .`, check whether you also need
	the broader dependencies from `requirements.txt`.
- If the app starts but login or grading features fail, make sure you have also
	configured the required environment variables and API keys.


