# SPDX-License-Identifier: Apache-2.0
"""
Hotframe CLI — project management commands.

Usage::

    hf startproject myapp
    hf startapp accounts
    hf startmodule blog
    hf runserver
    hf migrate
    hf makemigrations
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import typer

app = typer.Typer(
    name="hotframe",
    help="Hotframe — Modular Python web framework CLI.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# startproject
# ---------------------------------------------------------------------------


@app.command()
def startproject(name: str) -> None:
    """Create a new hotframe project. Use '.' to create in the current directory."""
    if name == ".":
        project_dir = Path.cwd()
        name = project_dir.name
        # Check it's empty enough (allow .venv, pyproject.toml, uv.lock)
        existing = {p.name for p in project_dir.iterdir()} - {
            ".venv",
            "pyproject.toml",
            "uv.lock",
            ".git",
            ".gitignore",
            "__pycache__",
            ".python-version",
        }
        if existing:
            typer.echo(
                f"Error: directory is not empty. Found: {', '.join(sorted(existing))}", err=True
            )
            raise typer.Exit(1)
    else:
        project_dir = Path(name)
        if project_dir.exists():
            typer.echo(f"Error: directory '{name}' already exists.", err=True)
            raise typer.Exit(1)
        project_dir.mkdir(parents=True)

    # main.py
    (project_dir / "main.py").write_text(
        dedent("""\
        from hotframe import create_app
        from settings import settings

        app = create_app(settings)
    """)
    )

    # asgi.py
    (project_dir / "asgi.py").write_text(
        dedent("""\
        from main import app  # noqa: F401
        # uvicorn asgi:app
    """)
    )

    # settings.py
    (project_dir / "settings.py").write_text(
        dedent(f'''\
        from hotframe import HotframeSettings
        from pydantic_settings import SettingsConfigDict


        class Settings(HotframeSettings):
            model_config = SettingsConfigDict(
                env_prefix="{name.upper()}_",
                env_file=".env",
                env_file_encoding="utf-8",
                case_sensitive=False,
                extra="ignore",
            )

            APP_TITLE: str = "{name.replace("_", " ").title()}"

            # -----------------------------------------------------------------
            # Auth (uncomment and configure when you add user authentication)
            # -----------------------------------------------------------------
            # AUTH_USER_MODEL: str = "apps.accounts.models.User"
            # AUTH_LOGIN_URL: str = "/login"
            # AUTH_UNAUTHORIZED_URL: str = "/unauthorized"
            # PERMISSION_RESOLVER: str = ""

            # -----------------------------------------------------------------
            # CORS (uncomment to enable cross-origin requests)
            # -----------------------------------------------------------------
            # CORS_ORIGINS: list[str] = ["http://localhost:3000"]
            # CORS_METHODS: list[str] = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
            # CORS_HEADERS: list[str] = ["*"]
            # CORS_CREDENTIALS: bool = True

            # -----------------------------------------------------------------
            # CSRF (override to add exempt routes)
            # -----------------------------------------------------------------
            # CSRF_EXEMPT_PREFIXES: list[str] = ["/api/", "/health", "/static/"]

            # -----------------------------------------------------------------
            # Rate limiting
            # -----------------------------------------------------------------
            # RATE_LIMIT_API: int = 120          # requests/min for /api/
            # RATE_LIMIT_HTMX: int = 300         # requests/min for /m/
            # RATE_LIMIT_AUTH: int = 60           # requests/min for auth routes
            # RATE_LIMIT_AUTH_PREFIXES: list[str] = []

            # -----------------------------------------------------------------
            # Session
            # -----------------------------------------------------------------
            # SESSION_COOKIE_NAME: str = "session"
            # SESSION_MAX_AGE: int = 2592000     # 30 days

            # -----------------------------------------------------------------
            # Static & Media
            # -----------------------------------------------------------------
            # STATIC_ROOT: str = "./static"
            # STATIC_URL: str = "/static/"
            # MEDIA_ROOT: str = "./media"
            # MEDIA_URL: str = "/media/"
            # MEDIA_STORAGE: str = "local"       # "local" or "s3"
            # MEDIA_S3_BUCKET: str = ""

            # -----------------------------------------------------------------
            # CSP (Content Security Policy)
            #
            # CSP_ENFORCE = False (default): report-only mode, logs violations
            # CSP_ENFORCE = True: blocks any resource not explicitly allowed
            #
            # CSP_TRUSTED_TYPES = True (default): enables Trusted Types policy
            # in the CSP header and renders the JS policy in base.html so that
            # HTMX and Alpine.js work under Trusted Types enforcement.
            #
            # CSP_ALLOWED_SOURCES: allow-list of external domains per resource
            # type. The example below shows the CDNs used by base.html. Add
            # your own domains as needed (S3 buckets, Google Fonts, Stripe...).
            # -----------------------------------------------------------------
            # CSP_ENFORCE: bool = False
            # CSP_TRUSTED_TYPES: bool = True
            # CSP_ALLOWED_SOURCES: dict[str, list[str]] = {{
            #     "script": [                         # <script src="...">
            #         "https://unpkg.com",            # HTMX, Alpine.js
            #         "https://cdn.jsdelivr.net",     # Iconify
            #     ],
            #     "style": [],                        # <link rel="stylesheet">
            #     "connect": [],                      # fetch(), WebSocket
            #     "img": [],                          # <img src="...">
            #     "font": [],                         # @font-face
            # }}

            # -----------------------------------------------------------------
            # Modules
            # -----------------------------------------------------------------
            # KERNEL_MODULE_NAMES: list[str] = []
            # MODULE_MARKETPLACE_URL: str = ""
            # MODULE_STATE_MODEL: str = ""

            # -----------------------------------------------------------------
            # Extra routers (dotted paths, for routers outside apps/)
            # -----------------------------------------------------------------
            # EXTRA_ROUTERS: list[str] = []

            # -----------------------------------------------------------------
            # Template context hook (async callable: request -> dict)
            # -----------------------------------------------------------------
            # GLOBAL_CONTEXT_HOOK: str = ""

            # -----------------------------------------------------------------
            # Middleware (override to add/remove/reorder)
            # -----------------------------------------------------------------
            # MIDDLEWARE: list[str] = [
            #     "hotframe.middleware.timeout.TimeoutMiddleware",
            #     "hotframe.middleware.error_pages.ErrorPageMiddleware",
            #     "hotframe.middleware.body_limit.BodyLimitMiddleware",
            #     "hotframe.middleware.request_id.RequestIdMiddleware",
            #     "hotframe.middleware.rate_limit.APIRateLimitMiddleware",
            #     "hotframe.middleware.module_middleware.ModuleMiddlewareManager",
            #     "hotframe.auth.csrf.CSRFMiddleware",
            #     "hotframe.middleware.htmx_messages.HtmxMessagesMiddleware",
            #     "hotframe.middleware.htmx.HtmxMiddleware",
            #     "hotframe.middleware.language.LanguageMiddleware",
            #     "hotframe.middleware.csp.CSPMiddleware",
            #     "hotframe.middleware.session.SessionMiddleware",
            # ]


        settings = Settings()
    ''')
    )

    # manage.py
    (project_dir / "manage.py").write_text(
        dedent('''\
        #!/usr/bin/env python
        """Management CLI — delegates to hotframe."""
        from hotframe.management.cli import app

        if __name__ == "__main__":
            app()
    ''')
    )

    # .env
    (project_dir / ".env").write_text(
        dedent("""\
        # Database (SQLite for development)
        DATABASE_URL=sqlite+aiosqlite:///./app.db
        SECRET_KEY=change-me-in-production
        DEBUG=true
    """)
    )

    # .gitignore
    (project_dir / ".gitignore").write_text(
        dedent("""\
        # Python
        __pycache__/
        *.py[cod]
        *.egg-info/
        dist/
        build/
        .venv/

        # Cache (pytest, ruff, mypy)
        .cache/

        # Environment
        .env

        # Database
        *.db
        *.sqlite3

        # IDE
        .vscode/
        .idea/
    """)
    )

    # pyproject.toml — skip if already exists (user may have uv.lock, custom deps)
    if not (project_dir / "pyproject.toml").exists():
        (project_dir / "pyproject.toml").write_text(
            dedent(f'''\
            [project]
            name = "{name}"
            version = "0.1.0"
            requires-python = ">=3.12"
            dependencies = [
                "hotframe",
            ]

            [project.optional-dependencies]
            dev = [
                "pytest>=8.0",
                "pytest-asyncio>=0.24",
                "ruff>=0.7",
            ]

            [tool.pytest.ini_options]
            asyncio_mode = "auto"
            testpaths = ["tests"]
            cache_dir = ".cache/pytest"

            [tool.ruff]
            cache-dir = ".cache/ruff"
            line-length = 100

            [tool.mypy]
            cache_dir = ".cache/mypy"
        ''')
        )

    # apps/ directory
    apps_dir = project_dir / "apps"
    apps_dir.mkdir(exist_ok=True)
    (apps_dir / "__init__.py").write_text("")

    # apps/shared/ — base app with welcome page
    shared_dir = apps_dir / "shared"
    shared_dir.mkdir(parents=True)
    (shared_dir / "__init__.py").write_text("")

    (shared_dir / "app.py").write_text(
        dedent(f'''\
        from hotframe import AppConfig


        class SharedConfig(AppConfig):
            name = "shared"
            verbose_name = "{name.replace("_", " ").title()} Shared"

            def ready(self):
                pass
    ''')
    )

    (shared_dir / "routes.py").write_text(
        dedent('''\
        """Shared routes — index page and base endpoints."""
        from fastapi import APIRouter, Request
        from fastapi.responses import HTMLResponse

        router = APIRouter()


        @router.get("/", response_class=HTMLResponse)
        async def index(request: Request):
            """Index page — proves the app is running."""
            templates = getattr(request.app.state, "templates", None)
            if templates:
                return templates.TemplateResponse(
                    request, "shared/index.html",
                    {"request": request, "app_title": request.app.title},
                )
            return HTMLResponse(
                f"<h1>{request.app.title}</h1>"
                f"<p>Powered by <a href=\\"https://github.com/ERPlora/hotframe\\">hotframe</a></p>"
            )
    ''')
    )

    # apps/shared/templates/
    shared_tpl = shared_dir / "templates" / "shared"
    shared_tpl.mkdir(parents=True)

    (shared_tpl / "base.html").write_text(
        dedent(f"""\
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
            <title>{{%- block title %}}{name.replace("_", " ").title()}{{%- endblock %}}</title>

            {{# ================================================================== #}}
            {{# Trusted Types policy — allows Alpine.js and HTMX to work with CSP #}}
            {{# Controlled by CSP_TRUSTED_TYPES setting (default: True)           #}}
            {{# Creates a permissive 'default' policy so libraries like HTMX and  #}}
            {{# Alpine.js work under Trusted Types enforcement.                   #}}
            {{# ================================================================== #}}
            {{%- if csp_trusted_types %}}
            <script nonce="{{{{ csp_nonce }}}}">
            if (window.trustedTypes && trustedTypes.createPolicy) {{
                trustedTypes.createPolicy('default', {{
                    createHTML: (s) => s,
                    createScript: (s) => s,
                    createScriptURL: (s) => s,
                }});
            }}
            </script>
            {{%- endif %}}

            {{# ================================================================== #}}
            {{# HTMX + extensions                                                 #}}
            {{# ================================================================== #}}
            <script src="https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js" nonce="{{{{ csp_nonce }}}}"></script>
            <script src="https://unpkg.com/idiomorph@0.4.0/dist/idiomorph-ext.min.js" nonce="{{{{ csp_nonce }}}}"></script>
            <script src="https://unpkg.com/htmx-ext-preload@2.1.0/preload.js" nonce="{{{{ csp_nonce }}}}"></script>
            <script src="https://unpkg.com/htmx-ext-loading-states@2.0.1/loading-states.js" nonce="{{{{ csp_nonce }}}}"></script>
            <script src="https://unpkg.com/htmx-ext-sse@2.2.2/sse.js" nonce="{{{{ csp_nonce }}}}"></script>

            {{# ================================================================== #}}
            {{# Alpine.js plugins (BEFORE Alpine core, all with defer)            #}}
            {{# ================================================================== #}}
            <script src="https://unpkg.com/@alpinejs/collapse@3.15.8/dist/cdn.min.js" defer nonce="{{{{ csp_nonce }}}}"></script>
            <script src="https://unpkg.com/@alpinejs/intersect@3.15.8/dist/cdn.min.js" defer nonce="{{{{ csp_nonce }}}}"></script>
            <script src="https://unpkg.com/@alpinejs/focus@3.15.8/dist/cdn.min.js" defer nonce="{{{{ csp_nonce }}}}"></script>
            <script src="https://unpkg.com/@alpinejs/mask@3.15.8/dist/cdn.min.js" defer nonce="{{{{ csp_nonce }}}}"></script>
            <script src="https://unpkg.com/@alpinejs/sort@3.15.8/dist/cdn.min.js" defer nonce="{{{{ csp_nonce }}}}"></script>

            {{# Alpine.js core (MUST be LAST, after all plugins) #}}
            <script src="https://unpkg.com/alpinejs@3.15.8/dist/cdn.min.js" defer nonce="{{{{ csp_nonce }}}}"></script>

            {{# ================================================================== #}}
            {{# Iconify (icon system via CDN)                                     #}}
            {{# ================================================================== #}}
            <script src="https://cdn.jsdelivr.net/npm/@iconify/iconify@3.1.1/dist/iconify.min.js" defer nonce="{{{{ csp_nonce }}}}"></script>

            {{# ================================================================== #}}
            {{# HTMX configuration: morph by default, no settle delay, CSP nonce  #}}
            {{# ================================================================== #}}
            <meta name="htmx-config" content='{{"defaultSwapStyle":"morph","defaultSettleDelay":"0","inlineScriptNonce":"{{{{ csp_nonce }}}}"}}'>

            {{# ================================================================== #}}
            {{# Global styles                                                     #}}
            {{# ================================================================== #}}
            <style>
                /* Alpine.js cloak — prevent flash of unstyled content */
                [x-cloak] {{ display: none !important; }}

                /* Smooth content transition */
                @keyframes page-enter {{
                    from {{ opacity: 0; transform: translateY(4px); }}
                    to   {{ opacity: 1; transform: translateY(0); }}
                }}
                .page-entering {{
                    animation: page-enter 0.18s ease-out both;
                }}

                /* HTMX request indicator */
                .htmx-indicator {{ opacity: 0; transition: opacity 0.2s ease; }}
                .htmx-request .htmx-indicator,
                .htmx-request.htmx-indicator {{ opacity: 1; }}

                /* Fixed top progress bar */
                #htmx-indicator {{
                    position: fixed;
                    top: 0;
                    left: 0;
                    right: 0;
                    height: 3px;
                    background: var(--color-primary, #3b82f6);
                    z-index: 9999;
                    opacity: 0;
                    transition: opacity 0.2s ease-out;
                }}
                .htmx-request #htmx-indicator,
                .htmx-request.htmx-indicator {{ opacity: 1; }}
                #htmx-indicator::after {{
                    content: '';
                    position: absolute;
                    top: 0;
                    left: 0;
                    right: 0;
                    bottom: 0;
                    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.4), transparent);
                    animation: htmx-loading 1.5s ease-in-out infinite;
                }}
                @keyframes htmx-loading {{
                    0% {{ transform: translateX(-100%); }}
                    100% {{ transform: translateX(100%); }}
                }}

                /* Prevent body scroll when modal is open */
                body.modal-open {{ overflow: hidden; }}
            </style>

            {{%- block head_extra %}}{{%- endblock %}}
        </head>
        <body hx-boost="true" hx-ext="morph,preload,loading-states,sse" hx-headers='{{"X-CSRF-Token": "{{{{ csrf_token }}}}"}}' {{%- block body_attrs %}}{{%- endblock %}}>

            {{# Fixed top progress bar #}}
            <div id="htmx-indicator"></div>

            {{%- block body %}}
            {{%- block content %}}{{%- endblock %}}
            {{%- endblock %}}

            {{# Modal container — for HTMX-loaded modals #}}
            <div id="modal-container"></div>

            {{# Toast container #}}
            <div id="toast-container" style="position:fixed; bottom:1rem; left:50%; transform:translateX(-50%); z-index:9999; display:flex; flex-direction:column; gap:0.5rem; align-items:center;"></div>

            {{# ================================================================== #}}
            {{# Toast & Confirm — UI primitives                                   #}}
            {{# ================================================================== #}}
            <script nonce="{{{{ csp_nonce }}}}">
            (function() {{
                var icons = {{
                    info: '<svg style="width:20px;height:20px;flex-shrink:0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z"/></svg>',
                    success: '<svg style="width:20px;height:20px;flex-shrink:0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/></svg>',
                    warning: '<svg style="width:20px;height:20px;flex-shrink:0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z"/></svg>',
                    error: '<svg style="width:20px;height:20px;flex-shrink:0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z"/></svg>'
                }};

                window.dismissToast = function(el) {{
                    el.style.opacity = '0';
                    el.style.transform = 'translateY(10px)';
                    setTimeout(function() {{ el.remove(); }}, 300);
                }};

                window.showToast = function(message, type, duration) {{
                    type = type || 'default';
                    duration = duration || 4000;
                    var container = document.getElementById('toast-container');
                    if (!container) return;
                    var icon = icons[type] || '';
                    var el = document.createElement('div');
                    el.style.cssText = 'display:flex; align-items:center; gap:0.5rem; padding:0.75rem 1rem; border-radius:0.5rem; background:#1f2937; color:#fff; font-size:0.875rem; box-shadow:0 4px 12px rgba(0,0,0,0.15); transition:opacity 0.3s, transform 0.3s; max-width:24rem;';
                    el.innerHTML = icon + '<span>' + message + '</span>';
                    el.onclick = function() {{ window.dismissToast(el); }};
                    container.appendChild(el);
                    setTimeout(function() {{ window.dismissToast(el); }}, duration);
                }};

                window.Toast = {{
                    success: function(msg, dur) {{ showToast(msg, 'success', dur); }},
                    error: function(msg, dur) {{ showToast(msg, 'error', dur || 5000); }},
                    warning: function(msg, dur) {{ showToast(msg, 'warning', dur); }},
                    info: function(msg, dur) {{ showToast(msg, 'info', dur); }}
                }};

                window.showConfirm = function(header, message, onConfirm, confirmLabel, cancelLabel) {{
                    var backdrop = document.createElement('div');
                    backdrop.style.cssText = 'position:fixed; inset:0; z-index:9999; background:rgba(0,0,0,0.5); display:flex; align-items:center; justify-content:center;';
                    backdrop.innerHTML =
                        '<div style="background:#fff; border-radius:0.75rem; padding:1.5rem; max-width:24rem; width:90%; box-shadow:0 20px 60px rgba(0,0,0,0.3);">' +
                            '<h3 style="margin:0 0 0.5rem; font-size:1.125rem;">' + header + '</h3>' +
                            '<p style="margin:0 0 1.5rem; color:#6b7280;">' + message + '</p>' +
                            '<div style="display:flex; justify-content:flex-end; gap:0.5rem;">' +
                                '<button data-action="cancel" style="padding:0.5rem 1rem; border:1px solid #d1d5db; border-radius:0.375rem; background:#fff; cursor:pointer;">' + (cancelLabel || 'Cancel') + '</button>' +
                                '<button data-action="confirm" style="padding:0.5rem 1rem; border:none; border-radius:0.375rem; background:#3b82f6; color:#fff; cursor:pointer;">' + (confirmLabel || 'Confirm') + '</button>' +
                            '</div>' +
                        '</div>';
                    document.body.appendChild(backdrop);
                    document.body.classList.add('modal-open');
                    function close() {{
                        document.body.classList.remove('modal-open');
                        backdrop.remove();
                    }}
                    backdrop.querySelector('[data-action="cancel"]').addEventListener('click', close);
                    backdrop.querySelector('[data-action="confirm"]').addEventListener('click', function() {{
                        close();
                        if (onConfirm) onConfirm();
                    }});
                    backdrop.addEventListener('click', function(e) {{
                        if (e.target === backdrop) close();
                    }});
                }};

                {{# HX-Trigger event listeners #}}
                document.body.addEventListener('showMessage', function(e) {{
                    var d = e.detail || {{}};
                    var msg = d.message || d.value || '';
                    if (msg) showToast(msg, d.type || 'success', d.type === 'error' ? 5000 : 4000);
                }});
                document.body.addEventListener('showNotification', function(e) {{
                    var d = e.detail || {{}};
                    var text = d.title ? (d.title + ': ' + (d.message || '')) : (d.message || '');
                    if (text) showToast(text, d.type || 'default');
                }});
            }})();
            </script>

            {{%- block scripts %}}{{%- endblock %}}

            {{# ================================================================== #}}
            {{# Alpine.js Global Stores (nav + sidebar + ui)                      #}}
            {{# ================================================================== #}}
            <script nonce="{{{{ csp_nonce }}}}">
            document.addEventListener('alpine:init', function() {{
                {{# Navigation Store — tracks current active path #}}
                Alpine.store('nav', {{
                    currentPath: window.location.pathname,
                    setPath: function(path) {{
                        this.currentPath = path;
                    }},
                    isActive: function(itemPath) {{
                        if (!itemPath || !this.currentPath) return false;
                        return this.currentPath === itemPath ||
                               this.currentPath.startsWith(itemPath + '/');
                    }},
                    init: function() {{}}
                }});

                {{# Sidebar Store — open/close sidebar state #}}
                Alpine.store('sidebar', {{
                    isOpen: false,
                    title: '',
                    open: function(title) {{
                        this.title = title || '';
                        this.isOpen = true;
                    }},
                    close: function() {{
                        this.isOpen = false;
                        this.title = '';
                    }},
                    toggle: function() {{
                        this.isOpen = !this.isOpen;
                    }}
                }});

                {{# UI Store — toast from Alpine components #}}
                Alpine.store('ui', {{
                    toast: function(message, type, duration) {{
                        if (typeof showToast === 'function') {{
                            showToast(message, type || 'default', duration || 4000);
                        }}
                    }},
                    success: function(message) {{ this.toast(message, 'success'); }},
                    error: function(message) {{ this.toast(message, 'error', 5000); }}
                }});
            }});
            </script>

            {{# ================================================================== #}}
            {{# HTMX — progress indicator, CSRF helper, script re-execution       #}}
            {{# ================================================================== #}}
            <script nonce="{{{{ csp_nonce }}}}">
            document.addEventListener('DOMContentLoaded', function() {{
                {{# Progress indicator — show/hide during HTMX requests #}}
                document.body.addEventListener('htmx:beforeRequest', function() {{
                    document.body.classList.add('htmx-request');
                }});
                document.body.addEventListener('htmx:afterRequest', function() {{
                    document.body.classList.remove('htmx-request');
                }});

                {{# CSRF helper for manual fetch() calls #}}
                window.getCsrfToken = function() {{
                    var match = document.cookie.match(/(^|;\\s*)csrf_token=([^;]+)/);
                    return match ? match[2] : '';
                }};

                {{# ============================================================ #}}
                {{# Script re-execution after HTMX morph swap.                   #}}
                {{# Idiomorph does NOT execute inline scripts — this handler      #}}
                {{# re-executes them and reinitializes Alpine + Iconify.          #}}
                {{# ============================================================ #}}
                var _pageNonce = '{{{{ csp_nonce }}}}';
                var _executedScripts = new WeakSet();

                document.body.addEventListener('htmx:afterSettle', function(event) {{
                    var target = event.detail.target;
                    if (!target) return;

                    var scripts = target.querySelectorAll('script:not([src])');
                    var executed = 0;
                    scripts.forEach(function(oldScript) {{
                        if (_executedScripts.has(oldScript)) return;

                        var newScript = document.createElement('script');
                        newScript.nonce = _pageNonce;
                        newScript.textContent = oldScript.textContent;

                        Array.from(oldScript.attributes).forEach(function(attr) {{
                            if (attr.name !== 'nonce' && attr.name !== 'type') {{
                                newScript.setAttribute(attr.name, attr.value);
                            }}
                        }});

                        oldScript.parentNode.replaceChild(newScript, oldScript);
                        _executedScripts.add(newScript);
                        executed++;
                    }});

                    {{# Re-initialize Alpine components after script re-execution #}}
                    if (executed > 0 && typeof Alpine !== 'undefined') {{
                        Promise.resolve().then(function() {{
                            try {{
                                Alpine.initTree(target);
                            }} catch (e) {{
                                console.warn('[HTMX] Alpine.initTree error:', e.message);
                            }}
                        }});
                    }}

                    {{# Re-scan for Iconify icons in swapped content #}}
                    if (typeof Iconify !== 'undefined') {{
                        Iconify.scan(target);
                    }}
                }});

                {{# Update nav store when URL changes via HTMX #}}
                document.body.addEventListener('htmx:pushedIntoHistory', function(event) {{
                    if (typeof Alpine !== 'undefined' && Alpine.store('nav')) {{
                        Alpine.store('nav').setPath(event.detail.path);
                    }}
                }});

                window.addEventListener('popstate', function() {{
                    if (typeof Alpine !== 'undefined' && Alpine.store('nav')) {{
                        Alpine.store('nav').setPath(window.location.pathname);
                    }}
                }});
            }});
            </script>
        </body>
        </html>
    """)
    )

    (shared_tpl / "index.html").write_text(
        dedent("""\
        {% extends "shared/base.html" %}

        {% block content %}
        <h1>{{ app_title }}</h1>
        <p>Your hotframe application is running.</p>
        <hr>
        <h3>Next steps</h3>
        <ul>
            <li><code>hf startapp accounts</code> — create your first app</li>
            <li><code>hf startmodule blog</code> — create a dynamic module</li>
            <li>Edit <code>settings.py</code> to configure your project</li>
        </ul>
        <p><small>Powered by <a href="https://github.com/ERPlora/hotframe">hotframe</a></small></p>
        {% endblock %}
    """)
    )

    (shared_tpl.parent / "errors").mkdir()
    for code, msg in [("404", "Page not found"), ("500", "Server error")]:
        ((shared_tpl.parent / "errors") / f"{code}.html").write_text(
            dedent(f"""\
            {{% extends "shared/base.html" %}}
            {{% block title %}}{code} - {msg}{{% endblock %}}
            {{% block content %}}<h1>{code}</h1><p>{msg}</p>{{% endblock %}}
        """)
        )

    # modules/ directory
    modules_dir = project_dir / "modules"
    modules_dir.mkdir(exist_ok=True)

    # tests/ directory
    tests_dir = project_dir / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "__init__.py").write_text("")
    (tests_dir / "conftest.py").write_text(
        dedent('''\
        """Shared test fixtures."""
        import pytest

        from hotframe.testing import create_test_app, test_db_session


        @pytest.fixture
        async def app():
            """Create a test application."""
            return create_test_app()


        @pytest.fixture
        async def db(app):
            """Create a test database session."""
            async for session in test_db_session():
                yield session
    ''')
    )

    typer.echo(f"Created project '{name}'")
    if name != project_dir.name or str(project_dir) != str(Path.cwd()):
        typer.echo(f"  cd {name}")
    typer.echo("  hf runserver")


# ---------------------------------------------------------------------------
# startapp
# ---------------------------------------------------------------------------


@app.command()
def startapp(name: str) -> None:
    """Create a new app inside apps/."""
    app_dir = Path("apps") / name
    if app_dir.exists():
        typer.echo(f"Error: app '{name}' already exists.", err=True)
        raise typer.Exit(1)

    app_dir.mkdir(parents=True)

    (app_dir / "__init__.py").write_text("")

    (app_dir / "app.py").write_text(
        dedent(f'''\
        from hotframe import AppConfig


        class {name.title().replace("_", "")}Config(AppConfig):
            name = "{name}"
            verbose_name = "{name.replace("_", " ").title()}"

            def ready(self):
                pass
    ''')
    )

    (app_dir / "models.py").write_text(
        dedent('''\
        """SQLAlchemy models."""
        from hotframe import Base
        # Define your models here
    ''')
    )

    (app_dir / "routes.py").write_text(
        dedent(f'''\
        """HTMX views."""
        from fastapi import APIRouter

        router = APIRouter(prefix="/{name}", tags=["{name}"])
    ''')
    )

    (app_dir / "api.py").write_text(
        dedent(f'''\
        """REST API endpoints."""
        from fastapi import APIRouter

        api_router = APIRouter(prefix="/api/v1/{name}", tags=["{name}"])
    ''')
    )

    templates_dir = app_dir / "templates" / name
    templates_dir.mkdir(parents=True)
    (templates_dir / "pages").mkdir()
    (templates_dir / "partials").mkdir()

    migrations_dir = app_dir / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "versions").mkdir()
    (migrations_dir / "env.py").write_text(_generate_env_py(name))

    tests_dir = app_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("")

    typer.echo(f"Created app 'apps/{name}/'")


# ---------------------------------------------------------------------------
# startmodule
# ---------------------------------------------------------------------------


@app.command()
def startmodule(
    name: str,
    api_only: bool = typer.Option(False, "--api-only", help="API only, no HTMX views"),
    system: bool = typer.Option(False, "--system", help="System module, no views or API"),
) -> None:
    """Create a new dynamic module inside modules/.

    Examples::

        hf startmodule blog              # views + API (default)
        hf startmodule payments --api-only   # API only
        hf startmodule audit --system        # system module
    """
    mod_dir = Path("modules") / name
    if mod_dir.exists():
        typer.echo(f"Error: module '{name}' already exists.", err=True)
        raise typer.Exit(1)

    has_views = not api_only and not system
    has_api = not system
    class_name = name.title().replace("_", "")
    verbose = name.replace("_", " ").title()

    mod_dir.mkdir(parents=True)

    (mod_dir / "__init__.py").write_text("")

    # module.py
    (mod_dir / "module.py").write_text(
        dedent(f'''\
        from hotframe import ModuleConfig


        class {class_name}Module(ModuleConfig):
            name = "{name}"
            verbose_name = "{verbose}"
            version = "1.0.0"
            is_system = {system}
            has_views = {has_views}
            has_api = {has_api}
            requires_restart = False
            dependencies = []

            async def ready(self) -> None:
                pass

            async def install(self, ctx) -> None:
                pass

            async def uninstall(self, ctx) -> None:
                pass
    ''')
    )

    # models.py
    (mod_dir / "models.py").write_text(
        dedent('''\
        """SQLAlchemy models."""
        from hotframe import Base
        # Define your models here
    ''')
    )

    # routes.py (views)
    if has_views:
        (mod_dir / "routes.py").write_text(
            dedent(f'''\
            """HTMX views for {verbose}."""
            from fastapi import APIRouter, Request
            from fastapi.responses import HTMLResponse

            router = APIRouter(prefix="/m/{name}", tags=["{name}"])


            @router.get("/", response_class=HTMLResponse)
            async def index(request: Request):
                """Module landing page."""
                return request.app.state.templates.TemplateResponse(
                    request, "{name}/pages/index.html", {{
                        "request": request,
                        "module_name": "{verbose}",
                    }},
                )
        ''')
        )

        # Template
        templates_dir = mod_dir / "templates" / name
        templates_dir.mkdir(parents=True)
        (templates_dir / "pages").mkdir()
        (templates_dir / "partials").mkdir()
        (templates_dir / "pages" / "index.html").write_text(
            dedent(f"""\
            {{% extends "shared/base.html" %}}
            {{% block title %}}{verbose}{{% endblock %}}
            {{% block content %}}
            <h1>{verbose}</h1>
            <p>Module <strong>{name}</strong> is installed and running.</p>
            <p><a href="/">&larr; Home</a></p>
            {{% endblock %}}
        """)
        )

    # api.py
    if has_api:
        (mod_dir / "api.py").write_text(
            dedent(f'''\
            """REST API for {verbose}."""
            from fastapi import APIRouter

            api_router = APIRouter(prefix="/api/v1/{name}", tags=["{name}"])


            @api_router.get("/")
            async def list_items():
                """List items."""
                return {{"module": "{name}", "items": []}}
        ''')
        )

    # migrations/
    migrations_dir = mod_dir / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "versions").mkdir()
    (migrations_dir / "env.py").write_text(_generate_env_py(name))

    # tests/
    tests_dir = mod_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("")

    parts = []
    if has_views:
        parts.append("views")
    if has_api:
        parts.append("API")
    if system:
        parts.append("system")
    mode = " + ".join(parts) if parts else "minimal"

    typer.echo(f"Created module 'modules/{name}/' ({mode})")


# ---------------------------------------------------------------------------
# modules (subcommand group)
# ---------------------------------------------------------------------------

modules_app = typer.Typer(help="Module lifecycle management.")
app.add_typer(modules_app, name="modules")


@modules_app.command("list")
def modules_list() -> None:
    """List all modules and their status."""
    from pathlib import Path

    modules_dir = Path("modules")
    if not modules_dir.exists():
        typer.echo("No modules found in modules/")
        return

    typer.echo(f"{'Module':<20} {'Status':<12} {'Version':<10} {'Views':<6} {'API':<6}")
    typer.echo("-" * 60)

    for mod_dir in sorted(modules_dir.iterdir()):
        if not mod_dir.is_dir() or mod_dir.name.startswith((".", "_")):
            continue
        if not (mod_dir / "module.py").exists():
            continue

        name = mod_dir.name
        version = ""
        has_views = "yes"
        has_api = "yes"
        is_system = False

        try:
            import importlib

            mod = importlib.import_module(f"modules.{name}.module")
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if (
                    isinstance(attr, type)
                    and hasattr(attr, "name")
                    and getattr(attr, "name", None) == name
                ):
                    version = getattr(attr, "version", "")
                    has_views = "yes" if getattr(attr, "has_views", True) else "no"
                    has_api = "yes" if getattr(attr, "has_api", True) else "no"
                    is_system = getattr(attr, "is_system", False)
                    break
        except Exception:
            pass

        status = "available"
        if is_system:
            status += " (system)"
        typer.echo(f"{name:<20} {status:<12} {version:<10} {has_views:<6} {has_api:<6}")


@modules_app.command("install")
def modules_install(source: str) -> None:
    """Install a module from name, URL, or .zip path."""
    import asyncio

    async def _install():
        from hotframe.config.database import get_engine, get_session_factory
        from hotframe.config.settings import get_settings
        from hotframe.engine.module_runtime import ModuleRuntime
        from hotframe.models.base import Base
        from hotframe.signals.dispatcher import AsyncEventBus
        from hotframe.signals.hooks import HookRegistry
        from hotframe.templating.slots import SlotRegistry

        settings = get_settings()
        bus = AsyncEventBus()
        hooks = HookRegistry()
        slots = SlotRegistry()
        runtime = ModuleRuntime(
            app=None, settings=settings, event_bus=bus, hooks=hooks, slots=slots
        )

        # For CLI without DB, just do a simple filesystem install
        # Create tables directly
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = get_session_factory()
        async with factory() as session:
            result = await runtime.install(session, hub_id=None, module_id=source, source=source)
            if result.success:
                typer.echo(f"OK: Module '{result.module_id}' v{result.version} installed")
            else:
                typer.echo(f"Error: {result.error}", err=True)
                raise typer.Exit(1)
            await session.commit()

        await engine.dispose()

    asyncio.run(_install())


@modules_app.command("update")
def modules_update(source: str) -> None:
    """Update a module to a new version."""
    import asyncio

    async def _update():
        from hotframe.config.database import get_session_factory
        from hotframe.config.settings import get_settings
        from hotframe.engine.module_runtime import ModuleRuntime
        from hotframe.signals.dispatcher import AsyncEventBus
        from hotframe.signals.hooks import HookRegistry
        from hotframe.templating.slots import SlotRegistry

        settings = get_settings()
        runtime = ModuleRuntime(
            app=None,
            settings=settings,
            event_bus=AsyncEventBus(),
            hooks=HookRegistry(),
            slots=SlotRegistry(),
        )

        factory = get_session_factory()
        async with factory() as session:
            result = await runtime.update(
                session, hub_id=None, module_id=source, new_version=None, source=source
            )
            if result.success:
                typer.echo(f"OK: Module '{result.module_id}' updated to v{result.to_version}")
            else:
                typer.echo(f"Error: {result.error}", err=True)
                raise typer.Exit(1)
            await session.commit()

        from hotframe.config.database import dispose_engine

        await dispose_engine()

    asyncio.run(_update())


@modules_app.command("activate")
def modules_activate(name: str) -> None:
    """Activate a disabled module."""
    import asyncio

    async def _activate():
        from hotframe.config.database import get_session_factory
        from hotframe.config.settings import get_settings
        from hotframe.engine.module_runtime import ModuleRuntime
        from hotframe.signals.dispatcher import AsyncEventBus
        from hotframe.signals.hooks import HookRegistry
        from hotframe.templating.slots import SlotRegistry

        settings = get_settings()
        runtime = ModuleRuntime(
            app=None,
            settings=settings,
            event_bus=AsyncEventBus(),
            hooks=HookRegistry(),
            slots=SlotRegistry(),
        )

        factory = get_session_factory()
        async with factory() as session:
            result = await runtime.activate(session, hub_id=None, module_id=name)
            if result.success:
                typer.echo(f"OK: Module '{name}' activated")
            else:
                typer.echo(f"Error: {result.error}", err=True)
                raise typer.Exit(1)
            await session.commit()

        from hotframe.config.database import dispose_engine

        await dispose_engine()

    asyncio.run(_activate())


@modules_app.command("deactivate")
def modules_deactivate(name: str) -> None:
    """Deactivate an active module (keeps data)."""
    import asyncio

    async def _deactivate():
        from hotframe.config.database import get_session_factory
        from hotframe.config.settings import get_settings
        from hotframe.engine.module_runtime import ModuleRuntime
        from hotframe.signals.dispatcher import AsyncEventBus
        from hotframe.signals.hooks import HookRegistry
        from hotframe.templating.slots import SlotRegistry

        settings = get_settings()
        runtime = ModuleRuntime(
            app=None,
            settings=settings,
            event_bus=AsyncEventBus(),
            hooks=HookRegistry(),
            slots=SlotRegistry(),
        )

        factory = get_session_factory()
        async with factory() as session:
            result = await runtime.deactivate(session, hub_id=None, module_id=name)
            if result.success:
                typer.echo(f"OK: Module '{name}' deactivated")
            else:
                typer.echo(f"Error: {result.error}", err=True)
                raise typer.Exit(1)
            await session.commit()

        from hotframe.config.database import dispose_engine

        await dispose_engine()

    asyncio.run(_deactivate())


@modules_app.command("uninstall")
def modules_uninstall(
    name: str,
    keep_data: bool = typer.Option(False, "--keep-data", help="Keep database tables"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Uninstall a module (removes files, optionally drops tables)."""
    import asyncio

    if not yes:
        confirm = typer.confirm(
            f"Uninstall module '{name}'?"
            + (" (keeping data)" if keep_data else " (including database tables)")
        )
        if not confirm:
            typer.echo("Cancelled.")
            raise typer.Exit(0)

    async def _uninstall():
        from hotframe.config.database import get_session_factory
        from hotframe.config.settings import get_settings
        from hotframe.engine.module_runtime import ModuleRuntime
        from hotframe.signals.dispatcher import AsyncEventBus
        from hotframe.signals.hooks import HookRegistry
        from hotframe.templating.slots import SlotRegistry

        settings = get_settings()
        runtime = ModuleRuntime(
            app=None,
            settings=settings,
            event_bus=AsyncEventBus(),
            hooks=HookRegistry(),
            slots=SlotRegistry(),
        )

        factory = get_session_factory()
        async with factory() as session:
            result = await runtime.uninstall(session, hub_id=None, module_id=name)
            if result.success:
                typer.echo(f"OK: Module '{name}' uninstalled")
            else:
                typer.echo(f"Error: {result.error}", err=True)
                raise typer.Exit(1)
            await session.commit()

        from hotframe.config.database import dispose_engine

        await dispose_engine()

    asyncio.run(_uninstall())


# ---------------------------------------------------------------------------
# runserver
# ---------------------------------------------------------------------------


@app.command()
def runserver(
    host: str = "0.0.0.0",
    port: int = 8000,
    reload: bool = True,
) -> None:
    """Start the development server."""
    import sys

    import uvicorn

    # Ensure CWD is in sys.path so uvicorn can import main.py
    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    typer.echo(f"Starting server at http://{host}:{port}")
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=reload,
    )


# ---------------------------------------------------------------------------
# migrate
# ---------------------------------------------------------------------------


@app.command()
def migrate(
    name: str = typer.Argument(
        None, help="App or module name (e.g. 'accounts'). Omit to migrate all."
    ),
) -> None:
    """Run migrations for all apps and modules (or a specific one).

    Scans apps/*/migrations/ and modules/*/migrations/ and runs
    Alembic upgrade head for each, using namespaced version tables.

    Examples::

        hf migrate              # all apps + modules
        hf migrate accounts     # only accounts app
        hf migrate sales        # only sales module
    """
    import asyncio

    async def _migrate():
        from hotframe.config.settings import get_settings
        from hotframe.migrations.runner import ModuleMigrationRunner

        settings = get_settings()
        runner = ModuleMigrationRunner()
        db_url = runner.get_sync_db_url(settings.DATABASE_URL)
        cwd = Path.cwd()

        targets: list[tuple[str, Path]] = []

        if name:
            # Specific app or module
            app_path = cwd / "apps" / name
            mod_path = cwd / "modules" / name
            if app_path.exists():
                targets.append((name, app_path))
            elif mod_path.exists():
                targets.append((name, mod_path))
            else:
                typer.echo(f"Error: '{name}' not found in apps/ or modules/", err=True)
                raise typer.Exit(1)
        else:
            # All apps
            apps_dir = cwd / "apps"
            if apps_dir.exists():
                for d in sorted(apps_dir.iterdir()):
                    if (
                        d.is_dir()
                        and not d.name.startswith((".", "_"))
                        and (d / "migrations").exists()
                    ):
                        targets.append((d.name, d))
            # All modules
            modules_dir = cwd / "modules"
            if modules_dir.exists():
                for d in sorted(modules_dir.iterdir()):
                    if (
                        d.is_dir()
                        and not d.name.startswith((".", "_"))
                        and (d / "migrations").exists()
                    ):
                        targets.append((d.name, d))

        if not targets:
            typer.echo("No migrations found in apps/ or modules/")
            return

        for mid, mpath in targets:
            if runner.has_migrations(mpath):
                typer.echo(f"  Migrating {mid}...")
                await runner.upgrade(mid, mpath, db_url)
            else:
                typer.echo(f"  {mid}: no migration scripts, skipping")

        typer.echo(f"Done — {len(targets)} migration(s) processed.")

    asyncio.run(_migrate())


# ---------------------------------------------------------------------------
# makemigrations
# ---------------------------------------------------------------------------


@app.command()
def makemigrations(
    name: str = typer.Argument(..., help="App or module name (e.g. 'accounts')"),
    message: str = typer.Option("auto", "-m", "--message", help="Migration message"),
) -> None:
    """Generate a new migration for an app or module.

    Creates an Alembic revision in apps/{name}/migrations/ or
    modules/{name}/migrations/ with autogenerate.

    Examples::

        hf makemigrations accounts -m "add email field"
        hf makemigrations sales -m "initial"
    """
    import asyncio

    async def _makemigrations():
        from alembic import command
        from alembic.config import Config

        from hotframe.config.settings import get_settings

        settings = get_settings()
        cwd = Path.cwd()

        # Find the app or module
        app_path = cwd / "apps" / name
        mod_path = cwd / "modules" / name
        if app_path.exists():
            target_path = app_path
        elif mod_path.exists():
            target_path = mod_path
        else:
            typer.echo(f"Error: '{name}' not found in apps/ or modules/", err=True)
            raise typer.Exit(1)

        migrations_dir = target_path / "migrations"
        versions_dir = migrations_dir / "versions"

        # Create migrations structure if it doesn't exist
        migrations_dir.mkdir(exist_ok=True)
        versions_dir.mkdir(exist_ok=True)

        # Create env.py if missing
        env_py = migrations_dir / "env.py"
        if not env_py.exists():
            env_py.write_text(_generate_env_py(name))
            typer.echo(f"  Created {migrations_dir}/env.py")

        # Build Alembic config programmatically
        db_url = settings.DATABASE_URL.replace("+asyncpg", "").replace("+aiosqlite", "")
        version_table = f"alembic_{name}"

        config = Config()
        config.set_main_option("script_location", str(migrations_dir))
        config.set_main_option("sqlalchemy.url", db_url)
        config.set_main_option("version_table", version_table)

        typer.echo(f"Generating migration for '{name}': {message}")

        await asyncio.to_thread(command.revision, config, message=message, autogenerate=True)
        typer.echo(f"Done — migration created in {migrations_dir}/versions/")

    asyncio.run(_makemigrations())


def _generate_env_py(name: str) -> str:
    """Generate a minimal env.py for Alembic migrations."""
    return f'''\
"""Alembic migration environment for {name}."""
from alembic import context
from sqlalchemy import create_engine, pool

# Import Base so Alembic sees the models
from hotframe.models.base import Base  # noqa: F401

# Import this app/module's models
try:
    import importlib
    # Try as app first, then as module
    try:
        importlib.import_module("apps.{name}.models")
    except ImportError:
        importlib.import_module("modules.{name}.models")
except ImportError:
    pass

target_metadata = Base.metadata
config = context.config


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    # Check if a connection was passed (from ModuleMigrationRunner)
    connectable = config.attributes.get("connection")
    if connectable is None:
        url = config.get_main_option("sqlalchemy.url")
        connectable = create_engine(url, poolclass=pool.NullPool)

    if hasattr(connectable, "connect"):
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
                render_as_batch=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    else:
        context.configure(
            connection=connectable,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
'''


# ---------------------------------------------------------------------------
# version
# ---------------------------------------------------------------------------


@app.command()
def version() -> None:
    """Show hotframe version."""
    from hotframe import __version__

    typer.echo(f"hotframe {__version__}")


if __name__ == "__main__":
    app()
