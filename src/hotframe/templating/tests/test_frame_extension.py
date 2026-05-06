"""Tests for the Datastar-powered ``{% frame %}`` Jinja2 extension."""

from __future__ import annotations

from jinja2 import Environment

from hotframe.templating.frame_extension import FrameExtension


def _render(template_source: str) -> str:
    env = Environment(extensions=[FrameExtension], autoescape=False)
    return env.from_string(template_source).render()


class TestFrameExtensionDatastar:
    """The frame tag must emit Datastar attributes, never HTMX ones."""

    def test_frame_lazy_emits_intersect(self):
        out = _render(
            "{% frame 'foo' src='/x' lazy=true %}<p>fallback</p>{% endframe %}"
        )
        assert 'id="foo"' in out
        assert "data-on-intersect=\"@get('/x')\"" in out
        assert "<p>fallback</p>" in out
        # No HTMX bleed.
        assert "hx-" not in out

    def test_frame_eager_emits_on_load(self):
        out = _render("{% frame 'foo' src='/x' %}{% endframe %}")
        assert 'id="foo"' in out
        assert "data-on:load=\"@get('/x')\"" in out
        assert "data-on-intersect" not in out
        assert "hx-" not in out

    def test_frame_click_trigger(self):
        out = _render(
            "{% frame 'foo' src='/x' trigger='click' %}click me{% endframe %}"
        )
        assert "data-on:click=\"@get('/x')\"" in out
        assert "data-on:load" not in out
        assert "hx-" not in out

    def test_frame_explicit_load_trigger(self):
        # trigger='load' is the default behavior; should still emit data-on:load.
        out = _render(
            "{% frame 'foo' src='/x' trigger='load' %}{% endframe %}"
        )
        assert "data-on:load=\"@get('/x')\"" in out

    def test_frame_lazy_takes_precedence_over_trigger(self):
        out = _render(
            "{% frame 'foo' src='/x' lazy=true trigger='click' %}{% endframe %}"
        )
        assert "data-on-intersect=\"@get('/x')\"" in out
        assert "data-on:click" not in out

    def test_frame_push_url_history(self):
        out = _render(
            "{% frame 'foo' src='/x' push_url=true %}{% endframe %}"
        )
        assert "data-on:load=\"@get('/x', {history: 'push'})\"" in out
        assert "hx-push-url" not in out

    def test_frame_without_src_emits_only_id(self):
        out = _render("{% frame 'foo' %}body{% endframe %}")
        assert 'id="foo"' in out
        assert "data-on" not in out
        assert "@get" not in out
        assert "body" in out

    def test_frame_swap_and_target_are_silently_ignored(self):
        # Datastar drives selection from the server (patch_elements), so swap
        # and target must not leak into the rendered markup, but they remain
        # accepted kwargs for backwards compatibility with old templates.
        out = _render(
            "{% frame 'foo' src='/x' swap='outerHTML' target='#bar' %}{% endframe %}"
        )
        assert "swap" not in out
        assert "target" not in out
        assert "#bar" not in out
        assert "data-on:load=\"@get('/x')\"" in out

    def test_frame_body_is_preserved(self):
        out = _render(
            "{% frame 'foo' src='/x' lazy=true %}"
            "<div class='skeleton'>loading</div>"
            "{% endframe %}"
        )
        assert "<div class='skeleton'>loading</div>" in out
