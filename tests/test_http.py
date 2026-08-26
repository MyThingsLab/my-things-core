from __future__ import annotations

import io
import urllib.error
import urllib.request
from typing import Any

import pytest

from mythings.fetch import USER_AGENT
from mythings.http import DEFAULT_TIMEOUT_S, get_json, http_get, with_params


class _FakeResponse(io.BytesIO):
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def _urlopen(request: urllib.request.Request, timeout: float | None = None) -> _FakeResponse:
        seen["request"] = request
        seen["timeout"] = timeout
        return _FakeResponse(b'{"ok": true}')

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    return seen


def test_http_get_returns_body_bytes(captured: dict[str, Any]) -> None:
    assert http_get("https://api.example.com/x") == b'{"ok": true}'


def test_http_get_sends_the_fleet_user_agent(captured: dict[str, Any]) -> None:
    http_get("https://api.example.com/x")
    assert captured["request"].get_header("User-agent") == USER_AGENT


def test_http_get_lets_a_caller_override_the_user_agent(captured: dict[str, Any]) -> None:
    # Crossref etiquette wants a contactable mailto UA; my-bibliography relies
    # on this being per-call rather than a module constant.
    http_get("https://api.crossref.org/works", user_agent="my-bibliography (mailto:x@y.z)")
    assert captured["request"].get_header("User-agent") == "my-bibliography (mailto:x@y.z)"


def test_http_get_merges_extra_headers_over_the_default(captured: dict[str, Any]) -> None:
    http_get("https://api.example.com/x", headers={"Accept": "application/json"})
    assert captured["request"].get_header("Accept") == "application/json"
    assert captured["request"].get_header("User-agent") == USER_AGENT


def test_http_get_issues_a_post_when_data_is_given(captured: dict[str, Any]) -> None:
    http_get("https://api.tavily.com/search", data=b'{"q": "x"}')
    request = captured["request"]
    assert request.get_method() == "POST"
    assert request.data == b'{"q": "x"}'


def test_http_get_issues_a_get_without_data(captured: dict[str, Any]) -> None:
    http_get("https://api.example.com/x")
    assert captured["request"].get_method() == "GET"


def test_http_get_applies_the_default_timeout(captured: dict[str, Any]) -> None:
    http_get("https://api.example.com/x")
    assert captured["timeout"] == DEFAULT_TIMEOUT_S


def test_http_get_applies_an_overridden_timeout(captured: dict[str, Any]) -> None:
    http_get("https://api.example.com/x", timeout=1.5)
    assert captured["timeout"] == 1.5


def test_http_get_propagates_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    # Deliberate: npm returns 400 ERR_TEXT_LENGTH for an over-long query and
    # my-librarian degrades that to an empty result set. Swallowing it here
    # would erase the distinction between "bad query" and "no matches".
    def _raise(request: object, timeout: float | None = None) -> None:
        raise urllib.error.HTTPError("https://x", 400, "Bad Request", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(urllib.request, "urlopen", _raise)
    with pytest.raises(urllib.error.HTTPError):
        http_get("https://registry.npmjs.org/-/v1/search")


def test_get_json_parses_an_injected_fetchers_body() -> None:
    assert get_json("https://api.example.com/x", fetch=lambda url: b'{"a": [1, 2]}') == {
        "a": [1, 2]
    }


def test_get_json_forwards_kwargs_to_the_fetcher() -> None:
    seen: dict[str, Any] = {}

    def _fetch(url: str, **kwargs: Any) -> bytes:
        seen.update(kwargs)
        return b"{}"

    get_json("https://api.example.com/x", fetch=_fetch, headers={"Accept": "application/json"})
    assert seen == {"headers": {"Accept": "application/json"}}


def test_get_json_defaults_to_the_real_fetcher(captured: dict[str, Any]) -> None:
    assert get_json("https://api.example.com/x") == {"ok": True}


def test_with_params_sorts_keys_for_a_stable_url() -> None:
    assert (
        with_params("https://api.example.com/s", {"q": "gauge", "limit": 10})
        == "https://api.example.com/s?limit=10&q=gauge"
    )


def test_with_params_drops_none_valued_params() -> None:
    assert (
        with_params("https://api.example.com/s", {"q": "x", "cursor": None})
        == "https://api.example.com/s?q=x"
    )


def test_with_params_returns_a_bare_url_when_nothing_is_left() -> None:
    assert with_params("https://api.example.com/s", {"cursor": None}) == "https://api.example.com/s"


def test_with_params_url_encodes_values() -> None:
    assert with_params("https://x/y", {"q": "a b&c"}) == "https://x/y?q=a+b%26c"


def test_module_name_does_not_shadow_the_stdlib_http_package() -> None:
    # `mythings/http.py` sits next to a stdlib top-level package of the same
    # name; absolute imports keep them distinct, and urllib depends on it.
    import http.client

    import mythings.http

    assert http.client.HTTPConnection is not None
    assert mythings.http.http_get is http_get
