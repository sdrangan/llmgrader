from llmgrader.app import create_app

import os
import argparse

# Default parameters
qrepo = None
questions_root = os.path.join(os.getcwd(), "questions")
scratch_dir = os.path.join(os.getcwd(), "scratch")

if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--qrepo", type=str, default=None,
                        help="Git repo URL for questions (if not local)")
    args = parser.parse_args()
    qrepo = args.qrepo

    # Create the Flask app
    app = create_app(
        questions_root=questions_root,
        scratch_dir=scratch_dir,
        qrepo=qrepo
    )

    # Run locally only
    app.run(debug=True, use_reloader=False)

else:
    # Render imports this branch
    app = create_app(
        questions_root=questions_root,
        scratch_dir=scratch_dir,
        qrepo=qrepo
    )