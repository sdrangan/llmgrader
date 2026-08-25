---
title: Build Your Own Course
parent: Getting Started
nav_order: 3
has_children: false
---

# Build Your Own Course

The [Quickstart](./quickstart.md) ran the example course that ships with the
repository.  This page builds a course of your own, with one question you write
yourself, and grades it on your laptop.

It is deliberately small: **one unit, one question**.  The goal is to go all the
way through the loop once, so the structure is familiar before you scale up.  You
will not need a server, a deployment, or a Gradescope assignment.

Every command below was run start to finish while writing this page.

---

## 1. Create a Repository for Your Course

Your course content lives in its own repository, separate from the `llmgrader`
code.  Create an empty repository on GitHub -- for example `robotics-soln` -- and
clone it:

```bash
git clone https://github.com/<your-github-user>/robotics-soln.git
cd robotics-soln
```

A separate repo keeps your course material yours: you can make it private, share
it with a TA, and pull `llmgrader` updates without touching your content.

> Keep the virtual environment you made in the Quickstart active.  The commands
> below come from the `llmgrader` package, but they run against *this* directory.

## 2. Create a Unit Folder

Each unit gets a folder.  The layout is up to you -- the config file records where
things are -- but one folder per unit is the convention:

```bash
mkdir unit1
```

### How the Two Repositories Sit Together

Your course repo is a **sibling** of the `llmgrader` repo, not inside it.  By the
end of this page you will have:

```
repos/
├── llmgrader/                  ← the application (cloned in the Quickstart)
│   ├── run.py
│   ├── example_repo/
│   └── ...
│
└── robotics-soln/              ← your course content (this page)
    ├── llmgrader_config.xml    ← lists the units in the course      (step 5)
    ├── unit1/
    │   ├── statics.xml         ← the questions you write            (step 3)
    │   └── statics.html        ← generated preview                  (step 4)
    ├── soln_package/           ← generated: what you run locally    (step 6)
    └── soln_package.zip        ← generated: what you upload later   (step 6)
```

Two things worth noting:

- **Keep them separate.** The `llmgrader` repo is code you pull updates into; the
  course repo is content you own.  Mixing them makes updating painful.
- **The generated items are disposable.** `soln_package/` and `soln_package.zip`
  are rebuilt every time you run the packaging command, so there is no need to
  commit them.  A `.gitignore` with these two lines keeps the repo clean:

  ```
  soln_package/
  soln_package.zip
  ```

  The rendered `.html` previews are regenerable too, but do not blanket-ignore
  `*.html`: if you later write [HTML notes](../buildcourse/htmlnotes.md) as course
  content, those are real source files you want to keep.

The sibling layout is why step 7 can refer to your package as
`../robotics-soln/soln_package`.  If you put the two repos somewhere else, adjust
that path accordingly.

> **In VS Code, open both folders at once.**  Open your course folder, then use
> **File → Add Folder to Workspace...** to add `llmgrader`.  Two separate repos,
> one window.  This is worth doing even though you will only edit the course
> folder: it lets an AI agent read the working examples in `example_repo/` and the
> schemas in `llmgrader/schemas/` while it drafts your XML, which makes its output
> markedly better.  See [Selecting an IDE](../setup/editor.md).

## 3. Write the Unit XML

Create `unit1/statics.xml`.  This is a complete, working example -- paste it in,
then change the subject matter to your own later:

```xml
<unit id="statics" title="Unit 1: Statics" version="1.0">

    <question qtag="Beam reaction" preferred_model="simple">
        <question_text><![CDATA[
        <p>A uniform beam of length \(L\) and weight \(W\) rests on two supports,
        one at each end. A point load \(P\) is placed a distance \(a\) from the
        left support. Find the vertical reaction at the left support.</p>
        ]]></question_text>

        <solution><![CDATA[
        <p>Take moments about the right support. With \(R_L\) the left reaction:</p>
        <p class="math">
        \[
            R_L L - W\frac{L}{2} - P(L-a) = 0
            \implies R_L = \frac{W}{2} + P\frac{L-a}{L}
        \]
        </p>
        ]]></solution>

        <partial_credit>true</partial_credit>
        <required>false</required>

        <parts>
            <part>
                <part_label>all</part_label>
                <points>10</points>
            </part>
        </parts>

        <rubrics>
            <item id="moment_balance" condition_type="positive" point_adjustment="5">
                <display_text>Sets up a moment balance</display_text>
                <condition>Student writes a moment equilibrium equation about one of the supports (or an equivalent force-and-moment system).</condition>
            </item>
            <item id="beam_weight" condition_type="positive" point_adjustment="2">
                <display_text>Includes the beam weight at midspan</display_text>
                <condition>Student accounts for the distributed beam weight W acting at the midpoint of the beam.</condition>
            </item>
            <item id="correct_result" condition_type="positive" point_adjustment="3">
                <display_text>Correct final expression</display_text>
                <condition>Student arrives at R_L = W/2 + P(L-a)/L, or an algebraically equivalent form.</condition>
            </item>
            <item id="ignores_weight" condition_type="negative" point_adjustment="-2">
                <display_text>Ignores the beam weight</display_text>
                <condition>Student treats the beam as massless when the problem states it has weight W.</condition>
            </item>
        </rubrics>
    </question>

</unit>
```

The parts worth understanding before you edit it:

| Element | What it does |
|---|---|
| `question_text` | What the student sees.  HTML inside `CDATA`; LaTeX in `\( \)` or `\[ \]` |
| `solution` | Your reference solution.  The model sees this, the student does not |
| `partial_credit` | `true` scores by rubric points; `false` is pass/fail |
| `parts` | How many points the question is worth |
| `rubrics` | The checklist the model scores against.  `point_adjustment` adds or subtracts |

Notice that the positive rubric items sum to the 10 points declared in `parts`,
and the negative item is a penalty for one specific mistake.  That relationship is
the heart of rubric design -- see
[Rubrics and Grading Notes](../buildcourse/rubrics.md) when you start writing your
own.

## 4. Render the Unit to HTML

Before wiring anything up, check that your XML renders the way you expect:

```bash
create_qfile --input unit1/statics.xml --output unit1/statics.html
```

Open `unit1/statics.html` in a browser.  You should see your question with the
math typeset.  This is the fastest way to catch a malformed CDATA block or broken
LaTeX, and it costs nothing -- no API calls are involved.

To render with the reference solution included, which is useful for a handout or
your own review:

```bash
create_qfile --input unit1/statics.xml --output unit1/statics_soln.html --soln
```

If the XML is invalid, this step fails and reports the problem.

## 5. Create the Config File

The config file lists the units in the course.  Create `llmgrader_config.xml` at
the repo root:

```xml
<llmgrader>
  <course>
    <name>My Course</name>
    <semester>Fall 2026</semester>
  </course>

  <units>
    <unit>
      <name>Unit 1: Statics</name>
      <source>unit1/statics.xml</source>
      <destination>unit1_statics.xml</destination>
    </unit>
  </units>
</llmgrader>
```

`source` is where the file lives in your repo; `destination` is what it is called
inside the built package.  Add one `<unit>` block per unit as the course grows.

If your questions reference images, you add an `<assets>` section here as well --
see [Course Package Configuration](../buildcourse/pkgconfig.md).  The example
above has no images, so it needs none.

## 6. Build the Package

```bash
create_soln_pkg --config llmgrader_config.xml
```

This produces a `soln_package/` directory and a `soln_package.zip`.  The ZIP is
what you would upload to a deployed portal later; the directory is what you run
against locally.

## 7. Run It Locally

From the `llmgrader` repo, point the app at the package you just built:

```bash
cd ../llmgrader
python run.py --soln_pkg ../robotics-soln/soln_package
```

Open <http://127.0.0.1:5000/> and you should see **Unit 1: Statics** with your
question in it.

## 8. Grade It

Add your OpenAI key under **File → Preferences** if you have not already, then
answer your own question and click **Grade**.

The most informative thing you can do here is answer it *badly on purpose*.  Try:

- a correct answer that ignores the beam weight -- does `ignores_weight` fire?
- a correct setup with an algebra slip -- do you get the setup points but not the
  result point?
- a correct answer by a different valid method -- does it still score full marks?

That third case is the one worth dwelling on.  Rubrics that describe *evidence of
reasoning* tolerate alternative solution paths; rubrics that describe *one
specific sequence of steps* do not.  Watching the model score an unexpected but
valid answer tells you more about your rubric than any amount of reading about
rubrics.

---

## Where to Go Next

You now have the whole loop.  From here:

- **Add more questions and units** -- repeat steps 3 and 5.  The full XML format
  is documented in [Creating a Unit](../buildcourse/unitxml.md).
- **Let an agent do the tedious part.**  If you use VS Code with an AI agent, set
  up the [MCP server](../setup/mcp_setup.md).  It can read the homework and
  solutions you already have and draft the unit XML for you, which is far faster
  than writing rubrics by hand.  This is the intended authoring workflow -- see
  [Using the LLM Course Builder Agent](../buildcourse/agent.md).
- **Pin down your rubrics** with [grading tests](../buildcourse/gradetests.md):
  write trial answers, declare the score each one should get, and re-run the suite
  from the command line whenever you edit a rubric or switch models.
- **Put it in front of students** -- [Deploying the App](../deploy/).
- **Compare against the example course.**  `example_repo/` in the `llmgrader` repo
  has richer questions than the minimal one above, including multi-part problems,
  images, and binary pass/fail grading.
