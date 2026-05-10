# migrations.md — Per-module Alembic runner

> **Carpeta cubierta:** `src/hotframe/migrations/`. Cuatro archivos:
> `__init__.py`, `runner.py`, `multi_namespace.py`, `env_helpers.py`.
> Cada módulo con `HAS_MODELS=True` puede shipear sus propias
> migraciones Alembic; el runner garantiza que cada uno tenga su
> propio `version_table` y no colisione con los demás.

---

## 1. `__init__.py`

Documenta el contrato. No reexporta nada — los consumers (engine,
CLI) importan directamente:

```python
from hotframe.migrations.runner import ModuleMigrationRunner
```

---

## 2. `runner.py` — `ModuleMigrationRunner`

```python
class ModuleMigrationRunner:
    async def upgrade(self, module_id, module_path, db_url):
        alembic_dir = module_path / "migrations"
        if not alembic_dir.exists(): return

        version_table = f"alembic_{module_id}"
        config = self._build_config(module_id, module_path, db_url, version_table)

        # Add module parent to sys.path so env.py can import the module
        sys.path.insert(0, str(module_path.parent))

        from sqlalchemy import create_engine
        def _run_upgrade():
            engine = create_engine(db_url, poolclass=NullPool)
            config.attributes["connection"] = engine
            command.upgrade(config, "head")
            engine.dispose()
        await asyncio.to_thread(_run_upgrade)

    async def downgrade(self, module_id, module_path, db_url):
        # Equivalente con command.downgrade(..., "base")
        ...

    def has_migrations(self, module_path) -> bool:
        return (module_path / "migrations" / "versions").exists() and \
               any((module_path / "migrations" / "versions").glob("*.py"))

    @staticmethod
    def get_sync_db_url(async_url) -> str:
        return async_url.replace("+asyncpg", "").replace("+aiosqlite", "")
```

### 2.1 Decisiones críticas

1. **`version_table = f"alembic_{module_id}"`** — cada módulo tiene
   su propia tabla de versiones. Sin esto, dos módulos con un
   `001_initial` se pisarían.

2. **`asyncio.to_thread(...)`** — Alembic es síncrono. Lo ejecutamos
   en un thread para no bloquear el event loop.

3. **`get_sync_db_url`** convierte URL async → sync. Alembic usa
   psycopg2 (no asyncpg) por defecto, así que despoja el sufijo
   `+asyncpg`/`+aiosqlite`.

4. **`config.attributes["connection"] = engine`** — pasamos el
   engine como attribute. El `env.py` del módulo puede leerlo y
   reusar la conexión, en lugar de crear su propio engine. Esto
   evita que `env.py` use `async_engine_from_config` y falle con
   psycopg2.

5. **`NullPool`** — Alembic abre y cierra la conexión por comando.
   No queremos un pool persistente para una migración one-shot.

6. **`sys.path.insert(0, str(module_path.parent))`** — el `env.py`
   del módulo tiene `from modules.<id>.models import Model`. Sin
   añadir el parent al path, `import modules` falla.

### 2.2 `downgrade` — al uninstall

```python
async def downgrade(self, module_id, module_path, db_url):
    config = self._build_config(...)
    await asyncio.to_thread(command.downgrade, config, "base")
```

Borra **todas** las tablas del módulo. Llamado por
`module_runtime.uninstall` después del `on_uninstall` hook (que el
módulo puede usar para preservar datos en otro lado si quiere).

`base` significa "versión cero" — antes de la primera revisión.

### 2.3 `_build_config(...)`

```python
@staticmethod
def _build_config(module_id, module_path, db_url, version_table):
    migrations_dir = module_path / "migrations"
    ini_path = migrations_dir / "alembic.ini"
    config = Config(str(ini_path)) if ini_path.exists() else Config()
    config.set_main_option("script_location", str(migrations_dir))
    config.set_main_option("sqlalchemy.url", db_url)
    config.set_main_option("version_table", version_table)
    config.attributes["module_id"] = module_id
    config.attributes["module_path"] = str(module_path)
    config.attributes["version_table"] = version_table
    return config
```

`alembic.ini` es opcional dentro del módulo. Si no existe, Alembic
construye un `Config()` vacío y los `set_main_option` configuran
todo desde cero.

`config.attributes` permite que un `env.py` lea info via
`context.config.attributes["module_id"]` — útil para construir el
`version_table` allí.

---

## 3. `multi_namespace.py`

Helper para casos en los que **múltiples paquetes** (apps + módulos
+ core) compartan migraciones bajo un mismo proyecto Alembic.

```python
class MultiNamespaceRunner:
    """Run migrations across multiple namespaces with namespacing.

    For projects that prefer ONE alembic/ directory with all migrations
    rather than per-module directories. Each migration is tagged with
    a `namespace` attribute and the runner upgrades only those matching
    the current run.
    """
    async def upgrade(self, namespaces: list[str], db_url): ...
```

Patrón menos común — el setup default (per-module Alembic) es lo
recomendado. `MultiNamespaceRunner` existe para proyectos legacy
que ya tienen ese layout.

---

## 4. `env_helpers.py`

Funciones para usar dentro de `migrations/env.py` en el módulo:

```python
def configure_async_target_metadata(config, base_metadata, ...):
    """Helper to wire an async-aware env.py with the runner's connection."""
    ...

def get_module_metadata(config) -> MetaData:
    """Return only the metadata of tables defined in this module."""
    module_id = config.attributes.get("module_id")
    return _filter_metadata_by_module(Base.metadata, module_id)
```

Los `env.py` que generamos con `hf startmodule` ya usan estos
helpers. Para módulos legacy escritos a mano, los devs pueden
adoptar.

---

## 5. Estructura típica de migrations dentro de un módulo

```
modules/<id>/
└── migrations/
    ├── alembic.ini    # opcional
    ├── env.py
    ├── script.py.mako
    └── versions/
        ├── 001_initial.py
        ├── 002_add_field_x.py
        └── ...
```

### 5.1 `env.py` (template generado)

```python
from logging.config import fileConfig
from alembic import context
from sqlalchemy import pool

from hotframe.models.base import Base
from modules.<id> import models   # imports trigger model registration

config = context.config
target_metadata = Base.metadata     # all base subclasses

def run_migrations_online():
    connectable = config.attributes.get("connection")  # provided by runner
    if connectable is None:
        connectable = engine_from_config(config.get_section(config.config_ini_section), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=config.get_main_option("version_table"),
            include_schemas=True,
            include_object=lambda obj, name, type_, ...:
                _belongs_to_this_module(obj, config.attributes["module_id"]),
        )
        with context.begin_transaction():
            context.run_migrations()

run_migrations_online()
```

`include_object` filtra: solo las tablas del módulo entran en el
autogenerate. Sin esto, un `alembic revision --autogenerate` en el
módulo X intentaría borrar las tablas de Y porque no están en el
metadata local.

---

## 6. Decisiones que conviene recordar

1. **Una `version_table` por módulo.** Aislamiento total. Permite
   instalar/desinstalar módulos sin tocar el state de otros.
2. **`asyncio.to_thread` para Alembic.** El runner expone una API
   async, pero por dentro Alembic es sync.
3. **`include_object` filtra.** Cada módulo "ve" solo sus tablas en
   autogenerate.
4. **`base` no es delete-all.** Es revertir al estado pre-primera-
   revisión. Si tu primera revisión `CREATE TABLE`, `downgrade base`
   `DROP TABLE`.
5. **`get_sync_db_url`** quita sufijos async. Necesario porque
   Alembic + psycopg2 + URL `+asyncpg` no compilan.
6. **El runner no commitea.** `command.upgrade` lo hace
   internamente con su propia conexión. La `session` async del caller
   no se ve afectada.

---

## 7. Errores comunes

| Síntoma | Causa | Diagnóstico |
|---|---|---|
| `Can't load plugin: sqlalchemy.dialects:postgresql.asyncpg` | URL no convertida a sync. | Llama `runner.get_sync_db_url(settings.DATABASE_URL)`. |
| `Target database is not up to date` en autogenerate | Hay revisiones por aplicar. | `hf modules install` ya corre upgrade primero. Para dev solo, `alembic upgrade head` manual en el dir del módulo. |
| `KeyError: 'connection'` en `env.py` | El runner no pasó `connection`. | Verifica que el `env.py` usa `config.attributes.get("connection", ...)` con fallback. |
| `Multiple head revisions` | Tienes dos branches de migrations. | `alembic merge` para mergearlas, o resetea history. |
| Tablas de otros módulos aparecen en autogenerate | Falta `include_object` filter. | Añade el lambda en `context.configure`. |
| `ImportError: No module named modules.X` | `sys.path` no incluye el parent. | El runner ya lo añade — si lo ejecutas a mano, `cd` al raíz del proyecto antes de `alembic upgrade`. |
