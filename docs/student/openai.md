---
title: OpenAI Keys
parent: Student Guide
nav_order: 2
has_children: false
---

#  Using the OpenAI Models

## OpenAI Keys

The grader is based on [OpenAI's API platform](https://openai.com/api/) which provides access to its powerful GPT models.
To use the autograder, you will need to get an OpenAI API Key and register the key with the LLM grader:

* Go to the [OpenAI's API platform](https://openai.com/api/) page
* **Log In**.  If you do not have an account, you will be asked to create one
* Go to the [API Key page](
https://platform.openai.com/account/api-keys) page.
* Create a OpenAI key.  
* Go back to the Autograder webpage select **File->Preferences** and paste the key in the **OpenAI key** box.

**Important notes**
- Your API key is never stored on the server.
It stays entirely in your browser (using local storage) and is only sent with your grading request so the model can run. The server does not save, log, or retain your key.
- Costs are typically very low.
Each grading request uses only a small amount of model compute, so even frequent use should remain inexpensive. You can monitor your usage at any time on your OpenAI dashboard.

## Which model to use?

To the right of the **Grade** button, a **gear box** opens a preferences dialog
where you can pick the model. Most of the time you should not have to: your
instructor can pin the right model to each question, and the dialog is there
for the exceptions.

There are three models, one generation of the same family, named for how hard
the problem is rather than for what they cost:

| Model | Use it for | Cost per 1,000 graded questions | Typical response |
|---|---|---|---|
| **GPT-5.6 Luna** *(default)* | Routine short answers and single derivations | $0.30 | ~2 s |
| **GPT-5.6 Terra** | Multi-part derivations, proofs, short code | $2.84 | ~2 s |
| **GPT-5.6 Sol** | Projects, reports, anything needing long context or web search | $5.35 | ~3 s |

Worked examples:

* *"Differentiate \(y = a^x\)."* — **Luna.** One step, one right answer.
* *"Derive the transfer function, then find the critical path delay."* —
  **Terra.** Several dependent steps, where a model that loses the thread
  halfway through will mark a correct answer wrong.
* *"Here is my project outline; check it against the requirements."* —
  **Sol.** Long input, several criteria at once, and often a web search.

Luna is the default because it is the right answer for most questions, not
because it is the budget option — it graded a held-out sample of real
submissions as well as the more expensive models did. Reach for Terra or Sol
when a problem has several dependent steps, not as a general upgrade.

### What this costs you

All three prices above are measured on real grading requests, not list prices.
A single routine question on Luna costs about **three hundredths of a cent**;
you would have to grade several thousand questions to spend a dollar. A project
outline on Sol with a web search is the expensive case at roughly **2 cents per
grading**, because the search results are billed as input.

Your key is never stored on the server: it stays in your browser and is sent
with the grading request only. Monitor spend on your OpenAI dashboard.
