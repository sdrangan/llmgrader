---
title: How to Answer and Grade Questions
parent: Student Guide
nav_order: 1
---

# How to Answer and Grade Questions

Before using the LLM grader, you will need to [register an OpenAI API key](./openai.md).  Loading the OpenAI API key takes just a moment and lets you control your own usage and costs — nothing is stored on the server, and you can turn it off anytime.

Once you have set the OpenAI API key, go to the **Grade View** where you'll spend most of your time.  To open it, select **File → Switch View → Grade**.  In this view, you can read the question, write your answer, and get instant feedback from the LLM grader.
No mystery, no hidden steps — just a clean loop of *try → grade → improve*.

- Select a unit from the **Unit** dropdown.
- Select a question from the **Questions** dropdown.
- In the **Question** panel (left side on desktop, or the **Question** tab on mobile), you will see the problem and any diagrams or code snippets.
- Below the question, the **Your Solution** panel contains a composer where you enter your answer.  You can write in plain English, math, or short code fragments — whatever the question calls for.  The grader is flexible, but clearer answers usually get clearer feedback.

## The Solution Composer

The solution entry area is a chat-style composer with three parts:

- **＋ (attach) button** — attach one or more image files (photos, sketches, screenshots) to your answer.
- **Text area** — type your answer here.  The area expands as you type.
- **Grade button** — submit your answer for grading.

You can also press **Ctrl+Enter** (or **⌘+Enter** on Mac) to grade without reaching for the mouse.

### Attaching Images

If your answer includes hand-written work, circuit diagrams, or plots, attach them as images:

1. Click or tap the **＋** button inside the composer.
2. Select one or more image files from your device.
3. Thumbnails appear above the text area confirming the images are attached.
4. To remove an image before grading, click the **×** on its thumbnail.

Attached images are sent to the LLM along with your text, so the grader can see both.  Up to three images may be attached per question.

### Grading

Once you have typed your answer (and optionally attached images), click the **Grade** button in the composer.  Within a few seconds (typically 5-10 seconds) you will see:

- **Summary** — a quick, student-friendly explanation of how your answer compares.
- **Full Explanation** — a more detailed breakdown of the reasoning.

This feedback is meant to help you understand *why* something is correct or incorrect, not just whether you got it right.

You can revise your answer as many times as you like.  If the feedback points out something you missed, edit your answer and grade again.  Many students use this loop to check their understanding before submitting the final version.


## Saving and Loading Your Work

Your latest answer and grading results stay on the page, so you can generally switch views or come back later without losing anything.
If you want to save your results to a file, select the **Grade → Save Results…** menu option.  This creates a JSON file with:

- Your solution text
- Any attached images
- The feedback from OpenAI
- The full explanation
- The grade result

The file is downloaded to your Downloads folder.  You can store it anywhere and reload it later with **Grade → Load Results…**.


---

If you're ready to see how you're doing across the whole assignment, head over to the [Dashboard](./dashboard.md). When you're satisfied with your answers, follow the instructions there for submitting to Gradescope.
