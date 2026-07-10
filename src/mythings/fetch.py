from __future__ import annotations

import re
import urllib.error
import urllib.request
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse

# One deterministic, dependency-free way to turn a URL into clean text lives
# here and nowhere else. my-scraper grew the original; my-researcher,
# my-librarian, my-news and anything else that wants "fetch a page politely and
# read it" would otherwise each re-derive robots handling, HTML stripping, and
# the get/robots injection seam -- and drift on the details that matter (which
# tags to drop, whether a missing robots.txt means allow or deny, what counts
# as an empty page). Promoting it makes those decisions fleet-wide facts.
#
# Stdlib only (urllib + html.parser): core declares no runtime dependencies and
# that stays true. This is a fetching *primitive*, not a browser -- JS-rendered
# pages yield thin text and fall into the `empty` skip path by design. A
# headless-browser mode would pull in a real dependency and is deliberately out.
#
# Network is injected, never assumed. `get` and `robots_allowed` default to the
# real urllib implementations but every test swaps them for fakes, so the
# default suite touches no network -- the same seam pattern as engine.Runner and
# github.Runner. Nothing here runs at import; `fetch()` is inert until called.

USER_AGENT = "MyThings/0.1 (+https://github.com/MyThingsLab)"

# A Getter takes a URL and returns the raw response body as text, or raises.
Getter = Callable[[str], str]

# A RobotsChecker takes (url, user_agent) and returns whether fetching is
# allowed. The default fetches robots.txt over urllib; tests inject a fake.
RobotsChecker = Callable[[str, str], bool]

_SKIP_TAGS = {"script", "style", "nav", "footer"}


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    # set when ok is False: "robots_disallowed" | "fetch_error" | "empty"
    reason: str = ""
    text: str = ""
    # True when max_chars was applied and the source was longer.
    truncated: bool = False


def default_get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def default_robots_allowed(url: str, user_agent: str) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
    except OSError:
        # robots.txt unreachable -- default to allowed, don't punish a site
        # that has none rather than one that explicitly disallows us.
        return True
    return parser.can_fetch(user_agent, url)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._chunks.append(data)

    def text(self) -> str:
        return " ".join(self._chunks)


def strip_html(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    return re.sub(r"\s+", " ", extractor.text()).strip()


def fetch(
    url: str,
    *,
    get: Getter = default_get,
    robots_allowed: RobotsChecker = default_robots_allowed,
    user_agent: str = USER_AGENT,
    max_chars: int | None = None,
) -> FetchResult:
    if not robots_allowed(url, user_agent):
        return FetchResult(ok=False, reason="robots_disallowed")
    try:
        html = get(url)
    except (urllib.error.URLError, OSError, ValueError):
        return FetchResult(ok=False, reason="fetch_error")
    text = strip_html(html)
    if not text:
        return FetchResult(ok=False, reason="empty")
    truncated = max_chars is not None and len(text) > max_chars
    if truncated:
        text = text[:max_chars]
    return FetchResult(ok=True, text=text, truncated=truncated)
