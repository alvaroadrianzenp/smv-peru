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
from smv_peru import fetch_estados_financieros

# Anual, consolidado (defaults)
datos = fetch_estados_financieros(
    "ALICORC1",
    desde=2021,
    hasta=2023,
)

# Trimestral, individual
datos_q = fetch_estados_financieros(
    "ALICORC1",
    desde=2023, hasta=2023,
    tipo="individual",
    periodicidad="trimestral",
)

for p in datos["periods"]:
    print(p["fiscal_year"], p["revenue"])
```

## Tickers soportados

Por ahora la librería soporta empresas industriales con esquema contable 2D de SMV. Se irá ampliando conforme se añada soporte para más esquemas (bancos = 2F, aseguradoras = 2E).

| Ticker | Empresa |
|---|---|
| `ALICORC1` | Alicorp S.A.A. |
| `BACKUSI1` | Backus & Johnston |
| `CPACASC1` | Cementos Pacasmayo |
| `ENGEPEC1` | Engie Perú |
| `FERREYC1` | Ferreycorp |
| `INRETC1`  | InRetail Perú |
| `LUSURC1`  | Luz del Sur |
| `MINSURI1` | Minsur |
| `UNACEMC1` | UNACEM |
| `VOLCABC1` | Volcan Compañía Minera |

Si el ticker no está en el catálogo, se levanta `UnknownTickerError` con la lista completa en el mensaje.

## Formato del output

El dict devuelto tiene dos keys: `periods` (lista de dicts, uno por período) e `info` (reservado para metadata futura).

Cada período contiene:

| Campo | Tipo | Descripción |
|---|---|---|
| `fiscal_year` | int | Año fiscal del período. |
| `quarter` | int \| None | `None` si es anual; `1`, `2`, `3` o `4` si es trimestral. |
| `revenue`, `ebitda`, `net_income`, `equity`, `total_assets`, `total_debt`, `fcf` | float \| None | **Miles** de la moneda reportada por la empresa (típicamente soles). Ej. `revenue=13_655_764` ≈ S/. 13.66 mil millones. |
| `eps` | float \| None | Utilidad por acción, unidades base. |
| `current_ratio`, `roe`, `roic` | float \| None | **Decimales**, NO porcentajes. `roe=0.14` significa 14%. |

Si la API no encuentra datos (ni en consolidado ni individual), retorna `None`.

## Desarrollo

Este proyecto usa [uv](https://github.com/astral-sh/uv) como gestor de entornos y dependencias.

```bash
uv sync                # crea el venv e instala el paquete editable
uv run pytest          # corre los tests
uv run python          # entra a un REPL con el paquete disponible
```

## Roadmap

- [x] Estructura inicial de la librería.
- [x] API pública documentada con docstrings.
- [x] Tests unitarios y de integración con fixtures.
- [x] Cache configurable (parámetro, env var, o user cache dir del SO).
- [x] Soporte para periodicidad anual y trimestral.
- [x] Selección explícita de estados consolidados o individuales.
- [x] Catálogo de tickers BVL → SMV.
- [ ] Soporte para esquema 2F (bancos: BAP, BCP, BBVA, Interbank).
- [ ] Repo en GitHub público + GitHub Actions (CI).
- [ ] Publicar `0.1.0` en PyPI.
- [ ] (Más adelante) API web HTTP encima de esta librería, como módulo opcional.

## Disclaimer

Este proyecto **no es oficial**. No tiene afiliación, endorsement ni relación con la Superintendencia del Mercado de Valores del Perú (SMV) ni con la Bolsa de Valores de Lima (BVL).

Los datos provienen del portal público de datos abiertos de SMV; esta librería es un cliente que los reformatea. **No se garantiza la exactitud, completitud ni puntualidad de los datos** — pueden contener errores, estar desactualizados, o cambiar de formato sin aviso.

Esta librería se provee con **fines informativos y educativos**. **No constituye recomendación de inversión, asesoría financiera, análisis profesional ni opinión sobre la conveniencia de instrumentos financieros.** Cualquier decisión de inversión basada en los datos provistos es responsabilidad exclusiva del usuario.

## Licencias

- **Código:** MIT (ver `LICENSE`).
- **Datos:** los datos provienen de la SMV Perú. Esta librería es un cliente que reformatea esos datos; la atribución a la fuente es obligatoria al redistribuirlos.
