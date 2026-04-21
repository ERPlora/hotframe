# Contributing a hotframe

¡Gracias por tu interés en contribuir! `hotframe` es un proyecto open source bajo licencia Apache 2.0.

## Estado del proyecto

`hotframe` está en **pre-alpha**: el código vive temporalmente dentro del monorepo ERPlora (`hub-next/runtime/`) y se extraerá a este repo cuando alcance feature freeze. Mientras tanto, aceptamos:

- Feedback sobre la [arquitectura](ARCHITECTURE.md).
- Issues con ideas, casos de uso, críticas constructivas.

No aceptamos todavía PRs de código (no hay código que modificar).

## Cómo reportar un issue

1. Busca primero en los issues existentes.
2. Si no existe, abre uno con:
   - Qué esperabas.
   - Qué pasó.
   - Pasos para reproducir (si aplica).
   - Versión de Python + OS.

## Convenciones (para cuando empecemos a aceptar código)

### Commits

Convencional: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`. Sujeto en imperativo, ≤72 caracteres.

### Certificado de origen (DCO)

Cada commit debe firmarse con `git commit -s`. Al firmar certificas que el código es tuyo o puedes aportarlo bajo Apache 2.0. Ver https://developercertificate.org/.

### Estilo de código

- Python ≥3.12, formateado con `ruff format`.
- Lint con `ruff check`.
- Tipado estático con `mypy` (strict en módulos públicos).
- Tests con `pytest`. Cobertura mínima 90% para código nuevo.

### Proceso de PR

1. Fork + rama desde `main`.
2. Commits firmados con DCO.
3. CI en verde (lint + tests + import-linter + coverage).
4. PR con descripción de qué y por qué.
5. Al menos 1 review de mantenedor.

## Código de conducta

Este proyecto sigue el [Contributor Covenant](CODE_OF_CONDUCT.md). Reportes a hello@erplora.com.

## Licencia

Al contribuir aceptas que tu código se publique bajo [Apache 2.0](https://github.com/ERPlora/hotframe/blob/main/LICENSE).
