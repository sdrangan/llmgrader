---
title: Deploying on Render
parent: Administrator Guide
nav_order: 2
has_children: true
---
# Launching and Deploying the Grader

Once you have [built a course package](../buildcourse/), we can upload it to a portal.
First, I would test the portal on a local machine.
For running the portal on a local machine, navigate to the repo `llmgrader` and simply run:

```bash
python run.py --soln_pkg <soln_pkg>
```

where `<soln_pkg>` is the path to the solution package that was created following the
[packaging instructions](../buildcourse/upload.md).
You should now be able to see the course on your browser.

# Deploying on Render

Once you are ready to deploy the grader on a public render portal follow the following instructions:

- [Deploying on render](deploy.md)
- [Setting the password](password.md)
