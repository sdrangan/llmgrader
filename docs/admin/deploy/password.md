---
title: Creating and deploying
parent: Deploying on Render
nav_order: 2
has_children: false
---

# Google Sign-in and Admin Access

LLM Grader uses Google OAuth for sign-in and server-side email authorization for admin access.

---

## Overview

- Public/student functionality remains available without login.
- Any Google account may sign in.
- Admin routes are authorized by email lookup on the server.
- Initial admin is bootstrapped from `LLMGRADER_INITIAL_ADMIN_EMAIL`.
- Development bypass is available only with explicit `LLMGRADER_AUTH_MODE=dev-open`.

---

## Required environment variables

#### On Render (production)

1. Go to **Environment → Environment Variables**
2. Add these variables:

```
LLMGRADER_SECRET_KEY=your-stable-secret
LLMGRADER_GOOGLE_CLIENT_ID=...
LLMGRADER_GOOGLE_CLIENT_SECRET=...
LLMGRADER_GOOGLE_REDIRECT_URI=https://<your-domain>/auth/callback
LLMGRADER_INITIAL_ADMIN_EMAIL=you@example.com
```

3. Redeploy the service.

#### On your local machine (development)

**macOS / Linux**
```
export LLMGRADER_SECRET_KEY=dev-secret
export LLMGRADER_GOOGLE_CLIENT_ID=...
export LLMGRADER_GOOGLE_CLIENT_SECRET=...
export LLMGRADER_GOOGLE_REDIRECT_URI=http://127.0.0.1:5000/auth/callback
export LLMGRADER_INITIAL_ADMIN_EMAIL=you@example.com
```

---

## Development open mode (explicit only)

For local development convenience, you can bypass admin checks:

```
LLMGRADER_AUTH_MODE=dev-open
```

This is **opt-in** and should not be used in production.

---

## Recommended Usage

- **Local development:** use normal auth, or set `LLMGRADER_AUTH_MODE=dev-open` temporarily.
- **Production:** set all OAuth/admin env vars and keep `LLMGRADER_AUTH_MODE` unset (normal mode).
- **Admin management:** use the Admin UI to add/remove additional admin emails.

---

## Troubleshooting

- If sign-in is unavailable, verify Google client ID/secret/redirect URI env vars.
- If admin pages are denied after sign-in, verify your email is in the admin list or matches `LLMGRADER_INITIAL_ADMIN_EMAIL`.
- If sessions reset unexpectedly, verify `LLMGRADER_SECRET_KEY` is stable across deployments.
