# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Propósito

Cliente Python que descarga y normaliza estados financieros públicos de empresas peruanas desde el web service SOAP de la SMV (Superintendencia del Mercado de Valores). Cubre 27 tickers (21 industriales esquema 2D, 6 bancos esquema 2F) con datos históricos desde 1999.

Pre-release (v0.1.0). El núcleo solo usa stdlib (`urllib`, `gzip`, `json`, `threading`); `openpyxl` es opcional para exportar a Excel.

## Comandos

- Instalar dependencias: `uv sync`
- Tests (192 tests con fixtures sintéticos, no tocan SMV real): `uv run pytest`
- Test individual: `uv run pytest tests/test_<archivo>.py::test_<nombre>`
- Smoke test real contra SMV (27 tickers): `uv run python scripts/smoke_test.py`
- Demo de uso: `uv run python examples/demo.py`
- Construir paquete (backend: hatchling): `uv build`

No hay linter/formatter configurado, ni pre-commit, ni CI.

## Arquitectura

El núcleo es `client.py` (cliente SOAP) + catálogo de tickers en `empresas.py` + parsers por esquema contable. Para entender cualquier cambio no trivial hay que cruzar varios módulos.

**Esquemas contables** — la SMV publica con códigos de cuenta distintos según el tipo de empresa:
- `2D` — industriales bajo NIIF (21 empresas)
- `2F` — bancos (6 empresas; métricas NIM/ROE/NPL usan `Monto2` para promedios de stock)
- `2E` — aseguradoras (futuro, aún no soportado)

Cada esquema tiene su propio mapper (`_map_period_2d`, `_map_period_2f`) que convierte el dict SOAP crudo en un dict normalizado con ~95 campos (2D) o 50+ (2F).

**Cascada por tipo**: si una empresa no publica Consolidado en un período, el cliente cae automáticamente a Individual.

**Cache gzip**: respuestas SOAP cacheadas como `.json.gz` (reduce ~96% vs JSON crudo: ~50 MB vs ~1 GB para 10 años de 27 empresas). Por defecto: `~/Library/Caches/smv-peru` (macOS) o `~/.cache/smv-peru` (Linux). Configurable vía env `SMV_PERU_CACHE_DIR` o arg `cache_dir`.

**Normalización trimestral**: si el flujo de caja viene YTD acumulado, el cliente resta el período anterior para devolver period-only.

**Métricas derivadas**: 7 categorías (liquidez, solvencia, cobertura, rentabilidad, CF, capital, YoY).

## Convenciones no obvias

- **Montos en miles** de la moneda reportada (PEN/USD); ratios en **decimales** (`0.14` = 14%).
- **Signos por convención SMV**: COGS, `interest_expense`, `capex` vienen negativos; campos derivados (`dividends_paid`, `taxes_paid`) se devuelven en positivo.
- **`payout_ratio` con lag T-1**: convención peruana — dividendos del año T se miden contra net income de T-1.
- **D&A inyectable** vía `set_dna()` cuando la empresa publica CF directo (sin D&A en SMV); si no se inyecta, `EBITDA` queda `None`.
- **`periods_missing`**: lista de gaps de SMV o desviaciones de homogeneidad Consolidado/Individual.
- **Seguridad HTTP**: el cliente rechaza redirects 3xx (anti-MITM). Reintentos (3x con backoff) solo en errores transitorios; respuestas con formato inesperado no se reintentan.
- **`raw_accounts`**: expone cuentas SMV no mapeadas a campos amigables — útil para inspección/debug, no para análisis estable.

## Multi-empresa y exportadores

- `fetch_multi()` descarga lotes en paralelo (default 10 workers) con cache compartido. Típico: ~2 min cold, instantáneo warm.
- `excel.py` (requiere `openpyxl`) y `csv_export.py` (stdlib puro) detectan automáticamente si los datos son single/multi-empresa y si son esquema 2D o 2F.
