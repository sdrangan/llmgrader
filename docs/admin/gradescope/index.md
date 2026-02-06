---
title: Gradescope Integration
parent: Administrator Guide
nav_order: 3
has_children: true
---

# Gradescope Integration

The LLM grader application also provides a simple method to build autograders for Gradesccope.
The general flow is:

- Students answer questions on LLM grader portal for a particular unit
- Students are allowed an infinite number of tries until they get all questions correct
- Students then go to the Dashboard and then select **Download Submission**.  This
selection will create a JSON file submission.
- Students go to Gradescope and upload the submission.
- The autograder app will verify that the questions are correct.

Importantly, the autograder app on Gradescope simply reads the results from the LLM grader.
It makes no calls to OpenAI or perform any processing.

The following instructions describe how to [build and upload the autograder](./gradescope.md)
