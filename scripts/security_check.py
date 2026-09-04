"""Fail CI when high-confidence secrets or committed environment files are found."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SECRET_PATTERNS = (
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={PROJECT_ROOT.as_posix()}", "ls-files", "-z"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
    )
    return [
        PROJECT_ROOT / item.decode("utf-8")
        for item in result.stdout.split(b"\0")
        if item
    ]


def main() -> int:
    findings: list[str] = []
    for path in tracked_files():
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        filename = path.name.lower()
        if filename == ".env" or (
            filename.startswith(".env.") and filename != ".env.example"
        ):
            findings.append(f"tracked environment file: {relative}")
            continue
        try:
            if path.stat().st_size > 2 * 1024 * 1024:
                continue
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(content):
                findings.append(f"possible {label}: {relative}")
    if findings:
        print("Security check failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("Security check passed: no tracked environment files or high-confidence secrets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
