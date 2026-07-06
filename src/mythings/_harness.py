from __future__ import annotations

from importlib.resources import files

# The canonical build-harness rules ship as package data so any tool that
# installs mythings-core can diff its vendored HARNESS.md against this. Build
# tooling, not a contract — deliberately not exported from the package.


def harness_text() -> str:
    return files("mythings").joinpath("harness.md").read_text(encoding="utf-8")
