from llmgrader.app import create_app

import os
import argparse


questions_root = os.path.join(os.getcwd(), "questions")
scratch_dir = os.path.join(os.getcwd(), "scratch")

app = create_app(
    questions_root=questions_root, 
    scratch_dir=scratch_dir)

if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--questions_repo", type=str, default=None,\
                        help="Git repo URL for questions (if not local)")
    args = parser.parse_args()
    
    # Run the app
    # Note: use_reloader=False to avoid double initialization of Grader
    app.run(debug=True, use_reloader=False) 