from graderchat.app import create_app

import os
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--no_qtext_reload", default=False, action="store_true",
                    help="Disable question text reloading")
args = parser.parse_args()

# Overwrite the default if specified
args.no_qtext_reload = True

questions_root = os.path.join(os.getcwd(), "questions")
scratch_dir = os.path.join(os.getcwd(), "scratch")

app = create_app(
    questions_root=questions_root, 
    scratch_dir=scratch_dir,
    qtext_reload=not args.no_qtext_reload)

if __name__ == "__main__":
    
    # Run the app
    # Note: use_reloader=False to avoid double initialization of Grader
    app.run(debug=True, use_reloader=False) 