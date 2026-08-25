---
title: Quickstart
parent: Getting Started
nav_order: 2
has_children: false
---

# Quickstart: Grade Your First Question in 15 Minutes

This page gets you from nothing to a working grader running on your own laptop,
using the example course that ships with the repository.  There is no Google
Cloud setup, no packaging, and no deployment -- those come later, and only if
you decide you want them.

You need [a GitHub account, Python 3.12, and an OpenAI API key](./requirements.md).

---

## 1. Fork and Clone

Fork <https://github.com/sdrangan/llmgrader> on GitHub, then clone your fork:

```bash
git clone https://github.com/<your-github-user>/llmgrader.git
cd llmgrader
```

Forking now (rather than cloning the upstream repo directly) saves you a step
later if you decide to deploy on Render.

## 2. Create a Virtual Environment

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> **If PowerShell refuses to run the activation script** with a message about
> execution policies, run this first and then activate again.  It applies only
> to the current terminal window:
>
> ```powershell
> Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
> ```

Your prompt should now show `(.venv)`.

## 3. Install the Package

```bash
pip install -e .
```

Check that it worked:

```bash
python -c "import llmgrader; print('ok')"
```

## 4. Run the Example Course

```bash
python run.py --soln_pkg example_repo/soln_package
```

Open <http://127.0.0.1:5000/> in your browser.  You should see a course with two
units -- a calculus unit and a Python unit.

Nothing else needs to be configured.  The `--soln_pkg` flag loads the course
straight from disk, so you can skip the admin upload entirely while you explore.

## 5. Add Your OpenAI Key and Grade Something

The grader never stores API keys on the server -- each user supplies their own in
the browser, and it stays in local storage.

1. Get a key from the
   [OpenAI API key page](https://platform.openai.com/account/api-keys).
2. In the portal, go to **File → Preferences**.
3. Paste the key into the **OpenAI key** box.

Now pick a question, type an answer -- deliberately try a partially correct one --
and click **Grade**.  You should get back a score, per-rubric-item feedback, and
an explanation of why the model awarded each point.

A graded question costs a fraction of a cent.

---

## What to Look at Next

Now that it runs, the interesting question is what the grading rubric looks like.
Open [example_repo/unit1/calculus.xml](https://github.com/sdrangan/llmgrader/blob/main/example_repo/unit1/calculus.xml)
in your editor and compare it to what you just saw in the browser: the question
text, the reference solution, and the rubric items the model was scoring against.

That file is the whole content format.  Authoring a course means writing more
files like it.

## Then Choose Your Path

- **To see the admin view** (uploading course packages, the database viewer),
  restart the app with the development bypass -- no Google setup needed:

  ```bash
  # macOS / Linux
  export LLMGRADER_AUTH_MODE=dev-open

  # Windows PowerShell
  $env:LLMGRADER_AUTH_MODE = "dev-open"
  ```

  See [Deploying on a Local Machine](../deploy/local.md).

- **To write your own questions**, continue to
  [Build Your Own Course](./buildcourse.md), which walks through the same loop
  with one question of your own.  [Building a Course Package](../buildcourse/) is
  the full reference once you are past that.  If you use VS Code with an AI agent,
  the [MCP server](../setup/mcp_setup.md) can read the homework and solutions you
  already have and draft the XML for you, which is much faster than writing it by
  hand.

- **To put it in front of students**, go to [Deploying the App](../deploy/).
  This is where you will need a Render account and Google OAuth credentials.

- **To check that your rubrics grade the way you intend**, see
  [Testing your grading](../buildcourse/gradetests.md) -- you write trial answers,
  declare the score each should get, and re-run the suite from the command line.
