# engine.md — Module hot-mount engine

> **Carpeta cubierta:** `src/hotframe/engine/`. Doce archivos principales:
> `__init__.py`, `module_runtime.py` (1939 LOC, el orquestador), `loader.py`,
> `pipeline.py` (state machine + LIFO rollback), `state.py`, `boundary.py`,
> `dependency.py` (topological sort), `lifecycle.py`, `import_manager.py`
> (sys.modules + weakref), `marketplace_client.py`, `s3_source.py`, `models.py`.
> Es el **corazón** de hotframe — todo lo "hot-mount" pasa por aquí.

---

## 1. ¿Qué hace el subsistema?

Permite **instalar, activar, desactivar, actualizar y desinstalar
módulos en caliente**, sin reiniciar el proceso. Cada módulo es:

- Una carpeta con `module.py` (manifest + `ModuleConfig`),
  `models.py`, `routes.py`, `templates/`, `migrations/`, etc.
- Un paquete que el engine importa, monta como router en FastAPI,
  ejecuta sus migraciones Alembic, registra sus signals/hooks/slots,
  y vacía limpiamente al desinstalar.

Cada operación del ciclo de vida es **atómica**: si una fase falla,
las anteriores se deshacen en orden LIFO (`HotMountPipeline`).

---

## 2. `__init__.py` — fachada

```python
from hotframe.engine.import_manager import ImportedBundle, ImportManager, PurgeReport
from hotframe.engine.loader import ModuleLoader
from hotframe.engine.module_runtime import (
    ActivateResult, DeactivateResult, InstallResult,
    ModuleRuntime, UninstallResult, UpdateResult,
)
from hotframe.engine.pipeline import (
    HotMountPipeline, PhaseResult, PhaseStatus, PipelineState, RollbackHandle,
)
```

API pública: orquestador (`ModuleRuntime`), primitives (`ImportManager`,
`HotMountPipeline`, `ModuleLoader`), y los dataclasses de resultado.

---

## 3. `module_runtime.py` — `ModuleRuntime` (orquestador)

### 3.1 ¿Qué pasa con cada operación?

| Op | Pasos clave | Rollback |
|---|---|---|
| **install** | DOWNLOADING → VALIDATING (manifest + canonical rename) → VALIDATING (deps) → MIGRATING (DB row + alembic) → IMPORTING (`on_install`) → MOUNTING (loader + templates) → STACK_REBUILD (`on_activate` + DB activate) | LIFO via `HotMountPipeline` |
| **activate** | code-on-disk check → manifest → deps → loader.load → `on_activate` → DB activate | unload + set_error |
| **deactivate** | system-module check → dependents check (cascade?) → `on_deactivate` → unload → DB deactivate | set_error |
| **uninstall** | system check → dependents BLOCK (no cascade) → `on_deactivate` → unload → `on_uninstall` → migrations downgrade → DB delete | set_error |
| **update** | download new → validate → `on_deactivate` + unload → migrate → `on_upgrade` → load new → `on_activate` → DB update | reload old version + set_error |
| **boot** | restore S3 ETag cache → query active → resolve catalog versions → ensure code on disk → topological sort → load each | per-module set_error |
| **hot_reload** | re-load manifest → re-check deps → loader.reload | logged, returns False |

### 3.2 Sub-systems que orquesta

```python
class ModuleRuntime:
    def __init__(self, app, settings, event_bus, hooks, slots, components=None):
        self.registry = ModuleRegistry()              # in-memory state
        self.loader = ModuleLoader(...)               # importlib + mount
        self.state = ModuleStateDB()                  # hub_module CRUD
        self.s3 = S3ModuleSource(...) if MODULE_SOURCE=='s3' else None
        self.deps = DependencyManager()               # topological sort
        self.lifecycle = ModuleLifecycleManager()     # on_* hooks
        self.migrations = ModuleMigrationRunner()     # per-module Alembic
        self.watcher = ModuleWatcher()                # dev hot-reload
```

Cada uno tiene su archivo (ver más abajo). `ModuleRuntime` no
implementa la lógica detallada — la **delega** y se preocupa del
orden y los rollbacks.

### 3.3 Boot multi-worker — advisory lock

Detalle crítico: en producción uvicorn corre `--workers N`. Cada
worker hace `boot_all_active_modules` independientemente. Sin
coordinación, todos hacen `UPDATE hub_module SET manifest=...` y
deadlock en Postgres.

Solución: **advisory lock** por hub:

```python
async def _try_acquire_boot_lock(self, session, hub_id):
    if dialect != "postgresql":
        return True   # SQLite no necesita
    key = _hub_id_to_advisory_key(str(hub_id) if hub_id else "__global__")
    result = await session.execute(
        text("SELECT pg_try_advisory_xact_lock(:key)"),
        {"key": key},
    )
    return bool(result.first()[0])
```

`_hub_id_to_advisory_key` usa BLAKE2b → first 8 bytes → signed int64.
Determinista entre workers (no usa `hash()` que está salt-per-process).

Worker que pierde el lock: **monta routers en su FastAPI local**
(necesario para servir tráfico) pero **no escribe en BD** → flag
`skip_db_writes=True` en `boot()`.

### 3.4 Phases del install

Cada `_phase_X` retorna un `PhaseResult` con `payload` y un
`RollbackHandle` que sabe deshacer **solo sus efectos**. Ejemplo:

```python
async def _phase_download(self, module_id, version, checksum, source):
    # ... resolver source y descargar a target_path ...
    target_path = Path(MODULES_DIR) / module_id

    class _DownloadRollback:
        async def undo(self):
            if target_path.exists():
                shutil.rmtree(target_path, ignore_errors=True)

    return PhaseResult(
        phase_name="DOWNLOADING",
        rollback=_DownloadRollback(),
        payload={"module_path": target_path},
    )
```

Cinco source resolutions:
1. URL (`http://`/`https://`) → `MarketplaceClient.download`
2. Local `.zip` → extract directo
3. Ya en disco → skip download
4. `MODULE_MARKETPLACE_URL` → resolver + download
5. S3 fallback (legacy)

`_phase_validate`: parsea el manifest. Si `MODULE_ID` del manifest
difiere del catalog key, **renombra la carpeta** al canonical y
actualiza `HubModuleVersion.module_id` en BD. Documentado: "no undo
en el catalog rename — self-heals on next publish".

`_phase_check_deps`: usa `DependencyManager.check_install_deps`.
Falla si missing/version-mismatch/inactive (sin `auto_install_deps`).

`_phase_migrate`: `state.create(status='installing')` + Alembic
`upgrade` si `manifest.HAS_MODELS`. Rollback: `downgrade` + `state.delete`.

`_phase_on_install`: ejecuta el hook `on_install` del módulo. **Sin
undo** (los módulos limpian en `on_uninstall`).

`_phase_mount`: `loader.load_module` + `_refresh_templates`. Rollback:
`loader.unload_module`.

`_phase_activate`: `on_activate` + `state.activate`. Rollback no-op
(el `_phase_migrate.undo` ya borra el row, así que aquí flippear
status crearía race).

### 3.5 `_load_from_path` — defensive rollback

En boot, si un módulo falla, antes de `set_error`:

```python
try:
    await session.rollback()
except Exception:
    pass
try:
    await self.state.set_error(session, module_id, str(e), hub_id=hub_id)
```

El rollback es defensivo: si la transacción del `load_module` quedó
poisoned (e.g. constraint violation), `set_error` re-fallaría con
"current transaction is aborted". Limpiarla primero garantiza que
el log de error se persista.

---

## 4. `loader.py` — `ModuleLoader`

Donde realmente sucede el `import` y el `app.include_router`:

- **`load_module(module_id, path, manifest)`**:
  1. `ImportManager.import_module(path)` → trae `module.py`,
     `models.py`, `routes.py` etc. al `sys.modules` con namespace
     dotted.
  2. Si tiene `routes.py:router`, `app.include_router(router,
     prefix=f"/m/{module_id}", tags=[module_id])`.
  3. Discover & register components del módulo
     (`discover_module_components`).
  4. Mount component routers + static.
  5. Subscribe signals/hooks/slots desde `module.py`.
  6. `registry.register(RegisteredModule(...))`.

- **`unload_module(module_id)`**:
  1. Unsubscribe signals/hooks/slots.
  2. Unmount component routers + static (`unmount_component_*_for_module`).
  3. Unregister components (`registry.unregister_module`).
  4. Filtrar `app.router.routes` para quitar las del prefijo `/m/<id>`.
  5. `ImportManager.purge_bundle(...)` — borra de `sys.modules` y
     verifica zombies con weakref.
  6. `registry.unregister(module_id)`.

- **`reload_module`**: `unload` + `load` (la base del hot-reload).

`app.openapi_schema = None` después de mount/unmount para regenerar
el schema.

---

## 5. `pipeline.py` — `HotMountPipeline` (state machine)

```python
class PhaseStatus(str, Enum):
    PENDING, RUNNING, SUCCESS, ROLLED_BACK, FAILED

@dataclass
class PhaseResult:
    phase_name: str
    rollback: RollbackHandle
    payload: dict

class RollbackHandle(Protocol):
    async def undo(self) -> None: ...
```

`HotMountPipeline.run_phase(name, fn, *args)` ejecuta la fase, captura
su `PhaseResult`, y lo añade a su pila. Si lanza, el caller llama
`pipeline.rollback()` que itera la pila en LIFO ejecutando cada
`undo()`.

`commit()` marca todas las fases como `SUCCESS` y limpia la pila —
después de esto, `rollback()` es no-op.

```python
pipeline = HotMountPipeline(module_id="X")
await pipeline.run_phase("DOWNLOADING", _phase_download, ...)
await pipeline.run_phase("VALIDATING", _phase_validate, ...)
# ... if anything raises ...
errors = await pipeline.rollback()    # un-does in reverse
# ... if all good ...
await pipeline.commit()
```

Un `RollbackHandle` que falla **no para la cadena** — recolectamos
todos los errores y los devolvemos al caller. El state que quede
inconsistente lo arregla manualmente el operador.

---

## 6. `state.py` — `ModuleStateDB`

CRUD sobre la tabla `hub_module`:

```python
class ModuleStateDB:
    async def get_module(session, module_id, *, hub_id=None) -> RowOrNone
    async def get_active_modules(session, *, hub_id=None) -> list
    async def create(session, module_id, version, *, status, hub_id, ...) -> Row
    async def activate(session, module_id, manifest, *, hub_id) -> None
    async def deactivate(session, module_id, *, hub_id) -> None
    async def update_manifest(session, module_id, manifest, *, hub_id) -> None
    async def set_error(session, module_id, error_msg, *, hub_id) -> None
    async def delete(session, module_id, *, hub_id) -> None
```

El modelo es **swappable** vía `settings.MODULE_STATE_MODEL`. Helper:

```python
def _get_module_model() -> type[Any]:
    settings = get_settings()
    if settings.MODULE_STATE_MODEL:
        return importlib.import_module(...).Model
    from hotframe.engine.models import Module
    return Module
```

Permite a un Hub usar su propio `HubModule` (con `hub_id`,
`installed_by`, etc.) sin tocar hotframe. Si no se define,
`hotframe.engine.models.Module` es el modelo por defecto.

---

## 7. `boundary.py` — `ModuleBoundaryMiddleware`

Middleware que **captura excepciones de un módulo** y las convierte
en HTTP 500 con un payload uniforme + log con `module_id` y
`module_version`.

```python
class ModuleBoundaryMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        try:
            return await call_next(request)
        except Exception as e:
            module_id = self._extract_module_id(request.url.path)
            logger.exception("Module %s crashed: %s", module_id, e)
            return JSONResponse(
                {"detail": f"Module {module_id} error", "error_id": ...},
                status_code=500,
            )
```

Está fuera de `ModuleMiddlewareManager` para capturar incluso errores
de middlewares contribuidos por módulos. Es la última red de
seguridad antes del 500 genérico.

---

## 8. `dependency.py` — `DependencyManager`

```python
class DependencyManager:
    def resolve_load_order(self, items: list) -> list:
        """Topological sort: dependencies before dependents."""
    async def check_install_deps(self, session, manifest, *, hub_id) -> DepCheckResult:
        """missing? version_mismatch? inactive?"""
    async def check_can_deactivate(self, session, module_id, *, hub_id) -> Result:
        """Find modules that depend on this. cascade_order calculated."""
    async def check_can_uninstall(self, session, module_id, *, hub_id) -> Result:
        """Block unconditionally if any dependent (any status) exists."""
    async def deactivate_cascade(self, session, module_id, runtime, *, hub_id):
        """Walk the cascade_order and call runtime.deactivate on each."""
```

Topological sort: Kahn's algorithm con detección de ciclos (lanza
`CircularDependencyError`).

`check_install_deps` parsea version constraints (`>=1.0`, `<2`,
`==1.5`) y compara con la catalog table.

---

## 9. `lifecycle.py` — `ModuleLifecycleManager`

Invoca hooks declarados en `module.py`:

```python
class ModuleLifecycleManager:
    async def call(self, module_id, hook_name, *args, **kwargs):
        # Looks up sys.modules[f"modules.{module_id}.module"]
        # Calls hook_name if defined; logs and re-raises on error.
```

Hooks soportados:
- `on_install(session, hub_id)` — primer install
- `on_activate(session, hub_id)` — cada activación
- `on_deactivate(session, hub_id)` — cada desactivación
- `on_uninstall(session, hub_id)` — antes de borrar code/migrations
- `on_upgrade(session, hub_id, *, from_version, to_version)` — entre versiones

---

## 10. `import_manager.py` — `ImportManager`

El componente más sutil. Carga código en `sys.modules` y luego lo
**purga limpiamente**, detectando zombies (referencias residuales
que impedirían un re-import limpio).

```python
@dataclass
class ImportedBundle:
    module_id: str
    root_module: ModuleType   # modules.<id>.module
    all_names: list[str]      # ["modules.<id>", "modules.<id>.module", ...]
    weak_refs: dict[str, weakref.ref]

class ImportManager:
    def import_bundle(self, path) -> ImportedBundle:
        # spec_from_file_location for each .py
        # sys.modules[name] = module
    def purge_bundle(self, bundle: ImportedBundle) -> PurgeReport:
        for name in bundle.all_names:
            del sys.modules[name]
        gc.collect()
        zombies = {name: ref() for name, ref in bundle.weak_refs.items() if ref() is not None}
        return PurgeReport(removed=len(...), zombies=zombies)
```

`PurgeReport.zombies` lista cualquier objeto del módulo que sigue
vivo después del `gc.collect()` — pista de que algún consumer
(typeahead cache, signal sin desuscribir, etc.) está pinneando al
módulo y un re-install crearía un duplicado.

---

## 11. `marketplace_client.py` — `MarketplaceClient`

HTTP client para descargar módulos:

```python
class MarketplaceClient:
    async def resolve(module_id, version=None) -> ModuleInfo:
        # GET {marketplace_url}/modules/{id}/{version or 'latest'}
    async def download(url, cache_dir, expected_checksum) -> Path:
        # httpx GET → cache → verify SHA-256 → extract zip → return path
    @staticmethod
    def _extract_zip(zip_path, cache_dir) -> Path:
        # ZipFile.extractall, devuelve la primera subcarpeta
```

Cache en `MODULES_CACHE_DIR`. Si checksum no coincide, raise
`ChecksumMismatch` (no se cachea).

---

## 12. `s3_source.py` — `S3ModuleSource`

Backend alternativo al marketplace:

```python
class S3ModuleSource:
    def __init__(self, bucket, cache_dir, region):
        self.s3 = boto3.client("s3", region_name=region)
        self.etag_cache: dict[str, str] = {}
    def load_cached_etags(self):
        # Lee /tmp/etag-cache.json
    async def download(module_id, version, checksum) -> Path:
        # 1. HEAD s3://bucket/modules/{id}/{version}.zip → get ETag
        # 2. If cached etag matches → return cache path
        # 3. Else GET → verify checksum → extract → save etag
    async def download_many(items) -> dict:
        # asyncio.gather sobre download
    def clear_cache(module_id):
        # rm -rf cache/{module_id}*
```

ETag cache acelera boots: si el zip en S3 no cambió, no re-descarga.

---

## 13. `models.py` — `Module` (default state model)

Modelo SQLAlchemy default para `module` table:

```python
class Module(Base):
    __tablename__ = "module"
    module_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))  # installing, installed, active, disabled, error
    version: Mapped[str] = mapped_column(String(32))
    checksum_sha256: Mapped[str] = mapped_column(String(64), default="")
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    installed_at, activated_at, disabled_at: timestamps
```

Multi-tenant projects usan su propio modelo con `hub_id` y lo
declaran en `settings.MODULE_STATE_MODEL`.

---

## 14. Decisiones de diseño globales

1. **El pipeline es genérico.** `HotMountPipeline` no sabe nada de
   módulos. Se reusa para cualquier flujo con rollback LIFO.
2. **Cada fase es independiente.** Su `RollbackHandle` cierra solo
   sobre los valores capturados al éxito de esa fase — no hace
   suposiciones sobre fases siguientes.
3. **Errores en rollback no abortan otros rollbacks.** Recolectamos
   todos los errores; el operador decide si remediar.
4. **`set_error` siempre es best-effort.** Si la BD también está
   rota, no hay donde escribir; al menos el log sale.
5. **System modules (`is_system=True`) no se pueden desactivar ni
   desinstalar.** El runtime lo verifica antes de tocar nada.
6. **Código en disco vs catalog en BD.** BD es source-of-truth para
   "qué está instalado". S3/marketplace es source-of-truth para
   "qué código corresponde a qué versión". Disco local es caché.
7. **`/m/<module_id>/` es el namespace público.** Routers con otro
   prefix no funcionan con el unmount actual.
8. **Workers múltiples requieren advisory lock.** SQLite skipea.
   PostgreSQL serializa por hub. Cada worker monta routes localmente.

---

## 15. Errores comunes

| Síntoma | Causa | Diagnóstico |
|---|---|---|
| `Module X is already installed (status=...)` | Reinstalando un módulo activo. | Uninstall primero o usa update. |
| `Cannot deactivate: modules depend on this: [...]` | Tiene dependents activos. | Cascade=True o desactiva los dependents primero. |
| `Cannot uninstall: other modules depend on this one` | Cualquier dependent (incluso disabled). | Uninstall todos los dependents — uninstall NUNCA cascadea. |
| `Module code not available after S3 download` | El bucket no tiene la versión solicitada. | Verifica `S3_MODULES_BUCKET` y la version requested. |
| `Manifest validation failed` | `module.py` no exporta `ModuleConfig` válido. | Mira `apps/config.py` y comprueba `MODULE_ID`, `MODULE_NAME`, `MODULE_VERSION`. |
| `Hot-reload X: dependency Y is not loaded` | Cambiaste `DEPENDENCIES` de X y Y no estaba activo. | Activa Y o quita la dep. |
| Workers boot deadlock en Postgres | Sin advisory lock. | Asegúrate de que `_try_acquire_boot_lock` es llamado (lo está por defecto). |
| `current transaction is aborted` durante boot | Una excepción dejó la sesión rota. | El `_load_from_path` ya hace `session.rollback()` antes de `set_error`. Si todavía falla, mira el primer error. |
| `Zombies found in PurgeReport` | Algún consumer mantiene refs vivas a clases del módulo. | Mira `PurgeReport.zombies` — el dict te dice qué nombres siguen alive. Caches globales son el sospechoso típico. |
