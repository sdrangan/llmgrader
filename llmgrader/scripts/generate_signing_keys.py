#!/usr/bin/env python3
"""Generate an Ed25519 key pair for submission signing."""

import sys
from llmgrader.services.signing import generate_key_pair, private_key_from_env, public_key_from_env, verify_signature, sign_data
import argparse


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Ed25519 signing keys for LLM Grader submission signing."
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify that LLMGRADER_PRIVATE_KEY and LLMGRADER_PUBLIC_KEY form a valid key pair.",
    )
    args = parser.parse_args()

    if args.verify:
        private_key_b64 = private_key_from_env()
        public_key_b64 = public_key_from_env()

        if not private_key_b64:
            print("ERROR: LLMGRADER_PRIVATE_KEY is not set.")
            return 1
        if not public_key_b64:
            print("ERROR: LLMGRADER_PUBLIC_KEY is not set.")
            return 1

        test_data = b"llmgrader-key-verification"
        try:
            signature = sign_data(test_data, private_key_b64)
            valid = verify_signature(test_data, signature, public_key_b64)
        except Exception as exc:
            print(f"ERROR: Key verification failed: {exc}")
            return 1

        if valid:
            print("OK: Keys are set and form a valid pair.")
            return 0
        else:
            print("ERROR: Keys are set but do not form a valid pair.")
            return 1

    private_key_b64, public_key_b64 = generate_key_pair()

    print("Copy these values into your environment variables:\n")
    print(f"LLMGRADER_PRIVATE_KEY={private_key_b64}")
    print(f"LLMGRADER_PUBLIC_KEY={public_key_b64}")
    print()
    print("Set LLMGRADER_PRIVATE_KEY on Render (server) and both keys on your local machine.")
    print("Keep the private key secret — do not commit it to version control.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
