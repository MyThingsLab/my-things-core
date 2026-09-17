from pathlib import Path

import mythings


def test_the_suite_imports_this_checkouts_source_not_the_editable_install() -> None:
    # Every repo is installed editable into the shared root .venv, and that
    # install points at its MAIN checkout. A worker session runs inside a git
    # WORKTREE, so without `pythonpath = ["src"]` in the pytest config the
    # editable install wins and the suite exercises main's code instead of the
    # change under review (my-template#18).
    #
    # The failure is asymmetric: a change that ADDS a symbol fails loudly on
    # ImportError, but a change that MODIFIES existing behaviour passes green
    # against source it never ran. The quiet case is the dangerous one, and
    # `mycoder build --run-tests` is the step that inherits it -- which makes
    # this the only mechanical evidence a worker's diff is sound.
    repo_root = Path(__file__).resolve().parent.parent
    imported = Path(mythings.__file__).resolve()
    assert imported.is_relative_to(repo_root), (
        f"tests imported {imported}, which is outside this checkout ({repo_root}). "
        "The editable install shadowed the worktree -- check `pythonpath` in "
        "[tool.pytest.ini_options]."
    )


def test_every_public_export_resolves() -> None:
    # `__all__` is edited by hand alongside the import block above it, so a name
    # can be listed without ever being imported. Nothing raises at import time:
    # `from mythings import *` fails, and `_compat.resolves` reports the
    # capability unmet, which reads as core having dropped it.
    missing = [name for name in mythings.__all__ if not hasattr(mythings, name)]
    assert missing == [], f"listed in __all__ but never imported: {missing}"
