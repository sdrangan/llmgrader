from llmgrader.app import create_app

import os
import argparse

# Default parameters
qrepo = None
questions_root = os.path.join(os.getcwd(), "questions")
scratch_dir = os.path.join(os.getcwd(), "scratch")


# Called in command line (not called when running in render.com)
if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--qrepo", type=str, default=None,\
                        help="Git repo URL for questions (if not local)")
    args = parser.parse_args()
    qrepo = args.qrepo


# Create the Flask app
app = create_app(
    questions_root=questions_root, 
    scratch_dir=scratch_dir,
    qrepo=qrepo)
    
# Run the app
# Note: use_reloader=False to avoid double initialization of Grader
app.run(debug=True, use_reloader=False) 