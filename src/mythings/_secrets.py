from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass

# Build-tooling secret tripwire, not a contract: a cheap regex scan for common
# credential shapes in a diff, a dev-ledger/ledger entry, or a PR body -- before
# it lands in git history or gets posted publicly. Invoked as
# `python -m mythings._secrets`. Deliberately not exported from the package.

_PATTERNS: dict[str, re.Pattern[str]] = {
    "aws_access_key_id": re.compile(r"AKIA[0-9A-Z]{16}"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    "slack_token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    "private_key_block": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"
    ),
    # Catches `api_key = "..."` / `password: '...'` style assignments generic
    # enough to not be one of the named formats above. Requires quotes and a
    # 12+ char value so it doesn't fire on `password = input(...)` or similar.
    "generic_assignment": re.compile(
        r"(?i)\b(api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*"
        r"""['"][A-Za-z0-9/_+=\-]{12,}['"]"""
    ),
}


@dataclass(frozen=True)
class Finding:
    pattern: str
    line: int
    snippet: str


def scan_text(text: str) -> list[Finding]:
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for name, pattern in _PATTERNS.items():
            match = pattern.search(line)
            if match:
                findings.append(Finding(pattern=name, line=lineno, snippet=match.group(0)[:40]))
    return findings


def added_lines(diff_text: str) -> str:
    # Scan only additions: a secret already in history that a diff merely
    # shows as context shouldn't re-trigger the gate on every later commit.
    return "\n".join(
        line[1:]
        for line in diff_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


# This module's own test suite plants realistic-looking fake secrets on
# purpose, to prove the patterns actually match -- excluded from the diff scan
# so this file's own tests don't block every PR that touches it. Each repo
# that copies this scanner has its own test paths, so this exclusion only
# ever matches here, in my-things-core.
_EXCLUDED_PATHS = ("tests/test__secrets.py",)


def _run_git_diff(argv: list[str]) -> str:
    pathspec = [".", *(f":(exclude){p}" for p in _EXCLUDED_PATHS)]
    proc = subprocess.run(
        ["git", "diff", "-U0", *argv, "--", *pathspec], capture_output=True, text=True, check=True
    )
    return proc.stdout


def _report(findings: list[Finding]) -> int:
    if not findings:
        print("secret-scan: clean")
        return 0
    print(f"secret-scan: {len(findings)} possible secret(s) found:")
    for f in findings:
        print(f"  line {f.line}: {f.pattern} -- {f.snippet!r}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mythings._secrets",
        description="Cheap regex tripwire for common secret formats in a diff or text blob.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("scan-staged", help="scan added lines in the staged diff (git diff --cached)")

    scan_range = sub.add_parser("scan-diff-range", help="scan added lines between two refs/shas")
    scan_range.add_argument("range", help="e.g. abc123...def456 or origin/main...HEAD")

    sub.add_parser("scan-text", help="scan text from stdin (e.g. a PR title + body)")

    args = parser.parse_args(argv)

    if args.cmd == "scan-staged":
        text = added_lines(_run_git_diff(["--cached"]))
    elif args.cmd == "scan-diff-range":
        text = added_lines(_run_git_diff([args.range]))
    else:
        text = sys.stdin.read()

    return _report(scan_text(text))


if __name__ == "__main__":
    raise SystemExit(main())
