# SPDX-License-Identifier: Apache-2.0
"""
CSP utility functions.

Builds Content-Security-Policy header values with per-request nonces.
Extra sources can be added via settings (CSP_EXTRA_SCRIPT_SRC, etc.).
"""

from __future__ import annotations


def build_csp_header(nonce: str, enforce: bool) -> tuple[str, str]:
    """
    Build the CSP header name and value.

    Extra sources from settings are appended to the base directives.

    Args:
        nonce: Per-request nonce token.
        enforce: If True, use ``Content-Security-Policy`` (blocking).
                 If False, use ``Content-Security-Policy-Report-Only``.

    Returns:
        Tuple of (header_name, header_value).
    """
    from hotframe.config.settings import get_settings

    settings = get_settings()

    extra_script = " ".join(settings.CSP_EXTRA_SCRIPT_SRC)
    extra_style = " ".join(settings.CSP_EXTRA_STYLE_SRC)
    extra_connect = " ".join(settings.CSP_EXTRA_CONNECT_SRC)
    extra_img = " ".join(settings.CSP_EXTRA_IMG_SRC)
    extra_font = " ".join(settings.CSP_EXTRA_FONT_SRC)

    if enforce:
        connect_src = f"connect-src 'self' wss://* {extra_connect}".strip()
    else:
        connect_src = f"connect-src 'self' ws://localhost:* wss://* {extra_connect}".strip()

    directives = [
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}' 'unsafe-eval' {extra_script}".strip(),
        f"style-src 'self' 'unsafe-inline' {extra_style}".strip(),
        f"img-src 'self' data: blob: {extra_img}".strip(),
        connect_src,
        f"font-src 'self' {extra_font}".strip(),
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]

    header_name = "Content-Security-Policy" if enforce else "Content-Security-Policy-Report-Only"
    header_value = "; ".join(directives)

    return header_name, header_value
