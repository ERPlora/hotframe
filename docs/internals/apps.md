# `apps/` — App / Module configuration

Cuatro archivos. Define los **dos contratos base** del sistema: `AppConfig`
(apps estáticas que existen mientras vive el proceso) y `ModuleConfig`
(módulos dinámicos instalables/desinstalables en runtime). También
contiene el manifest validator (`ModuleManifest`) y los registries
en memoria (`ModuleRegistry`, `AppRegistry`).

```
apps/
├── __init__.py           ← (vacío, paquete marker)
├── config.py             ← ModuleManifest + AppConfig + ModuleConfig
├── registry.py           ← ModuleRegistry, AppRegistry, RegisteredModule
└── service_facade.py     ← ModuleService, @action, SERVICE_REGISTRY
```

---

## `apps/config.py` (~324 LOC)

**Propósito**: Schema strict del `module.py` (manifest) + clases base
para apps y módulos.

### `MenuConfig` y `NavigationItem`

```python
class MenuConfig(BaseModel):
    label: str
    icon: str = "cube-outline"
    order: int = 50

class NavigationItem(BaseModel):
    label: str
    icon: str
    id: str
    view: str = ""
```

Sub-models de Pydantic. El `MenuConfig` es la entrada en el sidebar
global; `NavigationItem` son las pestañas internas dentro del módulo.

### `ModuleManifest`

El **schema estricto** de lo que un `module.py` debe exponer. Si la
validación falla, el módulo NO carga y su fila DB queda en `error`.

```python
class ModuleManifest(BaseModel):
    MODULE_ID: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    MODULE_NAME: str
    MODULE_VERSION: str = Field(pattern=r"^\d+\.\d+\.\d+")
    MODULE_ICON: str = "cube-outline"
    MODULE_DESCRIPTION: str = ""
    MODULE_AUTHOR: str = ""
    HAS_MODELS: bool = False

    MENU: MenuConfig | None = None
    NAVIGATION: list[NavigationItem] = []
    PERMISSIONS: list[str] = []
    ROLE_PERMISSIONS: dict[str, list[str | tuple]] = {}
    DEPENDENCIES: list[str] = []
    MIDDLEWARE: str | None = None
    SCHEDULED_TASKS: list[dict] = []
    PRICING: dict | None = None
```

**Detalles**:

- **`MODULE_ID` regex**: `^[a-z][a-z0-9_]*$`. Sólo letras minúsculas,
  empieza por letra. Esto es porque el id se usa como path component
  (`/m/<id>/`) y como dotted Python path (`from <id>.routes import
  router`). Ambos exigen identifiers válidos.
- **`MODULE_VERSION` regex**: `\d+\.\d+\.\d+`. Semver requerido. El
  `DependencyManager` parsea para chequear compatibility.
- **`PERMISSIONS` validator**: acepta strings sueltos o tuplas
  `(codename, description)`. El normalizador toma sólo el codename:

  ```python
  @field_validator("PERMISSIONS", mode="before")
  @classmethod
  def normalize_permissions(cls, v: Any) -> list[str]:
      result = []
      for item in v:
          if isinstance(item, (tuple, list)):
              result.append(str(item[0]))
          else:
              result.append(str(item))
      return result
  ```

  Esto permite que el dev escriba `PERMISSIONS = [("view", "View customers"),
  ("edit", "Edit customers")]` y el manifest lo guarde como
  `["view", "edit"]`.

### `load_manifest(module_path)`

```python
def load_manifest(module_path: Path) -> ModuleManifest:
    module_py = module_path / "module.py"
    if not module_py.exists():
        raise FileNotFoundError(...)

    tmp_name = f"_manifest_loader_{module_path.name}"
    spec = importlib.util.spec_from_file_location(tmp_name, str(module_py))
    mod = importlib.util.module_from_spec(spec)

    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(tmp_name, None)

    data = {}
    for attr in _MANIFEST_FIELDS:
        value = getattr(mod, attr, None)
        if value is not None:
            data[attr] = value

    return ModuleManifest(**data)
```

**Algoritmo**:

1. Lee `module.py` con un nombre temporal en `sys.modules`.
2. **Inmediatamente lo saca de `sys.modules`** en el `finally` —
   sólo queremos extraer los atributos top-level, no que el módulo
   quede registrado.
3. Para cada atributo declarado en `_MANIFEST_FIELDS` (las keys de
   `ModuleManifest.model_fields`), si existe en el módulo, lo añade al
   dict.
4. Construye y valida con Pydantic. Cualquier campo inválido
   (regex, tipo, etc.) levanta `ValidationError`.

**Por qué nombre temporal**: si dos módulos diferentes definen
`MODULE_ID = "x"` no queremos que sus archivos `module.py` colisionen
en `sys.modules`. El nombre temporal incluye el path para garantizar
unicidad.

### `manifest_to_dict(manifest)`

Convierte el manifest validado a un dict JSON-safe con keys
"snake_case" cortas:

```python
_KEY_MAP = {
    "MODULE_ID": "module_id",
    "MODULE_NAME": "name",
    "MODULE_VERSION": "version",
    "MODULE_ICON": "icon",
    # ...
}
```

Esto es lo que se persiste en `module.manifest` (columna JSON). Los
templates y vistas leen siempre el formato corto.

### `AppConfig`

La clase base para apps estáticas:

```python
class AppConfig:
    name: str = ""
    verbose_name: str = ""
    mount_prefix: str = ""
    media_path: str = ""
    version: str = "0.1.0"
    depends: list[str] = []
    permissions: list[tuple[str, str]] = []
    role_permissions: dict[str, list[str]] = {}
    menu: dict | None = None
    navigation: list[dict] = []
    is_builtin: bool = False
    _abstract: bool = False

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if "_abstract" not in cls.__dict__:
            cls._abstract = False
        if cls._abstract:
            return
        if not cls.name:
            raise ValueError(f"{cls.__name__}: AppConfig subclass must define 'name'")

    async def ready(self) -> None:
        return None
```

**Detalles importantes**:

1. **`_abstract` flag**: `ModuleConfig` (subclase de `AppConfig`) lo
   pone a `True` para no requerir `name` en sí misma. Cualquier
   subclase concreta hereda el flag a `False` automáticamente, así
   que sí se le exige el `name`.
2. **El check de `name` corre en `__init_subclass__`**: cualquier
   subclase sin `name` lanza `ValueError` al **definir** la clase, no
   al instanciarla. Esto coge el bug temprano.
3. **`async def ready()`**: hook one-shot llamado tras montar todas
   las apps. Sirve para wireup de signals, hooks, etc. No bloquea el
   boot del proceso si tarda — pero `_auto_discover_apps` lo ejecuta
   en un loop fresco (`asyncio.run`) para que apps con ready async
   funcionen.

### `ModuleConfig`

```python
class ModuleConfig(AppConfig):
    _abstract: bool = True

    requires_restart: bool = False
    is_system: bool = False
    has_views: bool = True
    has_api: bool = True
    media_path: str = ""
    s3_key: str | None = None
    sha256: str | None = None

    async def install(self, ctx) -> None:
        return None

    async def uninstall(self, ctx) -> None:
        return None

    async def activate(self, ctx) -> None:
        return None

    async def deactivate(self, ctx) -> None:
        return None
```

Cuatro hooks adicionales sobre `AppConfig`:

- **`install`**: una vez cuando se instala. Seedeo de datos default,
  creación de configs.
- **`uninstall`**: cuando se desinstala. Cleanup idempotente.
- **`activate`**: cuando pasa a `active` (post-install o re-enable).
- **`deactivate`**: cuando el user lo desactiva.

`ctx` es un dict con (típicamente) `session`, `hub_id`, `module_path`.
Los hooks son no-op por defecto.

`is_system=True` → no se puede desinstalar desde UI (se reserva
para módulos que el host depende para funcionar).

---

## `apps/registry.py` (~275 LOC)

**Propósito**: Registries en memoria — la fuente única de verdad de
qué está cargado en el proceso AHORA MISMO.

### `RegisteredModule`

```python
@dataclass(slots=True)
class RegisteredModule:
    module_id: str
    manifest: ModuleManifest
    router: APIRouter | None = None
    api_router: APIRouter | None = None
    middleware: Any | None = None
    path: Path = field(default_factory=Path)
    loaded_at: datetime = field(default_factory=lambda: datetime.now(UTC))
```

Snapshot de un módulo cargado. Lo crea `ModuleLoader.load_module`
como retorno.

### `ModuleRegistry`

```python
class ModuleRegistry:
    def __init__(self) -> None:
        self._modules: dict[str, RegisteredModule] = {}
        self._version: int = 0

    def register(self, module_id, manifest, router, api_router, middleware, path) -> RegisteredModule:
        entry = RegisteredModule(...)
        self._modules[module_id] = entry
        self._version += 1
        return entry

    def unregister(self, module_id: str) -> None:
        if module_id in self._modules:
            del self._modules[module_id]
            self._version += 1
```

**Decisiones**:

1. **Counter `_version`** monotónico. Cada `register`/`unregister` lo
   incrementa. Caches downstream (menú, OpenAPI, template loader)
   pueden comparar contra un `_version` guardado para saber si
   reconstruir.
2. **No persiste**. En el restart, lo reconstruye `ModuleRuntime.boot`
   desde DB.
3. **No thread-safe**. Asume un único event loop asyncio (típico en
   uvicorn). Multi-worker => cada worker su propio registry.

### Métodos derivados

```python
def get_menu_items(self) -> list[dict]:
    items = []
    for entry in self._modules.values():
        menu = entry.manifest.MENU
        if menu is not None:
            items.append({
                "module_id": entry.module_id,
                "label": menu.label,
                "icon": menu.icon,
                "order": menu.order,
            })
    items.sort(key=lambda m: (m["order"], m["label"]))
    return items
```

Reúne items de menú de **todos** los módulos cargados que tengan
`MENU`. Sorting por `order`, luego label. El template del sidebar
itera esta lista.

```python
def get_navigation(self, module_id: str) -> list[dict]:
    entry = self._modules.get(module_id)
    if entry is None:
        return []
    return [{...} for nav in entry.manifest.NAVIGATION]
```

Tabs/pestañas internas de un módulo concreto. Llamado por `@view`
para inyectar `navigation` al contexto.

### `AppRegistry`

```python
class AppRegistry:
    def __init__(self) -> None:
        self._apps: dict[str, AppConfig] = {}
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def register(self, config: AppConfig) -> None:
        async with self._get_lock():
            if config.name in self._apps:
                raise ValueError(f"App {config.name!r} already registered")
            self._apps[config.name] = config

    async def unregister(self, name: str) -> AppConfig | None:
        async with self._get_lock():
            return self._apps.pop(name, None)

    def get(self, name: str) -> AppConfig | None:
        return self._apps.get(name)

    def by_kind(self, *, builtin: bool | None = None) -> list[AppConfig]:
        items = self._apps.values()
        if builtin is None:
            return list(items)
        return [c for c in items if c.is_builtin is builtin]
```

**Diferencias con `ModuleRegistry`**:

- **Guarda `AppConfig` instances** (no manifests + routers).
- **Async-protegido** (`asyncio.Lock` lazy).
- **Filter by `is_builtin`** para distinguir apps core de módulos
  dinámicos.

`AppRegistry` es el "registro nuevo" (Fase 3+). El plan a futuro es
unificarlo con `ModuleRegistry`. En v1.0 coexisten.

### Por qué dos registries

Razón histórica:

- **`ModuleRegistry`** trackea módulos cargados via `ModuleManifest`
  (el flujo legacy con `module.py` plain).
- **`AppRegistry`** trackea instancias de `AppConfig`/`ModuleConfig`
  (el flujo nuevo Django-like).

Ambos coexisten porque el proyecto migra gradualmente. Es la única
parte de hotframe con redundancia consciente.

---

## `apps/service_facade.py` (~381 LOC)

**Propósito**: API plumber para que módulos expongan acciones
invocables (assistant, RPC, debug) sin escribir routes manualmente.

### `ActionMeta` y `@action`

```python
@dataclass(frozen=True, slots=True)
class ActionMeta:
    permission: str
    mutates: bool = False
    description: str = ""

def action(*, permission: str, mutates: bool = False, description: str = "") -> Any:
    def decorator(fn: Any) -> Any:
        fn._action_meta = ActionMeta(
            permission=permission,
            mutates=mutates,
            description=description,
        )
        return fn
    return decorator
```

Decorador que **stampea metadata** en la función sin envolverla.
Igual patrón que `@event` del live runtime: cero overhead, sólo un
attr extra.

### `ModuleService`

```python
class ModuleService:
    module_id: str = ""

    def __init__(self, db: ISession, hub_id: UUID) -> None:
        self.db = db
        self.hub_id = hub_id

    def q(self, model: type) -> IQueryBuilder:
        return HubQuery(model, self.db, self.hub_id)

    def repo(self, model: type, *, search_fields=None, default_order="created_at") -> IRepository:
        return BaseRepository(model, self.db, self.hub_id,
                              search_fields=search_fields, default_order=default_order)
```

Base para servicios. Cada subclass declara `module_id` y métodos
decorados con `@action`. Los helpers `q()` y `repo()` ahorran
boilerplate (no tienes que pasar `self.db, self.hub_id` cada vez).

### Helpers built-in

```python
@staticmethod
def success(**fields) -> dict:
    return {"ok": True, **fields}

@staticmethod
def error(message: str, *, code: str = "", **fields) -> dict:
    body = {"ok": False, "error": message}
    if code:
        body["code"] = code
    body.update(fields)
    return body

@staticmethod
def parse_uuid(value) -> UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, UUID):
        return value
    return UUID(value)

@staticmethod
def parse_date(value, *, fmt="%Y-%m-%d"):
    if not value:
        return None
    return datetime.strptime(value, fmt).date()

@staticmethod
def parse_decimal(value):
    if value is None or value == "":
        return None
    return Decimal(value)

async def get_or_none(self, model, id_value):
    uid = self.parse_uuid(id_value)
    if uid is None:
        return None
    return await self.q(model).get(uid)

async def get_or_error(self, model, id_value, *,
                        not_found_message="Not found", code="not_found"):
    row = await self.get_or_none(model, id_value)
    if row is None:
        return None, self.error(not_found_message, code=code)
    return row, None

def atomic(self):
    from hotframe.orm.transactions import atomic as _atomic
    return _atomic(self.db)
```

API ergonómica para servicios:

- **`success/error`**: respuestas con shape consistente (`{"ok":
  True/False}`).
- **`parse_*`**: coerciones desde strings (assistant manda strings,
  no tipos Python). Devuelven `None` para empty/None.
- **`get_or_error`**: tuple `(row, error_dict)` para early-return:
  ```python
  row, err = await self.get_or_error(Customer, customer_id)
  if err:
      return err
  # ...
  ```
- **`atomic`**: shortcut para transactional blocks.

### `register_services(module_id)`

```python
SERVICE_REGISTRY: dict[str, dict[str, ServiceEntry]] = {}

def register_services(module_id: str) -> int:
    fqn = f"{module_id}.services"
    try:
        mod = importlib.import_module(fqn)
    except ModuleNotFoundError:
        return 0

    count = 0
    module_services = {}

    for attr_name in dir(mod):
        attr = getattr(mod, attr_name)
        if (isinstance(attr, type)
            and issubclass(attr, ModuleService)
            and attr is not ModuleService):
            attr.module_id = module_id
            actions = {}
            for method_name in dir(attr):
                method = getattr(attr, method_name, None)
                meta = getattr(method, "_action_meta", None)
                if meta is None:
                    continue
                full_perm = f"{module_id}.{meta.permission}"
                actions[method_name] = ActionEntry(
                    method_name=method_name,
                    permission=full_perm,
                    mutates=meta.mutates,
                    description=meta.description or "...",
                    parameters=_extract_parameters(method),
                )
            if actions:
                module_services[attr_name] = ServiceEntry(...)
                count += 1

    if module_services:
        SERVICE_REGISTRY[module_id] = module_services

    return count
```

Llamado por `ModuleLoader` cuando activa un módulo. Importa
`<module_id>.services`, encuentra todas las subclases de
`ModuleService`, y catálogo todos sus `@action` métodos en
`SERVICE_REGISTRY`.

`_extract_parameters(method)` usa `inspect.signature` + `get_type_hints`
para construir un schema JSON-friendly:

```python
{
    "customer_id": {"type": "string (UUID)", "required": True},
    "include_deleted": {"type": "boolean", "required": False, "default": False},
}
```

Esto luego lo consume el assistant para generar prompts dinámicos.

### `unregister_module_services(module_id)`

```python
def unregister_module_services(module_id: str) -> int:
    entry = SERVICE_REGISTRY.pop(module_id, None)
    if entry:
        return len(entry)
    return 0
```

Llamado por `ModuleLoader.unload_module`. `pop` con default `None`
hace la operación idempotente.

### `generate_module_context(module_id)` y `generate_all_contexts()`

```python
def generate_module_context(module_id: str) -> str:
    services = SERVICE_REGISTRY.get(module_id)
    if not services:
        return ""

    lines = []
    for service_name, entry in services.items():
        lines.append(f"### {service_name}")
        if entry.description:
            lines.append(entry.description)
        for action_name, action_def in entry.actions.items():
            params_parts = []
            for pname, pinfo in action_def.parameters.items():
                ptype = pinfo.get("type", "any")
                if pinfo.get("required"):
                    params_parts.append(f"{pname}: {ptype}")
                else:
                    default = pinfo.get("default", "")
                    if default != "" and default is not None:
                        params_parts.append(f"{pname}?: {ptype} = {default}")
                    else:
                        params_parts.append(f"{pname}?: {ptype}")
            params_str = ", ".join(params_parts)
            mode = "WRITE" if action_def.mutates else "READ"
            desc = action_def.description or action_name
            lines.append(f"- **{action_name}**({params_str}) → {desc} | {mode}")

    return "\n".join(lines)
```

Genera markdown describiendo todas las actions del módulo. Ejemplo:

```markdown
### CustomerService
Operations on customers
- **list_customers**(search?: string, limit?: integer = 50) → List customers | READ
- **create_customer**(name: string, email: string) → Create new customer | WRITE
```

Esto lo lee el assistant como contexto dinámico — sabe qué actions
puede invocar sin que el dev se lo escriba a mano.

### Por qué este subsistema

`ModuleService` + `@action` permite que un módulo exponga sus
operaciones como **API tipada** sin escribir routes manualmente. El
assistant (o un RPC framework) introspecciona `SERVICE_REGISTRY` y
sabe:

- Qué métodos existen.
- Qué permisos requieren.
- Qué params toman (con tipos).
- Si mutan o sólo leen.

El módulo escribe Python plano, hotframe genera el contrato.

---

## Cómo se conecta con el resto del framework

```
ModuleLoader.load_module(...)
    ├── load_manifest(path)           ← crea ModuleManifest
    ├── ModuleRegistry.register(...)  ← guarda RegisteredModule
    ├── register_services(id)         ← popula SERVICE_REGISTRY
    └── ...

ModuleLoader.unload_module(...)
    ├── ModuleRegistry.unregister(id)
    ├── unregister_module_services(id)
    └── ...

@view(module_id="customers", view_id="list")
    └── ModuleRegistry.get_navigation("customers")  ← inyecta al contexto

get_global_context(request)
    └── ModuleRegistry.get_menu_items()             ← inyecta al sidebar

assistant or RPC
    └── generate_module_context("customers")       ← describe actions
```

**Convenciones que verás en código de módulos**:

```python
# modules/customers/module.py
MODULE_ID = "customers"
MODULE_NAME = "Customers"
MODULE_VERSION = "1.0.0"
MENU = MenuConfig(label="Customers", icon="users", order=10)
NAVIGATION = [
    NavigationItem(label="List", icon="list", id="list", view="list"),
    NavigationItem(label="Groups", icon="folder", id="groups", view="groups"),
]
PERMISSIONS = [
    ("view", "View customers"),
    ("edit", "Edit customers"),
]
DEPENDENCIES = ["users>=1.0.0"]


# modules/customers/services.py
from hotframe import ModuleService, action

class CustomerService(ModuleService):
    @action(permission="view")
    async def list_customers(self, search: str = "") -> dict:
        result = await self.repo(Customer, search_fields=["name", "email"]).list(search=search)
        return self.success(items=[self.serialize(c) for c in result["items"]])
```

Esto es todo lo que un dev escribe — el resto lo arma hotframe.
