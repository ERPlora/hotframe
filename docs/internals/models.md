# models.md — Declarative base, mixins, query builder

> **Carpeta cubierta:** `src/hotframe/models/`. Cuatro archivos:
> `__init__.py`, `base.py`, `mixins.py`, `queryset.py`.
> Provee la base SQLAlchemy 2.0 (UUID PKs, timestamps), mixins
> componibles (`HubMixin`, `SoftDeleteMixin`, etc.) y un query
> builder (`HubQuery`) que filtra por hub y excluye soft-deleted
> automáticamente.

---

## 1. `__init__.py`

Solo docstring. Imports explícitos:

```python
from hotframe.models.base import Base, Model, TimeStampedModel, ActiveModel
from hotframe.models.mixins import HubMixin, TimestampMixin, AuditMixin, SoftDeleteMixin
from hotframe.models.queryset import HubQuery
```

Reexportados todos desde `hotframe` raíz.

---

## 2. `base.py` — `Base`, `Model`, etc.

### 2.1 `Base(DeclarativeBase)`

```python
class Base(DeclarativeBase):
    pass
```

Raíz de toda la jerarquía SQLAlchemy 2.0. Todos los modelos del
proyecto deben heredar (directa o indirectamente).

`bootstrap.lifespan` registra los listeners ORM contra `Base.metadata`
para que cualquier subclase emita eventos.

### 2.2 `Model(Base)` — el default

```python
class Model(Base):
    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(tz=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(tz=True), nullable=False,
                                                  server_default=func.now(), onupdate=func.now())
```

`Model` (alias `HubBaseModel` por backward compat) es la base
recomendada para casi todos los modelos:

- **UUID PK** generado en cliente (`default=uuid.uuid4`). Permite
  insertar y conocer el ID antes del flush.
- **`created_at`/`updated_at`** con timezone, `server_default=NOW()`,
  `onupdate=NOW()`. Postgres y SQLite soportados.
- **`__abstract__ = True`** — no crea tabla. Subclases declaran
  `__tablename__` y campos extra.

### 2.3 `TimeStampedModel(Base)` y `ActiveModel(Base)`

Variantes:
- `TimeStampedModel`: idéntico a `Model` pero con nombre distinto
  (semántica histórica).
- `ActiveModel`: añade `is_active: bool = True`. Útil para entidades
  con flag de activación (no confundir con soft-delete).

---

## 3. `mixins.py` — composición fina

Cuando no quieres heredar de `Model` (porque necesitas combinar
varios concerns) o quieres aplicar a un modelo existente:

### 3.1 `HubMixin`

```python
class HubMixin:
    @declared_attr
    def hub_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(Uuid, nullable=False, index=True)
```

Añade `hub_id` indexado. Requerido para multi-tenant — `HubQuery`
lo usa para auto-filtrar.

### 3.2 `TimestampMixin`

`created_at` y `updated_at`. Igual que en `Model` pero como mixin.

### 3.3 `AuditMixin`

```python
class AuditMixin:
    @declared_attr
    def created_by(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(Uuid, nullable=True)
    @declared_attr
    def updated_by(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(Uuid, nullable=True)
```

UUID del user que creó/modificó. **No se popula automáticamente** —
el código que crea el row debe asignar `created_by=current_user.id`.

### 3.4 `SoftDeleteMixin`

```python
class SoftDeleteMixin:
    @declared_attr
    def is_deleted(cls) -> Mapped[bool]:
        return mapped_column(Boolean, default=False, server_default="false", index=True)
    @declared_attr
    def deleted_at(cls) -> Mapped[datetime | None]:
        return mapped_column(DateTime(tz=True), nullable=True)
```

Compatible con `HubQuery.delete(id)` que setea `is_deleted=True` +
`deleted_at=now()` en lugar de `DELETE`.

### 3.5 Composición típica

```python
class Product(Base, HubMixin, TimestampMixin, AuditMixin, SoftDeleteMixin):
    __tablename__ = "products"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
```

Ojo: como mixins SI son `@declared_attr`, **no debes** repetir
columnas. Si ya heredas de `Model` (que ya tiene timestamps), no
añadas `TimestampMixin`.

---

## 4. `queryset.py` — `HubQuery[T]`

Query builder chainable async, scoped a `hub_id`, que cumple
`IQueryBuilder[T]`.

### 4.1 Constructor + state interno

```python
class HubQuery[T]:
    def __init__(self, model, session, hub_id):
        self._model: Any = model       # any porque mypy no ve column descriptors
        self._session = session
        self._hub_id = hub_id
        self._conditions: list = []
        self._order: list = []
        self._load_options: list = []
        self._limit: int | None = None
        self._offset: int | None = None
        self._include_deleted: bool = False
```

### 4.2 `_base_query()` — auto filtros

```python
def _base_query(self) -> Select:
    stmt = select(self._model)
    if hasattr(self._model, "hub_id"):
        stmt = stmt.where(self._model.hub_id == self._hub_id)
    if not self._include_deleted and hasattr(self._model, "is_deleted"):
        stmt = stmt.where(self._model.is_deleted == False)
    for cond in self._conditions:
        stmt = stmt.where(cond)
    for opt in self._load_options:
        stmt = stmt.options(opt)
    if self._order:
        stmt = stmt.order_by(*self._order)
    if self._limit is not None:
        stmt = stmt.limit(self._limit)
    if self._offset is not None:
        stmt = stmt.offset(self._offset)
    return stmt
```

Magia clave:

1. **`hub_id` filter automatic** — si el modelo lo tiene.
2. **`is_deleted=False`** automático — soft-delete by default.
3. **`with_deleted()`** rompe el filtro 2.
4. **Query builder real** — `filter`, `order_by`, `options`, `limit`,
   `offset` se acumulan y se materializan en `_base_query`.

### 4.3 Métodos terminales

```python
async def all() -> list[T]:
    result = await self._session.execute(self._base_query())
    return list(result.scalars().all())

async def first() -> T | None:
    result = await self._session.execute(self._base_query().limit(1))
    return result.scalars().first()

async def get(id) -> T | None:
    stmt = self._base_query().where(self._model.id == id)
    result = await self._session.execute(stmt)
    return result.scalars().first()
```

Y los aggregates:

```python
async def count() -> int:
    stmt = self._filtered_select(func.count(self._model.id))
    result = await self._session.execute(stmt)
    return result.scalar_one()

async def sum(column) -> Decimal:
    col = getattr(self._model, column) if isinstance(column, str) else column
    stmt = self._filtered_select(func.coalesce(func.sum(col), 0))
    result = await self._session.execute(stmt)
    return Decimal(str(result.scalar_one()))

async def exists() -> bool:
    stmt = self._filtered_select(self._model.id).limit(1)
    result = await self._session.execute(stmt)
    return result.first() is not None
```

`_filtered_select(...columnas)` reutiliza el filtro hub_id +
soft-delete pero proyectando las columnas dadas (no `SELECT *`).

### 4.4 `get_or_create(**defaults)`

```python
async def get_or_create(self, **defaults) -> tuple[T, bool]:
    instance = await self.first()
    if instance is not None:
        return instance, False
    create_kwargs = {"hub_id": self._hub_id, **defaults}
    instance = self._model(**create_kwargs)
    self._session.add(instance)
    try:
        await self._session.flush()
    except IntegrityError:
        await self._session.rollback()
        instance = await self.first()
        if instance is not None:
            return instance, False
        raise
    return instance, True
```

Doble protección race condition: si dos requests ven `first()=None`
y uno hace flush primero, el segundo cae en `IntegrityError` →
rollback → re-query (encuentra el row del primer request) → devuelve
`(instance, False)`.

### 4.5 `delete(id)` — soft delete

```python
async def delete(self, id) -> bool:
    instance = await self.get(id)
    if instance is None:
        return False
    if hasattr(instance, "is_deleted"):
        instance.is_deleted = True
        instance.deleted_at = datetime.now(UTC)
        await self._session.flush()
        return True
    # Sin SoftDeleteMixin → hard delete + warning
    await self._session.delete(instance)
    await self._session.flush()
    return True
```

`hard_delete(id)` siempre borra físicamente, incluso si el modelo
soporta soft-delete. Útil para GDPR right-to-be-forgotten.

### 4.6 Uso típico

```python
q = HubQuery(Product, db, hub_id)
items = await q.filter(Product.is_active == True) \
               .order_by(Product.name) \
               .limit(20) \
               .all()
total = await q.filter(Product.is_active == True).count()
exists = await q.filter(Product.sku == "ABC").exists()
sum_price = await q.filter(Product.is_active == True).sum(Product.price)
```

---

## 5. Decisiones que conviene recordar

1. **UUIDv4 como PK.** Genera client-side, evita round-trip al
   `flush()` para conocer el ID.
2. **`Model` es la base recomendada.** Solo usa mixins si necesitas
   componer fino.
3. **`HubQuery` autofitra** `hub_id` y `is_deleted`. Si necesitas
   bypass: `with_deleted()` o usa `select()` directo.
4. **`get_or_create` maneja race.** No reimplementes UPSERT manual.
5. **Soft-delete by default.** Modelos sin `SoftDeleteMixin` caen a
   hard-delete con warning — añade el mixin si quieres preservar.
6. **`HubQuery` no commitea.** Solo `flush`. El caller (handler con
   `DbSession`) hace commit al final.
7. **Mixins usan `@declared_attr`.** Evita el patrón `column = Column(...)`
   que rompe en herencia múltiple.

---

## 6. Errores comunes

| Síntoma | Causa | Solución |
|---|---|---|
| Query devuelve [] aunque hay datos | `hub_id` no coincide o `is_deleted=True`. | Imprime `q._base_query()` y verifica. |
| `Multiple inheritance: column "id" already mapped` | Heredas `Model` y mixin con `id`. | Quita uno; los mixins puros (sin id) no chocan. |
| `IntegrityError unique constraint` en `get_or_create` | El defaults conflicta con un row existente. | El método ya re-queriea — si lanza, son datos genuinamente conflictivos. |
| `count()` lento | Filtros con joins implícitos. | Mejor escribe el query manual con `select(func.count())`. |
| Soft-deleted records aparecen | Olvidaste `SoftDeleteMixin` y haces `is_deleted=True` manual. | Añade el mixin para que `_base_query` filtre auto. |
| `hub_id` is None error | Olvidaste `hub_id` en `create()`. | `BaseRepository.create` lo añade automáticamente; si construyes a mano, no olvides. |
