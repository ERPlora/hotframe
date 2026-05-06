"""
Jinja2 extension for Datastar frames (equivalent to Turbo Frames).

Provides a ``{% frame %}`` tag that generates Datastar-powered containers
emitting ``data-on-intersect`` / ``data-on:load`` / ``data-on:<event>``
attributes that drive a server-sent fragment stream.

Usage::

    {% frame "comments" src="/api/comments" %}
        <p>Loading...</p>
    {% endframe %}

    {% frame "sidebar" src="/sidebar" lazy=true %}
        <div class="skeleton h-32"></div>
    {% endframe %}

    {% frame "search-results" trigger="click" src="/search" %}
        <div>Click to load</div>
    {% endframe %}

The tag signature is preserved for backward compatibility; ``swap`` and
``target`` are accepted but no longer emitted into the markup because in
Datastar the server controls element selection via ``patch_elements``.
``push_url=true`` is forwarded as ``{history: 'push'}`` to ``@get``.
"""

from __future__ import annotations

from jinja2 import nodes
from jinja2.ext import Extension


class FrameExtension(Extension):
    """Jinja2 extension for Datastar frames (equivalent to Turbo Frames)."""

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
        swap="innerHTML",  # accepted for back-compat, not emitted in Datastar
        trigger=None,
        target=None,  # accepted for back-compat, not emitted in Datastar
        push_url=False,
        caller=None,
    ):
        attrs = [f'id="{frame_id}"']

        if src:
            # Build the Datastar action expression: @get('/url'[, {history: 'push'}])
            if push_url:
                action = f"@get('{src}', {{history: 'push'}})"
            else:
                action = f"@get('{src}')"

            if lazy:
                # Lazy load when the frame scrolls into view.
                attrs.append(f'data-on-intersect="{action}"')
            elif trigger and trigger != "load":
                # Custom DOM event (click, mouseenter, etc.)
                attrs.append(f'data-on:{trigger}="{action}"')
            else:
                # Default: fire as soon as the element is mounted.
                attrs.append(f'data-on:load="{action}"')

        attr_str = " ".join(attrs)
        inner = caller()
        return f"<div {attr_str}>{inner}</div>"
