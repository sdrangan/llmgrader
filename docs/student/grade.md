---
title: How to Answer and Grade Questions
parent: Student Guide
nav_order: 1
---

# How to Answer and Grade Questions

## Pre-requisites

Before using the LLM grader, you will need to [register an OpenAI API key](./openai.md).  Loading the OpenAI API key takes just a moment and lets you control your own usage and costs — nothing is stored on the server, and you can turn it off anytime.

Your instructor should provide you with the URL where they have deployed the class. Typically, this website is on `render.com`. For example, the Introduction to Hardware Design class at NYU uses this [render web portal](https://llmgrader-e6o7.onrender.com/).


## Selecting a Course

One portal can serve more than one course.  The course you are working in is
part of the web address, after `/c/`:

```
https://your-class.onrender.com/c/hwdesign/
```

If your instructor runs only one course on their portal, there is nothing to
do here — opening the portal's address sends you straight to it, and you can
skip to the next section.

To move between courses, select **File → Select Course…**.  The course you are
currently in is ticked and cannot be re-selected; choosing another one reloads
the page into it.  If the menu lists only one course, you are already in it.

Two things worth knowing:

- **Your saved work is kept separately for each course.** Answers, grades and
  feedback in one course are not visible from another, and switching between
  them never mixes them up.  Saved work lives in your own browser — see
  [Saving and Loading Your Work](#saving-and-loading-your-work).
- **A bookmark to a question includes the course.**  Sharing that link with a
  classmate sends them to the same course you were in.

If you bookmarked the portal before your instructor added a second course, your
old bookmark still works: it takes you to the portal, which forwards you to the
course you were last using.


## Grade View
Once you have set the OpenAI API key and a course URL, go to the **Grade View** where you'll spend most of your time.  To open it, select **File → Switch View → Grade**.  In this view, you can read the question, write your answer, and get instant feedback from the LLM grader.
No mystery, no hidden steps — just a clean loop of *try → grade → improve*.

- Select a unit from the **Unit** dropdown.
- Select a question from the **Question** dropdown.  Questions whose name begins with an asterisk (`*`) are **required**; on desktop, the `* = required` legend beside the dropdown is there to remind you.

  Required means that, if you are an NYU student in the class, you will have to submit a solution for that problem — see the [dashboard](./dashboard.md) for submitting solutions on Gradescope.  Every student, though — in the NYU class or just trying out the portal — is free and encouraged to try any problem for practice.  On desktop, once you open a question, the badge above the **Feedback** panel also shows whether it is `required` or `optional`.
- In the **Question** panel (left side on desktop, or the **Question** tab on mobile), you will see the problem and any diagrams or code snippets.
- Below the question, the **Your Solution** panel contains a composer where you enter your answer.  You can write in plain English, math, or short code fragments — whatever the question calls for.  The grader is flexible, but clearer answers usually get clearer feedback.

## The Solution Composer

The solution entry area is a chat-style composer with three parts:

- **＋ (attach) button** — attach one or more image files (photos, sketches, screenshots) to your answer.
- **Text area** — type your answer here.  The area expands as you type, and if your cursor is in the box you can paste an image directly from the clipboard.
- **Grade button** — submit your answer for grading.

You can also press **Ctrl+Enter** (or **⌘+Enter** on Mac) to grade without reaching for the mouse.

### Attaching Images

If your answer includes hand-written work, circuit diagrams, or plots, attach them as images:

1. Click or tap the **＋** button inside the composer.
2. Select one or more image files from your device.
3. Thumbnails appear above the text area confirming the images are attached.
4. To remove an image before grading, click the **×** on its thumbnail.

You can also paste an image from the clipboard while the text area is focused.  This is useful for screenshots or copied whiteboard work.

Attached images are sent to the LLM along with your text, so the grader can see both.  Up to five images may be attached per question.

### Grading

Once you have typed your answer (and optionally attached images), click the **Grade** button in the composer.  Within a few seconds (typically 5-10 seconds) you will see a response in the **Feedback** panel (on the right in desktop view and on a tab in mobile view).  


This feedback is meant to help you understand *why* something is correct or incorrect, not just whether you got it right.  You will also see a score for the problem.

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
