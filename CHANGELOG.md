# Changelog

Todos los cambios importantes de este proyecto se documentan en este archivo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
el proyecto sigue [Versionado Semántico](https://semver.org/lang/es/).

## [Unreleased]

## [0.1.0] - 2026-05-03

Primera versión pública. Cliente Python para el web service SOAP de la
Superintendencia del Mercado de Valores del Perú (SMV) que descarga estados
financieros, los procesa y opcionalmente exporta a Excel/CSV.

### API pública

- `fetch_eeff(ticker, desde, hasta, ...)` — descarga EEFF de una empresa para un
  rango de años.
- `fetch_multi(tickers, ...)` — descarga multi-empresa aprovechando el cache
  compartido (una call SOAP a SMV trae todas las empresas peruanas).
- `set_dna(result, dna)` — inyecta D&A externo cuando la empresa publica CF
  directo y SMV no expone Depreciación/Amortización.
- `to_excel(result, filepath, ...)` — exporta a `.xlsx` con secciones P&L,
  Balance, Cash Flow, ratios y crecimiento YoY (dep opcional `openpyxl`).
- `to_csv(result, filepath, ...)` — alternativa con stdlib pura.
- `EMPRESAS`, `FIELDS_TO_CODES_2D`, `FIELDS_TO_CODES_2F`, `resolve_ticker` —
  acceso al catálogo y a los mapeos amigable→código SMV.

### Catálogo soportado (27 tickers)

- **21 industriales** (esquema 2D NIIF): AENZAC1, ALICORC1, BACKUSI1, BVN,
  CASAGRC1, CORAREI1, CPACASC1, CVERDEC1, ENGEPEC1, FERREYC1, INRETC1, LUSURC1,
  MINSURI1, NEXAPEC1, ORYGENC1, PLUZC1, PORTINC1, RELAPAC1, UNACEMC1, VOLCABC1,
  YURAC1.
- **6 bancos / holdings financieros** (esquema 2F): BAP, BBVAC1, CREDITC1, IFS,
  INTERBC1, SCOTIAC1.

### Métricas y campos

- ~95 campos amigables por período en 2D, 50+ en 2F.
- Métricas derivadas organizadas en 7 categorías: liquidez, solvencia /
  apalancamiento, cobertura, rentabilidad, cash flow, política de capital,
  crecimiento YoY.
- LTM (Last Twelve Months) automáticas en trimestrales: numeradores como suma
  móvil de 4 trimestres, denominadores como promedio de stocks.
- `payout_ratio` con **lag T-1** (convención peruana JGA): los dividendos del
  año T se miden contra el net income del ejercicio cerrado anterior. En
  trimestrales LTM, el denominador es la suma de los 4 trimestres que terminan
  4Q antes del actual.
- EBITDA real cuando la empresa publica CF indirecto (D&A en cuenta `3D0602`).
  Para las que publican CF directo, `set_dna()` permite inyectar el dato
  externamente.
- Cuentas crudas adicionales (no expuestas como amigables) accesibles vía
  `period["raw_accounts"]` con su `DescripcionCuenta` oficial.

### Cobertura

- Periodicidad **anual** y **trimestral**. Cada trimestre se devuelve como
  period-only (no YTD acumulado), incluso cuando SMV publica el CF en YTD.
- **Cascada Consolidado → Q4 Anual**: cuando un Balance Consolidado anual está
  ausente pero el Q4 sí existe, usa Q4 como sustituto (stock idéntico al cierre
  anual, validado contra múltiples empresas). Caso real: BBVA 2022.
- **Política de homogeneidad C/I**: la serie nunca mezcla Consolidado con
  Individual. Si pides `tipo="consolidado"` y un período no lo tiene, ese
  período se omite — no se rellena con Individual.
- **Early-exit a Individual paralelizado**: si el RPJ no aparece en ningún
  resultado Consolidado del rango, toda la serie se baja en Individual de una
  sola pasada paralela. Caso típico: Cerro Verde, Interbank, Pluz Energía.
- Cobertura histórica empírica: desde **1999** (verificado con Alicorp
  1999-2025).

### Cache local

- Comprimido con **gzip** (extensión `.json.gz`) — reduce ~96% el tamaño en
  disco vs JSON crudo. Lectura imperceptiblemente más rápida (menor I/O
  compensa la descompresión).
- Compatibilidad retroactiva con formato `.json` legacy de versiones
  pre-publicación.
- **Cache compartido** entre empresas: una sola call SOAP a SMV devuelve
  TODAS las empresas peruanas para ese `(op, año, periodo, tipo)`. Descargar
  varios tickers del mismo rango es ~gratis tras el primero.
- **Escritura atómica** (write-to-temp + `os.replace`) — soporta uso
  concurrente de varios procesos compartiendo el mismo `cache_dir`.
- Directorio default: cache del usuario según el SO (macOS:
  `~/Library/Caches/smv-peru/`). Configurable vía `cache_dir=` o variable de
  entorno `SMV_PERU_CACHE_DIR`.
- **Reintentos con backoff exponencial** en errores transitorios de red
  (3 intentos por defecto).
- Descargas SOAP **en paralelo** (default `max_workers=10`, configurable 1-10).
  Cold cache 10 años trimestrales: ~2 min vs ~20 min serial.

### Exports

- Excel (`.xlsx`) con `openpyxl` como dep opcional. Layout: filas = campos
  agrupados por sección, columnas = períodos cronológicos. Header con metadata
  (empresa, moneda, fecha de generación).
- CSV con stdlib pura (sin deps).
- **Detección automática** single-empresa vs multi-empresa según la forma del
  resultado.
- **Auto-detección del ticker** desde `result["info"]["ticker"]` cuando no se
  pasa explícito — el header del Excel/CSV trae el nombre amigable de la
  empresa sin esfuerzo extra.
- Filtrado condicional del bloque CF directo vs indirecto según el método que
  la empresa reporta.
- Hoja opcional con cuentas crudas (`include_raw=True` en `to_excel`).

### Seguridad

- **Bloqueo de redirects HTTP/HTTPS** y validación del host final tras la
  respuesta — defensa contra envenenamiento del cache vía MITM o redirect
  malicioso. Cualquier respuesta cuyo `resp.url` no apunte a
  `https://mvnet.smv.gob.pe/` se descarta sin guardar.
- **Anti formula injection** en exports Excel: las descripciones de cuentas
  que comienzan con `=`, `+`, `-`, `@`, `\t`, `\r` se prefijan con `'` para
  que las herramientas de hoja de cálculo las traten como texto literal y no
  ejecuten la "fórmula" al abrir el archivo.
- **Validación estricta** de inputs en `_soap_envelope` (operación, ejercicio,
  periodo, tipo restringidos a sets de valores válidos) y `fetch_eeff`
  (años fiscales como `int` en `[1990, 2100]`) — defensa en profundidad contra
  inyección XML/SOAP.

### Limitaciones conocidas

- **6 tickers reportan en Individual** (matriz consolidante en el extranjero):
  - Siempre: CVERDEC1 (Cerro Verde), INTERBC1 (Interbank), PLUZC1 (Pluz
    Energía), PORTINC1 (Cosco Shipping Ports Chancay).
  - Mixtos: ENGEPEC1 (Engie — anuales en I, trimestrales 2024+ en C), NEXAPEC1
    (Nexa — C completo en anuales 2020-2023 y trimestrales 2023-2024; 2024
    anual aún no publicado).
- **3 cuentas del CF indirecto sin nombre amigable**: `3D0818`, `3D0830`,
  `3D0836`. SMV no expone su `DescripcionCuenta` vía web service. Accesibles
  vía `raw_accounts`.
- **EBITDA real solo cuando hay CF indirecto** (cuenta `3D0602` con D&A). Para
  empresas que publican CF directo, `ebitda` es `None` hasta que el analista
  inyecte D&A externo con `set_dna()`. Sigue el mismo patrón para
  `ebitda_margin`, `debt_to_ebitda`, `net_debt_to_ebitda`,
  `interest_coverage_ebitda`.
- **Aseguradoras (esquema 2E) no soportadas todavía** — RPJs detectados, pero
  el mapeo de cuentas no está implementado.
- **Trimestres recientes parcialmente publicados**: SMV típicamente publica
  cada trimestre con ~2-3 meses de retraso. La librería omite los períodos no
  publicados (no falla).

### Requisitos

- Python ≥ 3.9.
- **Cero dependencias** externas en producción (solo stdlib).
- `openpyxl ≥ 3.0` como dep opcional para `to_excel` (instalable con
  `pip install smv-peru[excel]`).

### Tests y validación

- 192 tests unitarios verdes en ~0.3 s (fixtures sintéticos + 21 fixtures de
  Alicorp para regresión).
- Smoke test multi-empresa contra el web service real: 27/27 tickers OK
  (anuales 2020-2024 + trimestrales 2023-2024). Ejecutable con
  `uv run python scripts/smoke_test.py`.
- Validación de signos y montos contra PDFs auditados de Alicorp, UNACEM,
  BBVA y BCP — los valores devueltos cuadran al peso.

[Unreleased]: https://github.com/alvaroadrianzenp/smv-peru/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/alvaroadrianzenp/smv-peru/releases/tag/v0.1.0
