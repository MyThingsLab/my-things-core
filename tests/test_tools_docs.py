import re
from pathlib import Path

DOCS_TOOLS = Path(__file__).parent.parent / "docs" / "tools"

# Mirrors the "docs/tools/<name>.md goes historical at first ship" rule in
# docs/CONVENTIONS.md: only the tool name should vary between banners.
HISTORICAL_BANNER_RE = re.compile(
    r"^> \*\*Historical\.\*\* This is the pre-build design plan, frozen as of "
    r"(?P<name>[\w-]+)'s\n"
    r"> first ship\. It is \*\*not\*\* kept in sync with the implementation — for current\n"
    r"> behavior \(CLI surface, flags, invariants\) read\n"
    r"> \[`(?P<tool>[\w-]+)/README\.md`\]\(\.\./\.\./\.\./(?P=tool)/README\.md\) and\n"
    r"> \[`(?P=tool)/CLAUDE\.md`\]\(\.\./\.\./\.\./(?P=tool)/CLAUDE\.md\) in the tool's own\n"
    r"> repo\. Only genuinely cross-tool contracts \(a new Engine-seam pattern, a new\n"
    r"> core dependency\) get a follow-up edit here\.",
    re.MULTILINE,
)


def test_my_tester_doc_has_historical_banner() -> None:
    text = (DOCS_TOOLS / "my-tester.md").read_text()
    match = HISTORICAL_BANNER_RE.search(text)
    assert match, "docs/tools/my-tester.md is missing the historical banner"
    assert match.group("tool") == "my-tester"


def test_my_tester_doc_banner_matches_shipped_pattern() -> None:
    # my-reporter.md is the reference implementation of the banner; both
    # should follow the exact same wording/link structure.
    reporter_text = (DOCS_TOOLS / "my-reporter.md").read_text()
    assert HISTORICAL_BANNER_RE.search(reporter_text)


def test_my_tester_doc_body_otherwise_unchanged() -> None:
    text = (DOCS_TOOLS / "my-tester.md").read_text()
    assert "**BUILD THIS FIRST.**" in text
    assert "Runs pytest with coverage, finds one uncovered unit" in text
