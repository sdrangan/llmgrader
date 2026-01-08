# Architecture Overview

GraderChat is structured as a Python package with a Flask interface.

## Key Components

### Application Factory
graderchat/app.py defines create_app(), which initializes the Flask app and registers blueprints.

### Routes
graderchat/routes/ contains modular route handlers.

### Services
graderchat/services/ will contain the OpenAI client, grading logic, and prompt builders.

### Templates and Static Files
graderchat/templates/ contains Jinja2 templates.
graderchat/static/ contains CSS and JavaScript assets.
