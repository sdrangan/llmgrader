---
title: Setting up Google OAuth
parent: Setting Up LLM Grader
nav_order: 2
has_children: false
---

# Setting up Google OAuth

LLM Grader uses Google OAuth 2.0 for sign-in. Public/student functionality can
be used anonymously, but administrator actions are protected by login and server-side email authorization.  See the [privacy notes](../../overview/dataprivacy.md) for discussion of what material is stored with the login.

In practice, this means:

- instructors and optionally users sign in with a Google account
- the app stores the signed-in user in the Flask session
- admin access is granted by email address on the server
- the first admin can be bootstrapped from `LLMGRADER_INITIAL_ADMIN_EMAIL`

If you are launching the app locally for development, you still need to provide
the OAuth client settings unless you deliberately use the development bypass in
[Google sign-in and admin access](password.md).

## What You Need Before You Start

You need:

- a Google account
- a Google Cloud project
- an OAuth 2.0 Web application client in that project
- the client ID and client secret for that OAuth client

You do not need to create a special Google account just for LLM Grader. A
normal Google account is enough to create the Google Cloud project and OAuth
credentials.

## Create the Google OAuth Credentials

1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project, or select an existing one.
3. Open **APIs & Services → OAuth consent screen** and configure the consent
	 screen if Google asks you to do so.  You may be asked for an App name.  You can put any name you like, *LLM Grader*.
4. Open **APIs & Services → Credentials**.
5. Click **Create Credentials → OAuth client ID**.
6. Choose **Web application**.
7. Add one or more **Authorized redirect URIs**.

For local development, the most common redirect URI is:

```text
http://127.0.0.1:5000/auth/callback
```

If you prefer to browse locally at `localhost` instead of `127.0.0.1`, add this
too:

```text
http://localhost:5000/auth/callback
```

For a deployed site, add your production callback URI, for example:

```text
https://your-domain.example/auth/callback
```

8. Save the client.
9. Copy the **Client ID** and **Client secret**.

## Required Environment Variables

LLM Grader reads these variables at runtime:

| Variable | Example | Purpose |
|----------|---------|---------|
| `LLMGRADER_SECRET_KEY` | long random string | Flask session secret |
| `LLMGRADER_GOOGLE_CLIENT_ID` | Google OAuth client ID | Google sign-in configuration |
| `LLMGRADER_GOOGLE_CLIENT_SECRET` | Google OAuth client secret | Google sign-in configuration |
| `LLMGRADER_GOOGLE_REDIRECT_URI` | `http://127.0.0.1:5000/auth/callback` | OAuth callback URI |
| `LLMGRADER_INITIAL_ADMIN_EMAIL` | `you@example.com` | Bootstraps the first admin |

Notes:

- `LLMGRADER_SECRET_KEY` should be stable across restarts so login sessions do
	not break.  
- If `LLMGRADER_GOOGLE_REDIRECT_URI` is omitted, the app will try to compute it
	automatically from the current request. That can work, but setting it
	explicitly is more predictable, especially in development and behind proxies.
- The redirect URI must exactly match one of the redirect URIs configured in the
	Google Cloud Console.

## Local Development on Windows PowerShell

Generate a secure session key first:

```powershell
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
[Convert]::ToBase64String($bytes)
```

Copy the generated value and use it for `LLMGRADER_SECRET_KEY`.

For a single PowerShell session, set the variables like this:

```powershell
$env:LLMGRADER_SECRET_KEY = "replace-with-a-long-random-string"
$env:LLMGRADER_GOOGLE_CLIENT_ID = "your-google-client-id"
$env:LLMGRADER_GOOGLE_CLIENT_SECRET = "your-google-client-secret"
$env:LLMGRADER_GOOGLE_REDIRECT_URI = "http://127.0.0.1:5000/auth/callback"
$env:LLMGRADER_INITIAL_ADMIN_EMAIL = "you@example.com"
```

To verify that the current PowerShell session can read them back:

```powershell
$env:LLMGRADER_SECRET_KEY
$env:LLMGRADER_GOOGLE_CLIENT_ID
$env:LLMGRADER_GOOGLE_CLIENT_SECRET
$env:LLMGRADER_GOOGLE_REDIRECT_URI
$env:LLMGRADER_INITIAL_ADMIN_EMAIL
```

If you installed LLM Grader in a virtual environment, activate that environment
first and you can also confirm the variables with:

```powershell
llmgrader_env_vars
```

Then launch the app from the same PowerShell window:

```powershell
python run.py --soln_pkg <path-to-solution-package>
```

If you installed your dependencies into a virtual environment, activate that
environment first, then run the commands above.

Important:

- these `$env:` assignments affect only the current PowerShell session
- if you open a new terminal, you must set them again unless you persist them
- LLM Grader does not automatically load a `.env` file by itself

If you want to persist them across new PowerShell sessions, use `setx`:

```powershell
setx LLMGRADER_SECRET_KEY "replace-with-a-long-random-string"
setx LLMGRADER_GOOGLE_CLIENT_ID "your-google-client-id"
setx LLMGRADER_GOOGLE_CLIENT_SECRET "your-google-client-secret"
setx LLMGRADER_GOOGLE_REDIRECT_URI "http://127.0.0.1:5000/auth/callback"
setx LLMGRADER_INITIAL_ADMIN_EMAIL "you@example.com"
```

After running `setx`, close the terminal and open a new one before starting the app.  

## Local Development on macOS or Linux

Generate a secure session key first:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the generated value and use it for `LLMGRADER_SECRET_KEY`.

For a single shell session:

```bash
export LLMGRADER_SECRET_KEY="replace-with-a-long-random-string"
export LLMGRADER_GOOGLE_CLIENT_ID="your-google-client-id"
export LLMGRADER_GOOGLE_CLIENT_SECRET="your-google-client-secret"
export LLMGRADER_GOOGLE_REDIRECT_URI="http://127.0.0.1:5000/auth/callback"
export LLMGRADER_INITIAL_ADMIN_EMAIL="you@example.com"

python run.py --soln_pkg <path-to-solution-package>
```

To verify that the current shell can read them back:

```bash
echo "$LLMGRADER_SECRET_KEY"
echo "$LLMGRADER_GOOGLE_CLIENT_ID"
echo "$LLMGRADER_GOOGLE_CLIENT_SECRET"
echo "$LLMGRADER_GOOGLE_REDIRECT_URI"
echo "$LLMGRADER_INITIAL_ADMIN_EMAIL"
```

If you installed LLM Grader in a virtual environment, activate that environment
first and you can also confirm the variables with:

```bash
llmgrader_env_vars
```

## Local Development Workflow

Once the environment variables are set:

1. Start the app with `python run.py --soln_pkg <path-to-solution-package>`.
2. Open `http://127.0.0.1:5000/` in your browser.
3. Click **Sign in**.
4. Complete Google sign-in.
5. If the signed-in email matches `LLMGRADER_INITIAL_ADMIN_EMAIL`, the app will
	 insert that email into the admin table automatically on startup.

If you use `http://localhost:5000/` in the browser instead of `127.0.0.1`, make
sure your configured redirect URI and Google OAuth settings use `localhost`
consistently.

## Development Bypass

If you want to bypass admin checks temporarily during local development, you can
set:

```text
LLMGRADER_AUTH_MODE=dev-open
```

This is only for development convenience. Do not use it in production.

## Render Deployment

On Render, set the same variables in **Environment → Environment Variables**.
The most important difference is the redirect URI. In production it should be
your public callback URL, for example:

```text
https://your-render-service.onrender.com/auth/callback
```

That value must also be registered in the Google Cloud Console as an authorized
redirect URI.

For the broader Render deployment checklist, see [Deploying on render](deploy.md).

## Troubleshooting

- If the **Sign in** button does not work, verify the client ID, client secret,
	and redirect URI.
- If Google returns a redirect mismatch error, compare the browser URL, the
	configured environment variable, and the Google Cloud redirect URI character
	for character.
- If admin access is denied after sign-in, verify that your email matches
	`LLMGRADER_INITIAL_ADMIN_EMAIL` or has already been added to the admin list.
- If login sessions reset after restart, verify that `LLMGRADER_SECRET_KEY`
	remains stable.