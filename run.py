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
    parser.add_argument("--local_repo", type=str, default=None,
                        help="Local repository path for questions (if testing locally)")
    args = parser.parse_args()
    qrepo = args.qrepo
    local_repo = args.local_repo

    # Create the Flask app
    app = create_app(
        questions_root=questions_root,
        scratch_dir=scratch_dir,
        qrepo=qrepo,
        local_repo=local_repo
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