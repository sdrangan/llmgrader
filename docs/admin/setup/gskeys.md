---
title: Submission Signing Keys
parent: Setting Up LLM Grader
nav_order: 5
has_children: false
---

# Submission Signing Keys

LLM Grader supports optional **digital signing** of student submission files. When enabled, the server signs each downloaded submission with a private key. The Gradescope autograder then verifies the signature using the corresponding public key before accepting the file. This prevents students from submitting hand-crafted or altered submission files.

Signing is opt-in and disabled by default. You only need to follow these steps if you intend to enable signing for one or more units.

---

## How It Works

When signing is enabled for a unit:

1. A student downloads their submission from the LLM Grader portal
2. The server signs the submission content (scores, feedback, question ID, and timestamp) using a **private key** stored on Render
3. The signature is embedded in the downloaded JSON file
4. When the student uploads that file to Gradescope, the autograder verifies the signature using a **public key** that was embedded in the autograder zip at build time
5. If the signature is missing or invalid, the autograder rejects the submission

---

## Generating Keys

Run the key generation script from your project directory with your virtual environment active:

```bash
generate_signing_keys
```

This script generates an Ed25519 key pair and prints both keys in a format ready to copy into your environment variables:

```
LLMGRADER_PRIVATE_KEY=<base64-encoded private key>
LLMGRADER_PUBLIC_KEY=<base64-encoded public key>
```

> **Keep the private key secret.** Do not commit it to version control or share it.
> The public key is not sensitive — it is embedded in the autograder zip file that students upload to Gradescope.

---

## Setting Environment Variables

### On your local machine

You need both keys set locally so that `build_autograder` can embed the public key when building the autograder zip.

**Windows — current session only (PowerShell):**

```powershell
$env:LLMGRADER_PRIVATE_KEY = "<paste private key here>"
$env:LLMGRADER_PUBLIC_KEY  = "<paste public key here>"
```

**Windows — persist across sessions (Command Prompt or PowerShell):**

```
setx LLMGRADER_PRIVATE_KEY "<paste private key here>"
setx LLMGRADER_PUBLIC_KEY  "<paste public key here>"
```

`setx` writes to the user-level registry. Open a new terminal after running it for the values to take effect.

**macOS / Linux:**

Add the following to your shell profile (`~/.zshrc`, `~/.bashrc`, etc.):

```bash
export LLMGRADER_PRIVATE_KEY="<paste private key here>"
export LLMGRADER_PUBLIC_KEY="<paste public key here>"
```

### On Render

Only the **private key** needs to be set on Render — the public key travels with the autograder zip. Add it following the general [Render environment variable instructions](./deploy/render.md).

---

## Verifying Your Setup

After setting the environment variables, run:

```bash
llmgrader_env_vars
```

This displays the status of all LLM Grader environment variables, including `LLMGRADER_PRIVATE_KEY` and `LLMGRADER_PUBLIC_KEY`. Both should show as set (the private key value will be masked). If either shows `MISSING`, re-check the steps above.

---

## Enabling Signing for a Unit

Once keys are set, enable signing in the unit XML file with:

```xml
<digitalsign>true</digitalsign>
```

See the [Unit XML format](./buildcourse/unitxml.md) for the full field description and where to place it.

When you then run `build_autograder`, the public key is automatically embedded in the autograder zip. If `LLMGRADER_PUBLIC_KEY` is not set and signing is enabled, `build_autograder` will print an error and exit before building.

---

## Key Rotation

If you need to generate new keys (for example, if the private key is compromised):

1. Run `generate_signing_keys` again to generate a new pair
2. Update `LLMGRADER_PRIVATE_KEY` and `LLMGRADER_PUBLIC_KEY` on your local machine
3. Update `LLMGRADER_PRIVATE_KEY` on Render and redeploy
4. Rebuild and re-upload the autograder zip for any affected units — the old autograder zip contains the old public key and will reject submissions signed with the new private key
