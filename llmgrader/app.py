from flask import Flask
from llmgrader.routes.api import APIController
from llmgrader.services.course_registry import CourseRegistry
import os

def create_app(
        scratch_dir : str ="scratch",
        soln_pkg : str | None = None) -> Flask:
    """
    Creates and configures the Flask application.

    Parameters
    ----------
    scratch_dir: str
        Path to the scratch directory for temporary files.  Used only when
        *soln_pkg* is given; a registered course keeps its scratch under
        <storage>/courses/<id>/scratch/pid-<pid>, per course so one course
        cannot clear another's and per process so one gunicorn worker cannot
        clear another's (plans/multicourse.md, phase 2).
    soln_pkg: str | None
        Path to solution package (if testing locally).  Given, that package is
        served as the sole course and no registry file is written -- which is
        what `python run.py --soln_pkg ...` has always meant.  Omitted, the
        registry under <storage>/courses/ governs, migrating the pre-registry
        <storage>/soln_pkg layout on first boot.
    """
    app = Flask(__name__)
    app.secret_key = os.environ.get("LLMGRADER_SECRET_KEY", "llmgrader-dev-secret-key")

    registry = CourseRegistry(soln_pkg=soln_pkg, scratch_dir=scratch_dir)
    app.registry = registry

    # The controller holds the registry, not one Grader: which course a
    # request is for comes from its /c/<course_id>/ path (plans/multicourse.md,
    # phase 5).
    controller = APIController(registry)
    app.api_controller = controller
    controller.register(app)

    return app
