from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from mythings.github import GitHubError, Runner, _gh

# GitHub Projects (v2) is GraphQL-only — the `gh` CLI's REST-ish surface that
# `github.GitHub` wraps has no ProjectV2 verbs. This module is the GraphQL half:
# same `Runner` boundary (argv after `gh`, here always `api graphql ...`), so
# tests mock only the `gh` process, exactly like github.py. It stays a separate
# type rather than bolted onto GitHub because the transport genuinely differs.
#
# Scope is deliberately sync-only for v0: read items + fields, write a field
# value. Board *views* have no create/update mutations at all (confirmed against
# the live schema) — they stay a one-time human setup step. Draft-issue / card
# creation is also out of scope: auto-creation is the path that hit a
# draft→issue conversion race in practice, so new cards are still added by hand.


@dataclass(frozen=True)
class ProjectField:
    id: str
    name: str
    # option name -> option id, for single-select fields; empty otherwise.
    options: dict[str, str] = field(default_factory=dict)

    def option_id(self, name: str) -> str | None:
        return self.options.get(name)


@dataclass(frozen=True)
class ProjectItem:
    id: str
    content_type: str  # "Issue" | "PullRequest" | "DraftIssue"
    title: str
    number: int | None = None  # None for a DraftIssue
    url: str = ""
    state: str = ""  # "OPEN" | "CLOSED" | "MERGED" | "" (draft)
    repo: str = ""  # repository name; "" for a draft
    fields: dict[str, str] = field(default_factory=dict)  # field name -> value (text/option name)


_ITEMS_QUERY = """
query($project: ID!, $cursor: String) {
  node(id: $project) {
    ... on ProjectV2 {
      items(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          type
          content {
            __typename
            ... on Issue { number title url state repository { name } }
            ... on PullRequest { number title url state repository { name } }
            ... on DraftIssue { title }
          }
          fieldValues(first: 30) {
            nodes {
              __typename
              ... on ProjectV2ItemFieldTextValue {
                text
                field { ... on ProjectV2FieldCommon { name } }
              }
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field { ... on ProjectV2FieldCommon { name } }
              }
            }
          }
        }
      }
    }
  }
}
"""

_FIELDS_QUERY = """
query($project: ID!) {
  node(id: $project) {
    ... on ProjectV2 {
      fields(first: 50) {
        nodes {
          __typename
          ... on ProjectV2FieldCommon { id name }
          ... on ProjectV2SingleSelectField { id name options { id name } }
        }
      }
    }
  }
}
"""

_PROJECT_ID_QUERY = """
query($org: String!, $number: Int!) {
  organization(login: $org) { projectV2(number: $number) { id } }
}
"""

_SET_TEXT = """
mutation($project: ID!, $item: ID!, $field: ID!, $text: String!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $project, itemId: $item, fieldId: $field, value: {text: $text}
  }) { projectV2Item { id } }
}
"""

_SET_OPTION = """
mutation($project: ID!, $item: ID!, $field: ID!, $option: String!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $project, itemId: $item, fieldId: $field, value: {singleSelectOptionId: $option}
  }) { projectV2Item { id } }
}
"""


class Projects:
    def __init__(self, *, runner: Runner = _gh) -> None:
        self._run = runner

    def _graphql(self, query: str, **variables: str | int) -> dict[str, Any]:
        argv = ["api", "graphql", "-f", f"query={query}"]
        for key, value in variables.items():
            # `-F` type-infers (int -> Int); `-f` always sends a string. bool is an
            # int subclass, so guard it out even though we never pass one today.
            flag = "-F" if isinstance(value, int) and not isinstance(value, bool) else "-f"
            argv += [flag, f"{key}={value}"]
        obj = json.loads(self._run(argv) or "{}")
        if obj.get("errors"):
            raise GitHubError(f"graphql errors: {json.dumps(obj['errors'])}")
        return obj.get("data") or {}

    def project_id(self, org: str, number: int) -> str:
        data = self._graphql(_PROJECT_ID_QUERY, org=org, number=number)
        node = ((data.get("organization") or {}).get("projectV2") or {}).get("id")
        if not node:
            raise GitHubError(f"no ProjectV2 #{number} under org {org!r}")
        return node

    def fields(self, project_id: str) -> list[ProjectField]:
        data = self._graphql(_FIELDS_QUERY, project=project_id)
        nodes = (((data.get("node") or {}).get("fields") or {}).get("nodes")) or []
        out: list[ProjectField] = []
        for node in nodes:
            if not node:  # a null appears for field types the query didn't fragment on
                continue
            options = {opt["name"]: opt["id"] for opt in node.get("options") or []}
            out.append(ProjectField(id=node["id"], name=node["name"], options=options))
        return out

    def items(self, project_id: str) -> list[ProjectItem]:
        out: list[ProjectItem] = []
        cursor: str | None = None
        while True:
            data = self._graphql(_ITEMS_QUERY, project=project_id, cursor=cursor or "")
            block = ((data.get("node") or {}).get("items")) or {}
            for node in block.get("nodes") or []:
                if node:
                    out.append(_item_from_node(node))
            page = block.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                return out
            cursor = page.get("endCursor")

    def set_text_field(self, project_id: str, item_id: str, field_id: str, text: str) -> None:
        self._graphql(_SET_TEXT, project=project_id, item=item_id, field=field_id, text=text)

    def set_single_select(
        self, project_id: str, item_id: str, field_id: str, option_id: str
    ) -> None:
        self._graphql(
            _SET_OPTION, project=project_id, item=item_id, field=field_id, option=option_id
        )


def _item_from_node(node: dict[str, Any]) -> ProjectItem:
    content = node.get("content") or {}
    fields = {}
    for fv in ((node.get("fieldValues") or {}).get("nodes")) or []:
        name = ((fv or {}).get("field") or {}).get("name")
        if not name:
            continue
        value = fv.get("text") if "text" in fv else fv.get("name")
        if value is not None:
            fields[name] = value
    return ProjectItem(
        id=node["id"],
        content_type=content.get("__typename", "DraftIssue"),
        title=content.get("title", ""),
        number=content.get("number"),
        url=content.get("url", ""),
        state=content.get("state", ""),
        repo=(content.get("repository") or {}).get("name", ""),
        fields=fields,
    )
