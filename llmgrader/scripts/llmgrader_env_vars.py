#!/usr/bin/env python3

import argparse
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class EnvVarSpec:
    name: str
    sensitive: bool = False


ENV_VARS = [
    EnvVarSpec("LLMGRADER_SECRET_KEY", sensitive=True),
    EnvVarSpec("LLMGRADER_GOOGLE_CLIENT_ID"),
    EnvVarSpec("LLMGRADER_GOOGLE_CLIENT_SECRET", sensitive=True),
    EnvVarSpec("LLMGRADER_GOOGLE_REDIRECT_URI"),
    EnvVarSpec("LLMGRADER_INITIAL_ADMIN_EMAIL"),
    EnvVarSpec("LLMGRADER_AUTH_MODE"),
    EnvVarSpec("LLMGRADER_STORAGE_PATH"),
]


def _format_value(value: str, *, sensitive: bool, show_secrets: bool) -> str:
    if not value:
        return "MISSING"
    if not sensitive or show_secrets:
        return value
    if len(value) <= 8:
        return "[set]"
    return f"{value[:4]}...{value[-4:]}"


def build_report(*, show_secrets: bool = False) -> str:
    lines = []
    for spec in ENV_VARS:
        raw_value = (os.environ.get(spec.name) or "").strip()
        formatted_value = _format_value(
            raw_value,
            sensitive=spec.sensitive,
            show_secrets=show_secrets,
        )
        lines.append(f"{spec.name}={formatted_value}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Display llmgrader environment variable status."
    )
    parser.add_argument(
        "--show-secrets",
        action="store_true",
        help="Print full secret values instead of masking them.",
    )
    args = parser.parse_args()

    print(build_report(show_secrets=args.show_secrets))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())