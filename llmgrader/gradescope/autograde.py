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

# Written by build_autograder when the course is known.  Absent, there is
# nothing to compare a submission against and the check does not run.
EXPECTED_COURSE_PATH = Path(__file__).parent / "expected_course.txt"


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


def _submitted_course_id(results_bytes: bytes) -> str:
    """The submission's ``course_id``, or "" when it does not carry one.

    Never raises: results.json has already been signature-verified by the time
    this runs, and a parse problem here must not turn a valid submission into
    a zero.
    """
    try:
        payload = json.loads(results_bytes.decode("utf-8"))
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("course_id") or "").strip()


def check_course(results_bytes: bytes) -> str | None:
    """Reject a submission built against a different course, or return None.

    A student with two courses on one portal can upload the wrong file and, in
    a world where every download is called submission.zip, get a
    plausible-looking score against questions they never answered.

    **Warn, then fail.** A submission with no ``course_id`` at all is accepted
    with a warning for one release: submissions downloaded before that field
    existed are still in flight, and failing them would punish students for a
    server-side change. Requiring the field comes in the release after this
    one.
    """
    if not EXPECTED_COURSE_PATH.exists():
        return None

    expected = EXPECTED_COURSE_PATH.read_text(encoding="utf-8").strip()
    if not expected:
        return None

    submitted = _submitted_course_id(results_bytes)
    if not submitted:
        print(
            "Warning: this submission does not name a course. It was downloaded "
            "before submissions carried one, and is being accepted for now.",
            flush=True,
        )
        return None

    if submitted != expected:
        return (
            f"This submission is for course '{submitted}', but this assignment grades "
            f"'{expected}'. It looks like the wrong submission.zip was uploaded. "
            "Download the submission for this course from the LLM Grader portal and "
            "upload that file."
        )
    return None


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

        wrong_course = check_course(results_bytes)
        if wrong_course:
            write_fallback(wrong_course)
            return

        shutil.copyfile(source_path, RESULTS_PATH)
        return

    try:
        results_bytes = source_path.read_bytes()
    except OSError:
        write_fallback()
        return

    wrong_course = check_course(results_bytes)
    if wrong_course:
        write_fallback(wrong_course)
        return

    shutil.copyfile(source_path, RESULTS_PATH)


if __name__ == "__main__":
    main()
