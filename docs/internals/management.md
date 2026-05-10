# management.md — CLI (`hf` command)

> **Carpeta cubierta:** `src/hotframe/management/`. Dos archivos:
> `__init__.py`, `cli.py` (1645 LOC).
> Implementa la CLI `hf` con Typer. Todos los comandos para crear
> proyecto, apps, módulos, gestionar el ciclo de vida de módulos,
> correr migraciones, abrir un shell interactivo.

---

## 1. ¿Qué expone?

El `pyproject.toml` declara:

```toml
[project.scripts]
hf = "hotframe.management.cli:app"
```

Tras `pip install hotframe`, `hf` está en el PATH. Comandos:

| Comando | Qué hace |
|---|---|
| `hf startproject <name>` | Genera scaffold de proyecto |
| `hf startapp <name>` | Crea `apps/<name>/` |
| `hf startmodule <name>` | Crea scaffold de módulo |
| `hf modules list` | Lista módulos + status |
| `hf modules install <source>` | Instala (name, .zip, URL, marketplace) |
| `hf modules update <source>` | Update con backup + rollback |
| `hf modules activate <name>` | disabled → active |
| `hf modules deactivate <name>` | active → disabled |
| `hf modules uninstall <name>` | Remove |
| `hf runserver` | uvicorn con reload |
| `hf migrate` | `alembic upgrade head` |
| `hf makemigrations` | `alembic revision --autogenerate` |
| `hf shell` | REPL interactivo con app context |
| `hf version` | Muestra versión |

---

## 2. `__init__.py`

Vacío salvo el package marker. La CLI completa vive en `cli.py`.

---

## 3. `cli.py` — la implementación

### 3.1 Estructura

```python
import typer

app = typer.Typer(name="hf", help="Hotframe CLI")
modules_app = typer.Typer(name="modules", help="Module management")
app.add_typer(modules_app, name="modules")

@app.command()
def startproject(name: str, path: Path = typer.Option(".", "--path")): ...
@app.command()
def startapp(name: str): ...
@app.command()
def startmodule(name: str, system: bool = False, api_only: bool = False): ...
@app.command("runserver")
def runserver(host: str = "127.0.0.1", port: int = 8000): ...
@app.command()
def migrate(): ...
@app.command()
def makemigrations(message: str = ""): ...
@app.command()
def shell(plain: bool = False, no_startup: bool = False, settings: str = ""): ...
@app.command()
def version(): ...

@modules_app.command("list")
def modules_list(): ...
@modules_app.command("install")
def modules_install(source: str, version: str = "", checksum: str = ""): ...
@modules_app.command("update")
def modules_update(source: str): ...
@modules_app.command("activate")
def modules_activate(name: str): ...
@modules_app.command("deactivate")
def modules_deactivate(name: str): ...
@modules_app.command("uninstall")
def modules_uninstall(name: str, keep_data: bool = False, yes: bool = False): ...
```

### 3.2 `startproject` — scaffold del proyecto

Crea estructura mínima:

```
my_project/
├── apps/
│   └── home/
│       ├── __init__.py
│       ├── app.py        # AppConfig
│       ├── routes.py     # APIRouter con "/"
│       └── templates/home/index.html
├── modules/              # vacío, listo para hf modules install
├── static/
├── media/
├── settings.py           # subclase HotframeSettings
├── main.py               # 3 lineas: from hotframe import create_app...
├── pyproject.toml
├── alembic.ini
├── alembic/env.py
└── .env                  # SECRET_KEY auto-generated
```

Con `hf startproject .` (con `.`), genera en el directorio actual
en lugar de un subdirectorio nuevo.

### 3.3 `startapp <name>`

Crea `apps/<name>/`:

```
apps/<name>/
├── __init__.py
├── app.py        # class <Name>Config(AppConfig)
├── routes.py     # router = APIRouter()
├── api.py        # api_router = APIRouter()
├── models.py     # class Model(Base): ...
├── templates/<name>/
└── static/<name>/
```

### 3.4 `startmodule <name>`

Genera scaffold de módulo en `modules/<name>/`:

```
modules/<name>/
├── module.py     # class Module(ModuleConfig): MODULE_ID, MODULE_NAME, ...
├── routes.py     # APIRouter — solo si NO --api-only
├── api.py        # APIRouter — siempre
├── models.py
├── services.py
├── templates/<name>/  # solo si NO --api-only
├── static/<name>/
├── migrations/
├── components/   # opcional
└── README.md
```

Flags:
- `--api-only`: no genera `routes.py`, `templates/`. Solo APIRouter.
- `--system`: marca `IS_SYSTEM = True` en el manifest. No se puede
  desinstalar (kernel module).

### 3.5 `runserver`

```python
@app.command()
def runserver(host="127.0.0.1", port=8000, reload=True):
    import uvicorn
    uvicorn.run("main:app", host=host, port=port,
                reload=reload, reload_dirs=["apps", "modules", "src"])
```

`reload_dirs` cubre los típicos en un proyecto. Para hot-reload de
módulos sin reiniciar uvicorn, usa `ModuleWatcher` (ver `dev.md`).

### 3.6 `migrate` y `makemigrations`

Wrappers de Alembic:

```python
@app.command()
def migrate():
    from alembic import command
    from alembic.config import Config
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")

@app.command()
def makemigrations(message=""):
    cfg = Config("alembic.ini")
    command.revision(cfg, message=message or "auto", autogenerate=True)
```

Para **migraciones de módulo**, usa `runtime.migrations.upgrade(...)`
o instala con `hf modules install` (corre las migrations en el flow).

### 3.7 `shell` — REPL

```python
@app.command()
def shell(plain=False, no_startup=False, settings=""):
    if not no_startup:
        # Run lifespan: DB, registries, ModuleRuntime
        ...
    namespace = {
        "app": app, "settings": settings, "db": session,
        "events": event_bus, "hooks": hooks, "slots": slots,
        "runtime": module_runtime, "SlotEntry": SlotEntry,
    }
    if not plain and ipython_available:
        from IPython import start_ipython
        start_ipython(argv=[], user_ns=namespace,
                      config=Config({"InteractiveShellApp": {"exec_lines": ["%autoawait asyncio"]}}))
    else:
        import code
        # Build a `run(coro)` helper for sync REPL
        namespace["run"] = lambda c: asyncio.run(c)
        code.interact(local=namespace, banner="...")
```

Decisiones:

1. **Auto-detect IPython.** `pip install "hotframe[shell]"` instala
   IPython como extra dep. Si está, lo usa con `%autoawait asyncio`
   para `await` directo en la REPL.
2. **Plain fallback.** Sin IPython, builtin `code.interact()` con
   helper `run(coro)`.
3. **`no_startup`** salta la fase async — no abre BD, no corre
   ModuleRuntime. Útil para tests rápidos del scaffolding.
4. **`settings=...`** override de la ruta dotted del settings (por
   defecto detecta de `main.py` o `settings.py`).

### 3.8 `modules list`

```python
@modules_app.command("list")
def modules_list():
    runtime = _get_runtime()
    async def _run():
        async with session_factory() as db:
            mods = await runtime.state.get_all_modules(db)
            for m in mods:
                typer.echo(f"{m.module_id:30} {m.status:10} v{m.version}")
    asyncio.run(_run())
```

Imprime todos los módulos en una tabla (id, status, version).

### 3.9 `modules install <source>`

`source` puede ser:
- nombre simple: `inventory` → mira `MODULES_DIR/inventory` o
  marketplace.
- ruta a `.zip`: `./build/inventory.zip` → extracta + instala.
- URL: `https://...inventory.zip` → descarga + instala.

Internamente llama a `runtime.install(session, hub_id, ...)`. El
hub_id en single-tenant mode es `None`.

### 3.10 Helper `_get_runtime()`

```python
def _get_runtime():
    """Boot the app to get a ModuleRuntime (without starting uvicorn)."""
    from main import app   # user's main.py
    # Run lifespan up to where ModuleRuntime is created
    ...
    return app.state.module_runtime
```

Reusa el mismo lifespan que uvicorn dispararía, pero sin abrir un
puerto. La sesión de BD se abre con `session_factory()`.

### 3.11 Manejo de errores

Cada comando captura `RuntimeError` y similar, e imprime con
`typer.echo(..., err=True)` y `raise typer.Exit(1)`. Stack trace
solo si `--verbose` (TBD: actualmente siempre traceback en errores
no controlados).

---

## 4. Decisiones de diseño que conviene recordar

1. **Typer, no argparse.** Typer aprovecha typing y se integra bien
   con docstrings.
2. **El CLI corre con el mismo `lifespan` que uvicorn.** Garantiza
   que `hf modules install` ve los mismos componentes que el server.
3. **`hf shell` es esencial para debugging.** Permite tocar el
   runtime, registry, slots, BD desde una REPL real.
4. **Scaffolding genera código mínimo.** No genera tests, ni docker,
   ni CI. El usuario añade lo que necesite.
5. **`startproject` con `.` en lugar de subdirectorio.** UX
   importante — el usuario ya está dentro del directorio que quiere
   convertir en proyecto.
6. **`startproject` genera `index.html`** (no `welcome.html`).
   Convención que evita choques con apps que tengan `welcome`.

---

## 5. Errores comunes

| Síntoma | Causa | Solución |
|---|---|---|
| `hf: command not found` | No instalado o venv no activo. | `pip install hotframe` y activa venv. |
| `hf migrate` falla con "alembic.ini not found" | Estás fuera del directorio del proyecto. | `cd` al raíz del proyecto. |
| `hf modules install` no encuentra el módulo | Path mal o marketplace no configurado. | Revisa `MODULES_DIR` y `MODULE_MARKETPLACE_URL`. |
| `hf shell` falla al cargar settings | `main.py` no existe o `settings` no está en path. | `cd` al raíz, o usa `--settings=...`. |
| `hf shell` sin `await` directo | Usando plain REPL sin IPython. | `pip install "hotframe[shell]"` o usa el helper `run(coro)`. |
| `hf runserver` reload spam | `reload_dirs` muy amplio. | Usa explícitamente `--reload-dir`. |
