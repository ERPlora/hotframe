# discovery.md — App / module filesystem scanner

> **Carpeta cubierta:** `src/hotframe/discovery/`. Tres archivos:
> `__init__.py`, `scanner.py`, `conventions.py`.
> Recorre un directorio (`apps/` o `modules/`) y devuelve
> `DiscoveryResult` por cada subdirectorio: qué entry-point tiene,
> qué archivos conocidos detectó, qué imports tuvieron éxito o fallo.
> NO monta routers, NO toca el registry — eso lo hace el orquestador
> (`engine.module_runtime` o `bootstrap._auto_discover_apps`).

---

## 1. `__init__.py`

Sin reexports. El consumidor importa directamente de
`hotframe.discovery.scanner`:

```python
from hotframe.discovery.scanner import scan, DiscoveryResult, find_entry_config
```

Decisión: el módulo es de bajo nivel y solo lo usan otros subsistemas
del framework (engine, bootstrap, tests). No se expone como API
pública del top-level `hotframe`.

---

## 2. `conventions.py` — la tabla de convenciones

### 2.1 `Kind` enum

```python
class Kind(str, Enum):
    ENTRY_POINT = "entry_point"   # app.py XOR module.py
    MODELS = "models"             # SQLAlchemy classes
    ROUTES = "routes"             # urlpatterns or router (HTML views)
    API = "api"                   # APIRouter for REST
    SCHEMAS = "schemas"           # Pydantic schemas
    SERVICES = "services"         # ModuleService subclasses
    REPOSITORY = "repository"     # BaseRepository subclasses
    SIGNALS = "signals"           # @receiver, side effect on import
    MIGRATIONS = "migrations"     # Alembic dir
    TEMPLATES = "templates"       # Jinja2 dir
    STATIC = "static"             # Static assets dir
    LOCALES = "locales"           # i18n dir
    TESTS = "tests"               # pytest dir
    MANAGEMENT = "management"     # management/commands/*.py
```

Cada valor representa un **rol** que un archivo o directorio puede
desempeñar. `str` enum permite serializar y comparar trivialmente.

### 2.2 `Convention` dataclass

```python
@dataclass(frozen=True, slots=True)
class Convention:
    filename_or_dir: str           # "models.py" o "templates"
    kind: Kind
    is_directory: bool = False
    optional: bool = True          # False = ausencia es error
    required_exports: tuple[str, ...] = ()
```

`required_exports` tiene semántica **at-least-one-of**. Si está, el
módulo importado debe exportar **al menos uno** de los nombres. Esto
permite que una convención acepte múltiples shapes equivalentes —
por ejemplo:

```python
Convention("routes.py", Kind.ROUTES, optional=True,
           required_exports=("urlpatterns", "router"))
```

acepta tanto el shape Django-like (`urlpatterns = [...]`) como el
FastAPI-like (`router = APIRouter()`).

### 2.3 `APP_CONVENTIONS` — la lista canónica

```python
APP_CONVENTIONS: tuple[Convention, ...] = (
    Convention("app.py",       Kind.ENTRY_POINT),
    Convention("module.py",    Kind.ENTRY_POINT),
    Convention("models.py",    Kind.MODELS),
    Convention("routes.py",    Kind.ROUTES,
               required_exports=("urlpatterns", "router")),
    Convention("api.py",       Kind.API,
               required_exports=("router", "api_router")),
    Convention("schemas.py",   Kind.SCHEMAS),
    Convention("services.py",  Kind.SERVICES),
    Convention("repository.py", Kind.REPOSITORY),
    Convention("signals.py",   Kind.SIGNALS),
    Convention("migrations",   Kind.MIGRATIONS, is_directory=True),
    Convention("templates",    Kind.TEMPLATES, is_directory=True),
    Convention("static",       Kind.STATIC, is_directory=True),
    Convention("locales",      Kind.LOCALES, is_directory=True),
    Convention("tests",        Kind.TESTS, is_directory=True),
    Convention("management",   Kind.MANAGEMENT, is_directory=True),
)
```

Decisiones:

1. **Source of truth única.** Si quieres añadir un convention nuevo
   (e.g. `consumers.py` para Celery), lo añades aquí y el scanner
   lo recoge automáticamente.
2. **Todos optional excepto entry-point.** Una app/módulo puede tener
   solo `app.py` y nada más. Útil para apps "esqueleto" que solo
   exponen `AppConfig`.
3. **`app.py` XOR `module.py`** — comprobado en el scanner, no aquí.
4. **Orden cosmético**, no funcional. El scanner itera la tupla en el
   orden declarado solo por logs predecibles.

### 2.4 `conventions_by_kind()`

Helper para tests/introspección:

```python
def conventions_by_kind() -> dict[Kind, tuple[Convention, ...]]:
    grouped = defaultdict(list)
    for conv in APP_CONVENTIONS:
        grouped[conv.kind].append(conv)
    return {k: tuple(v) for k, v in grouped.items()}
```

`Kind.ENTRY_POINT → (Convention("app.py", ...), Convention("module.py", ...))`
es el único kind con dos convenciones; el resto son 1:1.

---

## 3. `scanner.py` — escáner

### 3.1 Modelo de datos

```python
@dataclass(slots=True)
class FileArtifact:
    convention: Convention
    path: Path
    imported_module: ModuleType | None = None  # set if imported
```

Una "cosa" detectada en el subdir: archivo o directorio que coincide
con una `Convention`.

```python
@dataclass(slots=True)
class DiscoveryResult:
    name: str                       # e.g. "accounts"
    root_path: Path                 # /path/to/apps/accounts
    package_name: str               # "apps.accounts"
    entry_point: FileArtifact | None = None
    artifacts: list[FileArtifact] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
```

`entry_point` se almacena por separado — es el único archivo
"singular" (todo lo demás puede haber 0/1 instancia).

`errors` se acumula sin abortar. Si un import falla pero la convención
era opcional, seguimos. Quien lea `errors` decide si elevar a fatal.

### 3.2 `scan(root, *, package_prefix, import_side_effects=True)`

Función principal:

```python
def scan(root, *, package_prefix, import_side_effects=True):
    if not root.is_dir():
        raise DiscoveryError(f"Root path is not a directory: {root}")

    results = []
    for subdir in sorted(root.iterdir(), key=lambda p: p.name):
        if not subdir.is_dir():
            continue
        if subdir.name in _SKIP_DIRS or subdir.name.startswith("."):
            continue
        result = _scan_subdir(subdir, package_prefix=package_prefix,
                              import_side_effects=import_side_effects)
        results.append(result)
    return results
```

- **Orden alfabético determinista** — `sorted(...).iterdir()`.
- **Skips**: `_SKIP_DIRS = {__pycache__, .pytest_cache, .mypy_cache,
  .ruff_cache, node_modules, .git}`, más cualquier dotfile.
- **`package_prefix`**: cómo importar la subdir como paquete dotted.
  Para `apps/`, pasa `"apps"`; el scanner construye `apps.accounts`,
  `apps.billing`, etc.
- **`import_side_effects=False`** — modo "dry run": no importa nada,
  solo lista paths. Útil para tests y para introspección.

### 3.3 `_scan_subdir(subdir, ...)`

Por cada subdirectorio:

1. **Crea el `DiscoveryResult` vacío.**

2. **Detecta colisión entry-point:**
   ```python
   app_py = subdir / "app.py"
   module_py = subdir / "module.py"
   if app_py.exists() and module_py.exists():
       raise DiscoveryError(...)
   ```
   Si tiene los dos, error duro — la convention es estricta.

3. **Itera `APP_CONVENTIONS`:**
   ```python
   for conv in APP_CONVENTIONS:
       candidate = subdir / conv.filename_or_dir
       if conv.is_directory:
           if not candidate.is_dir():
               continue
           result.artifacts.append(FileArtifact(conv, candidate))
           continue
       if not candidate.is_file():
           continue
       artifact = FileArtifact(conv, candidate)
       if import_side_effects:
           module_dotted = f"{package_name}.{candidate.stem}"
           try:
               artifact.imported_module = importlib.import_module(module_dotted)
           except ImportError as exc:
               result.errors.append(f"Failed to import {module_dotted}: {exc}")
           if artifact.imported_module is not None and conv.required_exports:
               present = [s for s in conv.required_exports
                          if hasattr(artifact.imported_module, s)]
               if not present:
                   raise DiscoveryError(...)
       if conv.kind is Kind.ENTRY_POINT:
           result.entry_point = artifact
       else:
           result.artifacts.append(artifact)
   return result
   ```

   Para directorios: solo registra paths, no importa nada (no son
   módulos Python). Para archivos: importa con `importlib`,
   verifica `required_exports`, y clasifica.

4. **Errores:**
   - `ImportError` → guardado en `result.errors` (no fatal — el caller
     decide).
   - Falla `required_exports` → `DiscoveryError` (fatal — la
     convention dice "uno de estos debe estar").

### 3.4 `find_entry_config(result)` — extrae el `AppConfig`/`ModuleConfig`

```python
def find_entry_config(result):
    if result.entry_point is None:
        raise DiscoveryError(...)
    if result.entry_point.imported_module is None:
        raise DiscoveryError(...)

    apps_config = importlib.import_module("hotframe.apps.config")
    AppConfig = apps_config.AppConfig

    module = result.entry_point.imported_module

    candidates = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if obj.__module__ != module.__name__:
            continue
        if not issubclass(obj, AppConfig):
            continue
        if obj is AppConfig:
            continue
        try:
            ModuleConfig = apps_config.ModuleConfig
            if obj is ModuleConfig:
                continue
        except AttributeError:
            pass
        candidates.append(obj)

    if len(candidates) == 0:
        raise DiscoveryError(f"No AppConfig/ModuleConfig subclass found in ...")
    if len(candidates) > 1:
        raise DiscoveryError(f"Multiple subclasses found: ...")

    return candidates[0]
```

Decisiones:

1. **Import deferido de `hotframe.apps.config`.** El scanner es
   "mid-layer" — `apps` es "high-layer". Importar estáticamente
   crearía un ciclo (`apps` también podría querer hablar con
   `discovery`). `importlib.import_module` rompe el ciclo.

2. **Filtro `obj.__module__ != module.__name__`**: ignora subclases
   importadas pero declaradas en otro fichero. Solo cuenta lo
   declarado **aquí**.

3. **Excluye las bases.** `AppConfig` y `ModuleConfig` no cuentan
   como candidates aunque sean subclases técnicas.

4. **Exactamente uno.** Cero o múltiples → error duro. Garantiza
   que cada `app.py`/`module.py` describe un único objeto config.

### 3.5 Quién llama a `scan`/`find_entry_config`

- **`bootstrap._auto_discover_apps`** llama a `scan` indirectamente
  (en realidad usa `Path.iterdir` directamente, pero la convention
  es la misma — el scanner es la API limpia para el mismo problema).
- **`engine.module_runtime`** lo usa al instalar un módulo — escanea
  `modules/<id>/`, encuentra `module.py`, llama `find_entry_config`,
  obtiene la subclase de `ModuleConfig`, y la usa para el manifest.
- **Tests** lo usan con `import_side_effects=False` para verificar
  estructura sin importar.

### 3.6 Decisiones que conviene recordar

1. **Discovery es side-effect-free salvo importlib.** No registra,
   no monta, no muta nada en `app.state`. Solo lee y lista.
2. **Errors no abortan, salvo `DiscoveryError`.** Imports fallidos
   se acumulan; convention violations son fatales.
3. **`required_exports` es at-least-one-of, no all-of.** Patrón clave
   para soportar múltiples shapes de un mismo concepto (Django vs
   FastAPI routes).
4. **El scanner desconoce `apps/`.** Importa via dotted path
   construido con `package_prefix`. Funciona igual sobre `modules/`
   o cualquier raíz.
5. **No es recursivo.** Escanea solo subdirectorios inmediatos.
6. **Determinista.** `sorted(iterdir())` garantiza orden estable
   entre runs y entornos.

### 3.7 Errores comunes

| Síntoma | Causa | Diagnóstico |
|---|---|---|
| `Subdirectory X contains BOTH app.py and module.py` | Confundiste apps con modules. | Decide cuál tipo eres y deja solo uno. |
| `routes.py must export at least one of: urlpatterns, router` | El archivo está pero no exporta ni `urlpatterns` ni `router`. | Añade `router = APIRouter()` o renombra el archivo. |
| `Failed to import apps.X.routes: ImportError ...` | El archivo tiene un syntax/import error. | Mira el `result.errors[0]` — el ImportError está literal. |
| `No AppConfig/ModuleConfig subclass found in app.py` | El `app.py` no declara una subclase. | Crea `class MyApp(AppConfig): name = "myapp"`. |
| `Multiple AppConfig subclasses found` | El archivo declara dos. | Déjalo en uno; el otro a un módulo separado. |

---

## 4. Cómo se relaciona con otros subsistemas

```
                        bootstrap.lifespan
                        engine.module_runtime
                                  │
                                  ▼
                         hotframe.discovery.scanner.scan()
                                  │
                                  ▼
                         list[DiscoveryResult]
                                  │
                                  ▼
                         find_entry_config(result) → AppConfig/ModuleConfig subclass
                                  │
                                  ▼
                         Caller monta routers, registra signals,
                         instancia services, etc.
```

`hotframe.components.discovery` (otra cosa, ojo) tiene su propia
lógica de escaneo orientada a `components/<name>/template.html`. Ese
es **distinto** del scanner aquí — no comparte código porque la
convention de "componente" es más rígida (siempre carpeta, siempre
`template.html` requerido) y la de apps/modules es más flexible.

---

## 5. Cuándo añadir una nueva convention

Si tu equipo decide que cada módulo debe poder declarar
`consumers.py` (e.g. para Kafka), el flujo es:

1. **Añadir entrada en `APP_CONVENTIONS`:**
   ```python
   Convention("consumers.py", Kind.CONSUMERS, optional=True,
              required_exports=("CONSUMERS",))
   ```
2. **Añadir `Kind.CONSUMERS` al enum.**
3. **El scanner los recoge automáticamente** — `result.find(Kind.CONSUMERS)`
   devuelve el `FileArtifact`.
4. **El consumer (engine, bootstrap, app) decide qué hacer** con el
   artefacto detectado.

Cero cambios en `scanner.py`. Toda la lógica vive en `conventions.py`.
