---
title: Deploying on a Local Machine
parent: Deploying the App
nav_order: 1
has_children: false
---

# Deploying the App on a Local Machine

Before deploying the app on a public portal, you should test the portal on a local machine. 

First, make sure you set up the [Google OAuth credentials](../setup/oauth.md).  This set-up is required even for a local deployment.

 Then, for running the portal on a local machine, navigate to the repo `llmgrader` and simply run:

```bash
python run.py --soln_pkg <soln_pkg>
```

where `<soln_pkg>` is the path to the solution package that was created following the [packaging instructions](../buildcourse/upload.md).  You should now be able to see the course on your browser.

---

Go to [deploying on render]