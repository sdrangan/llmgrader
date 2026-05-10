import base64
import json
import shutil
from pathlib import Path


if Path("/autograder").exists():
    SUBMISSION_DIR = Path("/autograder/submission")
    RESULTS_PATH = Path("/autograder/results/results.json")
else:
    SUBMISSION_DIR = Path.cwd() / "submission"
    RESULTS_PATH = Path.cwd() / "results" / "results.json"

SIGNING_KEY_PATH = Path(__file__).parent / "signing_public_key.txt"


def write_result(payload: dict) -> None:
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULTS_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f)


def write_fallback(message: str = "results.json missing or unreadable") -> None:
    write_result({"score": 0, "output": message})


def _verify_signature(data: bytes, signature_b64: str, public_key_b64: str) -> bool:
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        public_pem = base64.b64decode(public_key_b64)
        public_key = load_pem_public_key(public_pem)
        public_key.verify(base64.b64decode(signature_b64), data)
        return True
    except Exception:
        return False


def main() -> None:
    source_path = SUBMISSION_DIR / "results.json"
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)

    if SIGNING_KEY_PATH.exists():
        public_key_b64 = SIGNING_KEY_PATH.read_text().strip()
        signature_path = SUBMISSION_DIR / "signature.txt"

        if not signature_path.exists():
            write_fallback(
                "This submission requires a valid signature. "
                "Please re-download your submission from the LLM Grader portal and upload that file."
            )
            return

        try:
            results_bytes = source_path.read_bytes()
        except OSError:
            write_fallback()
            return

        signature_b64 = signature_path.read_text().strip()
        if not _verify_signature(results_bytes, signature_b64, public_key_b64):
            write_fallback(
                "Submission signature verification failed. "
                "The file may have been modified. "
                "Please re-download your submission from the LLM Grader portal and upload that file."
            )
            return

        shutil.copyfile(source_path, RESULTS_PATH)
        return

    try:
        with source_path.open("rb"):
            pass
        shutil.copyfile(source_path, RESULTS_PATH)
    except OSError:
        write_fallback()


if __name__ == "__main__":
    main()
