---
title:  Course Package Configuration
parent: Building a Course Package
nav_order: 1
has_children: false
---

# Configuring a Course Pacakage

## Course Package Overview 

Each **course** is assumed to be divied into **units**.  For example, a course on probabiliy may have units such as combinatorics, or random variables.
Each unit will have a set of questions. Typically, the instructor will  A **course package** (or **solution package**)
is a lightweight, instructor‑authored bundle that tells the LLM grader which units belong to a course and where to find their XML definitions
for the questions and solutions in that unit. It contains:

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
For example, we could have a directory structure such as:

```
hwdesign-soln/
    llmgrader_config.xml        ← optional: some instructors keep it here
    unit1/
        basic_logic.xml
        images/
            circuit_diag.jpg
            truth_table.png
    unit2/
        numbers.xml
        images/
            number_line.png
    unit3/
        alu.xml
```

In this example:

- Each unit lives in its own directory (`unit1/`, `unit2/`, …)
- The unit XML file is inside that directory  
- Supporting assets (images, diagrams, etc.) live in subfolders such as `images/`
- The `<source>` paths in `llmgrader_config.xml` refer to these locations

But again, any directory structure is possible.



## Directory Structure of a Solution Package

After [running the packaging script](./upload.md), the relevant files from the local directory
will be extracted to a **solution package** directory.  In the example above, this package
will look like:

```
soln_package/
    llmgrader_config.xml
    unit1_basic_logic.xml
    unit2_numbers.xml
    ...
```

In the future, we will permit the unit XML files and other assets,
such as images, to reside in sub-folders within the package.
But, for now, it is a single flat structure.
When zipped, the archive contains these files at the root level (no nested folder):

```
llmgrader_config.xml
unit1_basic_logic.xml
unit2_numbers.xml
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
</llmgrader>
```

This shows the mapping clearly:

- `<source>` points to the instructor’s local directory structure  
- `<destination>` is the filename that will appear in the **flat** solution package (for now)

Later, when nested directories and assets are supported, the `<destination>` paths can mirror the instructor repo structure (e.g., `unit1/basic_logic.xml`), allowing images and other files to be included naturally.



---

---

## Grader configuration file `llmgrader_config.xml`

Generally, we expect that the course solutions are in some file system,
typically a GitHub repository, although any folder system can be used.
The solution package configuration file, `llmgrader_config.xml` 
describes how to find the unit XML files within that local repository or file system.
Specifically, this file defines:

- the **course metadata** (name, term, etc.)
- the **list of units** included in the package
- the **mapping** from instructor repo paths → packaged filenames

The grader uses this file to:

- load units in the correct order  
- locate each unit’s XML file  
- display course information in the admin UI  


To make the config example concrete, here is a typical instructor solution repository:


---

Next:  [Describing the units](./unitxml.md) and examples of unit XML files.