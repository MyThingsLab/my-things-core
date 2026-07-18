from mythings.policy import (
    ALLOW,
    Action,
    Decision,
    Policy,
    PolicyResult,
    ownership_boundary,
    subtree_owner,
)


def test_decision_serializes_as_its_value() -> None:
    assert Decision.DENY.value == "deny"
    assert Decision("ask") is Decision.ASK


def test_blocked_is_deny_only() -> None:
    assert PolicyResult(Decision.DENY).blocked
    assert not PolicyResult(Decision.ASK).blocked
    assert not ALLOW.blocked


def test_unattended_collapses_ask_to_deny() -> None:
    ask = PolicyResult(Decision.ASK, reason="edits an invariant file")
    assert ask.under(unattended=True) is Decision.DENY
    assert ask.under(unattended=False) is Decision.ASK
    # allow/deny are unaffected by the unattended flag
    assert ALLOW.under(unattended=True) is Decision.ALLOW
    assert PolicyResult(Decision.DENY).under(unattended=False) is Decision.DENY


def test_action_is_hashable_and_typed() -> None:
    a = Action(kind="bash", payload={"command": "git push"})
    assert a.kind == "bash"
    assert a.payload["command"] == "git push"


def test_policy_protocol_is_structural() -> None:
    class Yes:
        def evaluate(self, action: Action) -> PolicyResult:
            return ALLOW

    assert isinstance(Yes(), Policy)
    assert not isinstance(object(), Policy)


OWNERS = {"data": "team-data", "models": "team-models", "models/training": "team-training"}


def test_subtree_owner_matches_whole_path_segments() -> None:
    assert subtree_owner("data/raw/loader.py", OWNERS) == "team-data"
    # "data" must not match "database/x.py" -- a segment, not a string, prefix.
    assert subtree_owner("database/x.py", OWNERS) is None


def test_subtree_owner_prefers_the_deepest_declared_subtree() -> None:
    assert subtree_owner("models/architecture.py", OWNERS) == "team-models"
    assert subtree_owner("models/training/loop.py", OWNERS) == "team-training"


def test_subtree_owner_is_none_for_an_undeclared_path() -> None:
    assert subtree_owner("README.md", OWNERS) is None


def test_ownership_boundary_allows_a_single_owner_diff() -> None:
    result = ownership_boundary(["data/raw/a.py", "data/raw/b.py"], OWNERS)
    assert result == ALLOW


def test_ownership_boundary_allows_an_owner_plus_shared_root_files() -> None:
    # A README/CI-config edit alongside one team's change is routine, not a
    # boundary crossing -- unowned paths never count toward the touched set.
    result = ownership_boundary(["data/raw/a.py", "README.md"], OWNERS)
    assert result == ALLOW


def test_ownership_boundary_allows_when_nothing_is_owned() -> None:
    assert ownership_boundary(["README.md", "LICENSE"], OWNERS) == ALLOW


def test_ownership_boundary_asks_when_two_owners_are_touched() -> None:
    result = ownership_boundary(["data/raw/a.py", "models/architecture.py"], OWNERS)
    assert result.decision is Decision.ASK
    assert "team-data" in result.reason and "team-models" in result.reason
    assert result.rule == "ownership-boundary"


def test_ownership_boundary_asks_across_three_owners() -> None:
    result = ownership_boundary(
        ["data/raw/a.py", "models/architecture.py", "models/training/loop.py"], OWNERS
    )
    assert result.decision is Decision.ASK
    for owner in ("team-data", "team-models", "team-training"):
        assert owner in result.reason


def test_ownership_boundary_ask_still_collapses_to_deny_unattended() -> None:
    # Reuses PolicyResult.under() exactly like any other ASK -- no separate
    # unattended-handling logic for this check.
    result = ownership_boundary(["data/a.py", "models/b.py"], OWNERS)
    assert result.under(unattended=True) is Decision.DENY
    assert result.under(unattended=False) is Decision.ASK
