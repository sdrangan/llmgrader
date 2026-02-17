---
title: How to Answer and Grade Questions
parent: Student Guide
nav_order: 1
---

# How to Answer and Grade Questions

Before using the LLM grader, you will need to [register an OpenAI API key](./openai.md).  Loading the OpenAI API key takes just a moment and lets you control your own usage and costs — nothing is stored on the server, and you can turn it off anytime.

Once you have set the OpenAI API key, you can
to the **Grade View** where you’ll spend most of your time.  To go to Grade view, select **File->Switch View->Grade**.  In this view, you can read the question, write your answer, and get instant feedback from the LLM grader.
No mystery, no hidden steps — just a clean loop of *try → grade → improve*.

- Select a unit from the **Unit Dropdown**.  
- Select a question from the **Questions Dropdown**
- In the **Question box** (left panel), you will see the problem and any diagrams or code snippets
- Below the question box, is a box **Your solution**.  You can type your answer there. You can write in plain English, math, or short code fragments — whatever the question calls for. The grader is flexible, but clearer answers usually get clearer feedback.
You can revise your answer as many times as you like before submitting to Gradescope. So do not be too worried about making mistakes.  The grader will give you feedback to help.
- In the top panel, you press the **Grade** button.  Within a moment (typically 5 to 10 seconds), you’ll see:

    - **Summary** — a quick, student‑friendly explanation of how your answer compares  
    - **Full Explanation** — a more detailed breakdown of the reasoning  
   This feedback is meant to help you understand *why* something is correct or incorrect, not just whether you got it right.
-  the feedback points out something you missed, you can edit your answer and grade again. Many students use this loop to check their understanding before submitting the final version to Gradescope.


## Saving and Loading Your Work

Your latest answer and grading results stay on the page, so you can generally switch views or come back later without losing anything.
But, if you want to save your results to a file, you can select the **Grade->Save Results...** menu option that will create a JSON file with:

- Your solution
- The feedback from OpenAI
- The full explanation
- The grade result

This file be downloaded to a JSON file to your Download folder.  You can store it anywhere.  You can then
select **Grade->Load Results...** to restore the results.  



---

If you’re ready to see how you’re doing across the whole assignment, head over to the [Dashboard](./dashboard.md). When you’re satisfied with your answers, follow the instructions for [submitting to Gradescope](./gradescope.md).
