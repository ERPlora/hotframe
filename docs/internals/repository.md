# repository.md — Typed CRUD repository on top of `HubQuery`

> **Carpeta cubierta:** `src/hotframe/repository/`. Un archivo:
> `base.py` (con `__init__.py` solo reexportando).
> `BaseRepository` es la implementación de `IRepository[T]`:
> CRUD tipado con paginación, búsqueda full-text, filtros por
> field, soft-delete via `HubQuery`.

---

## 1. ¿Qué resuelve?

Un repositorio elimina el boilerplate típico de los handlers:

```python
# Sin BaseRepository
async def list_products(db, hub_id, search):
    stmt = select(Product).where(Product.hub_id == hub_id, Product.is_deleted == False)
    if search:
        stmt = stmt.where(or_(Product.name.ilike(f"%{search}%"),
                              Product.sku.ilike(f"%{search}%")))
    items = (await db.execute(stmt.limit(50))).scalars().all()
    total = (await db.execute(select(func.count(Product.id)).where(...))).scalar_one()
    return {"items": items, "total": total}

# Con BaseRepository
async def list_products(db, hub_id, search):
    repo = BaseRepository(Product, db, hub_id, search_fields=["name", "sku"])
    return await repo.list(search=search, limit=50)
```

---

## 2. La clase `BaseRepository[T]`

```python
class BaseRepository[T]:
    def __init__(self, model, db, hub_id, *,
                 search_fields=None, default_order="created_at"):
        self.model = model
        self.db = db
        self.hub_id = hub_id
        self.search_fields = search_fields or []
        self.default_order = default_order

    def q(self) -> HubQuery[T]:
        return HubQuery(self.model, self.db, self.hub_id)
```

`q()` siempre devuelve una `HubQuery` fresca — los métodos del
repository la construyen y materializan en cada llamada (no estado
mutable compartido).

### 2.1 `list(...)`

```python
async def list(self, *, search=None, order_by=None, limit=50, offset=0,
               options=None, **filters):
    query = self.q()

    if search and self.search_fields:
        conditions = [getattr(self.model, f).ilike(f"%{search}%")
                      for f in self.search_fields if hasattr(self.model, f)]
        if conditions:
            query = query.filter(or_(*conditions))

    for field, value in filters.items():
        if hasattr(self.model, field) and value is not None:
            query = query.filter(getattr(self.model, field) == value)

    if options:
        query = query.options(*options)

    total = await query.count()

    order = order_by or self.default_order
    if isinstance(order, str):
        col = getattr(self.model, order, None)
        if col is not None:
            query = query.order_by(col)
    else:
        query = query.order_by(order)

    items = await query.offset(offset).limit(limit).all()
    return {"items": items, "total": total}
```

Devuelve `{"items": [...], "total": N}`. Decisiones:

1. **`search` aplica `ILIKE` con %s** sobre cada `search_field`
   declarado al constructor.
2. **`**filters` aplica equality** sobre cada field que exista en
   el modelo. `is_active=True`, `category_id=UUID(...)`, etc.
3. **`options=[...]`** se pasa a `query.options(...)` —
   típicamente `selectinload(Product.category)` para eager loading.
4. **`order_by` puede ser string o expresión.** String → `getattr` +
   default direction. Expresión → directly applied.
5. **Total y items en queries separadas.** `count()` ejecuta
   `SELECT COUNT(*)` con los mismos filtros pero sin limit/offset.
6. **Retorno como dict, no dataclass.** Compatible con JSON
   directamente; no hay coupling con un schema concreto.

### 2.2 `get(id, *, options=None)`

```python
async def get(self, id, *, options=None) -> T | None:
    query = self.q()
    if options:
        query = query.options(*options)
    return await query.get(id)
```

Devuelve la instancia o `None`. Aplica filtros automáticos
(`hub_id` + `is_deleted`).

### 2.3 `create(**kwargs)`

```python
async def create(self, **kwargs) -> T:
    instance = self.model(hub_id=self.hub_id, **kwargs)
    self.db.add(instance)
    await self.db.flush()
    return instance
```

`hub_id` se inyecta automáticamente. Después del `flush`, `instance.id`
está poblado (UUIDv4 client-side).

### 2.4 `update(id, **kwargs)`

```python
async def update(self, id, **kwargs) -> T | None:
    instance = await self.get(id)
    if instance is None:
        return None
    for key, value in kwargs.items():
        if hasattr(instance, key):
            setattr(instance, key, value)
    await self.db.flush()
    return instance
```

`hasattr` filter — evita asignar atributos desconocidos. Si el
caller pasa un kwarg que no existe en el modelo, se ignora
silenciosamente. (Considéralo "permissive update".)

### 2.5 `delete(id)` y `hard_delete(id)`

```python
async def delete(self, id) -> bool:
    return await self.q().delete(id)
async def hard_delete(self, id) -> bool:
    return await self.q().hard_delete(id)
```

Wrappers — `HubQuery` hace el trabajo. `delete` es soft si el modelo
tiene `SoftDeleteMixin`, fallback a hard si no.

### 2.6 `count(**filters)` y `exists(**filters)`

```python
async def count(self, **filters) -> int:
    query = self.q()
    for field, value in filters.items():
        if hasattr(self.model, field) and value is not None:
            query = query.filter(getattr(self.model, field) == value)
    return await query.count()

async def exists(self, **filters) -> bool:
    # Igual con .exists()
```

Convenientes para checks rápidos sin cargar el row.

---

## 3. `serialize(obj, *, fields=None, exclude=None)`

Función helper para convertir ORM → dict JSON-friendly:

```python
def serialize(obj, *, fields=None, exclude=None):
    exclude = exclude or set()
    if fields is None:
        if hasattr(obj, "__table__"):
            fields = [c.key for c in obj.__table__.columns if c.key not in exclude]
        else:
            return {}

    result = {}
    for attr in fields:
        if attr in exclude:
            continue
        val = getattr(obj, attr, None)
        if isinstance(val, (uuid.UUID, Decimal)):
            val = str(val)
        elif isinstance(val, (datetime, date)):
            val = val.isoformat()
        result[attr] = val
    return result

def serialize_list(items, *, fields=None, exclude=None):
    return [serialize(i, fields=fields, exclude=exclude) for i in items]
```

Conversiones automáticas:
- `UUID` → `str`
- `Decimal` → `str` (precisión preservada — JSON nativo perdería)
- `datetime`/`date` → `isoformat`

Si `fields=None`, lista todas las columnas del `__table__`. Para
incluir relaciones, especifícalas explícitamente:

```python
serialize(product, fields=["id", "name", "price", "category_name"])
# y previo: product.category_name = product.category.name
```

---

## 4. Patrón típico — handler con repository

```python
from hotframe import DbSession, view
from hotframe.repository.base import BaseRepository

@router.get("/m/inventory/products")
@view(module_id="inventory", view_id="list", permissions="inventory.view")
async def list_products(request, db: DbSession,
                       search: str = "", limit: int = 50, offset: int = 0,
                       category_id: UUID | None = None):
    hub_id = request.state.hub_id
    repo = BaseRepository(Product, db, hub_id,
                          search_fields=["name", "sku", "barcode"])
    result = await repo.list(
        search=search, limit=limit, offset=offset,
        category_id=category_id, is_active=True,
        options=[selectinload(Product.category)],
    )
    return {"products": result["items"], "total": result["total"]}
```

---

## 5. Subclasing — repositorios específicos

```python
from hotframe.repository.base import BaseRepository
from sqlalchemy.orm import selectinload

class ProductRepository(BaseRepository[Product]):
    def __init__(self, db, hub_id):
        super().__init__(Product, db, hub_id,
                         search_fields=["name", "sku", "barcode"],
                         default_order="-created_at")

    async def list_low_stock(self, threshold=10):
        return await self.q().filter(Product.stock < threshold).all()

    async def by_category(self, category_id, *, limit=50):
        return await self.list(category_id=category_id, limit=limit,
                               options=[selectinload(Product.category)])
```

Heredar permite añadir métodos custom sin perder los CRUD básicos.

---

## 6. Decisiones de diseño que conviene recordar

1. **Repository es opcional.** Si tu query es trivial, usa `HubQuery`
   o `select()` directo. El repo es para CRUD repetitivo.
2. **`list()` devuelve dict** con `items` + `total` para listados
   paginados. Compatible con JSON. Evita un dataclass por modelo.
3. **`update()` es permissive** — kwargs desconocidos se ignoran.
   Si quieres strict, valida con un Pydantic schema antes.
4. **`search_fields` aplica `ILIKE`** con wildcards. Para full-text
   real (PostgreSQL `tsvector`), heredar y override.
5. **`options=[]` para eager loading.** Por defecto las relaciones
   son lazy — pasa `selectinload(Model.relation)` cuando lo necesites.
6. **`serialize()` es JSON-friendly por design.** UUID → str,
   Decimal → str, datetime → isoformat.
7. **El repo NO commitea.** Solo `flush()`. El handler con
   `DbSession` hace commit al final del request (o `atomic()` lo
   hace).

---

## 7. Errores comunes

| Síntoma | Causa | Solución |
|---|---|---|
| `list(category="X")` no filtra | `category` no existe como column. | Verifica el atributo del modelo, o usa `query.filter` directamente. |
| Total > items en `list()` | Usaste `limit` pero `total` es global. | Es esperado — `total` es el conteo total sin paginación. |
| `update()` ignora un kwarg | `hasattr(model, kwarg) == False`. | Verifica el spelling o el atributo del modelo. |
| `delete()` devuelve `True` pero el row sigue | El modelo no tiene `SoftDeleteMixin`, default es hard delete con warning. | Mira el log o añade el mixin. |
| `serialize()` falta una columna | `__table__.columns` no la incluye (e.g. es una relación). | Pasa `fields=[...]` explícitamente. |
| N+1 queries con relations | Sin eager loading. | `options=[selectinload(Model.relation)]` en `list()` o `get()`. |
