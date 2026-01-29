---
title: Database viewer
parent: Analytics
nav_order: 1
has_children: false
---

# Database Viewer (DB Viewer)

## Overview

Each time a user submits a grade request,
the usage is logged in an SQLite database.
All data is stored in an anonymized manner -- there
are no fields with user identifying information.
Right now, we have a simple **database viewer** available at:

```
/admin/dbviewer
```

It is accessible only to authenticated admins.

The page provides:

- a **default query** showing the 20 most recent submissions
- a **SQL query box** for custom inspection
- a **CSV download** link for exporting results
- a **View** button for each row, opening a detailed submission page in a new tab

This tool is the foundation of the system’s analytics and observability layer.

---

## Default Table Columns

The default view shows the following fields:

| Column         | Meaning |
|----------------|---------|
| **timestamp**  | When the submission was graded (UTC). |
| **unit_name**  | The unit or module the question belongs to. |
| **qtag**       | The question identifier. |
| **result**     | `"correct"`, `"incorrect"`, or `"error"`. |
| **model**      | The model used for grading. |
| **latency_ms** | Total wall‑clock time from start of grading to completion. |
| **timed_out**  | `1` if the request exceeded the timeout window. |

The table is intentionally compact so you can quickly scan for:

- slow submissions
- repeated failures
- model‑specific issues
- unit‑specific patterns

---

## Viewing Full Submission Details

Each row includes a **View** button:

```
View
```

Clicking this opens:

```
/admin/submission/<id>
```

in a new tab.

The detail page shows:

- the full question text (HTML rendered)
- the reference solution
- grading notes
- the student’s submitted solution
- the raw prompt sent to the model
- the full explanation returned by the model
- feedback text
- all metadata fields (model, timeout, latency, etc.)

Text fields are displayed using:

```
<pre style="white-space: pre-wrap;">
```

so indentation and line breaks are preserved while still wrapping naturally in the browser.

---

## Running Custom SQL Queries

The DB Viewer includes a SQL query box that allows you to run read‑only queries against the `submissions` table.

Examples:

### Show all timeouts
```sql
SELECT timestamp, unit_name, qtag, model, timeout, latency_ms
FROM submissions
WHERE timed_out = 1
ORDER BY id DESC;
```

### Slowest submissions
```sql
SELECT timestamp, unit_name, qtag, model, latency_ms
FROM submissions
ORDER BY latency_ms DESC
LIMIT 20;
```

### Errors by model
```sql
SELECT model, COUNT(*) AS errors
FROM submissions
WHERE result = 'error'
GROUP BY model;
```

### Activity for a specific unit
```sql
SELECT *
FROM submissions
WHERE unit_name = 'Unit 3'
ORDER BY id DESC;
```

The first 20 rows of any query are shown in the table.  
You can download the full result set as CSV using the **Download CSV** link.

---

## CSV Export

After running a query, the **Download CSV** link re‑executes the SQL stored in your session and returns:

- column headers
- all rows (not just the first 20)

This is useful for:

- grading audits
- latency analysis
- error pattern detection
- research on model behavior

---

## Latency Measurement

The `latency_ms` field measures **total wall‑clock time** from the moment grading begins until the grade (or error) is produced.

This includes:

- prompt construction
- thread scheduling
- model latency
- timeout waiting
- exception handling

This value reflects the **actual delay experienced by the student**, making it the most meaningful performance metric.

---

## Timeouts and Error Handling

The DB Viewer logs **every** grading attempt, including:

- missing API keys
- client creation failures
- SDK timeouts
- thread timeouts
- unexpected exceptions

This ensures you always have a complete picture of system behavior, even when grading fails.

Timeouts are marked with:

```
timed_out = 1
```

and typically show large `latency_ms` values corresponding to the timeout window.

---

## Future Extensions

The DB Viewer is the foundation for a broader analytics layer. Future enhancements may include:

- latency histograms
- per‑unit and per‑qtag performance dashboards
- model comparison charts
- recent failures panel
- diff view between student and reference solutions
- error clustering and diagnostics

Placing this documentation under `docs/analytics/` allows the section to grow naturally as new tools are added.