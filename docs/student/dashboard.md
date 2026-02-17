---
title: Using the Dashboard and Submitting on Gradescope
parent: Student Guide
nav_order: 3
has_children: false
---

# Submitting Your Answers on Gradescope

## Dashboard

If you select the **File->Select View->Dashboard**, you will be directed to
a dashboard page with a table of the problems and the points you have received
on each problem.  You can track your progress here.

## Submitting your answers for Gradescope

If you are an NYU student taking the class,  the **required** column indicates
if the problem is to be submitted for grading.  You should know how to do
all the problems for the midterm and final.  But, we only grade a subset.

Once you are satisfied with your results on the required problem, click the
**Download submission** button on the top right.  This selection will create a zip file with:

- A JSON file of the results on all submitted problems
- A text version of the file that can be read by a human grader, if there
is a dispute or clarification needed.

Now simply upload that zip file to gradescope.

## What happens next?

An autograder on Gradescope will read your results and grade you.  The score should be
identical to the value on the dashboard.  The Gradescope grader **does not** regrade
the problems -- it has no access to the LLM.  It simply reads the results from the JSON file.
