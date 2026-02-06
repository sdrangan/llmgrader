---
title: Building an Autograded Assignment
parent: Gradescope Integration
nav_order: 1
has_children: false
---

# Building an Auto
## Building the Gradescope Autograder

To build the Gradescope autograder:

- Navigate to the location for unit XML file, say `unit1_basic_logic.xml`.
- Activate the virtual environment with `llmgrader` in a terminal
- Run

```bash
build_autograder --schema unit1_basic_logic.xml
```

or whatever your unit name is.

- This command creates a file `autograder.zip`

## Creating the Gradescope assignment

Now go to Gradescope:

- Select your course and go to **Assignments**
- Select **Create Assignment** (bottom right)
- Select **Programming Assignment** and fill in the standard information such as name, due data
    - For **Autograder Points** select the total number of points for the unit.
    This value will be sum of all the points in the units for the required questions
    - Uncheck **manual grading** since we will be completely grading the assignment automatically
- On the **Configure autograder** page:
   - For **autograder configuration** select **zip file upload**
   - Select the autograder file, `autograder.zip` created in the previous step
   - Select **Update Autograder**.  
   - The Autograder will now take a minute or two to build
   - If you have a JSON file submission, you can test it now.  Otherwise, go to the next section to create a JSON file to test the autograder.

Your assignment is now ready for students to start uploading solutions.
In general, you want to be able to have the students see the grades as soon as they submit.  To enable this setting:

- On gradescope, select **Assignments** and then select the assignment you created
- On the left panel, select **Review Grades**
- This will give you a page where you can see all the student submissions. Even though there will initially be
no submissions, on the bottom right, select **Publish Grades**.  This way students can see the grades as soon as the students submit


## Testing the Autograder

To test the autograder:

- Go back to the AI grader portal on render
- Answer some or all of the questions that are required for the unit
- Go the **Dashboard** and then select **Download sumbission**.  This selection will create a JSON submission
- Go back to the Assignment in Gradescope
- Select **Configure Autograder**.  Select **Test autograder**.  Then, upload the JSON submission
