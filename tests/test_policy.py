from mythings.policy import ALLOW, Action, Decision, Policy, PolicyResult


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
