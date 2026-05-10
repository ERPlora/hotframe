# db.md — Persistence protocols, encrypted types, singleton mixin

> **Carpeta cubierta:** `src/hotframe/db/`. Cuatro archivos:
> `__init__.py`, `protocols.py`, `types.py`, `singletons.py`.
> Es la capa **más baja** del subsistema de persistencia: protocolos
> abstractos para que el resto del framework no dependa directamente
> de SQLAlchemy, tipos de columna que cifran al vuelo, y un mixin
> para modelos "configuración" (one row per tenant).

---

## 1. `__init__.py` — qué reexporta

Solo los protocolos. Los tipos cifrados y el mixin se importan por
ruta explícita.

```python
from hotframe.db.protocols import (
    IExecuteResult, IQueryBuilder, IRepository, IScalarResult, ISession,
)

__all__ = [
    "IExecuteResult", "IQueryBuilder", "IRepository",
    "IScalarResult", "ISession",
]
```

Decisión: los protocolos son la **única API estable** de este paquete.
`EncryptedString`/`EncryptedText` son helpers para schemas concretos y
no se reexportan de este nivel — los importas con
`from hotframe.db.types import EncryptedString` para que la dependencia
sea explícita.

`SingletonMixin` igual: `from hotframe.db.singletons import SingletonMixin`.

---

## 2. `protocols.py` — interfaces estructurales

Cinco `Protocol` (PEP 544 — duck-typing con verificación estática) que
definen lo que el resto del framework consume cuando habla con la BD.

### 2.1 `IScalarResult[T_co]`

```python
class IScalarResult[T_co](Protocol):
    def all(self) -> list[T_co]: ...
    def first(self) -> T_co | None: ...
```

Lo que devuelve `result.scalars()`. Itera sobre la primera columna del
result set (típicamente, los objetos ORM).

### 2.2 `IExecuteResult`

```python
class IExecuteResult(Protocol):
    def scalars(self) -> IScalarResult[Any]: ...
    def scalar_one(self) -> Any: ...
    def scalar_one_or_none(self) -> Any | None: ...
    def first(self) -> Any | None: ...
    def all(self) -> list[Any]: ...
```

Lo que devuelve `session.execute(stmt)`. SQLAlchemy implementa
`scalar_one` (lanza si 0 o >1) y `scalar_one_or_none` (devuelve None
si 0).

### 2.3 `ISession` — el corazón del protocolo

```python
class ISession(Protocol):
    async def execute(self, statement, parameters=None) -> IExecuteResult: ...
    def add(self, instance) -> None: ...
    async def flush(self, objects=None) -> None: ...
    async def rollback(self) -> None: ...
    async def commit(self) -> None: ...
    async def delete(self, instance) -> None: ...
    def in_transaction(self) -> bool: ...
    def begin(self) -> Any: ...
    def begin_nested(self) -> Any: ...
```

Una `AsyncSession` de SQLAlchemy cumple este protocolo
**estructuralmente** — sin que el código de hotframe declare
`AsyncSession: ISession`. Esto significa:

1. **Tu código de aplicación** declara `db: ISession`. Mypy verifica
   que solo uses los métodos del protocolo.
2. **Tests** pueden inyectar un mock que implemente solo lo que
   necesite (no `class FakeSession(AsyncSession)` con tons of
   abstract methods).
3. **En el futuro**, otra implementación (raw asyncpg, motor de
   queries propio, prisma-py, etc.) puede satisfacer el protocolo y
   funcionar sin cambiar consumidores.

Métodos diseñados para cubrir el 95% de uso real: ejecutar SELECT,
insertar/borrar, transacciones (`begin`, `begin_nested` para
savepoints), y commit/rollback.

### 2.4 `IQueryBuilder[T]`

```python
class IQueryBuilder[T](Protocol):
    def filter(self, *conditions) -> Self: ...
    def order_by(self, *columns) -> Self: ...
    def options(self, *opts) -> Self: ...
    def limit(self, n: int) -> Self: ...
    def offset(self, n: int) -> Self: ...
    def with_deleted(self) -> Self: ...
    async def all(self) -> list[T]: ...
    async def first(self) -> T | None: ...
    async def get(self, id: UUID) -> T | None: ...
    async def count(self) -> int: ...
    async def sum(self, column) -> Decimal: ...
    async def exists(self) -> bool: ...
    async def get_or_create(self, **defaults) -> tuple[T, bool]: ...
    async def delete(self, id: UUID) -> bool: ...
    async def hard_delete(self, id: UUID) -> bool: ...
```

Patrón builder con encadenamiento (`Self` como retorno). La
implementación canónica es `HubQuery` (en `models/queryset.py`), que
añade el filtro automático por `hub_id` para multi-tenancy.

`with_deleted()` es escape hatch para incluir filas soft-deleted —
por defecto, `HubQuery` excluye `deleted_at IS NOT NULL`.

`get_or_create(**defaults)` retorna `(instance, created: bool)` —
útil para singletons o "asegurar que existe".

`delete()` (soft) vs `hard_delete()` (DELETE real) son dos métodos
distintos: el primero respeta `SoftDeleteMixin`, el segundo borra
físicamente.

### 2.5 `IRepository[T]`

```python
class IRepository[T](Protocol):
    async def list(self, *, search=None, order_by=None, limit=50, offset=0,
                   options=None, **filters) -> dict[str, Any]: ...
    async def get(self, id: UUID, *, options=None) -> T | None: ...
    async def create(self, **kwargs) -> T: ...
    async def update(self, id: UUID, **kwargs) -> T | None: ...
    async def delete(self, id: UUID) -> bool: ...
    async def hard_delete(self, id: UUID) -> bool: ...
    async def count(self, **filters) -> int: ...
    async def exists(self, **filters) -> bool: ...
```

Una capa más arriba que el QueryBuilder: CRUD tipado con paginación.
`list(...)` retorna `dict[str, Any]` con keys estándar
(`{items, total, page, limit, ...}`) — ideal para endpoints de listado.

`BaseRepository` (en `repository/base.py`) implementa este protocolo
sobre `HubQuery`.

### 2.6 ¿Por qué Protocol y no ABC?

- **Cero acoplamiento.** Los consumidores de hotframe no tienen que
  importar `AsyncSession` o el ABC y heredar de él para satisfacer
  el contrato. Si tu mock de tests tiene los métodos correctos,
  funciona.
- **Variance.** `T_co` (covariante) en `IScalarResult` permite que
  `IScalarResult[User]` se use donde se espera `IScalarResult[Any]`.
- **Estructura, no nombre.** Importar protocolos de otra librería
  (e.g. `prisma-py` algún día) sin tener que cambiar la jerarquía.

### 2.7 `# type: ignore` notable en consumers

Cuando un handler hace `db: ISession` y luego pasa a una función
que espera `AsyncSession`, mypy quizá protesta. La solución:

```python
async def my_handler(db: DbSession):
    result = await db.execute(stmt)  # ISession.execute() → IExecuteResult ✓
    rows = result.scalars().all()    # IScalarResult[Any].all() → list[Any] ✓
    # No casts needed.
```

Si necesitas pasar `db` a algo que espera `AsyncSession` literal,
**ese receptor está mal tipado** — debería aceptar `ISession`.

---

## 3. `types.py` — `EncryptedString` y `EncryptedText`

`TypeDecorator` de SQLAlchemy: la columna existe en la BD como
`VARCHAR`/`TEXT` con ciphertext, y al leer/escribir se cifra/descifra
con Fernet.

### 3.1 `EncryptedString`

```python
class EncryptedString(TypeDecorator):
    impl = String
    cache_ok = True

    def __init__(self, length: int = 512, **kwargs):
        super().__init__(length=length, **kwargs)

    def process_bind_param(self, value: str | None, dialect):
        if value is None:
            return None
        return encrypt_secret(value)   # → ciphertext (Fernet token base64)

    def process_result_value(self, value: str | None, dialect):
        if value is None:
            return None
        return decrypt_secret(value)
```

Decisiones:

- **`impl = String`** — backed por `VARCHAR`. Para payloads pequeños
  (~hasta 100 bytes plaintext, dado que ciphertext crece ~4× con
  base64 + IV).
- **`cache_ok = True`** — SQLAlchemy puede cachear queries que usan
  este tipo. Sin él, cada SELECT con un `EncryptedString` se compila
  desde cero. `True` es seguro porque el tipo no depende del valor.
- **`length=512` default** — capacidad del **ciphertext**, no del
  plaintext. Regla aproximada: `length >= 4 * plaintext_max`.
- **`None` passthrough.** Una columna nullable puede ser `NULL` —
  no ciframos None.

`encrypt_secret` y `decrypt_secret` viven en `auth/crypto.py` y usan
la `SECRETS_KEY` (Fernet) de settings. Si la key cambia, los datos
existentes se vuelven ilegibles → catástrofe. Por eso settings exige
`SECRETS_KEY` en producción y valida que sean 32 bytes b64.

### 3.2 `EncryptedText`

Idéntico a `EncryptedString` pero `impl = Text` — sin límite de
tamaño. Para certificados PEM, `.pfx` en base64, blobs JSON, etc.

```python
class EncryptedText(TypeDecorator):
    impl = Text
    cache_ok = True
    # process_bind_param y process_result_value idénticos a EncryptedString
```

### 3.3 Cuándo usarlos

```python
class StripeAccount(Base):
    __tablename__ = "stripe_account"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    api_key: Mapped[str] = mapped_column(EncryptedString(512))      # secret
    cert: Mapped[str] = mapped_column(EncryptedText(), nullable=True)  # large blob
```

El query builder no ve nada raro:

```python
account = await db.scalar(select(StripeAccount).where(StripeAccount.id == x))
account.api_key   # plaintext en Python
```

Pero `WHERE api_key = 'foo'` **no funciona** — el ciphertext en BD
no será `'foo'`. Las columnas cifradas son **leer-y-usar**, no
filtrables. Si necesitas filtrar por un valor, considera un hash
auxiliar (e.g. una columna `api_key_hash` indexada).

### 3.4 Migración cuando `SECRETS_KEY` rota

Caso real: el sysadmin necesita rotar la key. Solución típica:

1. Añadir nueva columna `api_key_v2` con la nueva key activa.
2. Migrar datos: por cada row, descifrar con vieja, cifrar con nueva,
   guardar en v2.
3. Drop de columna vieja.

`auth/crypto.py` no soporta multi-key out-of-the-box; añadir si llega
el momento. Mientras, **no rotes** sin un plan de migración.

---

## 4. `singletons.py` — `SingletonMixin`

Mixin para modelos que deben tener **exactamente una row por tenant**
(o globales: una sola row y ya). El caso típico: configuración de
shop, branding, integraciones, feature flags.

### 4.1 Código

```python
class SingletonMixin:
    @classmethod
    async def get_config(cls, session: ISession, hub_id: UUID) -> Self:
        stmt = select(cls).where(cls.hub_id == hub_id).limit(1)
        result = await session.execute(stmt)
        instance = result.scalars().first()

        if instance is not None:
            return instance

        instance = cls(hub_id=hub_id)
        session.add(instance)
        await session.flush()
        return instance
```

### 4.2 Uso

```python
class ShopConfig(Base, SingletonMixin, HubMixin, TimestampMixin):
    __tablename__ = "shop_config"
    shop_name: Mapped[str] = mapped_column(String(255), default="My Shop")
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    # ... más fields ...

# En un handler:
config = await ShopConfig.get_config(db, hub_id=request.state.hub_id)
config.shop_name = "New Name"
await db.commit()
```

Si `shop_config` no tiene aún ninguna row para este `hub_id`,
`get_config` la crea con defaults y la flushea (sin commit — el
caller decide cuándo commit, evitando dobles). Si ya hay una, la
devuelve.

### 4.3 Por qué SELECT-then-INSERT y no UPSERT

- **Portable.** UPSERT difiere entre PostgreSQL (`INSERT ... ON
  CONFLICT`) y SQLite (`INSERT OR REPLACE`). SELECT-then-INSERT
  funciona igual en cualquier motor.
- **Seguro con unique constraint.** Asume que el modelo declara
  `UniqueConstraint('hub_id')`. Si dos requests concurrentes pasan
  por aquí a la vez:
  - Ambas hacen SELECT y devuelven None.
  - Ambas hacen INSERT — uno gana, el otro recibe IntegrityError.
  - El que pierde puede reintentar (la siguiente request lee la row
    creada por el ganador).

  Para el patrón "config singleton" esto es aceptable; es un caso
  raro y se puede manejar con un retry simple.

### 4.4 Por qué exige `HubMixin`

El mixin asume que `cls.hub_id` existe — es lo que filtra. Si un
modelo lo usa sin `HubMixin`, el `cls.hub_id` no existe y mypy
lanza el `# type: ignore[attr-defined]` que ves en el código.

Si necesitas un singleton global sin tenant (raro), no uses este
mixin: un modelo con un PK fijo (e.g. `id=1`) y un `get_or_create`
manual.

### 4.5 ¿Por qué no uno por sesión?

`get_config` siempre hace SELECT — no cachea. El caller puede cachear
el resultado en `request.state` si necesita evitar repetidas lecturas
en el mismo request. Hotframe no tiene un cache global de "config
por tenant" porque eso es responsabilidad del consumer.

---

## 5. Cómo se relacionan los archivos

```
config.database.get_db()
    │  yields AsyncSession
    ▼
DbSession = Annotated[ISession, Depends(get_db)]
    │  (auth/current_user.py — alias)
    ▼
async def my_handler(db: DbSession):
    # `db` cumple ISession structurally.
    config = await MyConfig.get_config(db, hub_id)   # SingletonMixin
    config.api_key = "xyz"                           # EncryptedString
                                                    # → ciphertext en INSERT
    await db.commit()
```

Y la cadena de protocolos:

```
ISession.execute(stmt) → IExecuteResult
                        │
                        ├─ scalars() → IScalarResult[T]
                        │                ├─ all() → list[T]
                        │                └─ first() → T | None
                        │
                        ├─ scalar_one() → T  (raises if 0 or >1)
                        ├─ scalar_one_or_none() → T | None
                        ├─ first() → Row | None
                        └─ all() → list[Row]
```

`HubQuery` (queryset chainable) y `BaseRepository` (CRUD tipado) se
documentan en sus respectivas md (`models.md`, `repository.md`) — son
las implementaciones canónicas de `IQueryBuilder` e `IRepository`.

---

## 6. Decisiones que conviene recordar

1. **Los protocols son la API pública estable.** Importar
   `AsyncSession` directamente desde tu app es legítimo pero te ata
   a SQLAlchemy.
2. **`EncryptedString` cifra, no firma.** Quien tiene `SECRETS_KEY`
   puede descifrar. Si el atacante consigue la BD **y** la env var,
   no hay defensa.
3. **`SECRETS_KEY` es Fernet (32 bytes b64).** El validator del
   settings rechaza cualquier otra cosa. No la cambies sin un plan.
4. **Columnas cifradas no son filtrables.** `WHERE api_key = '...'`
   no funciona con `EncryptedString`. Usa hash si necesitas search.
5. **`SingletonMixin` exige `hub_id`.** Para singletons sin tenant,
   no uses este mixin.
6. **Concurrencia en `get_config`** — el caller debe asumir que dos
   requests pueden crear la fila a la vez. UniqueConstraint +
   reintento de la 2ª.
7. **`cache_ok = True`** en TypeDecorators — necesario para que
   SQLAlchemy ≥1.4 no compile la query desde cero cada vez. Si lo
   olvidas, ves un warning y degradas perf.

---

## 7. Errores comunes

| Síntoma | Causa | Diagnóstico |
|---|---|---|
| `cryptography.fernet.InvalidToken` al leer | `SECRETS_KEY` cambió o el dato fue insertado con otra key. | Necesitas la key original o re-encriptar el dato. |
| Filtros `WHERE api_key = '...'` no devuelven nada | La columna está cifrada — el ciphertext no coincide. | Quita el filtro y filtra in-memory, o añade un hash auxiliar. |
| `IntegrityError: UNIQUE constraint failed: shop_config.hub_id` | Dos requests llamaron `get_config` simultáneamente y el segundo perdió el INSERT. | Reintenta — la segunda llamada leerá la row del ganador. |
| `attr-defined: cls has no attribute hub_id` (mypy) | Usaste `SingletonMixin` sin `HubMixin`. | Añade `HubMixin` o quita `SingletonMixin`. |
| `argument 'length' is required for VARCHAR on PG` | Olvidaste el `length=` en `EncryptedString` y el dialecto rechaza VARCHAR sin tamaño. | `EncryptedString(512)` o `EncryptedText` si no quieres preocuparte. |
