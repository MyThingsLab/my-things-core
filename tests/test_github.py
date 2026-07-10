import base64
import io
import json
import subprocess
import urllib.error
from pathlib import Path

import pytest

from mythings.github import (
    CIStatus,
    GitHub,
    GitHubError,
    _mint_app_jwt,
    _pr_number,
    _rollup_status,
    github_app_runner,
    github_app_token,
)


class FakeGh:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        return self.reply


def test_list_issues_parses_and_flattens_labels() -> None:
    payload = json.dumps(
        [
            {
                "number": 7,
                "title": "fix parser",
                "body": "it crashes",
                "url": "https://github.com/o/r/issues/7",
                "labels": [{"name": "bug"}, {"name": "p1"}],
            }
        ]
    )
    fake = FakeGh(payload)
    gh = GitHub(runner=fake)

    issues = gh.list_issues(labels=["bug"], limit=5)

    assert len(issues) == 1
    assert issues[0].number == 7
    assert issues[0].labels == ["bug", "p1"]
    argv = fake.calls[0]
    assert argv[:2] == ["issue", "list"]
    assert "--label" in argv and "bug" in argv
    assert "5" in argv


def test_repo_flag_is_appended_when_set() -> None:
    fake = FakeGh("[]")
    GitHub(repo="o/r", runner=fake).list_issues()
    assert fake.calls[0][-2:] == ["--repo", "o/r"]


def test_open_pr_extracts_number_from_url() -> None:
    fake = FakeGh("https://github.com/o/r/pull/42\n")
    pr = GitHub(runner=fake).open_pr(
        title="t", body="b", base="main", head="feature", draft=True
    )
    assert pr.number == 42
    assert "--draft" in fake.calls[0]


def test_gh_error_raises() -> None:
    def boom(argv: list[str]) -> str:
        raise GitHubError("nope")

    with pytest.raises(GitHubError):
        GitHub(runner=boom).list_issues()


def test_pr_number_parsing() -> None:
    assert _pr_number("https://github.com/o/r/pull/99") == 99
    assert _pr_number("https://github.com/o/r/pull/99/") == 99


def test_rollup_status_aggregation() -> None:
    assert _rollup_status([]) is CIStatus.NONE
    assert _rollup_status([{"status": "COMPLETED", "conclusion": "SUCCESS"}]) is CIStatus.SUCCESS
    assert _rollup_status([{"status": "IN_PROGRESS"}]) is CIStatus.PENDING
    assert (
        _rollup_status(
            [
                {"status": "COMPLETED", "conclusion": "SUCCESS"},
                {"status": "COMPLETED", "conclusion": "FAILURE"},
            ]
        )
        is CIStatus.FAILURE
    )
    # A StatusContext uses `state` rather than status/conclusion.
    assert _rollup_status([{"state": "SUCCESS"}]) is CIStatus.SUCCESS
    assert _rollup_status([{"state": "PENDING"}]) is CIStatus.PENDING
    # A failed StatusContext reports either FAILURE or ERROR; both are failures.
    assert _rollup_status([{"state": "FAILURE"}]) is CIStatus.FAILURE
    assert _rollup_status([{"state": "ERROR"}]) is CIStatus.FAILURE
    assert _rollup_status([{"state": "SUCCESS"}, {"state": "ERROR"}]) is CIStatus.FAILURE


def test_pr_status_reads_rollup() -> None:
    fake = FakeGh(json.dumps({"statusCheckRollup": [{"state": "SUCCESS"}]}))
    assert GitHub(runner=fake).pr_status(3) is CIStatus.SUCCESS


def test_create_issue_extracts_number_from_url() -> None:
    fake = FakeGh("https://github.com/o/r/issues/13\n")
    issue = GitHub(runner=fake).create_issue(title="t", body="b")

    assert issue.number == 13
    assert issue.title == "t"
    assert issue.body == "b"
    argv = fake.calls[0]
    assert argv[:2] == ["issue", "create"]
    assert "--title" in argv and "t" in argv
    assert "--body" in argv and "b" in argv


def test_add_labels_sends_one_flag_per_label() -> None:
    fake = FakeGh("")
    GitHub(repo="o/r", runner=fake).add_labels(13, ["my-uni", "my-researcher"])

    argv = fake.calls[0]
    assert argv[:3] == ["issue", "edit", "13"]
    assert argv.count("--add-label") == 2
    assert "my-uni" in argv and "my-researcher" in argv
    assert argv[-2:] == ["--repo", "o/r"]


@pytest.fixture()
def rsa_keypair(tmp_path: Path) -> Path:
    key_path = tmp_path / "app.pem"
    subprocess.run(
        ["openssl", "genrsa", "-out", str(key_path), "2048"], capture_output=True, check=True
    )
    return key_path


def _decode_b64url(segment: str) -> bytes:
    padded = segment + "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(padded)


def test_mint_app_jwt_has_expected_header_and_payload(rsa_keypair: Path) -> None:
    jwt = _mint_app_jwt("4260739", rsa_keypair)

    header_b64, payload_b64, sig_b64 = jwt.split(".")
    header = json.loads(_decode_b64url(header_b64))
    payload = json.loads(_decode_b64url(payload_b64))

    assert header == {"alg": "RS256", "typ": "JWT"}
    assert payload["iss"] == "4260739"
    assert payload["exp"] > payload["iat"]
    assert _decode_b64url(sig_b64)  # a real signature, not empty


def test_mint_app_jwt_signature_verifies_against_the_public_key(
    tmp_path: Path, rsa_keypair: Path
) -> None:
    pub_path = tmp_path / "app.pub"
    subprocess.run(
        ["openssl", "rsa", "-in", str(rsa_keypair), "-pubout", "-out", str(pub_path)],
        capture_output=True,
        check=True,
    )

    jwt = _mint_app_jwt("4260739", rsa_keypair)
    signing_input, sig_b64 = jwt.rsplit(".", 1)

    # openssl dgst -signature only reads a real file, not a pipe/fd, so the
    # signature has to be written out before it can be verified.
    sig_path = tmp_path / "sig.bin"
    sig_path.write_bytes(_decode_b64url(sig_b64))
    verify = subprocess.run(
        ["openssl", "dgst", "-sha256", "-verify", str(pub_path), "-signature", str(sig_path)],
        input=signing_input.encode(),
        capture_output=True,
    )
    assert verify.returncode == 0, verify.stderr.decode()


def test_mint_app_jwt_fails_loudly_on_bad_key(tmp_path: Path) -> None:
    bad_key = tmp_path / "not-a-key.pem"
    bad_key.write_text("not a real private key")

    with pytest.raises(GitHubError, match="failed to sign"):
        _mint_app_jwt("4260739", bad_key)


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_mint_installation_token_parses_token_and_expiry(monkeypatch, rsa_keypair: Path) -> None:
    body = json.dumps({"token": "ghs_abc123", "expires_at": "2026-07-10T01:41:15Z"}).encode()
    captured_req = {}

    def fake_urlopen(req):
        captured_req["url"] = req.full_url
        captured_req["headers"] = {k.lower(): v for k, v in req.headers.items()}
        return _FakeResponse(body)

    monkeypatch.setattr("mythings.github.urllib.request.urlopen", fake_urlopen)

    from mythings.github import _mint_installation_token

    token, expires_at = _mint_installation_token("4260739", "145558758", rsa_keypair)

    assert token == "ghs_abc123"
    assert expires_at == "2026-07-10T01:41:15Z"
    assert captured_req["url"] == "https://api.github.com/app/installations/145558758/access_tokens"
    assert captured_req["headers"]["accept"] == "application/vnd.github+json"
    assert captured_req["headers"]["authorization"].startswith("Bearer ")


def test_github_app_token_returns_just_the_token(monkeypatch, rsa_keypair: Path) -> None:
    monkeypatch.setattr(
        "mythings.github._mint_installation_token",
        lambda *a: ("ghs_abc123", "2999-01-01T00:00:00Z"),
    )

    token = github_app_token("4260739", "145558758", rsa_keypair)

    assert token == "ghs_abc123"


def test_mint_installation_token_raises_githuberror_on_http_error(
    monkeypatch, rsa_keypair: Path
) -> None:
    def fake_urlopen(req):
        raise urllib.error.HTTPError(
            req.full_url, 404, "Not Found", {}, io.BytesIO(b'{"message": "Not Found"}')
        )

    monkeypatch.setattr("mythings.github.urllib.request.urlopen", fake_urlopen)

    from mythings.github import _mint_installation_token

    with pytest.raises(GitHubError, match="404"):
        _mint_installation_token("4260739", "145558758", rsa_keypair)


def test_github_app_runner_mints_once_and_reuses_within_ttl(monkeypatch, rsa_keypair: Path) -> None:
    mint_calls = []

    def fake_mint(app_id, installation_id, private_key_path):
        mint_calls.append((app_id, installation_id))
        return "tok-1", "2999-01-01T00:00:00Z"

    monkeypatch.setattr("mythings.github._mint_installation_token", fake_mint)

    run_calls = []

    def fake_run(argv, *, capture_output, text, env):
        run_calls.append(env["GH_TOKEN"])
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    runner = github_app_runner("4260739", "145558758", rsa_keypair)
    runner(["issue", "list"])
    runner(["pr", "create"])

    assert len(mint_calls) == 1, "second call within TTL must reuse the cached token"
    assert run_calls == ["tok-1", "tok-1"]


def test_github_app_runner_remints_after_expiry(monkeypatch, rsa_keypair: Path) -> None:
    tokens = iter(["tok-1", "tok-2"])
    mint_calls = []

    def fake_mint(app_id, installation_id, private_key_path):
        mint_calls.append(1)
        # Already-expired timestamp so the very next call re-mints too.
        return next(tokens), "1970-01-01T00:00:00Z"

    monkeypatch.setattr("mythings.github._mint_installation_token", fake_mint)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout="ok", stderr=""),
    )

    runner = github_app_runner("4260739", "145558758", rsa_keypair)
    runner(["issue", "list"])
    runner(["issue", "list"])

    assert len(mint_calls) == 2, "an expired cached token must be re-minted, not reused"


def test_github_app_runner_raises_on_gh_failure(monkeypatch, rsa_keypair: Path) -> None:
    monkeypatch.setattr(
        "mythings.github._mint_installation_token",
        lambda *a: ("tok-1", "2999-01-01T00:00:00Z"),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom"),
    )

    runner = github_app_runner("4260739", "145558758", rsa_keypair)

    with pytest.raises(GitHubError, match="boom"):
        runner(["issue", "list"])


class RaisingGh:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def __call__(self, argv: list[str]) -> str:
        raise self.exc


def test_diff_returns_patch_and_appends_repo() -> None:
    fake = FakeGh("--- a\n+++ b\n@@ -1 +1 @@\n-x\n+y\n")
    gh = GitHub(repo="o/r", runner=fake)

    patch = gh.diff(7)

    assert patch.startswith("--- a")
    assert fake.calls[0][:3] == ["pr", "diff", "7"]
    assert fake.calls[0][-2:] == ["--repo", "o/r"]


def test_diff_truncates_oversize_patch() -> None:
    fake = FakeGh("x" * 50)
    gh = GitHub(runner=fake)

    patch = gh.diff(1, max_bytes=10)

    assert patch.startswith("x" * 10)
    assert patch.endswith("[diff truncated]\n")
    assert len(patch) < 50


def test_list_labels_flattens_names() -> None:
    fake = FakeGh(json.dumps([{"name": "bug"}, {"name": "core-contract"}]))
    gh = GitHub(repo="o/r", runner=fake)

    assert gh.list_labels() == ["bug", "core-contract"]
    assert fake.calls[0][:2] == ["label", "list"]
    assert fake.calls[0][-2:] == ["--repo", "o/r"]


def test_repo_list_returns_slugs_without_repo_flag() -> None:
    fake = FakeGh(json.dumps([{"nameWithOwner": "Org/a"}, {"nameWithOwner": "Org/b"}]))
    gh = GitHub(repo="o/r", runner=fake)

    assert gh.repo_list("Org") == ["Org/a", "Org/b"]
    argv = fake.calls[0]
    assert argv[:3] == ["repo", "list", "Org"]
    assert "--repo" not in argv  # org-wide, never scoped to a single repo


def test_get_file_contents_decodes_base64() -> None:
    payload = base64.b64encode(b"[tool.ruff]\nline-length = 100\n").decode()
    # GitHub's API returns base64 wrapped across lines; decode must tolerate it.
    fake = FakeGh(payload[:4] + "\n" + payload[4:] + "\n")
    gh = GitHub(runner=fake)

    content = gh.get_file_contents("Org/repo", "pyproject.toml")

    assert content == "[tool.ruff]\nline-length = 100\n"
    assert "repos/Org/repo/contents/pyproject.toml?ref=main" in fake.calls[0][1]


def test_get_file_contents_returns_none_on_404() -> None:
    gh = GitHub(runner=RaisingGh(GitHubError("gh api ... failed (1): gh: Not Found (HTTP 404)")))

    assert gh.get_file_contents("Org/repo", "missing.toml") is None


def test_get_file_contents_reraises_non_404() -> None:
    gh = GitHub(runner=RaisingGh(GitHubError("gh api ... failed (1): server error (HTTP 500)")))

    with pytest.raises(GitHubError, match="500"):
        gh.get_file_contents("Org/repo", "x.toml")
