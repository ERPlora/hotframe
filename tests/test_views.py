"""Tests for hotframe.views."""
from hotframe.views.responses import (
    htmx_redirect,
    htmx_refresh,
    htmx_trigger,
)
from hotframe.views.streams import StreamResponse, TurboStream


class TestHTMXHelpers:
    def test_htmx_redirect(self):
        response = htmx_redirect("/login")
        assert response.headers["HX-Redirect"] == "/login"
        assert response.status_code == 200

    def test_htmx_refresh(self):
        response = htmx_refresh()
        assert response.headers["HX-Refresh"] == "true"

    def test_htmx_trigger_simple(self):
        result = htmx_trigger("cartUpdated")
        assert result == {"cartUpdated": True}

    def test_htmx_trigger_with_data(self):
        result = htmx_trigger("cartUpdated", {"count": 5})
        assert result == {"cartUpdated": {"count": 5}}


class TestTurboStream:
    def test_append(self):
        stream = TurboStream.append("#list", html="<li>new</li>")
        oob = stream.to_oob_html()
        assert 'id="list"' in oob
        assert 'hx-swap-oob="beforeend"' in oob
        assert "<li>new</li>" in oob

    def test_replace(self):
        stream = TurboStream.replace("#form", html="<form>new</form>")
        oob = stream.to_oob_html()
        assert 'hx-swap-oob="outerHTML"' in oob

    def test_update(self):
        stream = TurboStream.update("#count", html="42")
        oob = stream.to_oob_html()
        assert 'hx-swap-oob="innerHTML"' in oob
        assert "42" in oob

    def test_remove(self):
        stream = TurboStream.remove("#empty")
        oob = stream.to_oob_html()
        assert 'hx-swap-oob="delete"' in oob

    def test_prepend(self):
        stream = TurboStream.prepend("#list", html="<li>first</li>")
        oob = stream.to_oob_html()
        assert 'hx-swap-oob="afterbegin"' in oob

    def test_morph(self):
        stream = TurboStream.morph("#item", html="<div>morphed</div>")
        oob = stream.to_oob_html()
        assert 'hx-swap-oob="morph:outerHTML"' in oob

    def test_text_escapes(self):
        stream = TurboStream.text("#count", "<script>alert(1)</script>")
        oob = stream.to_oob_html()
        assert "<script>" not in oob
        assert "&lt;script&gt;" in oob

    def test_stream_response(self):
        response = StreamResponse(
            TurboStream.append("#list", html="<li>1</li>"),
            TurboStream.text("#count", "1"),
        )
        body = response.body.decode()
        assert 'id="list"' in body
        assert 'id="count"' in body


class TestBroadcast:
    def test_broadcast_hub_import(self):
        from hotframe.views.broadcast import BroadcastHub
        hub = BroadcastHub()
        assert hub is not None
