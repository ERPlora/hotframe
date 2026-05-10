# dev.md — Development-mode utilities (hot reload watcher)

> **Carpeta cubierta:** `src/hotframe/dev/`. Dos archivos:
> `__init__.py`, `autoreload.py`.
> Subsistema que **solo se activa en `DEBUG=True`**: en producción es
> un no-op (no se importa nada). Provee `ModuleWatcher` para detectar
> cambios en filesystem y disparar hot-reload de módulos.

---

## 1. `__init__.py` — descripción del paquete

Solo docstring. No importa nada al cargar — el cliente importa por
ruta explícita:

```python
from hotframe.dev.autoreload import ModuleWatcher
```

Documenta que:

- `ModuleWatcher` está construido sobre `watchfiles` (FSEvents en macOS,
  inotify en Linux), con fallback silencioso si no está instalado.
- Solo activo en dev. En producción `DEBUG=False` y nadie crea el
  watcher.

---

## 2. `autoreload.py` — `ModuleWatcher`

### 2.1 Filosofía

> Cuando un dev edita un fichero `.py` o `.html` de un módulo, debería
> ver el cambio en el navegador inmediatamente, sin reiniciar el
> servidor. Si el editor toca un archivo, **el watcher recarga ese
> módulo en memoria** vía `ModuleRuntime.hot_reload`.

Esto es un acelerador del ciclo dev — uvicorn ya tiene `--reload` que
reinicia el proceso entero al cambiar archivos. La diferencia es que
el `ModuleWatcher`:

- **No reinicia el proceso.** Mantiene la BD pool, sesiones live,
  caches en memoria.
- **Recarga solo el módulo afectado.** Si tocas
  `modules/inventory/routes.py`, solo `inventory` se recarga; el
  resto del Hub sigue.

### 2.2 La clase

```python
class ModuleWatcher:
    WATCH_EXTENSIONS = frozenset({".py", ".html", ".json", ".jinja2"})

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event = asyncio.Event()
```

Stateful pero sencillo: un task asyncio (`_task`) que corre el loop
de watchfiles, y un evento (`_stop_event`) para señalizar shutdown.

### 2.3 `start(modules_dir, on_change)`

```python
async def start(self, modules_dir, on_change):
    if self._task is not None:
        logger.warning("ModuleWatcher already running")
        return
    self._stop_event.clear()
    self._task = asyncio.create_task(
        self._watch_loop(modules_dir, on_change),
        name="module-watcher",
    )
```

`on_change` es un callable `(module_id: str) -> None | Awaitable`.
Típicamente `runtime.hot_reload`. Idempotente — llamar `start` dos
veces sobre el mismo watcher avisa con warning y no arranca otro.

### 2.4 `stop()`

```python
async def stop(self):
    if self._task is None:
        return
    self._stop_event.set()
    self._task.cancel()
    try:
        await self._task
    except asyncio.CancelledError:
        pass
    self._task = None
```

Dos señales: el `stop_event` (que `awatch` honra) y el `cancel()` de
asyncio (que también lo respeta). Tras `await self._task`, el watcher
está completamente parado.

### 2.5 `_watch_loop` — el corazón

```python
async def _watch_loop(self, modules_dir, on_change):
    try:
        from watchfiles import awatch
    except ImportError:
        logger.warning(
            "watchfiles not installed — hot-reload disabled. "
            "Install with: pip install watchfiles"
        )
        return

    debounce_ms = 300
    recently_reloaded: dict[str, float] = {}

    try:
        async for changes in awatch(
            modules_dir,
            stop_event=self._stop_event,
            debounce=debounce_ms,
            recursive=True,
        ):
            changed_modules: set[str] = set()

            for _change_type, changed_path in changes:
                path = Path(changed_path)
                if path.suffix not in self.WATCH_EXTENSIONS:
                    continue
                module_id = self._extract_module_id(modules_dir, path)
                if module_id:
                    changed_modules.add(module_id)

            now = asyncio.get_event_loop().time()
            for module_id in changed_modules:
                last = recently_reloaded.get(module_id, 0)
                if now - last < 1.0:
                    continue
                recently_reloaded[module_id] = now

                logger.info("Change detected in module %s — triggering hot-reload", module_id)
                try:
                    result = on_change(module_id)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    logger.exception("Error during hot-reload of %s", module_id)
    except asyncio.CancelledError:
        pass
```

Decisiones:

1. **`watchfiles` con import lazy.** Si la dep no está instalada, log
   warning y termina sin error. Hace el subsistema **opcional**.
2. **`debounce_ms=300`** — `watchfiles` ya agrupa cambios cercanos en
   un solo evento. 300ms cubre el caso de un editor que escribe
   varios archivos en rápida sucesión (e.g. saving + reformatting).
3. **`WATCH_EXTENSIONS`** — Solo `.py`, `.html`, `.json`, `.jinja2`.
   Ignora `.pyc`, `.git`, swap files. Reduce ruido.
4. **Deduplicación por `module_id`.** Si tres archivos del mismo
   módulo cambian, se reload una sola vez.
5. **Throttle de 1s por módulo** — `recently_reloaded[id] = now`. Si
   el dev guarda dos veces en menos de 1s, solo el primer save
   dispara reload. Sin esto, un autosave del editor podría dispar
   spam de reloads.
6. **Errores no crashean el loop.** `try/except` alrededor de cada
   `on_change` con `logger.exception` — un módulo que falla al
   reload no para el watcher.

### 2.6 `_extract_module_id(modules_dir, changed_path)`

```python
@staticmethod
def _extract_module_id(modules_dir, changed_path):
    try:
        relative = changed_path.relative_to(modules_dir)
        parts = relative.parts
        if parts:
            return parts[0]
    except ValueError:
        pass
    return None
```

`/tmp/modules/inventory/routes.py` con `modules_dir=/tmp/modules` →
`relative=inventory/routes.py` → `parts[0]='inventory'`. Si el path
no está bajo `modules_dir`, `relative_to` lanza `ValueError` y
devolvemos `None`.

### 2.7 Cómo se enchufa en el ciclo de vida

`bootstrap.py` no monta el `ModuleWatcher` automáticamente — es opt-in.
La integración típica:

```python
# main.py o un app.lifespan custom
from hotframe.dev.autoreload import ModuleWatcher

if settings.DEBUG:
    watcher = ModuleWatcher()
    runtime: ModuleRuntime = app.state.module_runtime

    async def on_change(module_id: str):
        try:
            await runtime.hot_reload(module_id)
        except Exception:
            logger.exception(f"Hot-reload of {module_id} failed")

    await watcher.start(settings.MODULES_DIR, on_change)
    # En shutdown:
    await watcher.stop()
```

`hot_reload` del runtime hace deactivate → activate del módulo (con
re-import de `sys.modules` por el `ImportManager`).

### 2.8 ¿Qué NO hace `ModuleWatcher`?

- **No recarga código del propio framework hotframe.** Solo módulos
  bajo `MODULES_DIR`. Si editas `hotframe/auth/csrf.py`, necesitas
  reiniciar el proceso (uvicorn `--reload` te ayuda).
- **No recarga apps bajo `apps/`.** Apps son estáticas (parte del
  proyecto). Cambiarlas requiere reinicio.
- **No recompila assets estáticos.** Si tu pipeline genera
  bundles, eso está fuera del scope.
- **No expira caches en memoria.** Los caches (e.g. `lru_cache`,
  config lazy) siguen calientes. Si tu módulo tiene un cache global,
  necesitas limpiarlo en el path de `hot_reload`.

### 2.9 Por qué watchfiles y no watchdog

- **watchfiles** es Rust-backed (notify crate), API async-friendly,
  rápido en dirs grandes.
- **watchdog** es pure Python, API sync con polling fallback. Más
  ligero pero menos eficiente.

Hotframe elige `watchfiles` porque el `awatch()` se integra
directamente con `asyncio` y soporta `stop_event` nativamente.

### 2.10 Errores comunes

| Síntoma | Causa | Diagnóstico |
|---|---|---|
| `watchfiles not installed — hot-reload disabled` | Falta dep. | `pip install watchfiles`. |
| Cambios no se reflejan | Editor guarda fuera de `modules_dir` o suffix no en `WATCH_EXTENSIONS`. | Verifica path. Añade el suffix si necesario. |
| Reload spam tras guardar | Editor toca múltiples archivos. | El throttle ya está en 1s; si necesitas más, sube el umbral. |
| Servicio no reapunta a la nueva versión | El `hot_reload` no limpió bien `sys.modules`. | Revisa logs del `ImportManager` y `ModuleRuntime.hot_reload`. |
| Watcher no para en shutdown | `stop()` no fue awaited. | Asegúrate de `await watcher.stop()` en el lifespan shutdown. |
