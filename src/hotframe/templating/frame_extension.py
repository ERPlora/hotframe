"""
Jinja2 extension for HTMX frames (equivalent to Turbo Frames).

Provides a ``{% frame %}`` tag that generates HTMX-powered containers
with automatic ``hx-get``, ``hx-trigger``, ``hx-swap`` attributes.

Usage::

    {% frame "comments" src="/api/comments" %}
        <p>Loading...</p>
    {% endframe %}

    {% frame "sidebar" src="/sidebar" lazy=true %}
        <div class="skeleton h-32"></div>
    {% endframe %}

    {% frame "search-results" %}
        <div id="search-results">
            {% for item in items %}...{% endfor %}
        </div>
    {% endframe %}
"""

from __future__ import annotations

from jinja2 import nodes
from jinja2.ext import Extension


class FrameExtension(Extension):
    """Jinja2 extension for HTMX frames (equivalent to Turbo Frames)."""

    tags = {"frame"}

    def parse(self, parser):
        lineno = next(parser.stream).lineno

        # Parse frame ID (required)
        frame_id = parser.parse_expression()

        # Parse optional kwargs as Keyword nodes
        kwargs = []
        while parser.stream.current.test("name") and parser.stream.current.value in (
            "src",
            "lazy",
            "swap",
            "trigger",
            "target",
            "push_url",
        ):
            key = parser.stream.expect("name").value
            parser.stream.expect("assign")
            value = parser.parse_expression()
            kwargs.append(nodes.Keyword(key, value, lineno=value.lineno))

        # Parse body
        body = parser.parse_statements(["name:endframe"], drop_needle=True)

        return nodes.CallBlock(
            self.call_method("_render_frame", [frame_id], kwargs),
            [],
            [],
            body,
        ).set_lineno(lineno)

    def _render_frame(
        self,
        frame_id,
        src=None,
        lazy=False,
        swap="innerHTML",
        trigger=None,
        target=None,
        push_url=False,
        caller=None,
    ):
        attrs = [f'id="{frame_id}"']

        if src:
            attrs.append(f'hx-get="{src}"')
            if lazy:
                attrs.append('hx-trigger="revealed"')
            else:
                attrs.append('hx-trigger="load"')
            attrs.append(f'hx-swap="{swap}"')
        elif target:
            attrs.append(f'hx-target="{target}"')

        if push_url:
            attrs.append('hx-push-url="true"')

        if trigger and not lazy:
            attrs.append(f'hx-trigger="{trigger}"')

        attr_str = " ".join(attrs)
        inner = caller()
        return f"<div {attr_str}>{inner}</div>"
