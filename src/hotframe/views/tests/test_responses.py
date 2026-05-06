"""Tests for hotframe.views."""

from __future__ import annotations

import asyncio

import pytest
from starlette.requests import Request

from hotframe.views.responses import (
    add_message,
    htmx_redirect,
    htmx_refresh,
    htmx_trigger,
    htmx_view,
    is_htmx_request,
    is_reactive_request,
    reactive_message,
    reactive_redirect,
    reactive_refresh,
    reactive_trigger,
    view,
)


def _make_request(headers: dict[str, str] | None = None, query: str = "") -> Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw_headers,
        "query_string": query.encode(),
    }
    return Request(scope)


async def _collect_body(response) -> str:
    chunks: list[bytes] = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, str):
            chunks.append(chunk.encode())
        else:
            chunks.append(chunk)
    return b"".join(chunks).decode("utf-8")


def _body(response) -> str:
    """Run _collect_body on a fresh loop so it works inside pytest-asyncio tests too."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_collect_body(response))
    # We're inside an event loop — drain on a new one in a worker thread.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, _collect_body(response)).result()


class TestIsReactiveRequest:
    def test_detects_datastar_header(self):
        req = _make_request({"Datastar-Request": "true"})
        assert is_reactive_request(req) is True

    def test_no_header_no_query(self):
        req = _make_request()
        assert is_reactive_request(req) is False

    def test_partial_query_param_escape_hatch(self):
        req = _make_request(query="partial=true")
        assert is_reactive_request(req) is True

    def test_legacy_alias(self):
        """is_htmx_request is the backward-compat alias for is_reactive_request."""
        req = _make_request({"Datastar-Request": "true"})
        assert is_htmx_request(req) is True
        assert is_htmx_request(_make_request()) is False


class TestReactiveRedirect:
    def test_returns_sse_event_with_redirect(self):
        response = reactive_redirect("/login")
        body = _body(response)
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "datastar-patch-elements" in body
        assert "/login" in body

    def test_legacy_htmx_redirect_alias(self):
        response = htmx_redirect("/login")
        body = _body(response)
        assert "/login" in body
        assert "datastar-patch-elements" in body


class TestReactiveRefresh:
    def test_emits_location_reload(self):
        response = reactive_refresh()
        body = _body(response)
        assert "location.reload()" in body
        assert "datastar-patch-elements" in body

    def test_legacy_htmx_refresh_alias(self):
        response = htmx_refresh()
        body = _body(response)
        assert "location.reload()" in body


class TestReactiveTrigger:
    def test_dispatches_custom_event(self):
        response = reactive_trigger("cartUpdated", count=5)
        body = _body(response)
        assert "cartUpdated" in body
        assert "dispatchEvent" in body
        assert "CustomEvent" in body
        assert '"count": 5' in body or '"count":5' in body

    def test_no_detail(self):
        response = reactive_trigger("ping")
        body = _body(response)
        assert "ping" in body
        assert "dispatchEvent" in body


class TestLegacyHtmxTrigger:
    def test_htmx_trigger_simple(self):
        # Legacy compat shim: still returns a dict payload.
        result = htmx_trigger("cartUpdated")
        assert result == {"cartUpdated": True}

    def test_htmx_trigger_with_data(self):
        result = htmx_trigger("cartUpdated", {"count": 5})
        assert result == {"cartUpdated": {"count": 5}}


class TestReactiveMessage:
    def test_emits_toast_patch(self):
        response = reactive_message("success", "Item created")
        body = _body(response)
        assert "datastar-patch-elements" in body
        assert "#toast-container" in body
        assert "Item created" in body
        assert "toast-success" in body

    def test_escapes_html(self):
        response = reactive_message("info", "<script>alert(1)</script>")
        body = _body(response)
        assert "<script>alert" not in body
        assert "&lt;script&gt;" in body


class TestAddMessage:
    def test_appends_to_request_state(self):
        req = _make_request()
        add_message(req, "success", "Saved")
        add_message(req, "error", "Oops")
        assert req.state._messages == [
            {"level": "success", "text": "Saved"},
            {"level": "error", "text": "Oops"},
        ]


class TestViewDecorator:
    """The new `view` decorator detects Datastar via the request header.

    These tests run the wrapper directly with a stub Request — they do
    not exercise template rendering (covered by integration tests).
    """

    def test_view_is_callable_and_alias_matches(self):
        assert callable(view)
        # htmx_view kept as alias during 0.2.x.
        assert htmx_view is view

    @pytest.mark.asyncio
    async def test_login_required_redirects_full_page_when_not_reactive(self, monkeypatch):
        from hotframe.config.settings import HotframeSettings

        # Monkeypatch get_settings so AUTH_LOGIN_URL is deterministic.
        settings = HotframeSettings(AUTH_LOGIN_URL="/login")
        monkeypatch.setattr(
            "hotframe.config.settings.get_settings", lambda: settings
        )
        # Stub session_user_id to None.
        monkeypatch.setattr(
            "hotframe.views.responses.get_session_user_id", lambda r: None
        )

        @view(login_required=True)
        async def handler(request):  # pragma: no cover — auth blocks before call
            return {}

        req = _make_request()
        resp = await handler(req)
        # Plain HTTP redirect, not a reactive SSE redirect.
        assert resp.status_code == 302
        assert resp.headers["location"] == "/login"

    @pytest.mark.asyncio
    async def test_login_required_returns_reactive_redirect_when_datastar(
        self, monkeypatch
    ):
        from hotframe.config.settings import HotframeSettings

        settings = HotframeSettings(AUTH_LOGIN_URL="/login")
        monkeypatch.setattr(
            "hotframe.config.settings.get_settings", lambda: settings
        )
        monkeypatch.setattr(
            "hotframe.views.responses.get_session_user_id", lambda r: None
        )

        @view(login_required=True)
        async def handler(request):  # pragma: no cover
            return {}

        req = _make_request({"Datastar-Request": "true"})
        resp = await handler(req)
        body = _body(resp)
        # Reactive redirect = streaming SSE event, not a 302.
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert "/login" in body


class TestBroadcast:
    def test_broadcast_hub_import(self):
        from hotframe.views.broadcast import BroadcastHub

        hub = BroadcastHub()
        assert hub is not None
