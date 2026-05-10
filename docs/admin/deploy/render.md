---
title: Deploying on Render
parent: Deploying the App
nav_order: 2
has_children: false
---

# Deploying the LLM Grader on Render 

## Overview

LLM grader is generally hosted on a server.  We suggest [Render](https://render.com/) that can directly load from a GitHub repository and a persistent disk.  Render handles the build, environment, and hosting automatically, so deployment is simple and repeatable.

A Render deployment consists of:

- a **Web Service** running the Flask application  
- a **Persistent Disk** mounted at `/var/data`  
- environment variables for Google sign-in and admin authorization  
- automatic redeploys on Git pushes  

The grader stores uploaded solution packages on the persistent disk, so course content survives restarts and redeploys.  Before starting you will need to create a Render account by
linking your GitHub account to Render.

---

## 🧱 1. Create a Persistent Disk on Render

In the Render dashboard:

1. Go to **Disks**  
2. Click **New Disk**  
3. Name it something like `grader-data`  
4. Choose a size (1–2 GB is plenty)  
5. Set the mount path to:

```
/var/data
```

This directory will store:

- extracted solution packages  
- logs (if you choose to write any)  
- future assets such as images  

Render guarantees that `/var/data` persists across deploys.

---

## 🌐 2. Create the Web Service

1. Click **New → Web Service**  
2. When prompted for a repository, select your **fork** of `llmgrader`, not the original upstream repository  
3. Choose the branch in your fork that you want Render to deploy, typically `main`  
4. Use these settings:

**Environment:**  
```
Python 3.x
```

**Build Command:**  
```
pip install -r requirements.txt
```

**Start Command:**  
```
gunicorn run:app
```

Grading now runs as a background job with polling, so long grade operations no longer
depend on a single long-lived `/grade` request. The current implementation keeps
grading simple and safe by allowing only one active grading job per app instance
at a time.

**Instance Type:**  
- Start with **Starter** or **Basic**  
- Upgrade later if needed

**Persistent Disk:**  
- Attach the disk you created  
- Mount it at `/var/data`

Render will clone and deploy from the fork and branch you selected above. That
lets you maintain an independent version of the repo for your own portal.

---

## 🔐 3. Set Environment Variables

In the Render dashboard:

1. Open your web service.
2. Go to **Environment**.
3. Find the **Environment Variables** section.
4. Click **Add Environment Variable**.
5. Enter the variable name in the **Key** field and its value in the **Value** field.
6. Repeat for each variable below.
7. Click **Save Changes** when you are done.

Add these variables:

| Variable | Suggested value | Remarks 
|----------|---------|--------- |
| `LLMGRADER_SECRET_KEY` | Long random string | Stable Flask session secret |
| `LLMGRADER_GOOGLE_CLIENT_ID` | OAuth client ID | Google OAuth configuration |
| `LLMGRADER_GOOGLE_CLIENT_SECRET` | OAuth client secret | Google OAuth configuration |
| `LLMGRADER_GOOGLE_REDIRECT_URI` | `https://<host>/auth/callback` | OAuth callback URL |
| `LLMGRADER_INITIAL_ADMIN_EMAIL` | `you@example.com` | Bootstraps first admin |
| `PYTHON_VERSION` | `3.12.3` | Update with python version |
| `LLMGRADER_STORAGE_PATH` | /var/data/| Root for persistent storage |  
| `LLMGRADER_PRIVATE_KEY` | (generated value) | Optional — required only if using [submission signing](../gskeys.md) |

Example values for a Render deployment might look like this:

```text
LLMGRADER_SECRET_KEY = <a long random string that you generated>
LLMGRADER_GOOGLE_CLIENT_ID = 123456789012-abcdefg.apps.googleusercontent.com
LLMGRADER_GOOGLE_CLIENT_SECRET = GOCSPX-xxxxxxxxxxxxxxxx
LLMGRADER_GOOGLE_REDIRECT_URI = https://your-service-name.onrender.com/auth/callback
LLMGRADER_INITIAL_ADMIN_EMAIL = you@example.com
PYTHON_VERSION = 3.12.3
LLMGRADER_STORAGE_PATH = /var/data
LLMGRADER_PRIVATE_KEY = <base64-encoded private key from generate_signing_keys>
```

For more detail on where the Google OAuth values come from, how to choose
`LLMGRADER_SECRET_KEY`, and how to set the redirect URI, see [Setting up Google
OAuth](../setup/oauth.md).

Notes:

- `LLMGRADER_GOOGLE_REDIRECT_URI` must exactly match one of the authorized redirect URIs in Google Cloud.
- `LLMGRADER_STORAGE_PATH` should match the persistent disk mount path.
- `LLMGRADER_SECRET_KEY` is your app's Flask session secret, not a Google value.
- After saving environment-variable changes, Render will usually trigger a redeploy. If it does not, manually redeploy the service.

---

## 🔄 4. Deploy and Verify

Render will:

- clone the selected branch from your fork  
- install dependencies  
- start the app with Gunicorn  
- mount the persistent disk  

Once deployed, render assign your service a unique URL such as:

```
https://llmgrader-xxxx.onrender.com
```

Use the URL shown in your Render dashboard.
---

## 🛠️ 5. Redeploying

Render redeploys automatically when you push to the branch that your service is tracking in your fork.  
You can also trigger a manual deploy from the dashboard.

Uploads and course content remain intact because they live on the persistent disk.

---

## 🧹 6. Cleaning or Resetting the Disk (Optional)

If you ever need to reset the grader:

- SSH into the instance (Render Shell)  
- Remove the contents of `/var/data/soln_repo`  
- Or delete and recreate the disk from the dashboard  

This does **not** affect your code deployment.

Once you are deployed, you can [upload the course package](../buildcourse/upload.md)

---

Go to [Google sign-in and admin access](./password.md)
