# Rubrics and Grading Notes

## Overview

Rubrics give the grader an explicit checklist of evidence to look for in a
student solution. They are most useful when the reference solution and grading
notes are not, by themselves, specific enough to drive consistent decisions.

In practice, rubrics work best when each item is:

- atomic, so the grader can decide it independently
- observable, so the grader can point to concrete evidence in the student work
- non-overlapping, so the same mistake is not penalized multiple times unless
  that is intentional
- phrased in terms of correctness or a recognizable misconception, not style

One additional field is especially helpful for making rubric-based grading
stable:

- `part`, which indicates which part of a multipart problem the rubric item
    applies to

In rare cases, you may also want an explicit grouping mechanism for rubric items
that should not be treated independently. That is described later in this page.

The rubric structure should be different for the two grading modes:

- In **binary grading**, rubric items act like gates or warnings.
- In **partial-credit grading**, rubric items act like score adjustments.

That split is sensible. A binary problem needs decisive pass/fail criteria,
while a partial-credit problem needs finer-grained scoring guidance.

This page describes the **planned rubric schema** for that design.

## Rubrics for Binary Grading

A **binary** graded problem is one in which the answer is either **pass** or
**fail**. In this mode, rubric items should capture conditions that are strong
enough to change the overall decision.

Use binary rubrics for things like:

- required evidence that must appear somewhere in a correct solution
- serious misconceptions that should force failure
- warnings that should produce feedback but not force failure

Avoid using binary rubrics for every small intermediate step. If too many minor
items are marked as `action="fail"`, the grader becomes brittle and valid
alternative solutions are more likely to be rejected.

### Binary Example

```xml
<question qtag="exponential_derivative" preferred_model="gpt-4.1-mini">
    <question_text><![CDATA[
    <p>Compute the derivative of \(y = a^x\) with respect to \(x\). Show your work.</p>
    ]]></question_text>

    <solution><![CDATA[
    <p>There are two standard methods.</p>

    <p>One method is to take the natural logarithm of both sides and then differentiate implicitly:</p>

    <p class="math">
        $$
        \begin{aligned}
        \ln(y) &= \ln(a^x) = x\ln(a) \\
        \frac{y'}{y} &= \ln(a) \\
        y' &= y\ln(a) = a^x\ln(a)
        \end{aligned}
        $$
    </p>

    <p>A second method is to write \(a^x = e^{x\ln(a)}\) and apply the chain rule:</p>

    <p class="math">
        $$
        \begin{aligned}
        y &= e^{x\ln(a)} \\
        y' &= e^{x\ln(a)}\ln(a) = a^x\ln(a)
        \end{aligned}
        $$
    </p>
    ]]></solution>

    <partial_credit>false</partial_credit>
    <required>false</required>
    <points>10</points>

    <rubrics>
        <item id="taking_logarithm" part="all" condition_type="positive" action="fail">
            <display_text>Uses logarithmic method correctly</display_text>
            <condition>Student takes the logarithm of both sides and differentiates correctly.</condition>
            <notes>This rubric may be skipped if the student uses another valid method.</notes>
        </item>

        <item id="exponential_form" part="all" condition_type="positive" action="fail">
            <display_text>Uses exponential-form method correctly</display_text>
            <condition>Student rewrites the function as \(e^{x\ln(a)}\) and applies the chain rule correctly.</condition>
            <notes>This rubric may be skipped if the student uses another valid method.</notes>
        </item>

        <item id="final_answer" part="all" condition_type="positive" action="fail">
            <display_text>Correct final derivative</display_text>
            <condition>Student gives the final derivative \(y' = a^x\ln(a)\).</condition>
        </item>

        <item id="polynomial_confusion" part="all" condition_type="negative" action="fail">
            <display_text>Treats the expression like a polynomial</display_text>
            <condition>Student differentiates as if \(a^x\) were a polynomial in \(x\), for example \(y' = xa^{x-1}\).</condition>
        </item>

        <item id="missing_justification" part="all" condition_type="negative" action="feedback">
            <display_text>No supporting work</display_text>
            <condition>Student states the correct answer but gives little or no supporting work.</condition>
        </item>
    </rubrics>
</question>
```

### Binary Rubric Fields

- `id`: Unique internal identifier for the rubric item.
- `part`: The question part to which the rubric applies. Use `all` when the rubric applies to the entire question.
- `condition_type="positive" | "negative"`: A `positive` condition is something the student should satisfy. A `negative` condition is something the student should not do.
- `action="fail" | "feedback"`: For binary grading, `fail` means the rubric item should cause failure when triggered. `feedback` means the item should influence feedback without forcing failure.
- `<display_text>`: Short human-readable label for the rubric item.
- `<condition>`: The exact behavior or evidence the grader should look for.
- `<notes>`: Optional clarification for waiver conditions, alternative valid approaches, or interpretation guidance.

### When Binary Rubrics Guide the LLM Well

Binary rubrics usually work well when:

- each `fail` item corresponds to a decisive correctness issue
- the rubric allows alternative valid methods through `notes`
- negative items capture common high-confidence misconceptions
- `feedback` items are reserved for issues that matter pedagogically but should
  not override a correct answer

Binary rubrics work poorly when:

- several `fail` items describe the same underlying mistake
- the conditions depend on wording rather than mathematical or logical content
- the rubric requires one specific solution path when several are valid

## Rubrics for Partial-Credit Questions

Partial-credit questions allow the student to earn some portion of the total
points. In this mode, rubric items should describe **independent additions or
deductions** to the score.

Use partial-credit rubrics for things like:

- awarding credit for major required components
- deducting points for identifiable mistakes or omissions
- separating mathematically correct work from implementation details

In this design, the reference solution and grading notes still establish what a
fully correct answer looks like. The rubric items then tell the grader how to
adjust the score based on specific evidence.

### Partial-Credit Example

```xml
<question qtag="ode_solver" preferred_model="gpt-4.1-mini">
    <question_text><![CDATA[
    <p>Write a Python function that implements a first-order Euler solution to the ODE</p>

    <p class="math">
        $$
        \frac{dx}{dt} = -a x(t) + b x(t)^2
        $$
    </p>

    <p>
        The function should take the initial condition, the parameters, the time step,
        and the number of steps. It should return the full trajectory of \(x(t)\) as
        an <code>ndarray</code>.
    </p>
    ]]></question_text>

    <solution><![CDATA[
    <p>One correct solution is:</p>

    <pre><code>def sim(x0, a, b, tstep, nsteps):
    x = np.zeros(nsteps + 1)
    x[0] = x0
    for i in range(nsteps):
        f = -a * x[i] + b * x[i] ** 2
        x[i + 1] = x[i] + tstep * f
    return x</code></pre>
    ]]></solution>

    <partial_credit>true</partial_credit>
    <required>false</required>
    <points>10</points>

    <rubrics>
        <item id="arguments" part="all" point_adjustment="+3">
            <display_text>Complete function interface</display_text>
            <condition>Student includes the initial condition, model parameters, time step, and number of steps as inputs.</condition>
            <notes>Different variable names, argument order, and omission of type hints are acceptable.</notes>
        </item>

        <item id="correct_update" part="all" point_adjustment="+4">
            <display_text>Correct Euler update</display_text>
            <condition>Student implements the mathematically correct Euler step for the given ODE.</condition>
            <notes>Any equivalent implementation of the same update should receive this credit.</notes>
        </item>

        <item id="returns_array" part="all" point_adjustment="+2">
            <display_text>Returns the full trajectory as an ndarray</display_text>
            <condition>Student returns an array containing all iterates, not only the final value.</condition>
        </item>

        <item id="uses_list" part="all" point_adjustment="-2">
            <display_text>Uses a list instead of an ndarray</display_text>
            <condition>Student stores the trajectory in a Python list rather than an <code>ndarray</code>.</condition>
        </item>

        <item id="syntax_incorrect" part="all" point_adjustment="-2">
            <display_text>Minor Python syntax errors</display_text>
            <condition>Student's solution has minor Python syntax errors that do not obscure the intended algorithm.</condition>
        </item>
    </rubrics>

    <grading_notes><![CDATA[
    Any mathematically correct Euler implementation that satisfies the specification should receive full credit.
    Do not require the exact variable names used in the reference solution.
    If the student omits an explicit NumPy import but the intended use of ndarray is otherwise clear, do not penalize that separately.
    ]]></grading_notes>
</question>
```

### Partial-Credit Rubric Fields

- `id`: Unique internal identifier for the rubric item.
- `part`: The question part to which the rubric applies. Use `all` when the rubric applies to the whole question.
- `point_adjustment`: Numeric score adjustment, such as `"+3"` or `"-2"`.
- `<display_text>`: Short human-readable label for the scoring item.
- `<condition>`: The exact evidence that justifies awarding or deducting the adjustment.
- `<notes>`: Optional clarification about acceptable variants or cases where the item should not be applied.

### When Partial-Credit Rubrics Guide the LLM Well

Partial-credit rubrics usually work well when:

- each item corresponds to a distinct scoring component
- positive items reward meaningful pieces of correct work
- negative items target specific, recognizable deficiencies
- the adjustments are sized so no single minor mistake dominates the score

Partial-credit rubrics work poorly when:

- two items reward the same evidence twice
- deductions are so large that the grader effectively reverts to binary grading
- an item mixes multiple concepts, such as correctness, efficiency, and style

## Part Field

The `part` field is worth using even in a first implementation.

### `part`

Use `part` to scope a rubric item to one part of a multipart question.

Examples:

- `part="a"` means the rubric applies only to part (a)
- `part="b"` means the rubric applies only to part (b)
- `part="all"` means the rubric applies to the entire question

This prevents the grader from accidentally applying a rubric item to the wrong
part of a response.

## Avoiding Double Counting

Yes, double counting is a real risk.

The main cases are:

- two positive items awarding credit for the same evidence
- a negative item and a missing positive item both penalizing the same mistake
- two deductions that are really two descriptions of one underlying error

You will not eliminate this risk with prompt wording alone, but good rubric
writing and prompt instructions can reduce it substantially.

Recommended prompt guidance:

- Do not award or deduct credit twice for the same evidence.
- For each triggered rubric item, identify the distinct evidence that supports it.

That will not solve every overlap case, but it will handle many of the common
ones.

## Optional Grouping for Rare Cases

Most rubric items can be treated independently. In those common cases, no
grouping metadata is needed.

However, some questions have multiple alternative conditions where satisfying
any one of them should be enough. For those rare cases, you can add an explicit
group block under `<rubrics>`.

### Example: `one_of` Group

```xml
<rubrics>
    <item id="taking_logarithm" part="all" condition_type="positive" action="fail">
        <display_text>Uses logarithmic method correctly</display_text>
        <condition>Student takes the logarithm of both sides and differentiates correctly.</condition>
    </item>

    <item id="exponential_form" part="all" condition_type="positive" action="fail">
        <display_text>Uses exponential-form method correctly</display_text>
        <condition>Student rewrites the function as \(e^{x\ln(a)}\) and applies the chain rule correctly.</condition>
    </item>

    <item id="final_answer" part="all" condition_type="positive" action="fail">
        <display_text>Correct final derivative</display_text>
        <condition>Student gives the final derivative \(y' = a^x\ln(a)\).</condition>
    </item>

    <group type="one_of">
        <id>taking_logarithm</id>
        <id>exponential_form</id>
    </group>
</rubrics>
```

In this example, the grader should interpret the group as follows:

- at least one listed rubric item should be satisfied
- the student does not need to satisfy all listed items
- the grouped items represent alternative valid methods, not cumulative checks

This keeps the common case simple while still letting you represent important
exceptions explicitly.

### When to Use Groups

Use a `<group>` only when the default assumption of independent rubric items is
wrong.

Typical cases include:

- two or more alternative valid solution methods
- multiple checks where only one should be required for a pass condition
- future advanced cases where the grader needs explicit non-independent logic

If the items are normally independent, do not group them.

### Prompt Guidance for Groups

If groups are present, the prompt should state:

- Treat rubric items as independent unless they are explicitly listed in a group.
- For a group with `type="one_of"`, satisfying any one listed item is sufficient.
- Do not require all items in a `one_of` group.
- Do not double count evidence across grouped items.

## Recommended Authoring Style

For both grading modes, write rubric conditions so that the grader can answer
the question, "What exact evidence in the student work would trigger this item?"

Good rubric conditions usually:

- name the concept or mistake directly
- allow equivalent formulations when appropriate
- avoid vague words like "good", "clear", or "reasonable"
- avoid enforcing formatting unless formatting is part of the requirement

Examples of strong conditions:

- "Student gives the correct final derivative \(y' = a^x\ln(a)\)."
- "Student implements the Euler update \(x[i+1] = x[i] + tstep\,f(x[i])\)."
- "Student treats the exponential as a polynomial, for example \(y' = xa^{x-1}\)."

Examples of weak conditions:

- "Student shows understanding."
- "Student solution is well written."
- "Student mostly uses the right method."

## Relationship to Grading Notes

Rubrics should not replace `<grading_notes>`. The two serve different roles:

- Use `<rubrics>` for structured, itemized checks that you want the grader to
  evaluate explicitly.
- Use `<grading_notes>` for broader policies, allowed alternative approaches,
  edge cases, and instructions that do not fit naturally into a single rubric item.

As a rule of thumb, if a piece of guidance should appear as a separate item in
the grader's reasoning, it belongs in `<rubrics>`. If it is a general policy or
exception, it belongs in `<grading_notes>`.