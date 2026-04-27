# smv-peru

Librería Python para acceder a los datos financieros públicos publicados por la **Superintendencia del Mercado de Valores del Perú (SMV)** vía su web service oficial.

## Estado

En desarrollo inicial. Aún no publicado en PyPI.

## Instalación

```bash
pip install smv-peru
```

> Mientras no se publique en PyPI, puedes instalarla desde el repositorio local con `pip install -e .` o `uv sync`.

## Uso

```python
from smv_peru import fetch_smv_fundamentals

# RUC de Alicorp como ejemplo
datos = fetch_smv_fundamentals("20100055237", years_back=10)
print(datos)
```

## Desarrollo

Este proyecto usa [uv](https://github.com/astral-sh/uv) como gestor de entornos y dependencias.

```bash
uv sync                # crea el venv e instala el paquete editable
uv run python          # entra a un REPL con el paquete disponible
```

## Roadmap

- [x] Estructura inicial de la librería.
- [ ] Documentar la API pública (`fetch_smv_fundamentals`).
- [ ] Tests con datos cacheados.
- [ ] Soporte de cache configurable (sin paths hardcoded).
- [ ] Soporte para esquema 2F (bancos).
- [ ] Publicar en PyPI.
- [ ] (Más adelante) API web HTTP encima de esta librería, como módulo opcional.

## Licencias

- **Código:** AGPL-3.0-or-later (ver `LICENSE`).
- **Datos:** los datos provienen de la SMV Perú. Esta librería es un cliente que reformatea esos datos; la atribución a la fuente es obligatoria al redistribuirlos.
