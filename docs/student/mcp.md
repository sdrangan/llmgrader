---
title: Studying with Your Own AI
parent: Student Guide
nav_order: 5
has_children: false
---
# Studying with Your Own AI (Course MCP)

If you already use an AI assistant such as Claude, ChatGPT or GitHub Copilot,
you can connect it to the course portal. Once connected, your assistant can look
up the course material for itself, so you can ask it things like:

- *List the problems in unit 2.*
- *Help me with the problem on the bouncing ball.*
- *Give me a similar problem to practice on.*
- *Where is this described in the class slides?*
- *Show me how the class demo declares AXI4-Lite registers.*

and it answers from this course's actual questions and slides, not from whatever
it remembers about the topic in general.

---

## What is an MCP?

The **Model Context Protocol (MCP)** is an open standard that lets an AI
assistant use tools provided by another service. The portal publishes a small
set of tools -- "list the units", "get this question" and so on -- and your
assistant decides when to call them while it talks to you.

A few things follow from that:

- **You use the assistant you already have**, on your own account. The portal
  does not run a chat of its own and does not see your conversation.
- **The portal only answers lookups.** It hands your assistant course material;
  your assistant does the explaining.
- **Nothing you do through the MCP is graded.** Graded work is still answered
  and submitted through the portal, as described in
  [How to Answer and Grade Questions](./grade.md).

---

## What your assistant can see

Once connected, your assistant can:

- **list the units and their problems**, and open any problem with its figures;
- **read the rubric** the portal grades a problem against, including the common
  mistakes it looks for;
- **read the worked solution**, to check your reasoning or give you a hint;
- **find where a topic is taught in the lecture slides**, and look at a slide
  -- its image, its text and the instructor's speaker notes;
- **read the class demos** -- their code and the docs pages that walk through
  them -- search them for a pragma or a signal name, and give you a link to the
  exact lines, when your instructor publishes them;
- **read past exams** your instructor has published, with their rubrics and
  solutions, and your instructor's description of what this term's exams are
  like -- so it can write practice problems in the style of the real exam.
  Past exams are not on the portal and are not graded there.

When your assistant looks at a slide, it sees the image but cannot paste it
into the chat. Ask it to **"give me the link to that slide"**: each slide has a
link that opens its image in your browser.

It is set up to help you study rather than hand you answers: it will usually
start with a hint and show the full solution only if you ask for it. To get the
most from it, try asking things like:

- *"I think the answer is X -- is my reasoning right?"*
- *"Give me a hint for part (b), not the answer."*
- *"Give me a similar problem, then check my answer."*
- *"Which slide explains this? Show me."*
- *"Which demo shows how to write a testbench for this? Link me to the lines."*
- *"Give me a midterm-style problem on FSMs, like the past midterm."*

Nothing you do through the MCP is graded. The portal counts its use
anonymously -- which problems, slides and demo files are looked at, and how
often -- so
your instructor can see what helps. It never records your name, your
questions or what your assistant says to you.

---

## What you need: the address

The course MCP's address is the course portal's address followed by `/mcp`:

```
https://<portal>/mcp
```

Your instructor will post it. That is usually all you need: skip every mention
of a token below.

### Only if your course uses a token

Some courses also require a **course access token**, a long string of letters
and digits your instructor gives you. If yours does, send it as a request
header named `Authorization`, with the value `Bearer` followed by a space and
the token:

```
Authorization: Bearer <token>
```

If your app has no way to add a header, put the token at the end of the
address instead, and add no header:

```
https://<portal>/mcp/<token>
```

{: .warning }
**Keep the token to yourself.** It is shared by the whole class, so do not post
it anywhere public, such as a public GitHub repository.

### Is it running?

Before connecting an assistant, you can check the address in your browser.
Open `https://<portal>/mcp`. That address is for an AI assistant, not a
browser, so the page you see is short -- what matters is what it says:

- **"This is the course MCP server, and it is running."** -- it is. Go ahead
  and connect.
- **A page saying Not Found** -- the MCP is not turned on for this portal, or
  the address is wrong. Check the address; if it is right, let your
  instructor know.

---

## Connecting Claude (claude.ai, desktop and mobile)

1. Sign in at [claude.ai](https://claude.ai).
2. Open **Settings → Connectors**.
3. Click **Add custom connector**.
4. Give it a name, such as `Hardware Design course`, and paste the address
   (ending in `/mcp`).
5. Under **Authentication**, leave **No sign-in** selected. Claude detects
   this on its own and marks it **Detected**.
6. *Only if your course uses a token:* under **Request headers**, click **Add
   header**. Enter `Authorization` as the name and `Bearer <token>` as the
   value -- the word `Bearer`, a space, then the token. Otherwise leave it
   empty.
7. Click **Add**.

If Claude will not accept `Authorization` as a header name, remove the header
and use the address with the token at the end instead (see above).

{: .note }
With **No sign-in**, Claude shows a warning: *"Without sign-in, anyone with the
server URL can use this connector."* **That is expected, and safe to accept.**
"Sign-in" here means a personal account, which the course MCP does not use. The course MCP is read-only: it only
hands out course material, and it never sees your Claude account, your chats or
your grades. Nothing you do through it is linked to you.

The connector belongs to your Claude account, so it also appears in the Claude
desktop and mobile apps once you have added it on the web. In a chat, check
that it is switched on in the tools menu under the message box.

Custom connectors are available on Claude's free plan, which is limited to one
custom connector. If you have already used that one, remove it or
connect through VS Code instead.

---

## Connecting VS Code (GitHub Copilot)

Copilot Chat in **agent mode** can use MCP servers.

1. Open the Command Palette (`Ctrl+Shift+P`, or `Cmd+Shift+P` on a Mac).
2. Run **MCP: Add Server...**.
3. Choose **HTTP** and paste the address (ending in `/mcp`).
4. Give it a name, such as `hwdesign`, and choose whether to add it for this
   workspace or for all of your workspaces.
5. *Only if your course uses a token:* VS Code opens the `mcp.json` file it
   wrote. Add the token as a `headers` entry, so the server's entry looks like
   this:

```json
{
  "servers": {
    "hwdesign": {
      "type": "http",
      "url": "https://<portal>/mcp",
      "headers": {
        "Authorization": "Bearer <token>"
      }
    }
  }
}
```

You can also create this file by hand: `.vscode/mcp.json` for one workspace.
Do not commit a file containing the token to a public repository.

Then open Copilot Chat, switch it to **Agent** mode, and check that the server's
tools are ticked in the tools picker.

---

## Connecting Claude Code (terminal or VS Code extension)

```bash
claude mcp add --transport http hwdesign https://<portal>/mcp
```

If your course uses a token, add `--header "Authorization: Bearer <token>"`.

`claude mcp list` shows whether it connected, and
`claude mcp remove hwdesign` removes it.

---

## Checking that it works

In a new chat, ask:

> List the problems in unit 2.

A working connection shows the assistant **calling a tool** -- Claude shows a
small "list_questions" box you can expand, and Copilot shows the tool call in
the chat -- and then answers with the unit's actual problems.

If instead the assistant answers from general knowledge without calling
anything, or says it has no such tool:

- **Does it say the course MCP "needs the course access token"?** The token is
  missing or mistyped. Check the header is exactly `Authorization` with the
  value `Bearer <token>` (one space after `Bearer`), or use the address with
  the token at the end.
- **Is the connector switched on** for this chat? Most assistants let you turn
  connectors on and off per conversation.
- **Is the address exactly right?** It ends in `/mcp` -- or in `/mcp/<token>`
  if you put the token in the address.
- **Did you start a new chat** after adding it? Some apps only pick up a new
  connector in a new conversation.
- **Ask it explicitly:** "Use the course tools to list the units." An assistant
  that still cannot find the tools is not connected.

If none of that helps, tell your instructor which app you are using and what
it says.
