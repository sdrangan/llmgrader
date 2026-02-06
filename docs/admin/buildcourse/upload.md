---
title:  Uploading the Package
parent: Building a Course Package
nav_order: 4
has_children: false
---

# Uploading a Solution Package 

If the service is running on Render or on your local machine,
we next show how to create a solution package ZIP file and upload it to the LLM grader’s admin interface.
The upload process installs the course configuration and all unit XML files into the grader’s persistent storage.

---

## 📦 1. Create the Solution Package

Once the [package configuration XML file](./pkgconfig.md) and the [unit XML files](./unitxml.md)
have been written, you can create the package.

* Activate the virtual environment with the `llmgrader` python package.
* Run 

```
python create_soln_pkg.py [--config llmgrader_config.xml]
```

This script produces:

```
soln_package.zip
```

The ZIP contains the files at the root level (no nested folder).

---

## 🧪 2. Validate the Package (Optional but Recommended)

Before uploading, you may want to inspect the ZIP:

- Ensure `llmgrader_config.xml` is present  
- Ensure all `<destination>` files listed in the config are present  
- Ensure filenames match exactly (case‑sensitive on Linux)  

If anything is missing, the admin upload page will reject the package with a clear error message.

---

## 🌐 3. Upload via the Admin Interface

Navigate to the admin upload page:

```
https://<your-app>.onrender.com/admin/upload
```

or, in local development:

```
http://localhost:5000/admin/upload
```

Steps:

1. Click **Choose File**  
2. Select `soln_package.zip`  
3. Click **Upload Package**

The grader will:

- delete the previous solution package directory  
- extract the new ZIP  
- load `llmgrader_config.xml`  
- validate and load all units  
- display a confirmation message

If any XML is malformed or missing, the upload will fail with a descriptive error.

---

## 🗂️ 4. What Happens After Upload

After a successful upload:

- The package is extracted into the grader’s persistent storage  
- Units are reloaded immediately  
- The admin UI displays the course name and number of units  

This means you can update course content at any time without redeploying the application.



