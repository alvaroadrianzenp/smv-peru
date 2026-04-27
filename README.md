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

# El primer argumento es el RPJ (código corto interno de SMV), NO el RUC.
# "B30006" corresponde a Alicorp S.A.A. (RUC 20100055237).
datos = fetch_smv_fundamentals("B30006", years_back=3, current_year=2024)
print(datos)
```

## Formato del output

El dict devuelto tiene dos keys: `years` (lista de dicts, uno por año fiscal,
ordenada cronológicamente) e `info` (reservado para metadata futura).

Cada año contiene `fiscal_year` (int) más métricas y ratios:

| Campo | Tipo | Unidad |
|---|---|---|
| `revenue`, `ebitda`, `net_income`, `equity`, `total_assets`, `total_debt`, `fcf` | float \| None | **Miles** de la moneda reportada por la empresa (típicamente soles). Ej. `revenue=13_655_764` ≈ S/. 13.66 mil millones. |
| `eps` | float \| None | Utilidad por acción, unidades base. |
| `current_ratio`, `roe`, `roic` | float \| None | **Decimales**, NO porcentajes. `roe=0.14` significa 14%. |

Si la API no encuentra datos (ni en consolidado ni individual), retorna `None`.

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

## Disclaimer

Este proyecto **no es oficial**. No tiene afiliación, endorsement ni relación con la Superintendencia del Mercado de Valores del Perú (SMV) ni con la Bolsa de Valores de Lima (BVL).

Los datos provienen del portal público de datos abiertos de SMV; esta librería es un cliente que los reformatea. **No se garantiza la exactitud, completitud ni puntualidad de los datos** — pueden contener errores, estar desactualizados, o cambiar de formato sin aviso.

Esta librería se provee con **fines informativos y educativos**. **No constituye recomendación de inversión, asesoría financiera, análisis profesional ni opinión sobre la conveniencia de instrumentos financieros.** Cualquier decisión de inversión basada en los datos provistos es responsabilidad exclusiva del usuario.

## Licencias

- **Código:** MIT (ver `LICENSE`).
- **Datos:** los datos provienen de la SMV Perú. Esta librería es un cliente que reformatea esos datos; la atribución a la fuente es obligatoria al redistribuirlos.
