from __future__ import annotations

import base64
import calendar
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

# A Runner takes the argument vector *after* `gh` and returns stdout. The default
# shells out; tests inject a fake so the boundary (the `gh` process) is the only
# thing mocked.
Runner = Callable[[list[str]], str]


class GitHubError(RuntimeError):
    pass


def _gh(argv: list[str]) -> str:
    proc = subprocess.run(["gh", *argv], capture_output=True, text=True)
    if proc.returncode != 0:
        raise GitHubError(f"gh {' '.join(argv)} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _mint_app_jwt(app_id: str, private_key_path: str | Path) -> str:
    # Core stays dependency-free (see pyproject.toml), so this shells out to
    # `openssl` for the RS256 signature rather than pulling in PyJWT/cryptography
    # -- the same "shell out, don't import a client library" choice _gh already
    # makes for the GitHub API itself.
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    # iat backdated 60s: a JWT "issued" at the exact current second can be
    # rejected as premature if this clock is even slightly ahead of GitHub's.
    payload = {"iat": now - 60, "exp": now + 540, "iss": app_id}
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode())
    )
    proc = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", str(private_key_path)],
        input=signing_input.encode(),
        capture_output=True,
    )
    if proc.returncode != 0:
        raise GitHubError(f"failed to sign GitHub App JWT: {proc.stderr.decode().strip()}")
    return signing_input + "." + _b64url(proc.stdout)


def _mint_installation_token(
    app_id: str, installation_id: str, private_key_path: str | Path
) -> tuple[str, str]:
    jwt = _mint_app_jwt(app_id, private_key_path)
    req = urllib.request.Request(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        method="POST",
        headers={"Authorization": f"Bearer {jwt}", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:  # noqa: S310 -- fixed https:// github API URL
            obj = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise GitHubError(f"failed to mint installation token ({exc.code}): {detail}") from exc
    return obj["token"], obj["expires_at"]


def github_app_token(app_id: str, installation_id: str, private_key_path: str | Path) -> str:
    # For callers that need a raw token string rather than a Runner -- e.g. to
    # set GH_TOKEN in a spawned subprocess's own environment (a headless
    # `claude -p` worker running its own `gh` commands), which can't go
    # through the Runner seam since it isn't Python code we control.
    token, _expires_at = _mint_installation_token(app_id, installation_id, private_key_path)
    return token


def github_app_runner(
    app_id: str,
    installation_id: str,
    private_key_path: str | Path,
    *,
    refresh_margin: float = 60.0,
) -> Runner:
    # Installation tokens last ~1h; caching avoids minting one per `gh` call
    # (each mint is a JWT sign + a real API round-trip). refresh_margin mints a
    # fresh token slightly before the cached one actually expires, so a run
    # spanning the boundary never hands `gh` a token that dies mid-call.
    cache: dict[str, str | float] = {"token": "", "expires_at": 0.0}

    def run(argv: list[str]) -> str:
        if time.time() >= cache["expires_at"] - refresh_margin:
            token, expires_at = _mint_installation_token(app_id, installation_id, private_key_path)
            cache["token"] = token
            cache["expires_at"] = calendar.timegm(time.strptime(expires_at, "%Y-%m-%dT%H:%M:%SZ"))
        env = {**os.environ, "GH_TOKEN": str(cache["token"])}
        proc = subprocess.run(["gh", *argv], capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            raise GitHubError(
                f"gh {' '.join(argv)} failed ({proc.returncode}): {proc.stderr.strip()}"
            )
        return proc.stdout

    return run


class CIStatus(StrEnum):
    NONE = "none"
    PENDING = "pending"
    SUCCESS = "success"
    FAILURE = "failure"


_FAILURE_CONCLUSIONS = {
    "FAILURE",
    "ERROR",
    "CANCELLED",
    "TIMED_OUT",
    "ACTION_REQUIRED",
    "STARTUP_FAILURE",
}


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    url: str
    labels: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str


class GitHub:
    def __init__(self, repo: str | None = None, *, runner: Runner = _gh) -> None:
        self.repo = repo
        self._run = runner

    def _argv(self, argv: list[str]) -> list[str]:
        return [*argv, "--repo", self.repo] if self.repo else argv

    def list_issues(
        self,
        *,
        labels: list[str] | None = None,
        state: str = "open",
        limit: int = 30,
    ) -> list[Issue]:
        argv = [
            "issue",
            "list",
            "--state",
            state,
            "--limit",
            str(limit),
            "--json",
            "number,title,body,labels,url",
        ]
        for label in labels or []:
            argv += ["--label", label]
        raw = json.loads(self._run(self._argv(argv)))
        return [
            Issue(
                number=obj["number"],
                title=obj["title"],
                body=obj.get("body", "") or "",
                url=obj["url"],
                labels=[lbl["name"] for lbl in obj.get("labels", [])],
            )
            for obj in raw
        ]

    def open_pr(
        self,
        *,
        title: str,
        body: str,
        base: str,
        head: str,
        draft: bool = False,
    ) -> PullRequest:
        argv = ["pr", "create", "--title", title, "--body", body, "--base", base, "--head", head]
        if draft:
            argv.append("--draft")
        url = self._run(self._argv(argv)).strip().splitlines()[-1]
        return PullRequest(number=_pr_number(url), url=url)

    def pr_status(self, number: int) -> CIStatus:
        argv = ["pr", "view", str(number), "--json", "statusCheckRollup"]
        rollup = json.loads(self._run(self._argv(argv))).get("statusCheckRollup") or []
        return _rollup_status(rollup)

    def create_issue(self, *, title: str, body: str) -> Issue:
        argv = ["issue", "create", "--title", title, "--body", body]
        url = self._run(self._argv(argv)).strip().splitlines()[-1]
        return Issue(number=_issue_number(url), title=title, body=body, url=url)

    def add_labels(self, number: int, labels: list[str]) -> None:
        argv = ["issue", "edit", str(number)]
        for label in labels:
            argv += ["--add-label", label]
        self._run(self._argv(argv))


def _pr_number(url: str) -> int:
    return int(url.rstrip("/").rsplit("/", 1)[-1])


def _issue_number(url: str) -> int:
    return int(url.rstrip("/").rsplit("/", 1)[-1])


def _rollup_status(rollup: list[dict[str, str]]) -> CIStatus:
    if not rollup:
        return CIStatus.NONE
    saw_pending = False
    for check in rollup:
        # CheckRun carries status/conclusion; StatusContext carries state
        # (both "FAILURE" and "ERROR" states mean the check failed).
        state = check.get("state")
        if state in _FAILURE_CONCLUSIONS or check.get("conclusion") in _FAILURE_CONCLUSIONS:
            return CIStatus.FAILURE
        completed = check.get("status") == "COMPLETED" or state in {"SUCCESS", "FAILURE", "ERROR"}
        if not completed:
            saw_pending = True
    return CIStatus.PENDING if saw_pending else CIStatus.SUCCESS
