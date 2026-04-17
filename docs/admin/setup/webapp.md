---
title: Launching the App Locally
parent: Setting Up LLM Grader
nav_order: 2
has_children: false
---

# Running the App Locally

Once you have [installed the Python package](python.md), the next step is to
build a solution package and launch the local web app.

This page shows the fastest end-to-end local workflow using the bundled
example course.

If you want full sign-in behavior locally, also configure the environment
variables described in [Setting up Google OAuth](oauth.md).

See the [deployment](../deploy/) section when you are ready to publish the app
to a hosted service such as Render.

## Local Workflow Summary

The local launch flow is:

1. build a solution package
2. start the Flask app and point it at that package
3. open the app in your browser

## Build the Example Course Package

The repository includes an example source course in `example_repo/`.

From the repository root:

```bash
cd example_repo
create_soln_pkg --config llmgrader_config.xml
cd ..
```

That command creates a packaged course in:

```text
example_repo/soln_package
```

This is the directory you pass to `run.py`.

If `create_soln_pkg` is not found, make sure your virtual environment is
activated and that you installed the package as described in [Installing the Python Package](python.md).

## Launch the App

From the repository root:

```bash
python run.py --soln_pkg example_repo/soln_package
```

Then open:

```text
http://127.0.0.1:5000/
```

You should see the example units from `example_repo`, including the demo
calculus and Python questions.

## Local Authentication Options

You have two reasonable options for local development.

### Option 1: Normal local OAuth

Use this if you want to test sign-in and admin behavior realistically.

Set the Google OAuth environment variables described in [Setting up Google OAuth](oauth.md), then run:

```bash
python run.py --soln_pkg example_repo/soln_package
```

### Option 2: Development open mode

Use this if you just want to work on the app locally without configuring Google
OAuth first.

Set the environment variable

```text
LLMGRADER_AUTH_MODE=dev-open
```

This bypasses admin authorization checks for local development.

To set the environment variables in Windows Powershell:

```powershell
$env:LLMGRADER_AUTH_MODE = "dev-open"
python run.py --soln_pkg example_repo/soln_package
```

In macOS/Linux:

```bash
export LLMGRADER_AUTH_MODE=dev-open
python run.py --soln_pkg example_repo/soln_package
```

Do not use `dev-open` in production.

## What `--soln_pkg` Means

The `--soln_pkg` argument points to a packaged course directory that contains:

- `llmgrader_config.xml`
- packaged unit XML files
- packaged assets such as images

In normal local development, you should usually point it at the output of
`create_soln_pkg` rather than at the raw authoring directory.

If you omit `--soln_pkg`, the app may still start, but it will only show course
content if an existing solution package is already available in the configured
storage area.

## Rebuilding After Editing the Example Course

If you edit files inside `example_repo/`, rebuild the package before relaunching
or retesting:

```bash
cd example_repo
create_soln_pkg --config llmgrader_config.xml
cd ..
```

Then restart the local app if needed.

## Troubleshooting

- If the app starts but no units appear, verify that `example_repo/soln_package`
	exists and contains `llmgrader_config.xml`.
- If `create_soln_pkg` fails, read the XML validation errors and fix them
	before retrying.
- If sign-in fails in normal mode, verify the Google OAuth settings in
	[Setting up Google OAuth](oauth.md).
- If you just need to get unstuck locally, use `LLMGRADER_AUTH_MODE=dev-open`
	temporarily.
