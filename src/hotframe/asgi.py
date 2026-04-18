"""
Runtime ASGI entry point.

Wrapped with ProxyFixMiddleware (outermost layer).
Usage: ``uvicorn hotframe.asgi:application``
"""

from hotframe.bootstrap import create_app
from hotframe.middleware.proxy_fix import ProxyFixMiddleware

application = ProxyFixMiddleware(create_app())
