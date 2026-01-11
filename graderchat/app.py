from flask import Flask
from graderchat.routes.api import APIController
from graderchat.services.grader import Grader

def create_app(
        questions_root : str ="questions", 
        scratch_dir : str ="scratch", 
        qtext_reload: bool =True):
    """
    Creates and configures the Flask application.
    
    Parameters
    ----------
    questions_root: str
        Path to the root directory containing question units.
    scratch_dir: str
        Path to the scratch directory for temporary files.
    qtext_reload: bool
        Whether to enable question text reloading.
        This will save time as each reload requires
        reading/parsing LaTeX files.
    """
    app = Flask(__name__)

    grader = Grader(
        questions_root=questions_root, 
        scratch_dir=scratch_dir, 
        qtext_reload=qtext_reload)
    controller = APIController(grader)
    controller.register(app)

    return app