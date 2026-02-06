---
title:  Creating HTML Files
parent: Building a Course Package
nav_order: 3
has_children: false
---

# Creating HTML and PDF Problems and Solution Files

## Overview

After you have [created the XML file for a unit](./unitxml.md), you can generate 
an HTML and PDF versions of the problems and solutions.  
While the questions will be visible in the LLM grader 
portal, you may also wish to distribute questions and/or solutions in separte documents.
Creating these versions will also let you verify the formating of the problems,
before you upload them to the LLM grader.  

## 🧾 Command Overview

The HTML and PDF files are generated from the unit XML using the `create_qfile` command:

```bash
create_qfile <unit_xml_file> [--soln] [--pdf]
```

Where:

- `<unit_xml_file>` is the path to a unit XML file (e.g., `unit1/basic_logic.xml`)
- `--soln` (optional) generates a **solution** version
- `--pdf` (optional) also generates a **PDF** from the HTML

If the `--soln` option is not selected, the program will generate
a **student-facing** HTML (no solutions shown). For example,

```bash
create_qfile unit1/basic_logic.xml
```
produces an HTML file:

```bash
unit1/basic_logic.html
```

If the `--pdf` option is selected, the output will be  `unit1/basic_logic.pdf` along
with the HTML file.  Similarly, if the `--soln` option is selected:

```bash
create_qfile --soln [--pdf] unit1/basic_logic.xml
```

the program will generate `unit1/basic_logic_soln.html` and/or 
`unit1/basic_logic_soln.pdf` which contains the questions and solutions.
This version is intended for instructors, TA(s), or students after they have
submitted their solution.

---

Next:  Go to [deploying the autograder on Render](./deploy.md)
