---
title: Overview
parent: LLM Grader
nav_order: 1
has_children: true
---

# How LLM Grader Works

LLM Grader is designed to make open-ended technical assessment more practical for instructors. It combines structured authoring, model-based grading, and lightweight course operations into one workflow. The goal is simple: help faculty create high-quality assessments, grade reasoning-heavy work more consistently, and give students faster feedback.

This is especially useful for courses where traditional autograders are too rigid. Instead of grading only exact numeric answers or fixed code outputs, LLM Grader is built to evaluate multi-step reasoning, derivations, design choices, partial progress, and explanation quality.

## Core Components

LLM Grader has five main pieces that work together.

### 1. Course package

The course package is the instructor-authored source of truth. It includes:

- questions
- reference solutions
- grading rubrics
- grading notes
- packaging metadata and assets

These are stored in a structured XML format so the grading behavior is explicit, inspectable, and versionable. The XML is detailed enough to support both binary and partial-credit grading, multipart questions, instructor notes, and packaged images or other assets.

The benefit of this structure is that instructors are not handing grading over to an opaque prompt. They are defining the question and grading intent in a format that can be validated, reused, and improved over time.

### 2. Web portal

LLM Grader includes a lightweight Flask-based portal where students can:

- view assigned questions
- submit responses
- receive grading feedback
- iterate on their work in a try, grade, and improve loop

For instructors, this creates a usable front end without requiring a large learning platform integration up front. It is intentionally lightweight so departments or individual faculty can pilot the system without a heavy deployment burden.

### 3. Back-end AI grader service

The grading service uses LLM-based evaluation to compare student work against the instructor's solution, grading notes, and rubric definitions. This is where LLM Grader differs most from conventional autograders.

It is intended for problems where the work matters, not just the final answer. Depending on the question design, the grader can evaluate:

- whether the student used a valid method
- whether intermediate reasoning is mathematically or technically sound
- whether the final result is correct
- whether partial credit should be awarded for substantial progress

The grading logic is guided by the structured authoring data, which makes the grading process more transparent and more controllable than a free-form prompt-only approach.

### 4. AI course builder

LLM Grader now includes an MCP-based authoring assistant for instructors working in Visual Studio Code. This agent can help with:

- scanning the workspace for likely course-authoring inputs
- drafting `llmgrader_config.xml`
- drafting unit XML questions
- suggesting an authoring plan before drafting more complex questions
- surfacing curated example questions
- validating the resulting XML before it is packaged

This matters because authoring structured grading content is powerful, but it can also be tedious if done entirely by hand. The MCP workflow is designed to accelerate the first draft while still keeping the instructor in control.

In practice, a strong authoring flow often looks like this:

1. scan the repo for available course inputs
2. inspect a close example question
3. review the supported XML structure and rubric conventions
4. draft a first XML version
5. validate the draft before packaging

Recent internal traces show that this plan-and-example-first workflow can produce a valid first unit XML draft without needing a repair loop, which is a promising result for practical instructor use.

### 5. Analytics and grading records

LLM Grader is also designed to support analytics and operational visibility. Over time, this can help instructors understand:

- where students are struggling
- which rubric items are frequently triggered
- how grading patterns differ across questions or cohorts
- where question wording or grading guidance may need improvement

The analytics layer is still evolving, but it is part of the overall design goal: grading should not just assign a score, it should generate insight for course improvement.

## Why This Is Useful for Instructors

For faculty, the main value is not that LLM Grader "automates everything." The value is that it reduces the manual friction around assessment while keeping the instructor's grading intent visible and editable.

LLM Grader is particularly well suited for:

- engineering and technical courses with open-ended reasoning
- math-heavy courses where method matters, not just the answer
- design or modeling questions with partial-credit grading
- project workflows where students improve their work iteratively

For an instructor at NYU, this means you can pilot AI-assisted grading and AI-assisted authoring in a way that is inspectable, local to your course materials, and grounded in explicit grading artifacts.

## What Makes It Different

Several design choices distinguish LLM Grader from a generic chatbot-based grading workflow.

- **Structured authoring**: questions and rubrics are stored in a reusable format instead of living only in prompts.
- **Validation tools**: authoring files can be checked before they are deployed.
- **Agent-assisted course building**: the system can help draft and revise course artifacts, not just grade final submissions.
- **Transparent workflow**: grading and authoring behavior can be inspected, tested, and improved.
- **Lightweight architecture**: the stack is small enough for instructors and developers to understand without a large platform team.

## Current Status

LLM Grader is already useful as a pilot system for AI-native technical assessment, but it should still be viewed as an evolving platform rather than a finished enterprise product.

Today, the system already supports:

- structured course and unit authoring
- XML validation for course packaging inputs
- LLM-assisted drafting of course artifacts through MCP tools
- rubric-driven question design, including multipart and partial-credit questions
- a lightweight web application and supporting grading infrastructure

The project is strongest when used by instructors who want a practical, inspectable, and extensible workflow for modern technical assessment.

## Bottom Line

LLM Grader helps instructors move from ad hoc prompting to a more reliable assessment pipeline. It gives faculty a way to author questions, define grading intent, use LLMs where they are most valuable, and keep the process reviewable.

For colleagues exploring AI in teaching at NYU, the pitch is not that this replaces instructor judgment. The pitch is that it makes high-quality grading and course authoring more scalable, more transparent, and easier to iterate.