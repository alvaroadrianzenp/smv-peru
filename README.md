# smv-peru

[![PyPI](https://img.shields.io/pypi/v/smv-peru)](https://pypi.org/project/smv-peru/)
[![Python](https://img.shields.io/pypi/pyversions/smv-peru)](https://pypi.org/project/smv-peru/)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Status](https://img.shields.io/badge/status-beta-orange)](https://github.com/alvaroadrianzenp/smv-peru)

> *Cliente Python para los datos financieros públicos de la Superintendencia del Mercado de Valores del Perú (SMV).*

Descarga estados financieros de 27 empresas listadas en la BVL (industriales y bancos) directamente desde el web service oficial de la SMV, sin scraping HTML ni dependencias externas. Pensada para analistas, estudiantes, inversionistas e investigadores que hacen análisis de crédito, valorización y modelado financiero de empresas peruanas.

## Instalación

```bash
pip install smv-peru                # core (cero dependencias)
pip install "smv-peru[excel]"       # opcional, para to_excel
```

Requiere Python ≥ 3.9.

## Quick Start

```python
from smv_peru import fetch_eeff, to_excel

datos = fetch_eeff("ALICORC1", desde=2020, hasta=2024)
to_excel(datos, "alicorp_2020_2024.xlsx")
```

Genera un Excel con P&L, Balance, Cash Flow, ratios y crecimiento YoY de Alicorp 2020-2024 (5 años anuales). El archivo se abre directo en Excel, Numbers o Google Sheets.

Para más ejemplos (trimestral con LTM, multi-empresa, comparar bancos, payout, inyectar D&A externo, exportar a CSV), ver la [guía de uso](docs/guia.md).

## Características

- **27 tickers BVL** (21 industriales NIIF + 6 bancos/holdings financieros).
- **Cobertura desde 1999** (verificado empíricamente con Alicorp 1999-2025).
- **Anual y trimestral**, con métricas LTM automáticas en trimestrales.
- **~95 campos amigables** en industriales + 50+ en bancos, más métricas derivadas en 7 categorías.
- **Convenciones peruanas** integradas: `payout_ratio` con lag T-1 (Ley General de Sociedades), monedas PEN/USD.
- **Cero dependencias** en producción, cache local comprimido (gzip) y descargas paralelas.
- **Exporta a Excel y CSV** con detección automática single/multi-empresa.

## Tickers soportados

<details>
<summary>21 industriales (esquema 2D)</summary>

| Ticker | Empresa | Sector |
|---|---|---|
| `AENZAC1` | AENZA (ex Graña y Montero) | construcción / concesiones |
| `ALICORC1` | Alicorp | consumo masivo / alimentos |
| `BACKUSI1` | Backus & Johnston | bebidas |
| `BVN` | Buenaventura | minería polimetálica |
| `CASAGRC1` | Casa Grande | agroindustria / azucarera |
| `CORAREI1` | Aceros Arequipa | siderurgia |
| `CPACASC1` | Cementos Pacasmayo | cementos |
| `CVERDEC1` | Sociedad Minera Cerro Verde | minería de cobre |
| `ENGEPEC1` | Engie Perú | electricidad / generación |
| `FERREYC1` | Ferreycorp | distribución industrial |
| `INRETC1` | InRetail Perú | retail / supermercados |
| `LUSURC1` | Luz del Sur | electricidad / distribución |
| `MINSURI1` | Minsur | minería de estaño |
| `NEXAPEC1` | Nexa Resources Perú (ex Milpo) | minería de zinc |
| `ORYGENC1` | Orygen Perú (ex Enel Generación) | electricidad / generación |
| `PLUZC1` | Pluz Energía Perú (ex Enel Distribución) | electricidad / distribución |
| `PORTINC1` | Inversiones Portuarias Chancay | logística / puertos |
| `RELAPAC1` | Refinería La Pampilla | refinación de petróleo |
| `UNACEMC1` | UNACEM | cementos |
| `VOLCABC1` | Volcan Compañía Minera | minería polimetálica |
| `YURAC1` | Yura | cementos |

</details>

<details>
<summary>6 bancos y holdings financieros (esquema 2F)</summary>

| Ticker | Empresa | Tipo |
|---|---|---|
| `BAP` | Credicorp Ltd. | Holding (matriz de BCP, Pacífico, Mibanco, Prima AFP) |
| `BBVAC1` | BBVA Perú | Banco operativo |
| `CREDITC1` | Banco de Crédito del Perú (BCP) | Banco operativo |
| `IFS` | Intercorp Financial Services | Holding (matriz de Interbank, Interseguro, Inteligo) |
| `INTERBC1` | Interbank (Banco Internacional del Perú) | Banco operativo |
| `SCOTIAC1` | Scotiabank Perú | Banco operativo |

</details>

> [!NOTE]
> Si el ticker no está en el catálogo, `fetch_eeff` levanta `UnknownTickerError`
> con la lista completa en el mensaje. Las aseguradoras (Pacífico, Rímac) usan
> esquema 2E, todavía no soportado — previsto para 0.2+.

## Documentación

- [Guía de uso](docs/guia.md) — ejemplos para los casos más comunes.
- [Conceptos clave](docs/conceptos.md) — esquemas 2D/2F, política Consolidado/Individual, convenciones, LTM, payout T-1, EBITDA y `set_dna`.
- [Campos del esquema 2D (industriales)](docs/campos-2d.md) — referencia completa de campos amigables y métricas derivadas.
- [Campos del esquema 2F (bancos)](docs/campos-2f.md) — referencia completa de campos bancarios y limitaciones.
- [Performance y cache](docs/performance.md) — paralelismo, cache gzip, reintentos, multi-empresa.

## Desarrollo

Este proyecto usa [uv](https://github.com/astral-sh/uv) como gestor de entornos.

```bash
uv sync                              # crea venv e instala el paquete editable
uv run pytest                        # 192 tests con fixtures sintéticos
uv run python scripts/smoke_test.py  # smoke test contra SMV real (27 tickers)
```

El [demo](examples/demo.py) muestra los principales casos de uso. El smoke test ejercita los 27 tickers contra el web service real para detectar regresiones que los unitarios con fixtures no cubren (cold cache ~5 min, warm <30 s).

## Roadmap

- [x] Soporte de esquema 2D (industriales) y 2F (bancos)
- [x] LTM trimestral, `payout_ratio` con lag T-1, EBITDA con `set_dna`
- [x] Cache gzip compartido, descargas paralelas, reintentos
- [x] Hardening de seguridad (TLS, formula injection, validación de inputs)
- [ ] Repo público en GitHub
- [ ] CI con GitHub Actions
- [ ] Publicación en PyPI
- [ ] Soporte de esquema 2E (aseguradoras: Pacífico, Rímac) — 0.2+

## Disclaimer

Esta librería **no es oficial**. No tiene afiliación, endorsement ni relación con la Superintendencia del Mercado de Valores del Perú (SMV) ni con la Bolsa de Valores de Lima (BVL).

Los datos provienen del portal público de SMV; **no se garantiza la exactitud, completitud ni puntualidad**. Provista con fines informativos y educativos — **no constituye recomendación de inversión, asesoría financiera ni opinión profesional sobre instrumentos financieros**. Cualquier decisión de inversión basada en estos datos es responsabilidad exclusiva del usuario.

## Licencia

Distribuido bajo la licencia MIT. Ver [LICENSE](LICENSE) para más detalles. Los datos provienen de la SMV Perú; la atribución a la fuente es obligatoria al redistribuirlos.

Mantenido por [Alvaro Adrianzén Puccio](https://github.com/alvaroadrianzenp).
