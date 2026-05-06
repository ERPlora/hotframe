from datastar_py import attribute_generator as reactive
from datastar_py.fastapi import (
    SSE_HEADERS,
    ReadSignals,
    ServerSentEventGenerator,
    read_signals,
)
from datastar_py.fastapi import (
    DatastarResponse as SSEResponse,  # ← standard SSE
)
from datastar_py.fastapi import (
    datastar_response as sse_response,  # ← decorator, "sse_" reads well
)

__all__ = [
    "SSE_HEADERS",
    "ReadSignals",
    "SSEResponse",  # class Response
    "ServerSentEventGenerator",
    "reactive",  # alias for attribute_generator (no standard)
    "read_signals",
    "sse_response",  # decorator
]
