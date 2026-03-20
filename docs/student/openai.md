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

To the right of the **Grade** button, you will see a **gear box** that opens a preferences dialog.  Here you can select the model.  These are my findings so far:

* `gpt-4.1.-mini`:  This is the fastest, about 10-20 seconds for a response.  On simple problems, this would be my choice.  But, on problems
where the model has to reason over multiple clock cycles it makes mistakes.
* `gpt-5-mini`:  This is slower, about 1-2 minutes for a response.  But, it can reason very well on more complex problems.
* `gpt-5.4`:  This model is excellent and you will definitely notice the difference on complex grading such as
project plans. 

Both `mini` models are very cheap.  Less than a dollar for a million tokens.  The `gpt-5.4` is about 2.5 times more expensive.
Typical problems consume about 1000 tokens which is a fraction of a penny for the mini models.  Grading a simple project plan with a web retrieval takes about 10000 tokens (mostly input).  On `gpt-5.4` that will cost about 2 to 4 cents.

