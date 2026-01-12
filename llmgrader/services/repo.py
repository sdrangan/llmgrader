# repo.py:  Methods for downloading the questions repository

import os

import subprocess

def load_from_repo(repo_url: str, target_dir: str = "solutions"):
    """
    Clone or update the private solutions repository.

    repo_url: URL of the private GitHub repo (SSH or HTTPS)
    target_dir: local folder where the repo should live
    """
    sol_path = os.path.abspath(target_dir)

    # If the directory doesn't exist, clone fresh
    if not os.path.exists(sol_path):
        print(f"[llmgrader] Cloning solutions repo into {sol_path}...")
        subprocess.run(
            ["git", "clone", repo_url, sol_path],
            check=True
        )
        print("[llmgrader] Clone complete.")
        return

    # If it exists, pull updates
    print(f"[llmgrader] Pulling latest updates in {sol_path}...")
    subprocess.run(
        ["git", "pull"],
        cwd=sol_path,
        check=True
    )
    print("[llmgrader] Pull complete.")
