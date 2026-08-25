---
title:  Course Package Configuration
parent: Building a Course Package
nav_order: 1
has_children: false
---

# Configuring a Course Pacakage

## Course Package Overview 

Each **course** is  divided into **units**.  For example, a course on probabiliy may have units such as combinatorics, or random variables.
Each unit will have a set of questions. A **course package** (or **solution package**)
is a lightweight, instructor‑authored bundle that describes the units and questions within the units. Each course package contains:

- a single **configuration file**: `llmgrader_config.xml`
- one **unit XML file** for each unit, each already validated by the instructor
- no source code, no student files, and no extra directories

The [unit XML file](./unitxml.md) describes the questions in each unit, along with reference solutions,
grading notes, point assignments, and other settings.  
Overall the package is small, predictable, and easy to debug.

## Local Directory Package Structure

The current flow we support is that the instructor directly writes the configuration and unit XML files
on a local machine using any editor (e.g., VSCode).
These files *are not* edited on the LLM grader portal, although we may add that feature in the future.
The files can be in any directory structure.  This way, the instructor can, for example, create a larger GitHub
repository or local folder, with course material and include the relevant files anywhere in that file structure.  

### Your Course Is a Separate Repository

Your course content lives in **its own repository, alongside `llmgrader` rather
than inside it**.  The `llmgrader` repo is application code that you pull updates
into; the course repo is content you own and may want to keep private.  Mixing
the two makes updating the application painful.

A typical arrangement looks like this:

```
repos/
├── llmgrader/                     ← the application, cloned from GitHub
│   ├── run.py
│   ├── example_repo/
│   └── ...
│
└── hwdesign-soln/                 ← your course content, a separate repo
    ├── llmgrader_config.xml       ← the configuration file
    ├── unit1/
    │   ├── basic_logic.xml
    │   └── images/
    │       ├── circuit_diag.jpg
    │       └── truth_table.png
    ├── unit2/
    │   ├── numbers.xml
    │   └── figures/
    │       └── number_line.png
    ├── unit3/
    │   └── alu.xml
    └── shared/
        └── logic_symbols.svg
```

In this example:

- Each unit lives in its own directory (`unit1/`, `unit2/`, …)
- The unit XML file is inside that directory  
- Supporting assets (images, diagrams, etc.) can live anywhere in the source repository
- The `<source>` paths in `llmgrader_config.xml` refer to these locations

But again, any directory structure is possible.  The configuration file records
where everything is, so the layout above is a convention rather than a
requirement.  The one thing that matters is that the two repositories stay
separate.

Separate repositories do not mean separate editor windows.  In VS Code, open your
course folder and then use **File → Add Folder to Workspace...** to add
`llmgrader` beside it, so both trees are visible at once.  This is worth doing
even if you never edit the application, because it lets an AI agent read the
working examples in `example_repo/` and the schemas in `llmgrader/schemas/` while
drafting your XML.  See [Selecting an IDE](../setup/editor.md) for the details.

If you are setting this up for the first time,
[Build Your Own Course](../gettingstarted/buildcourse.md) walks through creating
this structure step by step.



## Directory Structure of a Solution Package

After [running the packaging script](./upload.md), the relevant files from the local directory
will be extracted to a **solution package** directory.  In the example above, this package
will look like:

```
soln_package/
    llmgrader_config.xml
    unit1_basic_logic.xml
  unit1_assets/
        circuit_diag.jpg
        truth_table.png
    unit2_numbers.xml
  unit2_assets/
        number_line.png
  shared_assets/
    logic_symbols.svg
    ...
```

This package is generated automatically -- you do not need to create the directory structure.
Unit XML files are placed at the root of the package.
Any explicit asset mappings from `llmgrader_config.xml` are copied into the package at
the destination path you specify. This means the package layout is intentional and stable:
authors choose the public asset paths directly instead of relying on a sibling `images/`
directory convention.

For backward compatibility, if a unit source directory contains an `images/` subdirectory
and no equivalent explicit asset mapping is provided, the packaging tool still copies it to
`<destination-stem>_images/` as before.

When zipped, the archive preserves this directory structure:

```
llmgrader_config.xml
unit1_basic_logic.xml
unit1_assets/circuit_diag.jpg
unit1_assets/truth_table.png
unit2_numbers.xml
unit2_assets/number_line.png
shared_assets/logic_symbols.svg
```

This package will be uploaded to the portal.

## Configuration File Format

As a first step in building the course, we need to create the configuration file,
`llmgrader_config.xml` which indicates where to find each unit XML file
in the local directory structure and their destination path in the package.
The structure is fairly simple.
A minimal configuration file corresponding to the example above 
might reference these files like so:

```xml
<llmgrader>
  <course>
    <name>ECE-GY 9463:  Introduction to Hardware Design</name>
    <term>Spring 2026</term>
  </course>

  <units>
    <unit>
      <name>unit1_basic_logic</name>
      <source>unit1/basic_logic.xml</source>
      <destination>unit1_basic_logic.xml</destination>
    </unit>

    <unit>
      <name>unit2_numbers</name>
      <source>unit2/numbers.xml</source>
      <destination>unit2_numbers.xml</destination>
    </unit>
  </units>

  <assets>
    <asset>
      <source>unit1/images</source>
      <destination>unit1_assets</destination>
    </asset>

    <asset>
      <source>unit2/figures/number_line.png</source>
      <destination>unit2_assets/number_line.png</destination>
    </asset>

    <asset>
      <source>shared/logic_symbols.svg</source>
      <destination>shared_assets/logic_symbols.svg</destination>
    </asset>
  </assets>
</llmgrader>
```

This shows the mapping clearly:

- `<source>` points to the instructor’s local directory structure  
- `<destination>` is the filename that will appear in the solution package
- `<assets>` defines additional package files and directories to copy

Units are loaded and displayed **in the order they are listed here**, so the
sequence of `<unit>` blocks is what students see in the unit dropdown.

Asset mappings may copy either a whole directory or a single file:

- If `<source>` is a directory, its contents are copied under the destination directory.
- If `<source>` is a file, it is copied to the exact destination path.

In unit HTML, reference packaged assets with `/pkg_assets/<destination>`. For example,
the asset above at `unit2_assets/number_line.png` is served as:

```
/pkg_assets/unit2_assets/number_line.png
```

The `<destination>` path must be relative to the package root. Absolute paths and
paths containing `..` are rejected during validation.



---

## The Page Banner

The `<course>` block also drives the banner across the top of the portal.  Two
optional elements control it:

```xml
<course>
  <name>ECE-GY 9463:  Introduction to Hardware Design</name>
  <term>Spring 2026</term>
  <title>LLM Grader for NYU Hardware Design</title>
  <instructors>Profs. Ada Lovelace, Alan Turing</instructors>
</course>
```

| Element | Effect on the banner |
|---|---|
| `<title>` | The large headline.  **If omitted, the banner falls back to `<name>`** |
| `<instructors>` | The smaller line beneath it.  If omitted, that line is hidden entirely |

Both are optional, so existing configuration files keep working without changes --
they simply show `<name>` as the headline and no instructor line.

The banner updates when a new course package is loaded, so an administrator who
uploads a package does not have to restart the app to see the new title.

> **Upgrading an existing course:** if your banner text used to be built into the
> application, add `<title>` and `<instructors>` to your config to preserve it.
> Without a `<title>`, the banner will show your `<name>` value instead, which is
> often a course number rather than the display title you want.

---

Next:  [Describing the units](./unitxml.md) and examples of unit XML files.