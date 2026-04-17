# Plan: `runtime/` como librería open source (estado final)

## Contexto

Evaluación estratégica: cuando `hub-next/runtime/` esté terminado según
ARCHITECTURE.md (estado final, no el actual), ¿tiene sentido publicarlo como
librería open source al estilo Django/FastAPI?

**Qué asumimos del estado final** (según ARCHITECTURE.md):
- `runtime/` es genérico e inmutable, no contiene lógica de negocio ni migraciones.
- **Todo se parametriza vía `settings.py` (Pydantic BaseSettings)**. Cero hardcodes.
- Cero imports de `apps/`, `modules/`, `kernel_modules/` desde dentro de `runtime/`.
- API pública cerrada en `runtime/__init__.py` (AppConfig, ModuleConfig, path,
  include, View, Model, receiver, etc.).
- CLI con `startproject`, `startapp`, `startmodule`, `runserver`, `migrate`,
  `makemigrations` — equivalente funcional a `django-admin` y `manage.py`.
- Contratos públicos congelados (feature freeze), `import-linter` enforza capas.

**Qué vive fuera del runtime y es privado de ERPlora:**
- `apps/` (modelos de negocio: HubConfig, User, HubModule, compliance, catálogo…).
- `modules/` (los 96 módulos: fiscal_es, verifactu, invoice, POS, sales, payroll…).
- `kernel_modules/assistant/` (el GPT proxy + agentic tools).
- Cloud (SaaS, billing, marketplace, integraciones Stripe/VeriFactu).
- Infraestructura AWS productiva (cuentas, buckets, endpoints, JWT secrets).
- Branding, datos de clientes, demos comerciales.

La pregunta real: **publicar el runtime final (un framework modular
Django-like + hot-mount de plugins) ¿expone algo que comprometa el negocio?**

---

## Resumen ejecutivo

**Sí, publicar es una buena decisión estratégica.** Cuando `runtime/` esté
acabado según ARCHITECTURE.md, es infraestructura genérica: no contiene ni
una línea de lógica ERP. El producto de ERPlora son los **96 módulos + Cloud
SaaS + integraciones fiscales + catálogo sectorial + marketplace + hardware
bridge**, no el motor que los carga.

Un competidor que cogiese el runtime necesitaría replicar todo ese ecosistema
para competir — el runtime es quizá el 5-10% del esfuerzo total del producto.
A cambio, publicarlo da:

- **Adopción técnica** — desarrolladores aprenden el stack construyendo cosas
  triviales, y cuando necesitan un ERP ya saben cómo funciona ERPlora por dentro.
- **Contribuciones externas** — bugs, mejoras de performance, soporte a nuevas
  versiones de FastAPI/SQLAlchemy gratis.
- **Pipeline de módulos comunitarios** — el marketplace puede absorber módulos
  de terceros; ERPlora monetiza vía hosting + módulos premium propietarios.
- **Credibilidad técnica / reclutamiento** — tener un framework OSS conocido
  atrae perfil técnico top.
- **Documentación forzosa** — publicar obliga a tener docs públicas, que también
  sirven a quien trabaje en ERPlora.

**Decisiones tomadas** (16 abril 2026):
- Licencia: **Apache 2.0** — permisiva, cláusula de patentes, máxima adopción.
- Branding: **`hotframe`** (nombre final — hot-mount + framework).
  Razones:
  - Semántico — hot(mount) + frame(work): describe exactamente qué es.
  - Pronunciable en inglés y español.
  - Import limpio: `from hotframe import AppConfig, ModuleConfig, path, ...`.
  - CLI corto intuitivo: `hf` (sin -hotframe) — como `django-admin` → `django`.
  - No colisiona con marcas conocidas.

  Antes de crear el repo público: verificar dominios (`hotframe.dev`,
  `.io`, `.org`), handle de GitHub org (`hotframe` o `@hotframe`), y
  búsqueda básica de marca (Google + TMview EU + TESS USPTO).
- **Capa HTMX tipo Turbo/Livewire incluida** (ver sección "Capa HTMX" abajo).

---

## Filosofía: HTMX al nivel de Rails Turbo y Laravel Livewire

Python no tiene hoy un equivalente server-driven a lo que Rails tiene con **Turbo** y Laravel con **Livewire**. FastAPI + Jinja2 pelados obligan a cada proyecto a reinventar decoradores, respuestas HTMX tipadas, sistema de frames, broadcasting por WebSocket, etc. `hotframe` cierra ese hueco como característica first-class.

### Qué da Rails con Turbo (y cómo lo replica `hotframe`)

| Rails Turbo | Equivalente `hotframe` |
|---|---|
| `turbo_frame_tag "sidebar"` | `{% frame "sidebar" %}...{% endframe %}` |
| `turbo_stream.append "todos", partial: "todo"` | `TurboStream.append(target="#todos", template="todo.html")` |
| `turbo_stream.replace`, `prepend`, `remove`, `morph` | Acciones idénticas en `TurboStream` |
| Turbo Streams over WebSocket (broadcasting) | `bus.publish("topic", payload)` + `SSEResponse(topic=...)` / `WebSocketFrame` |
| Turbo Drive (navegación sin full reload) | Delegado a HTMX `hx-boost` (middleware lo detecta y renderiza el partial correcto) |
| `respond_to :turbo_stream` en controller | Decorador `@htmx_view` detecta cabeceras HX-* y devuelve layout/partial automáticamente |
| Morphing (actualización diff-based del DOM) | HTMX morphing extension + `TurboStream.morph(...)` |

### Qué da Laravel con Livewire (y cómo lo replica `hotframe`)

| Laravel Livewire | Equivalente `hotframe` |
|---|---|
| Componentes server-side con ciclo de vida | Vista basada en clase (`View`, `ListView`, `DetailView`) + `@htmx_view` |
| Validación inline sin full reload | `ModelForm` HTMX-aware: errores como partials reemplazan solo el campo |
| Binding reactivo (`wire:model`) | HTMX + Alpine.js: `hx-trigger="input changed delay:300ms"` + `x-model` |
| Acciones del usuario como métodos del componente | Rutas HTMX puras (`@htmx_view` por acción), sin stateful components en el servidor |
| Broadcasting con Laravel Echo | `AsyncEventBus.publish(topic, payload)` + SSE/WS |
| Lazy loading de componentes | `hx-trigger="revealed"` + partial views |
| Hot-reload de componentes en dev | Watcher de `hotframe.dev` recarga templates + módulos sin reiniciar |

### Decisión de diseño: stateless, no stateful

A diferencia de Livewire, `hotframe` **no mantiene estado de componente en el servidor** (no hay "hidden input" con el estado serializado ni reconciliation). Cada acción HTMX es un request independiente que renderiza HTML. Motivos:

1. **Escalabilidad horizontal trivial** — sin session afinity, sin estado que replicar entre workers.
2. **Compatibilidad con el hot-mount dinámico** — si un módulo se recarga, no hay componentes "huérfanos" con estado serializado de la versión anterior.
3. **Menor superficie de API** — no hay protocolo propietario entre cliente y servidor; todo es HTML + cabeceras HTMX estándar.
4. **Mejor DX con el stack ya elegido** — HTMX + Alpine ya resuelven el 95% de los casos que Livewire resuelve con componentes stateful, sin el coste cognitivo de un nuevo concepto.

El estado del cliente vive en Alpine (`x-data`, `x-model`) y el del servidor en la base de datos. Cada request HTMX reconcilia los dos vía HTML. Es lo que Rails llama **"HTML over the wire"** llevado a Python con disciplina.

### Posicionamiento de mercado

| Framework | Lenguaje | Server-driven UI | Hot-mount módulos | Licencia |
|---|---|---|---|---|
| Rails + Turbo + Hotwire | Ruby | Sí | No | MIT |
| Laravel + Livewire | PHP | Sí (stateful) | No | MIT |
| Phoenix LiveView | Elixir | Sí (WebSocket) | Hot code reload (BEAM) | Apache 2.0 |
| Django + django-htmx | Python | Parcial (solo middleware) | No | BSD / MIT |
| FastAPI pelado | Python | No (DIY) | No | MIT |
| **`hotframe`** | **Python** | **Sí (Turbo-style)** | **Sí** | **Apache 2.0** |

`hotframe` es el primero en Python en combinar **server-driven UI estilo Turbo + hot-mount dinámico de módulos** en una sola librería coherente. Ese es el pitch técnico: traer a Python la productividad de Rails/Laravel en el frontend, con la potencia del hot-reload dinámico que ni Rails ni Laravel tienen.

---

## Qué expone la librería (y por qué no es peligroso)

### 1. Motor de módulos dinámicos (`engine/`)
HotMountPipeline, ImportManager, GracefulRestartCoordinator, MigrationRunner.

- **Valor técnico**: hot-reload de plugins Python sin reiniciar el proceso —
  poco común, técnicamente interesante.
- **¿Peligro competitivo?** Bajo. Resolver correctamente weakrefs, zombies,
  metaclass conflicts, y rollback LIFO es trabajo de ingeniería que un
  competidor tendría que hacer igual, pero sin la lógica de negocio encima
  (que es donde está el valor del producto ERP). Publicarlo crea estándar;
  si somos los primeros, somos la referencia.

### 1b. Capa HTMX tipo Turbo/Livewire (`views/` + `templating/` + `routing/`)

Extensión sobre FastAPI + Jinja2 que da la ergonomía server-driven que Rails
tiene con Turbo y Laravel con Livewire. HTMX y Alpine.js ya son el front-end
estándar de ERPlora — la capa los hace first-class en el runtime.

**Componentes (diseño objetivo):**

1. **Decoradores** — `@htmx_view` / `@page_view` / `@partial_view` que:
   - Detectan cabeceras `HX-Request`, `HX-Boosted`, `HX-Target`, `HX-Trigger`.
   - Renderizan layout completo si es navegación directa, partial si es HTMX.
   - Manejan 4xx/5xx con HTML parcial para el inline error pattern.
2. **Respuestas tipadas** en `runtime/views/responses.py`:
   - `HTMXResponse(template, ctx, headers={"HX-Trigger": ...})`.
   - `TurboStream(action="append"|"prepend"|"replace"|"remove"|"morph", target=..., template=...)`
     — múltiples fragmentos en una sola respuesta, con IDs de destino.
   - `SSEResponse` — stream server-sent events, integrado con AsyncEventBus.
   - `WebSocketFrame` — broadcast por topic sobre WS.
   - `OOBSwap(target="#notifications", template=...)` — out-of-band swaps
     de alto nivel.
3. **Helpers de Jinja** en `runtime/templating/extensions.py`:
   - `{% frame "sidebar" %}...{% endframe %}` — define frames nombrados
     (Turbo-style) que HTMX puede target.
   - `{{ hx_get(url, target=..., swap=..., trigger=...) }}` — genera atributos
     `hx-*` con validación.
   - `{{ hx_indicator("#spinner") }}`, `{{ hx_confirm("¿Seguro?") }}`.
   - `{% slot "navbar" %}` ya existe (SlotRegistry) — se integra con frames.
4. **Middleware** — pobla `request.state.htmx` con estructura tipada:
   ```python
   request.state.htmx.is_request: bool
   request.state.htmx.target: str | None
   request.state.htmx.trigger: str | None
   request.state.htmx.boosted: bool
   ```
5. **Broadcasting por topic** — puente AsyncEventBus ↔ SSE/WS:
   - `bus.publish("chat:room:42", payload)` emite a todos los clientes
     suscritos al topic vía SSE o WS. Equivalente funcional a Turbo Streams
     over WebSocket.
6. **Alpine.js integración** — extensions de Jinja que serializan estado
   Pydantic a `x-data` con escape seguro y Trusted Types.
7. **Forms HTMX-aware** — `runtime/forms/rendering.py` renderiza ModelForm
   con atributos `hx-*` por defecto y manejo de validación inline (errores
   inyectados como partials sin full reload).

**Valor**: un dev Rails o Laravel viene, ve la sintaxis, y es productivo en
horas. Diferenciador claro vs FastAPI pelado (que requiere que cada proyecto
reinvente esta capa).

**Riesgo de mantenimiento**: superficie de API adicional que hay que estabilizar
antes del feature freeze. Mitigación: todo contrato de esta capa dentro de
`runtime/__init__.py` y cubierto por deprecation de 2 versiones. Tests ≥90%
específicos. Doc y ejemplos "desde Turbo/Livewire a hotframe" para onboarding.

**Scope explícitamente excluido** (para no convertirse en framework frontend):
- Componentes JS reactivos (eso es Alpine.js, lo dejamos que lo haga él).
- Sistema de routing cliente-side (HTMX ya lo hace bien con `hx-push-url`).
- State management cliente (Alpine `x-data` + server source of truth).

### 2. Framework Django-like (el resto de subpaquetes)
`apps/`, `routing/`, `views/`, `models/`, `orm/`, `repository/`, `signals/`,
`middleware/`, `templating/`, `auth/`, `forms/`, `management/`, `discovery/`,
`migrations/`, `testing/`, `dev/`, `utils/`, `db/`.

- **Valor**: azúcar ergonómico sobre FastAPI + SQLAlchemy + Jinja2 + Alembic
  con convenciones Django. Facilita que devs que vienen de Django adopten
  FastAPI sin reaprender.
- **¿Peligro competitivo?** Nulo. Todos estos patrones ya existen en Django,
  FastAPI, Rails, Laravel, Flask-AppBuilder. No hay IP que proteger aquí.

### 3. CLI y scaffolders
`startproject`, `startapp`, `startmodule` + comandos de gestión.

- **Valor**: experiencia de onboarding tipo `django-admin startproject`.
- **¿Peligro?** Ninguno. Los scaffolders serán genéricos (`hello-world`,
  template vacío). Los templates productivos de ERPlora (con cuentas,
  catálogo, UX específica) viven en `apps/` del monorepo privado.

### 4. Dependencias
Todas permisivas: FastAPI, SQLAlchemy, Alembic, Jinja2, Pydantic, Typer, httpx,
aioboto3, structlog, OpenTelemetry. Sin vendor lock, sin GPL.

---

## Qué NO expone la librería (lo valioso, queda privado)

| Privado en ERPlora | Por qué es el producto real |
|---|---|
| `apps/system/HubModule` con su schema concreto | Modela la instalación/billing por hub — IP |
| `apps/accounts/User`, `Role`, `Permission` | Modelo de autorización específico del SaaS |
| `apps/configuration/HubConfig` | Config por cliente |
| `apps/sync/catalog_sync` | Cómo hablamos con Cloud |
| `apps/system/compliance_resolver` | Reglas fiscales y de compliance ES |
| Cloud (Django): billing, Stripe, marketplace, catálogo sectorial | El SaaS entero |
| `modules/fiscal_es`, `verifactu`, `gestoria_es` | Implementación fiscal certificada |
| `modules/sales`, `pos`, `invoice`, `crm`… (96 módulos) | Lógica ERP real |
| `kernel_modules/assistant` | GPT proxy + tools + prompts propietarios |
| Bucket `erplora-modules`, Aurora, JWT signing keys, AWS account IDs | Infra |
| Network kit TPV, bridge hardware | Integración hardware |
| Branding, demos comerciales, clientes | Producto |

El runtime publicable **no sabe nada de nada de lo anterior**. Recibe por
`settings.py` un `DATABASE_URL`, un `S3_MODULES_BUCKET` (o cualquier otro
blob store), un `HUB_ID` genérico, y carga las apps/módulos que le pasen.

---

## Cómo se usaría desde fuera

### Flujo de un desarrollador externo

```bash
pip install hotframe             # Apache 2.0, PyPI público
hf startproject my_erp            # Crea main.py, asgi.py, settings.py, apps/, modules/
cd my_erp
hf startapp accounts              # Scaffolder de app estática
hf startmodule billing            # Scaffolder de módulo dinámico
hf makemigrations                 # Alembic per-namespace
hf migrate
hf runserver                      # Uvicorn con hot-reload
```

CLI instalado como `hf` (corto) y `hotframe` (largo explícito, fallback si
`hf` colisiona). `from hotframe import AppConfig, ModuleConfig, path, View, ...`

Resultado: un esqueleto ERP vacío funcional, donde el dev escribe sus módulos
exactamente como los escribimos nosotros en ERPlora. Pueden probar su módulo,
contribuirlo a un marketplace propio, o —si encaja— proponerlo al marketplace
de ERPlora (otro canal de negocio).

### Cómo consume ERPlora su propio runtime tras la separación
- `hub-next/` pasa a tener `pyproject.toml` con `hotframe >= X.Y` como dependencia.
- `runtime/` desaparece del monorepo y vive en su repo público separado.
- ERPlora sigue desarrollando `apps/`, `modules/`, `kernel_modules/` en privado.
- Releases del runtime con SemVer; Cloud/Hub pinchan a versión concreta.

---

## Beneficios de negocio concretos

1. **Módulos comunitarios** → marketplace con inventario gratis. ERPlora cobra
   por hosting, integraciones premium, y módulos propios certificados.
2. **Reclutamiento** → un framework OSS conocido en el CV de ERPlora atrae
   ingenieros senior sin pagar salarios FAANG.
3. **Credibilidad en ventas enterprise** → "nuestro core es open source auditable,
   nuestro producto es el ecosistema encima".
4. **Debugging externo** → bugs del runtime los arreglan contribuidores; ERPlora
   mantiene revisión y aprobación de PRs.
5. **Ecosistema de formación** → cursos, tutoriales, conferencias. SEO orgánico
   que arrastra a ERPlora.
6. **Moat defensivo por estándar de facto** → si el runtime se adopta, los
   módulos de terceros se escriben para él, y quien construya un ERP con él
   termina considerando seriamente nuestro marketplace.

---

## Riesgos residuales y mitigaciones

| Riesgo | Probabilidad | Mitigación |
|---|---|---|
| Competidor construye ERP SaaS usando el runtime | Baja — implicaría replicar 96 módulos, fiscal ES, Cloud, bridge | Apache 2.0 lo permite; se compite por producto, no por motor. Moat = módulos + Cloud. |
| Soporte a terceros consume tiempo de mantenimiento | Media | Governance clara: CODEOWNERS, política de PRs, triage bot, releases cada 3-6 meses. |
| Fork hostil (alguien cambia marca y compite directo con el runtime) | Baja | Apache protege marca; si pasa, ellos tienen el coste de mantenimiento también. |
| Contaminación GPL por dependencia | Baja | `pip-licenses --fail-on="GPL;AGPL"` en CI. Lista explícita de deps permitidas. |
| Vulnerabilidad en el runtime expone Hubs productivos | Media | SECURITY.md con disclosure privado; CVE process; releases de parche <24h. |
| Breaking change en API pública rompe a usuarios externos | Media | Feature freeze + deprecation de 2 versiones (ya declarado en ARCHITECTURE.md línea 970). |

---

## Prerrequisitos para publicar (cuando el runtime esté "acabado")

### Técnicos
1. Cero hits de `grep -r "apps\." runtime/` (ya planeado en fases del TODO).
2. Cero hardcodes de ERPlora en `settings.py` — todo por variables de entorno
   con defaults genéricos o `None`.
3. API pública cerrada en `runtime/__init__.py` con `__all__` completo.
4. Cobertura de tests ≥90% (gate ya declarado en ARCHITECTURE.md línea 926).
5. `import-linter` con contrato "runtime no importa apps/modules/kernel_modules".
6. En venv limpio sin el monorepo: `pip install .` + `<cli> startproject foo` +
   `<cli> runserver` → endpoint responde 200.
7. `<cli> startmodule hello` genera módulo compilable, instalable, con tests
   pasando.
8. CI público en el repo OSS (GitHub Actions).

### Documentación
1. README con quickstart en <5 minutos (`pip install` → `startproject` →
   página funcionando).
2. Docs en subdominio (MkDocs Material), guía conceptual (apps vs modules,
   hot-mount, signals), reference de API, tutorial de módulo de ejemplo,
   migration guide desde Django para quien llegue de ahí.
3. Repo aparte con ejemplo "hello-world module" + uno más complejo con CRUD.
4. Diagramas de ARCHITECTURE.md reutilizados (son buenos).

### Legal
1. `LICENSE` (Apache 2.0) en la raíz.
2. Header SPDX en cada `.py`: `# SPDX-License-Identifier: Apache-2.0`.
3. `CONTRIBUTING.md` con flujo de PRs y convención de commits.
4. `CODE_OF_CONDUCT.md` (Contributor Covenant estándar).
5. `SECURITY.md` con email de disclosure y SLA.
6. DCO enforzado en PRs (bot de GitHub). No CLA al principio.
7. Validar disponibilidad del nombre elegido en PyPI + GitHub + trademark search
   básico antes de registrar.

### Distribución
1. **Fase 1 (lanzamiento)**: repo en `github.com/ERPlora/hotframe`. Motivo: la marca ERPlora detrás da señal de producción real (como Vercel con Next.js, Sentry con sus SDKs). Un proyecto respaldado por una empresa que lo usa en producción inspira más confianza técnica y de continuidad que uno sin respaldo visible.
2. **Fase 2 (madurez)**: cuando el proyecto tenga tracción propia (estrellas, contribuidores externos regulares, uso fuera de ERPlora), considerar migración a organización independiente `hotframe/hotframe` para desacoplar la gobernanza. GitHub gestiona redirects automáticos de la URL antigua.
3. ERPlora monorepo consume como dependencia `hotframe>=X.Y`.
4. Publicación en PyPI automatizada vía GitHub Actions con releases SemVer (Trusted Publishing OIDC, sin API tokens).
5. Docs en `hotframe.dev` o subdominio.
6. Anuncio: blog post técnico + Hacker News + Reddit r/Python + Python Weekly.

---

## Calendario

No publicar antes de que:
1. `runtime/` cumpla el feature freeze declarado en ARCHITECTURE.md línea 962
   (scope congelado, <5% commits mensuales lo tocan).
2. Fases pendientes del TODO (6c, 7, 8, 9) estén cerradas.
3. Los 30 imports de `apps.*` en `runtime/` estén eliminados (Fase 5 del TODO).
4. Se haya operado en producción con el runtime durante al menos 3-6 meses
   sin cambios al contrato público → señal de que es estable.

Con estas condiciones, publicar = evento bajo riesgo. Sin ellas, publicar =
pagar en reputación cuando rompamos API a contribuidores.

---

## Verificación final antes de publicar

1. `grep -r "apps\." <runtime_repo>/` → 0 resultados en código.
2. `grep -ri "erplora" <runtime_repo>/` → 0 en código; solo permitido en
   `README.md` como "originalmente desarrollado para ERPlora".
3. `pip install .` en venv limpio funciona sin el monorepo ERPlora.
4. `<cli> startproject demo && cd demo && <cli> runserver` arranca y responde.
5. `<cli> startmodule hello` → módulo con tests → `pytest` verde.
6. `pytest --cov=runtime --cov-fail-under=90` pasa.
7. `pip-licenses --fail-on="GPL;AGPL"` verde.
8. `import-linter` verde.
9. Revisión legal externa breve del `LICENSE` + headers + disponibilidad del
   nombre.
10. Canary release: publicar como `0.1.0rc1` en TestPyPI, invitar a 2-3
    devs externos a probar el quickstart en <10 min. Si funciona → `0.1.0`
    en PyPI.

---

## Extras opcionales (post-launch)

- Scaffolder "full ERP demo" — comando que crea un proyecto con una app
  accounts mínima + un módulo CRUD de ejemplo + layout base. Acelera onboarding.
- Plugin de VSCode con snippets y comandos (`startmodule`, `migrate`) integrados.
- Plantilla de despliegue Docker + docker-compose para dev local sin configurar
  nada.
- Servidor de índice de módulos públicos independiente (tipo `crates.io` o
  `pypi`) para que la comunidad publique módulos OSS sin pasar por ERPlora.
  Decisión de negocio aparte.

---

## Archivos que se tocarán al ejecutar (cuando llegue el momento)

- Nuevo repo público `hotframe/` con `LICENSE`, `README.md`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`, `.github/workflows/{ci,release}.yml`,
  `pyproject.toml`, `docs/`.
- [hub-next/runtime/__init__.py](hub-next/runtime/__init__.py) — poblar API pública cerrada.
- [hub-next/pyproject.toml](hub-next/pyproject.toml) — pasar runtime a dependencia externa.
- Eliminar `hub-next/runtime/` del monorepo cuando la separación sea efectiva.
- Nuevo repo `hotframe-examples/` con `hello-module/` y `crud-module/` como
  tutoriales ejecutables.
