---
title: Administrator Guide
parent: LLM Grader
nav_order: 3
has_children: true
---

# Administrator Guide

This section contains documentation for instructors and administrators who wish to set-up and manage the LLM Grader system.  We recommend the following steps:

- [Set-up LLM grader](./setup/):  Install the LLM grader python package, IDE, and, optionally, a VS Code-based agentic service, on your local machine
- [Build the course package](./buildcourse/) on the local machine.  The course package will include all the units in the class, and XML descriptions of the problems and grading rubrics
- [Deploy the course on a web portal](./deploy/).  We recommend render.com.  At this point, students will be able to view and answer questions, and download submissions.
- [Integrate with Gradescope](./gradescope/):  For each unit, create an assignment in Gradescope with an autograder that can receive the student submissions.


