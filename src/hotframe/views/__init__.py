"""
views — HTMX view helpers, Turbo Streams, SSE responses, and real-time broadcasting.

``htmx_view`` is the main decorator/factory for Hub route handlers: it
selects the partial or full-page template based on the ``HX-Request``
header, injects the current user, permissions, and flash messages, and
returns an ``HTMLResponse``. ``TurboStream`` builds Turbo Stream HTML
fragments for out-of-band DOM updates. ``sse_stream`` yields a
``StreamingResponse`` for Server-Sent Events. ``BroadcastHub`` provides
topic-based fan-out for real-time SSE/WS broadcasting to connected clients.

Key exports::

    from hotframe.views.responses import htmx_view, htmx_redirect, sse_stream
    from hotframe.views.streams import TurboStream
    from hotframe.views.broadcast import BroadcastHub, broadcast_router, get_broadcast_hub

Usage::

    @router.get("/products")
    @htmx_view(template="products/list.html", partial="products/_rows.html")
    async def product_list(request: Request): ...
"""
