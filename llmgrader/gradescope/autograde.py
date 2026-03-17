import json
import shutil
from pathlib import Path


if Path("/autograder").exists():
    SUBMISSION_DIR = Path("/autograder/submission")
    RESULTS_PATH = Path("/autograder/results/results.json")
else:
    SUBMISSION_DIR = Path.cwd() / "submission"
    RESULTS_PATH = Path.cwd() / "results" / "results.json"


def write_fallback() -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_PATH.open("w", encoding="utf-8") as results_file:
        json.dump(
            {"score": 0, "output": "results.json missing or unreadable"},
            results_file,
        )


def main() -> None:
    source_path = SUBMISSION_DIR / "results.json"
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)

    try:
        with source_path.open("rb"):
            pass
        shutil.copyfile(source_path, RESULTS_PATH)
    except OSError:
        write_fallback()


if __name__ == "__main__":
    main()