from flask import Flask
from graderchat.routes.api import APIController
from graderchat.services.llm_client import LLMClient
from graderchat.services.grader import Grader

def create_app(questions_root="questions"):
    app = Flask(__name__)

    llm = LLMClient()
    grader = Grader(questions_root=questions_root)
    controller = APIController(llm, grader)
    controller.register(app)

    return app