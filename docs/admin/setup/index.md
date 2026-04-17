---
title: Setting Up LLM Grader
parent: Administrator Guide
nav_order: 1
has_children: true
---

# Overview 

LLM grader  has key two components:

- A Flask-based web app for the portal where students will see questions, input answers, and receive grades
- A **course package** which is simply an archived set of XML files with the course information 

The Flask web app is realized as a python package which also includes various utilities to assist in the creation of the course material.
