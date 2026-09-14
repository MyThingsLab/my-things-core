from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from mythings.github import Runner, _gh
from mythings.labels import parse as parse_labels

# A goal is one cross-repo objective, opened as a same-titled milestone in every
# repo it touches. The prefix is the whole mechanism: there is no goal registry
# to fall out of sync with GitHub, only a naming convention GitHub itself
# enforces uniqueness on per repo.
GOAL_PREFIX = "goal/"

# Nothing closed in this long, with open work outstanding, is a stalled goal
# whatever the arithmetic says. Two weeks is long enough that a quiet week over
# a holiday doesn't trip it and short enough to catch a goal inside its own
# due window.
STALL_DAYS = 14


@dataclass(frozen=True)
class IssueRef:
    repo: str
    number: int
    title: str
    state: str = "OPEN"
    url: str = ""
    labels: tuple[str, ...] = ()
    body: str = ""
    closed_at: str = ""

    @property
    def slug(self) -> str:
        return f"{self.repo}#{self.number}"

    @property
    def is_open(self) -> bool:
        return self.state.upper() == "OPEN"

    @property
    def facets(self):  # noqa: ANN201 - labels.Facets, re-exported through the property
        return parse_labels(self.labels)


@dataclass(frozen=True)
class Blocker:
    # The clause exactly as the issue body wrote it, kept verbatim so a report
    # can quote the author rather than paraphrase them.
    text: str
    resolved: IssueRef | None = None

    @property
    def cleared(self) -> bool:
        return self.resolved is not None and not self.resolved.is_open


@dataclass(frozen=True)
class GoalPart:
    repo: str
    open_issues: int = 0
    closed_issues: int = 0
    url: str = ""

    @property
    def total(self) -> int:
        return self.open_issues + self.closed_issues


@dataclass(frozen=True)
class GoalView:
    goal_id: str
    statement: str = ""
    done_when: tuple[str, ...] = ()
    phases: tuple[str, ...] = ()
    due_on: str = ""
    description: str = ""
    parts: tuple[GoalPart, ...] = ()
    issues: tuple[IssueRef, ...] = ()
    # issue slug -> the blockers named in its body. Only issues that name one
    # appear; an absent key means "nothing claimed", not "nothing blocking".
    blockers: dict[str, tuple[Blocker, ...]] = field(default_factory=dict)

    @property
    def slug(self) -> str:
        return (
            self.goal_id[len(GOAL_PREFIX) :]
            if self.goal_id.startswith(GOAL_PREFIX)
            else self.goal_id
        )

    @property
    def open_issues(self) -> tuple[IssueRef, ...]:
        return tuple(i for i in self.issues if i.is_open)

    @property
    def closed_issues(self) -> tuple[IssueRef, ...]:
        return tuple(i for i in self.issues if not i.is_open)

    def progress(self) -> tuple[int, int]:
        return len(self.closed_issues), len(self.issues)

    def _by_state(self, state: str) -> tuple[IssueRef, ...]:
        return tuple(i for i in self.open_issues if i.facets.state == state)

    @property
    def blocked(self) -> tuple[IssueRef, ...]:
        return self._by_state("blocked")

    @property
    def ready(self) -> tuple[IssueRef, ...]:
        return self._by_state("ready")

    @property
    def in_flight(self) -> tuple[IssueRef, ...]:
        return self._by_state("in-flight")

    @property
    def needs_human(self) -> tuple[IssueRef, ...]:
        return self._by_state("needs-human")

    @property
    def falsely_blocked(self) -> tuple[IssueRef, ...]:
        # Labelled blocked, but every blocker it names resolved to a closed
        # issue. An issue naming no blocker at all is NOT included: the label
        # is then the only evidence either way, and the label wins. Same for
        # an unresolvable clause -- see _resolve.
        found = []
        for issue in self.blocked:
            claimed = self.blockers.get(issue.slug, ())
            if claimed and all(b.cleared for b in claimed):
                found.append(issue)
        return tuple(found)

    @property
    def dispatchable(self) -> tuple[IssueRef, ...]:
        return self.ready + self.in_flight

    def verdict(self, *, now: datetime | None = None) -> str:
        # First match wins, cheapest and most damning first. Deliberately not a
        # score: every branch below is a different *kind* of problem and a
        # single number would average them into something unactionable.
        if not self.open_issues:
            return "met"
        # The condition that actually bit this fleet: 9 open issues, every one
        # labelled blocked, so the queue was empty while the board looked busy.
        # No velocity calculation can see this -- it is not slowness, it is a
        # loop with nothing to pick.
        if not self.dispatchable:
            return "blocked"
        moment = now or datetime.now(UTC)
        if self._days_since_progress(moment) > STALL_DAYS:
            return "stalled"
        if self._projected(moment) < len(self.open_issues):
            return "at_risk"
        return "on_track"

    def _days_since_progress(self, now: datetime) -> float:
        stamps = [_parse_ts(i.closed_at) for i in self.closed_issues]
        recent = max((s for s in stamps if s is not None), default=None)
        if recent is None:
            return float("inf")
        return (now - recent).total_seconds() / 86400

    def _projected(self, now: datetime) -> float:
        # Closures per day so far, extrapolated to the due date. With no due
        # date a goal cannot be late, so nothing is ever at_risk.
        due = _parse_ts(self.due_on)
        if due is None:
            return float("inf")
        opened = min(
            (s for s in (_parse_ts(i.closed_at) for i in self.closed_issues) if s is not None),
            default=None,
        )
        if opened is None or not self.closed_issues:
            return 0.0
        elapsed = max((now - opened).total_seconds() / 86400, 1.0)
        remaining = max((due - now).total_seconds() / 86400, 0.0)
        return (len(self.closed_issues) / elapsed) * remaining

    def brief(self, *, for_repo: str | None = None, dead_ends: Sequence[str] = ()) -> str:
        closed, total = self.progress()
        lines = [
            f"## Goal: {self.goal_id}",
            "",
            f"You are working inside a cross-repo goal spanning {len(self.parts)} "
            f"repos. {closed}/{total} of its issues are closed "
            f"({self.verdict()}{f', due {self.due_on[:10]}' if self.due_on else ''}).",
        ]
        if self.statement:
            lines += ["", self.statement]
        if self.done_when:
            lines += [
                "",
                "**Done when** (the goal's acceptance oracle — your change must "
                "move toward this, not away from it):",
            ]
            lines += [f"- {item}" for item in self.done_when]
        if self.phases:
            lines += ["", "**Phases:**"]
            lines += [f"{n}. {phase}" for n, phase in enumerate(self.phases, start=1)]

        peers = [i for i in self.dispatchable if for_repo is None or i.repo != for_repo]
        if peers:
            lines += ["", "**Sibling work in this goal, not yours to do:**"]
            lines += [f"- {i.slug} — {i.title}" for i in peers[:8]]
        landed = sorted(self.closed_issues, key=lambda i: i.closed_at, reverse=True)[:5]
        if landed:
            lines += ["", "**Already landed for this goal — build on it, do not rebuild it:**"]
            lines += [f"- {i.slug} — {i.title}" for i in landed]
        if dead_ends:
            # The one channel carrying knowledge nothing else holds: everything
            # else here is recoverable from GitHub, "we tried X and it does not
            # work, because Y" is recoverable from nowhere.
            lines += ["", "**Dead ends already hit in this goal — do not retry these:**"]
            lines += [f"- {item}" for item in dead_ends]
        return "\n".join(lines)


# ---- milestone description parsing ---------------------------------------

_DONE_WHEN_RE = re.compile(r"^\s*done[_ ]when\s*:\s*(.+)$", re.IGNORECASE)
_PHASE_RE = re.compile(r"^\s*phase\s*(\d+)\s*:\s*(.+)$", re.IGNORECASE)
_PHASES_RE = re.compile(r"^\s*phases\s*:\s*(.+)$", re.IGNORECASE)
_STATEMENT_RE = re.compile(r"^\s*statement\s*:\s*(.+)$", re.IGNORECASE)


def parse_description(text: str) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    # A milestone description is free text with optional `key: value` lines --
    # forgiving on purpose, because it is typed by a human into a GitHub form
    # with no validation. Anything unrecognized becomes the statement rather
    # than being dropped.
    statement: list[str] = []
    done_when: list[str] = []
    phases: dict[int, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if match := _DONE_WHEN_RE.match(line):
            done_when.append(match.group(1).strip())
        elif match := _PHASE_RE.match(line):
            phases[int(match.group(1))] = match.group(2).strip()
        elif match := _PHASES_RE.match(line):
            for n, part in enumerate(match.group(1).split("|"), start=1):
                if part.strip():
                    phases[n] = part.strip()
        elif match := _STATEMENT_RE.match(line):
            statement.append(match.group(1).strip())
        else:
            statement.append(line)
    ordered = tuple(phases[k] for k in sorted(phases))
    return " ".join(statement), tuple(done_when), ordered


# ---- blocker parsing ------------------------------------------------------

# The structured form, which is what new issues should use. Accepts a bare
# number, repo#N, or owner/repo#N.
_BLOCKED_BY_RE = re.compile(r"^\s*blocked[-_ ]by\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_REF_RE = re.compile(r"(?:([\w.-]+)/)?([\w.-]+)?#(\d+)")

# The prose form every existing issue in the fleet actually uses:
# "Blocked on mythings.session and the milestone helpers."
_BLOCKED_ON_RE = re.compile(r"\bblocked\s+on\s+(.+?)(?:\.\s|\.$|\n|$)", re.IGNORECASE)

# Splits one prose clause into the separate things it names.
_CONNECTIVE_RE = re.compile(
    r",\s*and\s+on\s+|,\s*and\s+|\s+and\s+on\s+|\s+and\s+|,\s*", re.IGNORECASE
)

# A trailing qualifier explains *why* something blocks, and its words are not
# part of the thing's name: "mythings.session for the Verdict type" names
# mythings.session. Truncating here narrows the token set, which can only make
# a match more ambiguous -- and ambiguous resolves to "stays blocked".
_QUALIFIER_RE = re.compile(r"\s+(?:for|to|in|so|which|that|because|since)\s+", re.IGNORECASE)

_STOPWORDS = frozenset(
    {"the", "a", "an", "issue", "issues", "work", "this", "its", "it", "of", "on", "and"}
)

# Below this length a token carries no discriminating power and prefix-matching
# it ("cad" against "candidate") invites a wrong resolution.
_MIN_TOKEN = 4


def _tokens(text: str) -> tuple[str, ...]:
    cleaned = re.sub(r"[^\w.]+", " ", text.replace("-", " ").replace("_", " "))
    return tuple(
        tok
        for tok in (t.lower() for t in cleaned.split())
        if tok not in _STOPWORDS and len(tok) >= _MIN_TOKEN
    )


def _matches(query: str, title: str) -> bool:
    # Every query token must appear in the title, allowing a prefix match in
    # either direction so "ranking" finds "rank" without a stemmer. All-tokens
    # rather than best-score: a scored match always returns *something*, and
    # the failure mode here (unblocking the wrong issue) is worse than the
    # failure mode of matching nothing (it stays blocked, a human looks).
    wanted = _tokens(query)
    if not wanted:
        return False
    have = _tokens(title)
    return all(
        any(tok.startswith(other) or other.startswith(tok) for other in have) for tok in wanted
    )


def _resolve(clause: str, candidates: Sequence[IssueRef]) -> IssueRef | None:
    # Exactly one candidate or nothing. Two matches means the author was
    # ambiguous, and guessing between them is precisely the judgement this
    # module must not make.
    hits = [c for c in candidates if _matches(clause, c.title)]
    return hits[0] if len(hits) == 1 else None


def blockers(body: str, candidates: Sequence[IssueRef] = ()) -> tuple[Blocker, ...]:
    by_slug = {c.slug: c for c in candidates}
    by_number = {c.number: c for c in candidates}
    found: list[Blocker] = []

    for line in _BLOCKED_BY_RE.findall(body or ""):
        for owner, repo, number in _REF_RE.findall(line):
            text = f"{owner + '/' if owner else ''}{repo or ''}#{number}"
            ref = by_slug.get(f"{repo}#{number}") if repo else by_number.get(int(number))
            found.append(Blocker(text=text, resolved=ref))

    if found:
        # An explicit machine-readable declaration is the author being precise;
        # prose in the same body is then commentary on it, not a second list.
        return tuple(found)

    for prose in _BLOCKED_ON_RE.findall(body or ""):
        for clause in _CONNECTIVE_RE.split(prose):
            name = _QUALIFIER_RE.split(clause.strip(), maxsplit=1)[0].strip(" .,")
            if not name:
                continue
            found.append(Blocker(text=name, resolved=_resolve(name, candidates)))
    return tuple(found)


# ---- collection -----------------------------------------------------------


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(text).astimezone(UTC)
    except ValueError:
        return None


def _goal_milestones(slug: str, runner: Runner) -> list[dict]:
    try:
        raw = runner(["api", f"repos/{slug}/milestones?state=all&per_page=100"])
    except Exception:  # noqa: BLE001 - unreachable repo renders as absent, never as zero
        return []
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [row for row in rows if str(row.get("title", "")).startswith(GOAL_PREFIX)]


def _milestone_issues(slug: str, title: str, runner: Runner) -> list[IssueRef]:
    argv = [
        "issue",
        "list",
        "--repo",
        slug,
        "--milestone",
        title,
        "--state",
        "all",
        "--limit",
        "200",
        "--json",
        "number,title,body,labels,state,url,closedAt",
    ]
    try:
        rows = json.loads(runner(argv))
    except Exception:  # noqa: BLE001 - same absent-not-guessed rule as above
        return []
    name = slug.split("/")[-1]
    return [
        IssueRef(
            repo=name,
            number=row["number"],
            title=row.get("title", ""),
            state=row.get("state", "OPEN"),
            url=row.get("url", "") or "",
            labels=tuple(lbl["name"] for lbl in row.get("labels", []) or []),
            body=row.get("body", "") or "",
            closed_at=row.get("closedAt", "") or "",
        )
        for row in rows
    ]


def collect(repos: Sequence[str], *, runner: Runner = _gh) -> tuple[GoalView, ...]:
    # Repos are passed in rather than discovered: enumerating the org is a
    # policy decision (which repos count) that belongs to the caller, and both
    # callers already hold the answer.
    milestones: dict[str, list[tuple[str, dict]]] = {}
    for slug in repos:
        for row in _goal_milestones(slug, runner):
            milestones.setdefault(row["title"], []).append((slug, row))

    views: list[GoalView] = []
    for title, entries in sorted(milestones.items()):
        issues: list[IssueRef] = []
        parts: list[GoalPart] = []
        description = ""
        due_on = ""
        for slug, row in entries:
            issues += _milestone_issues(slug, title, runner)
            parts.append(
                GoalPart(
                    repo=slug.split("/")[-1],
                    open_issues=row.get("open_issues", 0),
                    closed_issues=row.get("closed_issues", 0),
                    url=row.get("html_url", "") or "",
                )
            )
            # The same goal is a milestone in every repo it touches, so its
            # description is written N times. Longest wins: the repos that
            # were milestoned later usually carry a stub or an empty string.
            if len(row.get("description") or "") > len(description):
                description = row.get("description") or ""
            due_on = due_on or (row.get("due_on") or "")

        statement, done_when, phases = parse_description(description)
        claimed = {
            issue.slug: found
            for issue in issues
            if (found := blockers(issue.body, [c for c in issues if c.slug != issue.slug]))
        }
        views.append(
            GoalView(
                goal_id=title,
                statement=statement,
                done_when=done_when,
                phases=phases,
                due_on=due_on,
                description=description,
                parts=tuple(sorted(parts, key=lambda p: p.repo)),
                issues=tuple(issues),
                blockers=claimed,
            )
        )
    return tuple(views)
