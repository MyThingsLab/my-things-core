import json

import pytest

from mythings.github import GitHubError
from mythings.projects import Projects


class FakeGraphQL:
    # Mocks the `gh api graphql ...` boundary: routes by which query/mutation the
    # argv carries (matched on a distinctive substring of the `query=` payload).
    def __init__(self, replies: dict[str, dict]) -> None:
        self.replies = replies
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        assert argv[:2] == ["api", "graphql"]
        query = next(a.split("=", 1)[1] for a in argv if a.startswith("query="))
        for needle, reply in self.replies.items():
            if needle in query:
                return json.dumps(reply)
        raise AssertionError(f"unexpected graphql query: {query[:60]}...")


def _var(argv: list[str], name: str) -> str:
    return next(a.split("=", 1)[1] for a in argv if a.startswith(f"{name}="))


def _draft_node(item_id: str, title: str) -> dict:
    return {
        "id": item_id,
        "type": "ISSUE",
        "content": {"__typename": "DraftIssue", "title": title},
        "fieldValues": {"nodes": []},
    }


def test_items_parses_content_and_field_values() -> None:
    reply = {
        "data": {
            "node": {
                "items": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {
                            "id": "ITEM_1",
                            "type": "ISSUE",
                            "content": {
                                "__typename": "Issue",
                                "number": 12,
                                "title": "wire it up",
                                "url": "https://github.com/o/my-guard/issues/12",
                                "state": "OPEN",
                                "repository": {"name": "my-guard"},
                            },
                            "fieldValues": {
                                "nodes": [
                                    {
                                        "__typename": "ProjectV2ItemFieldSingleSelectValue",
                                        "name": "In Progress",
                                        "field": {"name": "Fleet Status"},
                                    },
                                    {
                                        "__typename": "ProjectV2ItemFieldTextValue",
                                        "text": "opened PR #12",
                                        "field": {"name": "Last step"},
                                    },
                                    {"__typename": "ProjectV2ItemFieldNumberValue"},
                                ]
                            },
                        },
                        {
                            "id": "ITEM_2",
                            "type": "DRAFT_ISSUE",
                            "content": {"__typename": "DraftIssue", "title": "a draft"},
                            "fieldValues": {"nodes": []},
                        },
                    ],
                }
            }
        }
    }
    fake = FakeGraphQL({"items(first": reply})

    items = Projects(runner=fake).items("PVT_x")

    assert len(items) == 2
    issue, draft = items
    assert issue.content_type == "Issue"
    assert issue.number == 12
    assert issue.repo == "my-guard"
    assert issue.state == "OPEN"
    assert issue.fields == {"Fleet Status": "In Progress", "Last step": "opened PR #12"}
    assert draft.content_type == "DraftIssue"
    assert draft.number is None
    assert draft.fields == {}


def test_items_follows_pagination_cursor() -> None:
    page1 = {
        "data": {
            "node": {
                "items": {
                    "pageInfo": {"hasNextPage": True, "endCursor": "CUR2"},
                    "nodes": [_draft_node("A", "a")],
                }
            }
        }
    }
    page2 = {
        "data": {
            "node": {
                "items": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [_draft_node("B", "b")],
                }
            }
        }
    }
    calls: list[str] = []

    def runner(argv: list[str]) -> str:
        cursor = _var(argv, "cursor")
        calls.append(cursor)
        return json.dumps(page2 if cursor == "CUR2" else page1)

    items = Projects(runner=runner).items("PVT_x")

    assert [i.id for i in items] == ["A", "B"]
    assert calls == ["", "CUR2"]  # first page empty cursor, then the returned one


def test_fields_flattens_single_select_options() -> None:
    reply = {
        "data": {
            "node": {
                "fields": {
                    "nodes": [
                        {"__typename": "ProjectV2Field", "id": "F_TEXT", "name": "Last step"},
                        {
                            "__typename": "ProjectV2SingleSelectField",
                            "id": "F_STATUS",
                            "name": "Fleet Status",
                            "options": [
                                {"id": "opt_ship", "name": "Shipped"},
                                {"id": "opt_prog", "name": "In Progress"},
                            ],
                        },
                        None,
                    ]
                }
            }
        }
    }
    fake = FakeGraphQL({"fields(first": reply})

    fields = {f.name: f for f in Projects(runner=fake).fields("PVT_x")}

    assert fields["Last step"].options == {}
    assert fields["Fleet Status"].option_id("Shipped") == "opt_ship"
    assert fields["Fleet Status"].option_id("nope") is None


def test_project_id_resolves_org_number() -> None:
    reply = {"data": {"organization": {"projectV2": {"id": "PVT_abc"}}}}
    fake = FakeGraphQL({"projectV2(number": reply})

    assert Projects(runner=fake).project_id("MyThingsLab", 1) == "PVT_abc"
    # $number: Int! must go over as a typed (-F) var, not a string (-f).
    argv = fake.calls[0]
    assert "-F" in argv and "number=1" in argv


def test_set_single_select_sends_option_var() -> None:
    fake = FakeGraphQL({"updateProjectV2ItemFieldValue": {"data": {}}})

    Projects(runner=fake).set_single_select("PVT_x", "ITEM_1", "F_STATUS", "opt_ship")

    argv = fake.calls[0]
    assert _var(argv, "option") == "opt_ship"
    assert _var(argv, "item") == "ITEM_1"


def test_missing_project_raises() -> None:
    fake = FakeGraphQL({"projectV2(number": {"data": {"organization": {"projectV2": None}}}})
    with pytest.raises(GitHubError):
        Projects(runner=fake).project_id("MyThingsLab", 99)


def test_graphql_errors_raise() -> None:
    fake = FakeGraphQL({"fields(first": {"errors": [{"message": "bad"}]}})
    with pytest.raises(GitHubError):
        Projects(runner=fake).fields("PVT_x")
