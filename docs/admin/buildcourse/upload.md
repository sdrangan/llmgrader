---
title:  Uploading the Package
parent: Building a Course Package
nav_order: 8
has_children: false
---

# Uploading a Solution Package 

If the service is running on Render or on your local machine,
we next show how to create a solution package ZIP file and upload it to the LLM grader’s admin interface.
The upload process installs the course configuration and all unit XML files into the grader’s persistent storage.

---

## Create the Solution Package

Once the [package configuration XML file](./pkgconfig.md) and the [unit XML files](./unitxml.md)
have been written, you can create the package.

* Activate the virtual environment with the `llmgrader` python package.
* Run 

```bash
create_soln_pkg --config llmgrader_config.xml
```

`create_soln_pkg` is a console script installed with the package, so it must be
run with the virtual environment active.  If `--config` is omitted, it looks for
`llmgrader_config.xml` in the current directory.

This script produces:

```
soln_package.zip
```

The ZIP contains the files at the root level (no nested folder).

---

## Validate the Package (Optional but Recommended)

Before uploading, you may want to inspect the ZIP:

- Ensure `llmgrader_config.xml` is present  
- Ensure all `<destination>` files listed in the config are present  
- Ensure filenames match exactly (case‑sensitive on Linux)  

If anything is missing, the admin upload page will reject the package with a clear error message.

---

## Upload via the Admin Interface

Navigate to the admin view with **File->Select View->Admin**.  
You must [login in as an administrator](../setup/oauth.md) for this view to be visible.

Then, select **File->Admin->Load course package...**.

Steps:

1. Choose the **course** to load into
2. Click **Choose File**
3. Select `soln_package.zip`
4. Click **Load**

The grader will:

- check that the package is for the course you chose
- extract the new ZIP to a temporary directory
- load `llmgrader_config.xml`
- validate and load all units
- replace the course's previous package, but only once the new one has loaded  
- display a confirmation message

If any XML is malformed or missing, the upload will fail with a descriptive error.

---

## What Happens After Upload

After a successful upload:

- The package is extracted into the grader’s persistent storage
- Units are reloaded immediately
- The admin UI displays the course name and number of units

This means you can update course content at any time without redeploying the application.

---

## If the Upload Is Refused

The grader refuses an upload rather than half-applying it, and in every case
**the course keeps serving what it served before**.

**"This package is for a different course."**  The package's
[`<course_id>`](./pkgconfig.md#the-course-id) does not match the course you
selected, and the message names both. Because `create_soln_pkg` names every
archive `soln_package.zip`, an instructor running two courses has two
identically named files — this check is what stops one course's content
replacing another's. Either you picked the wrong file, or you picked the wrong
target course, or the package belongs to a course that does not exist yet and
should be created with **Add Course**.

**A validation or extraction error.**  A corrupt ZIP, a missing file listed in
the configuration, or a unit that fails schema validation. The package is
parsed in a temporary directory before anything is replaced, so the error is
reported and the live course is untouched. Fix the package and upload again.

---

## Serving More Than One Course

One portal can host several courses, each with its own units, students' saved
work and submissions. Creating, updating and archiving them is covered in
[Serving several courses from one portal](../deploy/courses.md).



