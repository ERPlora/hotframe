# Changelog

All notable changes to `hotframe` are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versioning follows [SemVer](https://semver.org/).

## [Unreleased]

### Added
- Work in progress. Not yet released.

## [0.0.7] - 2026-04-20

### Fixed
- bootstrap: now calls `boot_kernel_modules` during lifespan (orphan function was defined but never invoked). Kernel modules listed in `settings.KERNEL_MODULE_NAMES` load from the Docker image BEFORE any S3-sourced dynamic module. Without this fix, `assistant` (the kernel module) was treated as an S3 module, attempted a download that never exists, and persisted `status=error` on every boot.

## [0.0.6] - 2026-04-20

### Added
- `views/broadcast`: WebSocket `/ws/stream/{topic:path}` now registered as a real route (was an orphan handler).
- `templating/extensions`: `timeformat` Jinja filter for HH:MM rendering.
- `bootstrap`: `CachedStaticFiles` subclass adds `Cache-Control: public, max-age=31536000, immutable` to all `/static/*` responses.
- `engine/module_runtime.boot_all_active_modules`: per-hub Postgres advisory lock so concurrent uvicorn workers no longer deadlock on `hub_module.manifest` UPDATE. Leader writes DB, followers mount routes in-memory only via `skip_db_writes=True`.

### Fixed
- SSE endpoints `/stream/{topic}` and `/stream/_mux` now require authentication (were unauthenticated — anyone could open a persistent event stream).
- `/stream/_mux` validates the `topics` list before constructing `EventSourceResponse` (was hanging 200 on empty topics).
- `middleware/language` and `auth/csrf`: skip `/static/*` paths when setting cookies. Static assets are now CDN-cacheable (previously every asset response carried `Set-Cookie` for `_lang` + `csrf_token`).

### Tests
- `tests/test_engine.py::TestBootAdvisoryLock` (6 tests).
- `tests/test_broadcast.py` (8 tests — SSE auth, WS registration, mux validation).

Total: **200 tests passing**, up from 178.

## [0.0.5] - 2026-04-19

### Removed
- Framework built-in components: `alert` and `badge` no longer ship under `hotframe/components/_builtin/`. The framework does not ship HTML or CSS-dependent UI.
- `discover_framework_components` helper and the `_builtin` discovery path.

### Added
- `hf startproject` now generates `alert` and `badge` example components under `apps/shared/components/`. They are plain scaffolding: projects may keep, modify, or delete them freely.

### Fixed
- `bootstrap.py`: `AppConfig.ready()` is now executed correctly when it is an `async def`. The discovery helper detects coroutine functions with `inspect.iscoroutinefunction` and runs them on a transient event loop (sync `ready` is still called directly).
- Telemetry: `FastAPIInstrumentor().instrument()` is now invoked on an instance, fixing the `BaseInstrumentor.instrument() missing 1 required positional argument: 'self'` error that appeared when telemetry auto-instrumentation was enabled.

## [0.0.4] - 2026-04-19

### Added
- Project-level component discovery under `apps/<app>/components/`.
- The `apps/` root is added automatically to the Jinja2 loader search path.

### Fixed
- Kwarg collision on `name` in `render_component` and the `{% component %}` tag that broke components declaring a `name` prop (for example `user_badge`). The component identifier is now positional-only internally.

## [0.0.3] - 2026-04-19

### Added
- Components subsystem: reusable UI widgets with typed props (Pydantic) or template-only shape.
- Public exports `ComponentRegistry`, `ComponentEntry`, `Component`.
- Jinja2 global `render_component()` for inline use.
- Jinja2 tag extension `{% component 'name' %}...body...{% endcomponent %}` with body support via `caller()`.
- Auto-mounting of per-component `APIRouter` at `/_components/<name>/...`.
- Per-component static assets scoped at `/_components/<name>/static/...`.
- Module-scoped discovery: modules can ship components at `modules/<id>/components/`.
- Context isolation: components receive only validated props plus a framework slice (`request`, `csrf_token`, `csp_nonce`, `user`, `is_htmx`, `current_path`).

## [0.0.2] - 2026-04-19

### Added
- `hf shell` command: interactive REPL that pre-loads `app`, `settings`, `db`, `events`, `hooks`, `slots`, `runtime`, `SlotEntry`. Auto-detects IPython; falls back to `code.interact()`. Supports `--plain`, `--no-startup`, `--settings=<path>` flags.
- Optional dependency group `[shell]`: installable via `pip install "hotframe[shell]"`.

[Unreleased]: https://github.com/ERPlora/hotframe/compare/v0.0.5...HEAD
[0.0.5]: https://github.com/ERPlora/hotframe/compare/v0.0.4...v0.0.5
[0.0.4]: https://github.com/ERPlora/hotframe/compare/v0.0.3...v0.0.4
[0.0.3]: https://github.com/ERPlora/hotframe/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/ERPlora/hotframe/compare/v0.0.1...v0.0.2
