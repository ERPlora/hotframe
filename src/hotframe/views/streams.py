"""
Multi-fragment HTMX responses (Turbo Streams equivalent).

Allows a single HTTP response to update multiple parts of the page
using HTMX's native OOB (Out-of-Band) swap mechanism.

Usage::

    from hotframe.views.streams import TurboStream, StreamResponse

    @router.post("/todos/")
    @htmx_view(module_id="todo", view_id="create")
    async def create_todo(request):
        todo = await Todo.create(title=request.form["title"])
        count = await Todo.count()
        return StreamResponse(
            TurboStream.append("#todo-list", html="<li>new item</li>"),
            TurboStream.text("#todo-count", str(count)),
            TurboStream.remove("#empty-state"),
        )
"""

from __future__ import annotations

from dataclasses import dataclass

from starlette.responses import HTMLResponse


@dataclass(frozen=True, slots=True)
class TurboStream:
    """A single OOB fragment to include in a StreamResponse."""

    target: str
    action: str  # innerHTML, outerHTML, beforeend, afterbegin, beforebegin, afterend, delete, morph:outerHTML
    html: str

    # --- Factory methods (most common actions) ---

    @classmethod
    def replace(cls, target: str, *, html: str = "") -> TurboStream:
        """Replace the target element entirely (outerHTML)."""
        return cls(target=target, action="outerHTML", html=html)

    @classmethod
    def update(cls, target: str, *, html: str = "") -> TurboStream:
        """Update the target's inner content (innerHTML)."""
        return cls(target=target, action="innerHTML", html=html)

    @classmethod
    def append(cls, target: str, *, html: str = "") -> TurboStream:
        """Append content to the end of the target (beforeend)."""
        return cls(target=target, action="beforeend", html=html)

    @classmethod
    def prepend(cls, target: str, *, html: str = "") -> TurboStream:
        """Prepend content to the beginning of the target (afterbegin)."""
        return cls(target=target, action="afterbegin", html=html)

    @classmethod
    def before(cls, target: str, *, html: str = "") -> TurboStream:
        """Insert content before the target (beforebegin)."""
        return cls(target=target, action="beforebegin", html=html)

    @classmethod
    def after(cls, target: str, *, html: str = "") -> TurboStream:
        """Insert content after the target (afterend)."""
        return cls(target=target, action="afterend", html=html)

    @classmethod
    def remove(cls, target: str) -> TurboStream:
        """Remove the target element from the DOM."""
        return cls(target=target, action="delete", html="")

    @classmethod
    def morph(cls, target: str, *, html: str = "") -> TurboStream:
        """Morph the target (diff-based update, preserves state)."""
        return cls(target=target, action="morph:outerHTML", html=html)

    @classmethod
    def text(cls, target: str, content: str) -> TurboStream:
        """Update the target's text content (innerHTML with escaped text)."""
        from markupsafe import escape

        return cls(target=target, action="innerHTML", html=str(escape(content)))

    def to_oob_html(self) -> str:
        """Render as an HTMX OOB swap element."""
        target_id = self.target.lstrip("#")
        if self.action == "delete":
            return f'<div id="{target_id}" hx-swap-oob="delete"></div>'
        return f'<div id="{target_id}" hx-swap-oob="{self.action}">{self.html}</div>'


class StreamResponse(HTMLResponse):
    """HTTP response containing multiple OOB swaps.

    The first fragment is the "main" content (rendered normally).
    Subsequent fragments are appended as OOB swaps.

    Usage::

        return StreamResponse(
            TurboStream.append("#list", html=rendered_item),
            TurboStream.text("#count", "42"),
            TurboStream.remove("#empty-state"),
        )
    """

    def __init__(
        self,
        *streams: TurboStream,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        main_content: str = "",
    ) -> None:
        parts = [main_content] if main_content else []
        for stream in streams:
            parts.append(stream.to_oob_html())
        body = "\n".join(parts)
        super().__init__(content=body, status_code=status_code, headers=headers)
