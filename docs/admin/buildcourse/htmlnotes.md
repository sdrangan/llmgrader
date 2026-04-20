---
title:  Creating HTML Files
parent: Building a Course Package
nav_order: 4
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
create_qfile --input <unit_xml_file> [--config <llmgrader_config.xml>] [--soln] [--pdf]
```

Where:

- `<unit_xml_file>` is the path to a unit XML file (e.g., `unit1/basic_logic.xml`)
- `--config` (optional) points to `llmgrader_config.xml` so `/pkg_assets/...` URLs can be rewritten for standalone HTML/PDF output
- `--soln` (optional) generates a **solution** version
- `--pdf` (optional) also generates a **PDF** from the HTML

If the `--soln` option is not selected, the program will generate
a **student-facing** HTML (no solutions shown). For example,

```bash
create_qfile --input unit1/calculus.xml
```
produces an HTML file:

```bash
unit1/calculus.html
```

If the `--pdf` option is selected, the output will be  `unit1/calculus.pdf` along
with the HTML file.  Similarly, if the `--soln` option is selected:

```bash
create_qfile --input unit1/basic_logic.xml --soln [--pdf]
```

the program will generate `unit1/calculus_soln.html` and/or 
`unit1/calculus_soln.pdf` which contains the questions and solutions.
This version is intended for instructors, TA(s), or students after they have
submitted their solution.

## Asset URLs in Standalone HTML

When unit XML references packaged assets such as:

```html
<img src="/pkg_assets/unit2_images/func.png" alt="Gradient descent figure">
```

the web application serves that URL from the uploaded solution package. For
standalone HTML or PDF output, `create_qfile` rewrites `/pkg_assets/...` to a
local file path using the asset mappings in `llmgrader_config.xml`.

You can pass the config explicitly:

```bash
create_qfile --input unit2/python.xml --config ../llmgrader_config.xml
```

If `--config` is omitted, `create_qfile` searches parent directories of the
input XML file for `llmgrader_config.xml` automatically.

---

Next:  Go to [uploading the solution package](./dupload.md)
