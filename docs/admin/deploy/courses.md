---
title: Serving Several Courses
parent: Deploying the App
nav_order: 3
has_children: false
---

# Serving Several Courses from One Portal

One deployment can serve any number of courses. Each has its own units, its own
students' saved work and its own submissions; they share the database, the
administrator list, the OpenAI key settings and the Gradescope signing key.

That means one Render service, one disk and one set of credentials per
*instructor*, rather than per course.

---

## How a Course Is Identified

Every course has a **course id**: a short, machine-facing name such as
`hwdesign`, distinct from the display name students see.

The id comes from the package's
[`<course_id>`](../buildcourse/pkgconfig.md#the-course-id). It appears in the
course's web address, names its directory in the portal's storage, and is
recorded against every submission it grades.

**The id is assigned once, when the course is first created, and read back from
then on.** Editing `<name>` or `<title>` in a later package changes the display
name and leaves the id alone, so a corrected package always lands on the same
course. This is why authoring `<course_id>` is recommended: without one the
portal derives an id from your display text, and a derived id is only as stable
as the words it was derived from.

---

## The Manage Courses Dialog

Navigate to the admin view with **File → Switch View → Admin**, then
**File → Manage Courses…**. You must be
[signed in as an administrator](../setup/oauth.md).

### Adding a course

**Add Course** takes a package ZIP and creates a course from it. You are not
asked to type a name: the package already carries `<course_id>`, `<name>` and
the term, and the portal reads its identity from there.

If the package's id already belongs to a registered course, the upload is
refused and the dialog names that course — the package you are holding is an
update to an existing course, not a new one.

### Updating a course

**Load Course Package** replaces the units of a course you choose from the
list. Use it whenever you fix a typo, add a unit or start a new term on the
same course.

The portal checks that the package's id matches the course you selected, and
**refuses the upload if it does not**, naming both courses. This matters more
than it looks: `create_soln_pkg` names every archive `soln_package.zip`, so
once you run two courses you have two identically named files, and picking the
wrong one is easy. Without the check you would replace one course's content
with another's.

If you do get a refusal, you have picked the wrong file, the wrong target
course, or you meant to create a new course rather than update one. The portal
will not rename a course to match a package: the id is recorded in the
database and in your students' browsers, and changing it is not something an
upload should do quietly.

### Deleting a course

**Delete Course** archives the course: it stops being served, but its package
and its submissions are kept. Grades are the one thing on the disk that cannot
be rebuilt, so nothing here removes them. The portal also refuses to archive
the last remaining course.

---

## A Failed Upload Leaves the Course Running

An uploaded archive is extracted to a temporary directory and parsed there
first. The live course is replaced only once the new package is known to load.

So a corrupt ZIP, a missing file or a unit that fails schema validation is
reported as an error and **the course keeps serving what it served before**.
You can fix the package and upload again without students noticing anything.

---

## Course Addresses

Each course is served under its id:

```
https://your-class.onrender.com/c/hwdesign/
https://your-class.onrender.com/c/intro_prob/
```

The portal's bare address forwards to the course the visitor last used, or to
the default course for a first-time visitor. Old bookmarks made before a second
course existed keep working through that redirect.

Students move between courses with **File → Select Course…**; see
[the student guide](../../student/grade.md#selecting-a-course).

---

## Gradescope

Each Gradescope assignment can be told which course it grades, so a student who
uploads the right file to the wrong assignment is caught rather than scored.
See [the Gradescope setup guide](../gradescope/gradescope.md).

---

## Upgrading a Portal That Already Served One Course

A portal deployed before multi-course support keeps its course, its units and
its submissions across the upgrade with no administrator action. The existing
package is moved into the new layout on the first boot and registered as the
default course.

The one thing worth doing **before** that deploy is choosing the id it will be
registered under — see
the "Naming your course on an upgrade" section of
[Deploying on Render](./render.md).
Afterwards, add `<course_id>` to the package itself so the id no longer depends
on an environment variable.
