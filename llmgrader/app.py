from flask import Flask
from llmgrader.routes.api import APIController
from llmgrader.services.grader import Grader

def create_app(
        questions_root : str ="questions", 
        scratch_dir : str ="scratch",
        qrepo : str | None = None,
        local_repo : str | None = None) -> Flask:
    """
    Creates and configures the Flask application.
    
    Parameters
    ----------
    questions_root: str
        Path to the root directory containing question units.
    scratch_dir: str
        Path to the scratch directory for temporary files.
    qrepo: str | None
        Git repository URL for questions (if not local).
    local_repo: str | None
        Local repository path for questions (if testing locally).
    """
    app = Flask(__name__)

    grader = Grader(
        questions_root=questions_root, 
        scratch_dir=scratch_dir,
        remote_repo=qrepo,
        local_repo=local_repo)
    controller = APIController(grader)
    controller.register(app)

    return app