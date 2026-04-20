# Hotframe Shell

`hf shell` launches an interactive Python REPL with the full hotframe application context pre-loaded. It is the hotframe equivalent of Django's `manage.py shell` or Flask's `flask shell`.

Use it for ad-hoc database queries, poking at the module runtime, registering slot contributions interactively, or debugging a running project's configuration without writing a throwaway script.

---

## Installation

The shell works out of the box with Python's built-in `code.interact()` REPL. For a richer experience (syntax highlighting, tab completion, `%autoawait`, magics) install the optional IPython extra:

```bash
pip install "hotframe[shell]"
```

If IPython is not installed, `hf shell` transparently falls back to the built-in REPL.

---

## Basic Usage

From the root of a hotframe project (where `settings.py` lives):

```bash
hf shell
```

On startup the command prints a banner listing the hotframe version, the REPL backend in use, and the variables available in the namespace, then drops you into the prompt.

```
hotframe 0.0.5 shell (IPython)
Loaded: app, settings, db, events, hooks, slots, runtime, SlotEntry
>>>
```

---

## Flags

| Flag | Description |
|---|---|
| `--plain` | Force the built-in `code.interact()` REPL even if IPython is installed. |
| `--no-startup` | Skip the FastAPI lifespan (faster boot, but `db`, `events`, `hooks`, `slots`, and `runtime` are not initialized). |
| `--settings=<dotted.path>` | Override settings module discovery. Use when your settings are not in `./settings.py`. |

Examples:

```bash
hf shell --plain
hf shell --no-startup
hf shell --settings=config.production
```

---

## Pre-loaded Variables

| Variable | Type | What it is |
|---|---|---|
| `app` | `FastAPI` | The hotframe application instance returned by `create_app(settings)`. |
| `settings` | `HotframeSettings` | The resolved settings object (same as `get_settings()`). |
| `db` | `AsyncSession` | An open async SQLAlchemy session. Rolled back on exit. |
| `events` | `AsyncEventBus` | The running event bus. Use to `emit` or `subscribe` interactively. |
| `hooks` | `HookRegistry` | The hook registry. Use `do_action` / `apply_filters` for debugging. |
| `slots` | `SlotRegistry` | The slot registry. Inspect or register template slot contributions. |
| `runtime` | `ModuleRuntime` | The module lifecycle orchestrator (install, activate, update, etc.). |
| `SlotEntry` | class | Convenience import for constructing slot entries without importing by hand. |

With IPython, `%autoawait asyncio` is enabled at startup so you can `await` coroutines directly at the prompt. In the plain REPL, a helper named `run(coro)` is available — it executes a coroutine on the session's event loop and returns its result.

---

## Examples

### 1. Query the database

```python
>>> from sqlalchemy import select
>>> from apps.accounts.models import User
>>> result = await db.execute(select(User).where(User.is_active == True))
>>> users = result.scalars().all()
>>> len(users)
42
```

Plain REPL equivalent (no `%autoawait`):

```python
>>> result = run(db.execute(select(User).where(User.is_active == True)))
>>> users = result.scalars().all()
```

### 2. Register a slot contribution interactively

```python
>>> slots.register(
...     "dashboard_widgets",
...     "loyalty/partials/widget.html",
...     module_id="loyalty",
...     priority=5,
... )
>>> [e.template for e in slots.get_entries("dashboard_widgets")]
['loyalty/partials/widget.html', 'sales/partials/summary.html']
```

The registration is in-memory for the shell session only — it is not persisted.

### 3. Inspect runtime module state

```python
>>> await runtime.list_modules()
[
    ModuleState(module_id='core', status='active', version='1.0.0'),
    ModuleState(module_id='blog', status='disabled', version='0.3.1'),
]
>>> await runtime.activate("blog")
>>> await runtime.list_modules()
[
    ModuleState(module_id='core', status='active', version='1.0.0'),
    ModuleState(module_id='blog', status='active', version='0.3.1'),
]
```

---

## Troubleshooting

**`settings.py` not found.** By default the shell auto-discovers `./settings.py` in the current working directory. If your settings live elsewhere, pass `--settings=dotted.path` explicitly (for example `--settings=myproject.config.production`). Make sure the parent package is importable — run `hf shell` from the project root, not from inside a subdirectory.

**IPython not installed.** The shell will still work with `code.interact()`. To upgrade, run `pip install "hotframe[shell]"`. If you want to verify which backend is active, check the banner printed at startup.

**`RuntimeError: no running event loop` / `SyntaxError: 'await' outside function`.** You are in the plain REPL without `%autoawait`. Use the `run(coro)` helper instead, or reinstall with the `[shell]` extra to get IPython's auto-await.

**`db` is `None` or missing.** You launched the shell with `--no-startup`. The lifespan was skipped, so no DB engine was created. Restart without the flag, or call `await app.router.startup()` manually (not recommended).

**Module imports fail.** The shell uses the same module discovery as `hf runserver`. If an app or module does not import, fix it the same way you would for the server — `--no-startup` can help isolate import errors from lifespan errors.

---

## Differences from `python -i` and `python -m hotframe`

| | `hf shell` | `python -i main.py` | `python -m hotframe` |
|---|---|---|---|
| Loads `settings.py` | Yes | Only if `main.py` does | No |
| Runs FastAPI lifespan (DB, events, hooks, slots) | Yes | No | No |
| Pre-loads `app`, `db`, `runtime`, etc. | Yes | No | No |
| IPython auto-await | Yes (with `[shell]`) | No | No |
| Works when `modules/` contains hot-mount plugins | Yes | No | No |

`python -i main.py` gives you a REPL after running `main.py`, but the FastAPI app has not gone through its lifespan — no DB engine, no event bus, no module runtime. `hf shell` runs the full startup sequence so the REPL mirrors a live request context.

---

## When Not to Use It

- **Production debugging.** Prefer logs, traces, and OpenTelemetry data. A live REPL that holds open DB sessions is risky on a production DB.
- **Long-running tasks.** The shell is for interactive exploration. Put anything repeatable into a management command or a test.
- **Module installation in CI.** Use `hf modules install` directly from the CLI; the shell is not required.
