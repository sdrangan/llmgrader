---
title: Deploying on a Local Machine
parent: Deploying the App
nav_order: 1
has_children: false
---

# Deploying the App on a Local Machine

Before deploying the app on a public portal, you should test it on your own
machine.  Running locally needs far less setup than a Render deployment -- in
particular, **you do not need Google OAuth credentials to run locally**.

## Running the Student Portal

Navigate to the `llmgrader` repo, activate your virtual environment, and run:

```bash
python run.py --soln_pkg <soln_pkg>
```

where `<soln_pkg>` is the path to the solution package that was created
following the [packaging instructions](../buildcourse/upload.md).  Then open
<http://127.0.0.1:5000/> in your browser.

The `--soln_pkg` flag loads the course directly from disk, so you can skip the
admin upload step entirely while you are authoring.  To try this immediately
with the bundled example course:

```bash
python run.py --soln_pkg example_repo/soln_package
```

The student-facing portal -- browsing units, answering questions, and grading --
works with no environment variables set at all.  Students supply their own
OpenAI key in the browser, so nothing needs to be configured on the server.

## Reaching the Admin View Locally

The **Admin** view (loading course packages, the database viewer) is protected by
login.  For local work you have two options:

### Option 1: Development bypass (recommended for local use)

Set one environment variable before starting the app:

```bash
# macOS / Linux
export LLMGRADER_AUTH_MODE=dev-open

# Windows PowerShell
$env:LLMGRADER_AUTH_MODE = "dev-open"
```

This grants admin access without any Google configuration.  It is intended for
local development only -- never set it on a public deployment.

### Option 2: Full Google OAuth

If you want to exercise the real sign-in flow locally, follow the
[Google OAuth setup](../setup/oauth.md) and register
`http://127.0.0.1:5000/auth/callback` as an authorized redirect URI.  This is
required for Render, but optional for local testing.

---

Next: [Deploying on Render](./render.md)
