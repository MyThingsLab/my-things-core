import subprocess
from pathlib import Path

import mythings._secrets as secrets


def test_scan_text_catches_aws_key() -> None:
    findings = secrets.scan_text("aws_key = AKIAABCDEFGHIJKLMNOP")
    assert any(f.pattern == "aws_access_key_id" for f in findings)


def test_scan_text_catches_github_token() -> None:
    findings = secrets.scan_text("token: ghp_abcdefghijklmnopqrstuvwxyz0123456789")
    assert any(f.pattern == "github_token" for f in findings)


def test_scan_text_catches_private_key_block() -> None:
    block = "-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n-----END RSA PRIVATE KEY-----"
    findings = secrets.scan_text(block)
    assert any(f.pattern == "private_key_block" for f in findings)


def test_scan_text_catches_anthropic_key_in_printenv_shaped_line() -> None:
    # The shape a worker session's own `printenv`/`env` allowlisted commands
    # actually emit: unquoted `NAME=value`, not `key = "value"`.
    findings = secrets.scan_text("ANTHROPIC_API_KEY=sk-ant-api03-" + "A" * 30)
    assert any(f.pattern == "anthropic_key" for f in findings)


def test_scan_text_catches_all_anthropic_key_prefixes() -> None:
    for infix in ("api03", "oat01", "admin"):
        findings = secrets.scan_text(f"CLAUDE_CODE_OAUTH_TOKEN=sk-ant-{infix}-" + "B" * 30)
        assert any(f.pattern == "anthropic_key" for f in findings), infix


def test_scan_text_catches_generic_assignment() -> None:
    findings = secrets.scan_text('password = "supersecretvalue123"')
    assert any(f.pattern == "generic_assignment" for f in findings)


def test_scan_text_clean_on_ordinary_code() -> None:
    text = "def f(password):\n    return password.strip()\n"
    assert secrets.scan_text(text) == []


def test_scan_text_does_not_false_positive_on_short_values() -> None:
    # A short/placeholder-looking value shouldn't trip the generic assignment
    # pattern -- otherwise every `token = "x"` test fixture becomes a false
    # alarm.
    assert secrets.scan_text('token = "short"') == []


def test_scan_text_catches_unquoted_env_dump_assignment() -> None:
    # printenv/env output is unquoted `KEY=value`, which the quoted-only
    # generic_assignment rule used to let straight through.
    findings = secrets.scan_text("SOME_SECRET_TOKEN=" + "x" * 20)
    assert any(f.pattern == "generic_assignment" for f in findings)


def test_scan_text_does_not_false_positive_on_ordinary_env_dump_lines() -> None:
    # An ordinary printenv/env line -- no secret-shaped keyword, or a
    # short/benign value -- must not trip the widened unquoted rule.
    assert secrets.scan_text("HOME=/home/worker") == []
    assert secrets.scan_text("DEBUG=true") == []
    assert secrets.scan_text("PATH=/usr/local/bin:/usr/bin:/bin") == []


def test_added_lines_ignores_context_and_removed_lines() -> None:
    diff = (
        "diff --git a/f b/f\n"
        "--- a/f\n"
        "+++ b/f\n"
        "-old_token = 'AKIAABCDEFGHIJKLMNOP'\n"
        "+new_line_no_secret = 1\n"
        " unchanged_context = 2\n"
    )
    assert "AKIA" not in secrets.added_lines(diff)
    assert "new_line_no_secret" in secrets.added_lines(diff)


def test_added_lines_catches_secret_only_in_addition() -> None:
    diff = "diff --git a/f b/f\n+++ b/f\n+aws_key = AKIAABCDEFGHIJKLMNOP\n"
    findings = secrets.scan_text(secrets.added_lines(diff))
    assert any(f.pattern == "aws_access_key_id" for f in findings)


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "-C", str(path), "add", "seed.txt"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "seed"], check=True)


def test_main_scan_staged_catches_planted_secret(tmp_path: Path, monkeypatch, capsys) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "config.py").write_text("AWS_KEY = 'AKIAABCDEFGHIJKLMNOP'\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "config.py"], check=True)
    monkeypatch.chdir(tmp_path)

    rc = secrets.main(["scan-staged"])

    out = capsys.readouterr().out
    assert rc == 1
    assert "aws_access_key_id" in out


def test_main_scan_staged_ignores_own_test_fixtures(tmp_path: Path, monkeypatch, capsys) -> None:
    # This module's own test file plants realistic-looking fake secrets on
    # purpose (the tests above); the scanner must not block a PR that edits
    # its own detector tests.
    _init_git_repo(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test__secrets.py").write_text("AWS_KEY = 'AKIAABCDEFGHIJKLMNOP'\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "tests/test__secrets.py"], check=True)
    monkeypatch.chdir(tmp_path)

    rc = secrets.main(["scan-staged"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "clean" in out


def test_main_scan_staged_clean_diff_passes(tmp_path: Path, monkeypatch, capsys) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "readme.txt").write_text("hello world\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "readme.txt"], check=True)
    monkeypatch.chdir(tmp_path)

    rc = secrets.main(["scan-staged"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "clean" in out


def test_main_scan_text_reads_stdin(monkeypatch, capsys) -> None:
    import io

    fake_stdin = io.StringIO("token: ghp_abcdefghijklmnopqrstuvwxyz0123456789")
    monkeypatch.setattr(secrets.sys, "stdin", fake_stdin)

    rc = secrets.main(["scan-text"])

    out = capsys.readouterr().out
    assert rc == 1
    assert "github_token" in out
