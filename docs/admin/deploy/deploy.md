---
title: Creating and deploying
parent: Deploying on Render
nav_order: 1
has_children: false
---

# Deploying the LLM Grader on Render 

## 🚀 Overview


LLM grader is generally hosted on a server.  We suggest [Render](https://render.com/) 
that can directly load from a GitHub repository and a persistent disk.
Render handles the build, environment, and hosting automatically, so deployment is simple and repeatable.


A Render deployment consists of:

- a **Web Service** running the Flask application  
- a **Persistent Disk** mounted at `/var/data`  
- environment variables for Google sign-in and admin authorization  
- automatic redeploys on Git pushes  

The grader stores uploaded solution packages on the persistent disk, so course content survives restarts and redeploys.  Before starting you will need to create a Render account, by
linking your GitHub to the Render.

---

## 📁 1. Prepare Your Repository

Your GitHub repository should contain:

```
llmgrader/
    app.py
    requirements.txt
    llmgrader/
        routes/
        services/
        templates/
        static/
        ...
```

Make sure:

- `requirements.txt` includes all dependencies  
- `gunicorn` is listed (Render uses it to run the app)  
- the app exposes `app` at the top level (e.g., in `app.py`)  

Example `app.py` entry point:

```python
from llmgrader import create_app
app = create_app()
```

---

## 🧱 2. Create a Persistent Disk on Render

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

## 🌐 3. Create the Web Service

1. Click **New → Web Service**  
2. Connect your GitHub repo  
3. Use these settings:

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
gunicorn app:app
```

**Instance Type:**  
- Start with **Starter** or **Basic**  
- Upgrade later if needed

**Persistent Disk:**  
- Attach the disk you created  
- Mount it at `/var/data`

---

## 🔐 4. Set Environment Variables

In the Render service settings, add:

| Variable | Suggested value | Remarks 
|----------|---------|--------- |
| `LLMGRADER_SECRET_KEY` | Long random string | Stable Flask session secret |
| `LLMGRADER_GOOGLE_CLIENT_ID` | OAuth client ID | Google OAuth configuration |
| `LLMGRADER_GOOGLE_CLIENT_SECRET` | OAuth client secret | Google OAuth configuration |
| `LLMGRADER_GOOGLE_REDIRECT_URI` | `https://<host>/auth/callback` | OAuth callback URL |
| `LLMGRADER_INITIAL_ADMIN_EMAIL` | `you@example.com` | Bootstraps first admin |
| `PYTHON_VERSION` | `3.12.3` | Update with python version |
| `LLMGRADER_STORAGE_PATH` | /var/data/| Root for persistent storage |  

---

## 🔄 5. Deploy and Verify

Render will:

- clone your repo  
- install dependencies  
- start the app with Gunicorn  
- mount the persistent disk  

Once deployed, render assign your service a unique URL such as:

```
https://llmgrader-xxxx.onrender.com
```

Use the URL shown in your Render dashboard.
---

## 🛠️ 6. Redeploying

Render redeploys automatically when you push to the main branch.  
You can also trigger a manual deploy from the dashboard.

Uploads and course content remain intact because they live on the persistent disk.

---

## 🧹 7. Cleaning or Resetting the Disk (Optional)

If you ever need to reset the grader:

- SSH into the instance (Render Shell)  
- Remove the contents of `/var/data/soln_repo`  
- Or delete and recreate the disk from the dashboard  

This does **not** affect your code deployment.

Once you are deployed, you can [upload the course package](../buildcourse/upload.md)

---

Go to [Google sign-in and admin access](./password.md)

