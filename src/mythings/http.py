from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from mythings.fetch import USER_AGENT

# One deterministic, dependency-free way to call a JSON/XML *API* lives here and
# nowhere else. This is the sibling of `mythings.fetch`, not a duplicate of it:
# `fetch` reads a *page* politely (robots.txt, HTML stripping, degrade-to-reason
# on failure); `http` calls a *known endpoint* (Crossref, arXiv, OpenLibrary,
# PyPI, npm, Tavily) where robots does not apply, the body is structured, and a
# non-200 is a fact the caller wants to handle rather than a page to skip.
#
# It is promoted rather than written: my-researcher, my-bibliography,
# my-textbook and my-librarian each carried a byte-identical private `_http`
# with the same signature, the same 30s timeout and the same urllib audit
# suppression. Four copies means four places for a timeout, a retry policy or a
# User-Agent fix to be applied three times and forgotten once.
#
# Stdlib only (urllib): core declares no runtime dependencies and that stays
# true.
#
# Errors propagate. `urllib.error.HTTPError`/`URLError` are raised to the
# caller, deliberately: registries differ in what a 4xx *means* (npm returns
# ERR_TEXT_LENGTH for an over-long query, which my-librarian degrades to an
# empty result set; a Crossref 404 is a genuine miss). Swallowing them here
# would force every caller to re-derive the distinction from an empty body.
#
# Network is injected, never assumed. `Fetcher` is the seam every consumer
# already types its `fetch=` parameter against, so adopting this module is an
# import swap, and the default test suite touches no network.

# A Fetcher takes a URL (plus optional data/headers) and returns the raw
# response body as bytes, or raises. Deliberately `...` in the parameter
# position: consumers inject fakes with narrower signatures.
Fetcher = Callable[..., bytes]

DEFAULT_TIMEOUT_S = 30.0


def http_get(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    user_agent: str = USER_AGENT,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> bytes:
    # `data` is not GET-only: passing it makes urllib issue a POST (Tavily's
    # search endpoint). Kept on one function because every consumer's injected
    # fake is a single callable, and splitting get/post would double the seam.
    request_headers = {"User-Agent": user_agent, **(headers or {})}
    request = urllib.request.Request(url, data=data, headers=request_headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed API endpoints
        body: bytes = response.read()
    return body


def get_json(url: str, *, fetch: Fetcher = http_get, **kwargs: Any) -> Any:
    # Three of the four promoted consumers wrote `json.loads(fetch(url))`; the
    # fourth parses Atom XML and keeps calling `fetch` directly.
    return json.loads(fetch(url, **kwargs))


def with_params(url: str, params: dict[str, Any]) -> str:
    # Sorted so a given params dict always produces the same URL: fakes in tests
    # key off the exact string, and a stable URL is a cacheable one.
    encoded = urllib.parse.urlencode({k: v for k, v in sorted(params.items()) if v is not None})
    return f"{url}?{encoded}" if encoded else url
