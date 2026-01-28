---
title:  Setting the Password
parent: Administrator Guide
nav_order: 1
has_children: false
---

# Admin Password Protection

LLM Grader includes optional password protection for all instructor‑only pages. 
This page explains how to enable it, how it works, and how to use it during development and deployment.

---

## Overview

The grader supports a single global admin password, controlled entirely through an environment variable.  
If the password is set, all routes under `/admin` require authentication using standard HTTP Basic Authentication.  
If the password is **not** set, the grader runs in open mode, which is convenient for local development.

This design keeps the system lightweight, stateless, and easy to deploy.

---

## Setting the Password

### 1. Choose a password  
Pick any string you want to use as the admin password.

### 2. Set the environment variable

#### On Render (production)

1. Go to **Environment → Environment Variables**
2. Add a new variable:

```
Key: LLMGRADER_ADMIN_PASSWORD
Value: your-secret-password
```

3. Redeploy the service.

#### On your local machine (development)

**macOS / Linux:**
```
export LLMGRADER_ADMIN_PASSWORD=your-secret-password
```

**Windows PowerShell:**
```
setx LLMGRADER_ADMIN_PASSWORD "your-secret-password"
```

Restart the terminal so the variable is available to Flask.

---

## How Basic Auth Works

- If `LLMGRADER_ADMIN_PASSWORD` is **not set**, all admin pages are accessible without authentication.
- If `LLMGRADER_ADMIN_PASSWORD` **is set**, any route under `/admin` requires authentication.
- When you visit an admin page, your browser will display a standard login dialog asking for a username and password.
- **The username is ignored** — you can enter anything (e.g., "admin", "user", or leave it blank if your browser allows).
- **Only the password matters** — it must match the value of `LLMGRADER_ADMIN_PASSWORD`.

If the password is incorrect or you cancel the dialog, the server returns a `401 Unauthorized` response.

Your browser will remember the credentials during your session, so you won't need to re-enter them on every page.

---

## Recommended Usage

- **Local development:** leave `LLMGRADER_ADMIN_PASSWORD` unset for convenience.
- **Production:** always set `LLMGRADER_ADMIN_PASSWORD` to protect student submissions and logs.
- **Sharing with TAs:** give them the password or create a separate Render environment for testing.

---

## Troubleshooting

- If admin pages are not protected, verify that `LLMGRADER_ADMIN_PASSWORD` is set in the environment.
- If you get repeated `401` errors, confirm that:
  - the password matches exactly (it's case-sensitive)
  - you're entering the password in the browser's login dialog
  - you haven't cached incorrect credentials (try clearing browser data or using an incognito window)
- After changing the password on Render, redeploy the service.