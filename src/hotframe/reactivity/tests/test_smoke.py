"""Smoke tests for hotframe.reactivity.

Checks that the subsystem loads and that `reactive` works.

It does not test re-export behavior (that is datastar-py's responsibility);
it only verifies that the facade is correctly built.
"""


def test_datastar_py_installed():
    """The SDK Datastar 1.x is installed and can be imported."""
    import datastar_py  # noqa: F401


def test_facade_reexports_all_neutral_names():
    """hotframe.reactivity exposes the 7 public symbols with their neutral names."""
    from hotframe.reactivity import (  # noqa: F401
        SSE_HEADERS,
        ReadSignals,
        ServerSentEventGenerator,
        SSEResponse,
        reactive,
        read_signals,
        sse_response,
    )


def test_reactive_generates_data_on_attribute():
    """`reactive.on('click', ...)` creates a `data-on:click=...` attribute."""
    from hotframe.reactivity import reactive

    rendered = str(reactive.on("click", "@get('/x')"))
    assert rendered.startswith("data-on:click")
    assert "@get(" in rendered


def test_reactive_supports_modifier_chaining():
    """Modifiers (`debounce`, `once`) are concatenated with `__`."""
    from hotframe.reactivity import reactive

    rendered = str(reactive.on("click", "x").debounce(300))
    assert "__debounce.300" in rendered

    rendered_once = str(reactive.on("click", "x").once)
    assert "__once" in rendered_once


def test_sse_headers_has_event_stream_content_type():
    """Los headers SSE incluyen el content-type estándar."""
    from hotframe.reactivity import SSE_HEADERS

    assert SSE_HEADERS["Content-Type"] == "text/event-stream"


def test_sse_response_is_a_starlette_response():
    """SSEResponse hereda de StreamingResponse (la base de Starlette)."""
    from starlette.responses import StreamingResponse

    from hotframe.reactivity import SSEResponse

    assert issubclass(SSEResponse, StreamingResponse)


def test_server_sent_event_generator_has_patch_methods():
    """La API de eventos SSE expone patch_elements y patch_signals."""
    from hotframe.reactivity import ServerSentEventGenerator

    assert hasattr(ServerSentEventGenerator, "patch_elements")
    assert hasattr(ServerSentEventGenerator, "patch_signals")


def test_reactive_is_jinja_global():
    """reactive está registrado como global de Jinja2."""
    import tempfile
    from pathlib import Path

    from hotframe.templating.engine import create_template_engine

    with tempfile.TemporaryDirectory() as tmp:
        templates = create_template_engine(modules_dir=Path(tmp))
        assert "reactive" in templates.env.globals
