---
title:  Rubrics and Grading Notes
parent: Building a Course Package
nav_order: 4
has_children: false
---

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
<question qtag="Exponential derivative" preferred_model="simple">
        <question_text><![CDATA[
        <p>Compute the derivative of \(y = a^x\) with respect to \(x\). Show your work.</p>
        ]]></question_text>

        <solution><![CDATA[
        <p>There are two standard methods.</p>

        <p>One method is to take the natural logarithm of both sides and then differentiate implicitly:</p>

        <p class="math">
        \[
            \begin{aligned}
            &\ln(y) = \ln(a^x) = x\ln(a) \\
            &\implies \frac{y'}{y} = \ln(a) \\
            &\implies y' = y\ln(a) = a^x \ln(a)
            \end{aligned}
        \]
        </p>

        <p>A second method is to write \(a^x\) as \(e^{x\ln(a)}\) and then apply the chain rule:</p>
        \[
            \begin{aligned}
            &y = e^{x\ln(a)} \\
            &y' = e^{x\ln(a)} \cdot \ln(a) = a^x \ln(a)
            \end{aligned}
        \]
        </p>
        ]]></solution>
        <partial_credit>false</partial_credit>
        <required>false</required>
        <parts>
             <part>
                    <part_label>all</part_label>
                    <points>10</points>
                </part>
        </parts>
        <rubrics>
            <item id="taking_logarithm" condition_type="positive" action="fail">
                <display_text>Taking logarithm</display_text>
                <condition>Student takes the logarithm of both sides to facilitate differentiation, which is a common and valid approach to this problem.</condition>
                <notes> This rubric can be skipped if the student uses an alternative valid method, such as chain rule.
                </notes>
            </item>
            <item id="exponential_form" condition_type="positive" action="fail">
                <display_text>Write the function in exponential form</display_text>
                <condition>Student correctly rewrites the function in terms of the natural exponential function and applies the chain rule to find the derivative.</condition>
                <notes> This rubric can be skipped if the student uses an alternative valid method, such as taking logarithms.
                </notes>
            </item>
            <item id="polynomial_confusion" condition_type="negative" action="fail">
                <display_text>Polynomial confusion</display_text>
                <condition>Student confuses the exponential function with a polynomial function, leading to incorrect differentiation, e.g. $y' = xa^{x-1}$</condition>
             </item>
             <item id="final_answer" condition_type="positive" action="fail">
                <display_text>Final answer</display_text>
                <condition>Student provides the correct derivative $y' = a^x \ln(a)$.</condition>
            </item>
            <group type="one_of">
                <id>taking_logarithm</id>
                <id>exponential_form</id>
            </group>
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
points. In this mode, rubric items should describe **independent additions or deductions** to the score.

Use partial-credit rubrics for things like:

- awarding credit for major required components
- deducting points for identifiable mistakes or omissions
- separating mathematically correct work from implementation details

In this design, the reference solution and grading notes still establish what a
fully correct answer looks like. The rubric items then tell the grader how to
adjust the score based on specific evidence.

### Partial-Credit Example

```xml
<question qtag="ODE Solver" preferred_model="standard">
    <question_text><![CDATA[
    <p>Write a Python function that implements a first-order Euler solution to the ODE:
    \[
    \frac{dx}{dt} = -a\,x(t) + b\,x(t)^2
    \]
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
    <required>true</required>
    <parts>
        <part>
            <part_label>all</part_label>
            <points>10</points>
        </part>
    </parts>

    <rubrics>
        <item id="arguments" part="all" point_adjustment="+4">
            <display_text>Complete function interface</display_text>
            <condition>Student includes the initial condition, model parameters, time step, and number of 
                steps as inputs.  If they supply some of the inputs but not all, award partial credit.</condition>
            <notes>Different variable names, argument order, and omission of type hints are acceptable.</notes>
        </item>

        <item id="correct_update" part="all" point_adjustment="+4">
            <display_text>Correct Euler update</display_text>
            <condition>Student implements the mathematically correct Euler step for the given ODE.</condition>
            <notes>Any equivalent implementation of the same update should receive this credit.</notes>
        </item>

        <item id="returns_array" part="all" point_adjustment="+2">
            <display_text>Returns the full trajectory as an ndarray</display_text>
            <condition>Student returns an array containing all iterates, not only the final value.  If returning a list, award only 1 point.</condition>
        </item>
        <item id="syntax_incorrect" part="all" point_adjustment="-2">
            <display_text>Minor Python syntax errors</display_text>
            <condition>Student's solution has minor Python syntax errors that do not obscure the intended algorithm. </condition>
        </item>
    </rubrics>
    <rubric_total>sum_positive</rubric_total> <!-- sets score exactly equal to the sum of point adjustments -->

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
- `<display_text>`: Short human-readable label for the scoring item. Do **not** begin it with the part label: the grader renders the criteria table as `Part a: {display_text}`, so `Part a: Correct slices` comes out as `Part a: Part a: Correct slices`. `llmgrader_test check` warns when it sees this.
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


## Feedback-Only Items

Sometimes you want the grader to *work something out* for the student without
scoring it: check an answer at its limits, trace a few steps of a program or a
state machine, estimate how long a design will take to build, or remind the
student what the next part will look for. A **feedback-only item** does that.
Mark the item `scored="false"`:

```xml
<item id="rc_limits" part="b" scored="false">
    <display_text>Check at the limits</display_text>
    <condition>Evaluate the student's own expression for v_C(t) at t = 0 and as t goes
    to infinity, and compare each with the physical values: the capacitor starts at
    2 V, and ends at 5 V once the current stops.  State both values the expression
    gives.  If one disagrees, say which.</condition>
</item>
```

The grader carries out the analysis the `<condition>` asks for on the student's
own answer, and reports it in a **Notes** section below the rubric table:

```text
Notes:
- Part b: Check at the limits: Using your expression, v_C(0) = 5(1 - e^0) = 0 V,
  while v_C(t) approaches 5 V as t goes to infinity. The final value agrees with
  the physical value, but the initial value disagrees with the required 2 V.
```

The item awards no points and passes or fails nothing. If the model returns a
score for it anyway, the grader drops it before any total is computed.

### Feedback-Only Fields

- `id`: Unique internal identifier, as for any item.
- `scored="false"`: Makes the item feedback-only. Omitting `scored`, or setting
  it to `true`, means an ordinary scored item.
- `part`: Optional. Any part, or `all`. `all` is allowed even on a multi-part
  `sum_positive` question, because the item counts toward no part.
- `<display_text>`: The label shown in the Notes section.
- `<condition>`: An *instruction*, not a criterion: say what to analyze and what
  to report. Required.
- `<notes>`: Optional private guidance to the grading model, as for any item.

`point_adjustment`, `condition_type` and `action` have no meaning on a
feedback-only item, and the validator rejects them. A feedback-only item cannot
be in a `one_of` group. It works the same way in binary and partial-credit
questions.

### Writing Good Feedback-Only Items

- **Ask for the student's own work.** "Evaluate the student's expression at
  t = 0" gives a specific, checkable report. "Check whether the answer is
  right" duplicates the scored items.
- **Ask for the numbers.** The report is most useful when it shows the values
  or steps, so the student can follow it and find the error themselves.
- **Keep the scored items independent of it.** The scored items decide the
  grade; a feedback-only item explains or adds context. Do not write a scored
  item that depends on what the feedback-only item found.

In grading tests (`llmgrader_test`), a feedback-only item needs no assertion,
and `check` refuses one: there is no score to compare. Read the Notes section of
each case's feedback in the run report instead.

The demo course has a complete example: `example_repo/unit3/circuits.xml`, an RC
step response with two feedback-only items (a check at the limits and a units
check), and its grading tests in `example_repo/unit3/tests/circuits_tests.xml`.


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

You can see an example in the exponential derivative example above:

```xml
<rubrics>
    ...

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