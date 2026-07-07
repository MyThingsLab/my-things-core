import re
from pathlib import Path

ARCHITECTURE_MD = Path(__file__).parent.parent / "docs" / "ARCHITECTURE.md"

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def test_contracts_header_count_matches_subsection_count() -> None:
    text = ARCHITECTURE_MD.read_text()
    header_match = re.search(r"^## The (\w+) contracts$", text, re.MULTILINE)
    assert header_match, "expected a '## The <N> contracts' header"

    header_count = NUMBER_WORDS[header_match.group(1).lower()]

    section_start = header_match.end()
    next_h2 = text.find("\n## ", section_start)
    section = text[section_start : next_h2 if next_h2 != -1 else len(text)]
    subsection_count = len(re.findall(r"^### ", section, re.MULTILINE))

    assert header_count == subsection_count
