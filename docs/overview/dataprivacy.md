---
title: Data Privacy
parent: Overview
nav_order: 3
has_children: false
---

# Data Privacy

This page describes what data LLM Grader stores, what it sends to third-party AI providers, and what would be exposed in a security breach. It is written to help university administrators evaluate regulatory compliance, faculty assess risk, and students understand their privacy.

---

## What Is and Is Not Stored

### Grading records (all users)

Every grading submission is logged to a server-side SQLite database. The following is stored for each submission:

| Stored | Example |
|---|---|
| Session UUID (`client_id`) | `a3f7b2c1` |
| Unit name and question tag | `unit2`, `q3` |
| Student answer text | The student's typed or uploaded response |
| Reference solution and rubric | Instructor-authored content from the course package |
| Grading result and feedback | `pass`, `partial`, or `fail` with explanation |
| Model, latency, token counts | `gpt-4.1-mini`, 1420 ms, 312 tokens |

**Not stored in grading records:** student name, email address, university ID, or any other personally identifying information. Each record is linked only to an 8-character random session UUID that is generated fresh per browser session and discarded when the session ends.

> **Important:** Student answer text is stored on the server and is associated with an anonymous session UUID. The text itself may contain identifying information if the student includes it (e.g., writing their own name in an answer). This is the student's responsibility to avoid.

---

### Login and account data (authenticated users only)

Authentication is **optional** and intended primarily for administrative access. If a student or instructor logs in via Google OAuth, the following profile data is stored in a separate `users` table:

| Stored | Purpose |
|---|---|
| Email address | Authentication and admin role checks |
| Display name | Display in the admin interface |
| Google profile picture URL | Display in the admin interface |
| Login timestamps | Account management |

**This profile information is stored in a separate table and is never linked to grading records.** The grading database uses only the anonymous session UUID, regardless of whether the user is logged in. A logged-in user's email cannot be joined to their grading history within the database schema.

---

### What is not stored

- Student API keys. Keys entered by students are sent with each request from the browser but are never written to disk on the server.
- Student progress or prior submission history between sessions. Each session starts fresh.
- Any data from students who only view questions without submitting.

---

## Third-Party Data Processing (OpenAI)

When a student submits an answer, the following content is sent to the AI provider (e.g., OpenAI) to perform grading:

- The question text
- The reference solution and grading rubric
- The student's answer text (and any attached images)

**This data leaves the LLM Grader server and is processed by a third-party AI provider.** OpenAI's data handling is governed by OpenAI's API data usage policies, not by LLM Grader. By default, OpenAI does not train on API inputs, but institutions with strict data governance requirements should verify this against their own policies and confirm that an appropriate Data Processing Agreement (DPA) is in place.

> **For university administrators:** Sending student answer text to a third-party API may constitute sharing of education records under FERPA if the answers can be linked to an identified student. Because LLM Grader does not attach student identity to the data it sends to OpenAI, this risk is mitigated — but not eliminated, since answer content itself could be identifying. Consult your institution's privacy office before deploying in a graded course context.

---

## Security Breach Scenario

The following describes what an attacker would obtain if the LLM Grader server were fully compromised.

### What would be exposed

**Grading database (submissions table):**
- Student answer texts, linked to anonymous 8-character UUIDs only
- Question content, reference solutions, and rubrics from the course package
- Grading outcomes (pass/fail/partial) with no student names attached

**User table (authenticated users only):**
- Email addresses, display names, and Google picture URLs of users who have logged in
- Login timestamps

**Admin configuration:**
- The admin's OpenAI API key (stored in a configuration file)
- Admin email address

### What would not be exposed

- No mapping from grading records to student identities (no join is possible between the users table and the submissions table)
- No student university IDs or enrollment data
- No student API keys
- No grades that are directly attributed to a named individual within this system

### Comparison with a Canvas-style breach

A breach of a learning management system typically exposes enrolled student names, IDs, email addresses, and course grades — all fully linked. A breach of LLM Grader in its default configuration exposes answer text tied to anonymous UUIDs, plus a separate list of emails for users who opted into login. **These two datasets cannot be linked within the LLM Grader database.** An attacker who obtains both datasets would need to use external information (such as matching answer content to a known student) to reconstruct identities.

---

## Summary by User Type

| | Anonymous (Guest) | Logged-In |
|---|---|---|
| Email stored on server | No | Yes (users table only) |
| Email linked to grading records | No | No |
| Answer text stored on server | Yes (anonymous UUID only) | Yes (anonymous UUID only) |
| Answer text sent to AI provider | Yes | Yes |
| Session persists across browser sessions | No | No |
| API key stored on server | No | No |

---

## Guidance for Institutions

**For administrators evaluating regulatory compliance:**
- LLM Grader does not create a database record that links a student's identity to their graded work. This significantly reduces FERPA exposure compared to systems that log grades against student IDs.
- The primary compliance consideration is the transmission of student answer text to a third-party AI provider (OpenAI or similar). Confirm that your institution's DPA with that provider covers this use.
- If institutional policy prohibits sending any student-produced content to external APIs, LLM Grader is not suitable for use with student data in its current form.

**For faculty:**
- A server breach would not yield a grade sheet. An attacker would see answer texts with no names attached. This is meaningfully different from a breach of a traditional grade database.
- The course package (questions, solutions, rubrics) is stored on the server and would be exposed in a breach. Treat it accordingly.
- Students using Guest Mode provide stronger privacy guarantees than students who log in, because no email is stored at all in Guest Mode.

**For students:**
- In Guest Mode, LLM Grader stores your answers but not your name or email. Your answers are linked to a random ID that disappears when you close your browser.
- Logging in stores your email and name for authentication, but does not link them to your answers or grades.
- Your answer text is sent to an external AI service (e.g., OpenAI) for grading. Do not include sensitive personal information in your answers.
- For maximum privacy, use Guest Mode and avoid including your name or ID in your answers.
