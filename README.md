# smv-peru

Librería Python para acceder a los datos financieros públicos publicados por la **Superintendencia del Mercado de Valores del Perú (SMV)** vía su web service oficial.

## Estado

Pre-release. Listo para publicar **0.1.0** en PyPI. Ver [`CHANGELOG.md`](CHANGELOG.md).

**Cobertura histórica:** SMV publica EEFF desde **1999** para empresas como Alicorp (verificado empíricamente). Esto da ~27 años de historia comparable. Empresas más nuevas (PORTINC1 = Chancay 2024) tienen cobertura desde su listado.

## Instalación

```bash
pip install smv-peru                # instalación core (sin dependencias externas)
pip install smv-peru[excel]         # opcional: agrega openpyxl para exportar a .xlsx
```

> Mientras no se publique en PyPI, puedes instalarla desde el repositorio local con `pip install -e .` o `uv sync`.

### Performance: descargas paralelas

Las llamadas SOAP a SMV son lentas (~9 segundos cada una). La librería **descarga en paralelo** (10 workers por default) para acelerar consultas multi-año. En cold cache, una consulta de 10 años trimestrales tarda ~2 minutos en lugar de ~20. En warm cache (datos ya descargados), las consultas son instantáneas.

```python
# Default: 10 workers en paralelo
datos = fetch_eeff("ALICORC1", desde=2016, hasta=2025, periodicidad="trimestral")

# Para descargas secuenciales (modo legacy):
datos = fetch_eeff("ALICORC1", desde=2023, hasta=2023, max_workers=1)
```

`max_workers` está limitado a un máximo de 10 para no saturar el web service de SMV.

### Cache comprimido con gzip

El cache local se almacena con compresión gzip (extensión `.json.gz`). Reduce ~96% el tamaño en disco vs JSON crudo, sin penalizar velocidad de lectura (la menor I/O compensa el costo CPU de descompresión). Para uso intensivo (10+ años, decenas de empresas), el cache pasa de ~1 GB a ~50 MB.

Compatibilidad: si tienes archivos `.json` de versiones anteriores, se leen sin problema. Solo se escribe en `.json.gz`.

### Reintentos automáticos en errores transitorios

Las llamadas SOAP fallidas por timeouts o errores de red se reintentan automáticamente hasta 3 veces con backoff exponencial. Errores definitivos (ej. respuesta sin formato esperado) no se reintentan (probablemente datos no existen).

### Múltiples empresas en una sola llamada

```python
from smv_peru import fetch_multi

# Descarga un sector de una vez (cache compartido = más rápido que loop)
sectorial = fetch_multi(
    ["CPACASC1", "UNACEMC1", "YURAC1"],
    desde=2019, hasta=2024,
)
# sectorial == {"CPACASC1": {...}, "UNACEMC1": {...}, "YURAC1": {...}}

# Tickers inválidos quedan como None sin abortar el resto
sectorial = fetch_multi(["ALICORC1", "TICKER_INVALIDO"], desde=2023, hasta=2023)
# sectorial["ALICORC1"] tiene datos; sectorial["TICKER_INVALIDO"] es None
```

`to_excel` y `to_csv` detectan automáticamente single vs multi-empresa: con multi, generan una hoja por ticker (Excel) o secciones por ticker (CSV).

## Uso

```python
from smv_peru import fetch_eeff

# Anual, consolidado (defaults)
datos = fetch_eeff(
    "ALICORC1",
    desde=2021,
    hasta=2023,
)

# Trimestral, individual
datos_q = fetch_eeff(
    "ALICORC1",
    desde=2023, hasta=2023,
    tipo="individual",
    periodicidad="trimestral",
)

# Recorre los períodos y consume los campos amigables
for p in datos["periods"]:
    print(
        p["fiscal_year"],
        f"revenue={p['revenue']:,.0f}",
        f"gross_margin={p['gross_margin']:.1%}",
        f"net_debt={p['net_debt']:,.0f}",
        f"fcf={p['fcf']:,.0f}",
    )

# Acceso a cuentas adicionales (raw) que no están como amigables
ultimo = datos["periods"][-1]
diferencias_de_cambio = ultimo["raw_accounts"].get("2D0410")
if diferencias_de_cambio:
    print(diferencias_de_cambio["nombre"], diferencias_de_cambio["monto"])
```

### Exportar a Excel (plantilla histórica para modelos financieros)

Con la extensión `[excel]` instalada (`pip install smv-peru[excel]`), genera un archivo `.xlsx` con los EEFF listos para tu modelo:

```python
from smv_peru import fetch_eeff, to_excel

datos = fetch_eeff("ALICORC1", desde=2019, hasta=2024)
to_excel(datos, "alicorp_2019_2024.xlsx", ticker="ALICORC1")

# Multi-empresa: genera Excel con una hoja por ticker
from smv_peru import fetch_multi
sectorial = fetch_multi(["CPACASC1", "UNACEMC1", "YURAC1"], desde=2019, hasta=2024)
to_excel(sectorial, "cementeras_2019_2024.xlsx")
```

Layout: filas = campos amigables agrupados por sección (Estado de Resultados, Balance, Cash Flow, Ratios, YoY); columnas = períodos cronológicos (`2019, 2020, ...` o `2023Q1, 2023Q2, ...` para trimestral). Header con metadata (ticker, esquema, fecha). Soporta industriales (2D) y bancos (2F) automáticamente. Con `include_raw=True` agrega una segunda hoja con las cuentas adicionales que SMV publica.

### Exportar a CSV (sin dependencias externas)

```python
from smv_peru import fetch_eeff, to_csv
datos = fetch_eeff("ALICORC1", desde=2019, hasta=2024)
to_csv(datos, "alicorp_2019_2024.csv", ticker="ALICORC1")
```

Solo usa `csv` de stdlib. Universal: abre en Excel, Numbers, Google Sheets, scripts. Soporta single y multi-empresa.

## Ejemplos de uso

Casos típicos de análisis financiero con la librería.

### Descargar un sector entero a Excel

```python
from smv_peru import fetch_multi, to_excel

# Las 3 cementeras del catálogo, anual 2020-2024
cementeras = fetch_multi(
    ["CPACASC1", "UNACEMC1", "YURAC1"],
    desde=2020, hasta=2024,
    periodicidad="anual",
)
to_excel(cementeras, "cementeras_2020_2024.xlsx")
```

El Excel resultante tiene una hoja por cementera con secciones P&L, Balance, Cash Flow y métricas en 7 categorías. El header de cada hoja muestra el nombre amigable de la empresa automáticamente (auto-detectado desde `info["ticker"]`).

### Comparar bancos peruanos

```python
from smv_peru import fetch_multi, to_excel

bancos = fetch_multi(
    ["BBVAC1", "CREDITC1", "INTERBC1", "SCOTIAC1"],
    desde=2020, hasta=2024,
    periodicidad="anual",
)
to_excel(bancos, "bancos_peruanos.xlsx")
```

Cada hoja trae métricas bancarias específicas (NIM, NPL, ROE, ROA, eficiencia operativa, costo del riesgo) ya calculadas con promedios usando `Monto2`.

### Tendencia anual de payout_ratio

```python
from smv_peru import fetch_eeff

# Pide 1 año extra atrás para que el primer payout se calcule (necesita T-1)
datos = fetch_eeff("ALICORC1", desde=2019, hasta=2024, periodicidad="anual")

print(f"{'Año':<6} {'Net Income':>15} {'Dividendos':>15} {'Payout':>8}")
for p in datos["periods"]:
    ni = p['net_income']
    div = p.get('dividends_paid')
    payout = p['payout_ratio']
    payout_str = f"{payout:.1%}" if payout is not None else "—"
    print(f"{p['fiscal_year']:<6} {ni:>15,.0f} "
          f"{(div or 0):>15,.0f} {payout_str:>8}")
```

El año 2019 mostrará `payout=—` porque no hay 2018 en la serie. Los siguientes sí se calculan: dividendos del año / utilidad del año anterior (convención JGA).

### Una sola empresa con LTM trimestral

```python
from smv_peru import fetch_eeff, to_excel

# Pide al menos 8 trimestres de historia para que las LTM se calculen completas
# (las métricas LTM en trimestrales necesitan 4 trimestres actuales + 4 lagged)
datos = fetch_eeff(
    "BACKUSI1", desde=2022, hasta=2024,
    periodicidad="trimestral",
)
to_excel(datos, "backus_trimestral.xlsx")
```

En el Excel resultante, los primeros trimestres mostrarán `—` en métricas LTM (ROE, debt_to_ebitda, payout, etc.) por falta de historia. Desde Q1 2024 en adelante todas las LTM están pobladas.

### Inyectar D&A externo cuando SMV no lo expone

```python
from smv_peru import fetch_eeff, set_dna, to_excel

# Alicorp publica con CF directo → SMV no expone D&A → ebitda=None
datos = fetch_eeff("ALICORC1", desde=2022, hasta=2024)

# D&A en miles de soles, desde notas a EEFF auditados
set_dna(datos, {2022: 420_000, 2023: 440_000, 2024: 460_000})

# Ahora ebitda, ebitda_margin, debt_to_ebitda están calculados
for p in datos["periods"]:
    print(f"{p['fiscal_year']}: EBITDA={p['ebitda']:,.0f}, "
          f"D/EBITDA={p['debt_to_ebitda']:.2f}x")

to_excel(datos, "alicorp_con_ebitda.xlsx")
```

### Ver los períodos faltantes (gaps de SMV)

```python
from smv_peru import fetch_eeff

# Datos hasta 2026 — al momento de la consulta, Q2-Q4 2026 aún no publicados
datos = fetch_eeff("UNACEMC1", desde=2024, hasta=2026, periodicidad="trimestral")

print(f"Pedidos: {datos['info']['periods_requested']}")
print(f"Recibidos: {datos['info']['periods_returned']}")
print(f"Faltantes: {datos['info']['periods_missing']}")
```

`periods_missing` también incluye los períodos donde se pidió Consolidado pero solo había Individual disponible (omitidos por la política de homogeneidad).

### Auditar el mapeo amigable → código SMV

```python
from smv_peru import FIELDS_TO_CODES_2D, FIELDS_TO_CODES_2F

print(f"cash (industrial): {FIELDS_TO_CODES_2D['cash']}")          # "1D0109"
print(f"cash (banco):      {FIELDS_TO_CODES_2F['cash']}")          # "1F0101"
print(f"loans_st (banco):  {FIELDS_TO_CODES_2F['loans_st']}")      # "1F0111"
```

Útil para verificar contra los PDFs auditados oficiales o el Manual SMV/CONASEV.

## Tickers soportados

La librería despacha automáticamente al esquema correcto según el ticker:
- **Esquema 2D** (industriales / NIIF estándar): Alicorp, UNACEM, Buenaventura, etc.
- **Esquema 2F** (bancos): BBVA Perú, BCP, Scotiabank Perú.

Cada período del output expone una key `"schema"` (`"2D"` o `"2F"`) para que sepas qué set de campos esperar. Algunas empresas reportan en modo **Consolidado** (matrices con subsidiarias) y otras solo en **Individual** (subsidiarias de matrices extranjeras como Cerro Verde, PLUZ Energía, Interbank).

**Política de homogeneidad C/I**: la serie devuelta nunca mezcla Consolidado con Individual. Las reglas son:

1. Si el ticker tiene Consolidado para todo el rango, se devuelve toda la serie en C.
2. Si el ticker NO aparece en Consolidado para ningún período del rango, se devuelve toda la serie en Individual (early-exit paralelizado, ~10s en cold cache).
3. Si algunos períodos tienen C y otros no (caso típico: trimestre más reciente aún sin publicar), los períodos sin C se **omiten** — no se rellenan con Individual. Aparecen en `info["periods_missing"]`.

Mezclar tipos en la misma serie distorsiona la lectura (la matriz consolidante puede tener Revenue ~10x mayor que la holding sola), por eso preferimos serie homogénea aunque sea parcial.

**Caso BBVA 2022**: cuando solo falta el Balance Consolidado anual y el Q4 Consolidado sí existe, la librería usa Q4 como sustituto del cierre anual (stock idéntico). Mantiene `tipo="consolidado"` y marca `period["balance_source"] = "Q4_consolidado"` para auditoría.

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

**Bancos y holdings financieros (esquema 2F):**

| Ticker | Empresa | Tipo |
|---|---|---|
| `BAP` | Credicorp Ltd. | Holding (matriz de BCP, Pacífico, Mibanco, Prima AFP) |
| `BBVAC1` | BBVA Perú | Banco operativo |
| `CREDITC1` | Banco de Crédito del Perú (BCP) | Banco operativo |
| `IFS` | Intercorp Financial Services | Holding (matriz de Interbank, Interseguro, Inteligo) |
| `INTERBC1` | Interbank (Banco Internacional del Perú) | Banco operativo |
| `SCOTIAC1` | Scotiabank Perú | Banco operativo |

Si el ticker no está en el catálogo, se levanta `UnknownTickerError` con la lista completa en el mensaje.

### Soporte futuro

Estas empresas son muy líquidas en BVL pero usan **otros esquemas contables** que la librería todavía no parsea:

- **Aseguradoras (esquema 2E):** Pacífico Seguros, Rímac Seguros.

Cuando se añada soporte para 2E, estos tickers entrarán al catálogo.

Por otro lado, hay empresas que cotizan en BVL pero **no publican EEFF en el endpoint SMV usado por esta librería**. En esos casos `fetch_eeff` retornaría `None`. Ejemplos detectados:

- **Southern Copper Corporation (ticker BVL: SCCO)**: matriz domiciliada en Delaware (EE.UU.), reporta a SEC americana, no a SMV peruana. Lo único en SMV es la sucursal peruana ("SOUTHERN PERU COPPER CORPORATION, SUCURSAL DEL PERU"), que **no es la entidad que cotiza**. Por eso no la incluimos en el catálogo — sería engañoso entregar datos de la sucursal cuando el usuario pide la matriz.
- **Telefónica del Perú**: deslistada de trading activo en BVL.

## Formato del output

El dict devuelto tiene dos keys: `periods` (lista de dicts, uno por período) e `info` (metadata de la consulta). Si la API no encuentra datos (ni en consolidado ni individual), retorna `None`.

### `info`: metadata de la consulta

```python
result["info"] == {
    "fetched_at": "2026-04-29T15:30:00+00:00",   # timestamp UTC ISO de la descarga
    "ticker": "ALICORC1",
    "schema": "2D",
    "tipo": "consolidado",                        # "consolidado" o "individual" (post-cascada)
    "periodicidad": "anual",
    "desde": 2021,
    "hasta": 2023,
    "periods_requested": [(2021, None), (2022, None), (2023, None)],
    "periods_returned":  [(2021, None), (2022, None), (2023, None)],
    "periods_missing":   [],                       # períodos solicitados pero sin datos en SMV
}
```

Si pides `desde=2024, hasta=2026 trimestral` y SMV solo tiene Q1 2026 publicado al momento, `periods_missing` listará `[(2026, 2), (2026, 3), (2026, 4)]` y se emite un WARNING. Útil para detectar gaps de data sin tener que comparar manualmente.

**Convenciones de unidades:**
- Montos en **miles** de la moneda reportada por la empresa. Cada período expone `period["currency"]` con código ISO (`"PEN"` soles, `"USD"` dólares). Ejemplos:
  - **Industriales y bancos** (Alicorp, BBVA, UNACEM, etc.): reportan en **PEN**.
  - **Mineras** (Buenaventura, Cerro Verde, Volcan, Minsur, Nexa): reportan en **USD** (sus ventas son commodities denominados en dólares).
- **Importante:** sumar o comparar revenue entre PEN y USD sin convertir es incorrecto. Verifica siempre `period["currency"]` antes de hacer comparativos sectoriales.
- Ratios en **decimales**, NO porcentajes. Ej. `roe = 0.14` significa 14%.
- Algunos signos siguen la convención SMV (gastos y salidas de caja vienen negativos): `cogs`, `interest_expense`, `income_tax`, `capex_ppe`, `capex_intangibles`, `debt_repaid`. Los campos derivados de "salidas" agregadas (`dividends_paid`, `interest_paid`, `taxes_paid`, `capex_total`) se exponen en valor absoluto positivo.

Cada período contiene un campo `schema` (`"2D"` o `"2F"`) y los grupos de campos correspondientes a ese esquema. **Los industriales (2D)** y **los bancos (2F)** tienen sets distintos.

### Identificadores (ambos esquemas)

| Campo | Tipo | Descripción |
|---|---|---|
| `schema` | str | `"2D"` (industriales) o `"2F"` (bancos). |
| `fiscal_year` | int | Año fiscal del período. |
| `quarter` | int \| None | `None` si es anual; `1`–`4` si es trimestral. |

### Datos trimestrales: siempre period-only

SMV publica el Cash Flow trimestral en modo **YTD acumulado** (Q1 = enero-marzo, Q2 = enero-junio, ..., Q4 = enero-diciembre). Esta librería **detecta el régimen automáticamente** y devuelve siempre datos **period-only**: para Q2-Q4 con CF YTD, descarga el trimestre anterior y resta. Para Q1 no se transforma (ya es period-only). El balance (cuentas de stock) nunca se transforma — es un saldo puntual al cierre del trimestre.

### Promedios para ROE/ROIC/ROA/NIM (uso de `Monto2`)

SMV envía en cada respuesta `Monto1` (período actual) y `Monto2` (comparativo del período anterior). Las métricas de rentabilidad usan `avg(stock) = (Monto1 + Monto2) / 2` para producir ratios anualizados estándar sin llamadas SOAP adicionales.

## Campos del esquema 2D (industriales)

### Estado de Resultados

| Campo | Descripción |
|---|---|
| `revenue` | Ingresos de actividades ordinarias. |
| `cogs` | Costo de ventas (negativo). |
| `gross_profit` | Ganancia bruta. |
| `admin_expenses`, `selling_expenses` | Gastos de administración y de ventas/distribución (negativos). |
| `other_op_income`, `other_op_expenses` | Otros ingresos/gastos operativos. |
| `operating_income` | Ganancia operativa. |
| `interest_income`, `interest_expense` | Ingresos y gastos financieros. |
| `pretax_income`, `income_tax`, `net_income` | Resultado antes de impuestos, impuesto a las ganancias y utilidad neta. |
| `eps` | Utilidad básica por acción ordinaria, en unidades base. |
| `ebitda` | `operating_income + abs(dna)` cuando la empresa publica CF indirecto. `None` si no — ver sección [EBITDA y métricas de crédito](#ebitda-y-métricas-de-crédito-esquema-2d). |

### Estado de Situación Financiera (Balance)

| Campo | Descripción |
|---|---|
| `cash`, `accounts_receivable`, `inventory` | Efectivo, cuentas por cobrar comerciales, inventarios. |
| `current_assets`, `noncurrent_assets`, `total_assets` | Subtotales y total de activos. |
| `ppe`, `intangibles` | Propiedades planta y equipo, intangibles distintos de plusvalía. |
| `accounts_payable` | Cuentas por pagar comerciales. |
| `debt_short_term`, `debt_long_term`, `total_debt` | Deuda con costo (Otros Pasivos Financieros) corriente, no corriente y total. |
| `current_liab`, `noncurrent_liab`, `total_liabilities` | Subtotales y total de pasivos. |
| `share_capital`, `retained_earnings`, `reserves`, `equity` | Capital emitido, resultados acumulados, otras reservas, patrimonio total. |

### Flujo de Efectivo (método directo)

| Campo | Descripción |
|---|---|
| `cash_from_customers` | Cobranzas a clientes (`3D0101`). |
| `cash_to_suppliers`, `cash_to_employees` | Pagos a proveedores y empleados (negativos). |
| `interest_paid_op`, `taxes_paid_op` | Intereses e impuestos pagados clasificados en operación. |
| `operating_cf` | Flujo neto de operación. |
| `ppe_proceeds`, `capex_ppe`, `capex_intangibles`, `capex_total` | Venta y compra de PP&E e intangibles. `capex_total` = `\|capex_ppe\| + \|capex_intangibles\|`. |
| `investing_cf` | Flujo neto de inversión. |
| `dividends_paid_fin`, `interest_paid_fin` | Dividendos e intereses pagados clasificados en financiación. |
| `debt_issued`, `debt_repaid` | Préstamos obtenidos y amortizados. |
| `financing_cf` | Flujo neto de financiación. |
| `end_cash` | Efectivo al cierre del ejercicio. |
| `dividends_paid`, `interest_paid`, `taxes_paid` | Salidas agregadas (positivas) sumando operación + financiación. |
| `fcf` | `operating_cf + capex_ppe + capex_intangibles` (capex viene negativo). |

### Métricas derivadas

| Campo | Fórmula |
|---|---|
| `gross_margin` | `gross_profit / revenue` |
| `operating_margin` | `operating_income / revenue` |
| `net_margin` | `net_income / revenue` |
| `current_ratio` | `current_assets / current_liab` |
| `quick_ratio` | `(cash + accounts_receivable) / current_liab` |
| `net_debt` | `total_debt - cash` |
| `interest_coverage` | `operating_income / \|interest_expense\|` |
| `effective_tax_rate` | `\|income_tax\| / pretax_income` |
| `payout_ratio` | `abs(dividends_paid_T) / net_income_(T-1)`. Convención peruana JGA — ver nota abajo. `None` para el primer período del rango si no hay T-1. |
| `capex_intensity` | `capex_total / revenue` |
| `roe` | `net_income / equity` |
| `roic` | `net_income / (equity + total_debt)` |

> **Nota sobre `payout_ratio`**: la Ley General de Sociedades del Perú exige que la JGA apruebe la distribución de dividendos sobre utilidades del **ejercicio cerrado anterior**. Por eso los dividendos pagados en T se miden contra el net income de T-1, no de T. Si pides `desde=2024 hasta=2024`, el `payout_ratio` de 2024 será `None` (no hay 2023 en la serie); si pides `desde=2023 hasta=2024`, sí se calcula. Para trimestrales LTM la convención se mantiene: el denominador es la suma de los 4 trimestres que terminan 4Q antes de T.

### EBITDA y métricas de crédito (esquema 2D)

SMV publica D&A (Depreciación, Amortización y Agotamiento) **solo cuando la empresa elige método indirecto** para su Estado de Flujos de Efectivo. La práctica peruana es mixta: algunas empresas (Backus, Cerro Verde, Cementos Pacasmayo, AENZA, Nexa, PLUZ) usan método indirecto; la mayoría usa método directo.

| Campo | Notas |
|---|---|
| `dna` | D&A real desde SMV (cuenta `3D0602`). `None` si la empresa publica con método directo. |
| `ebitda` | `operating_income + abs(dna)`. **`None` si `dna` no está disponible** — la librería NO usa proxy para no inducir errores en análisis de crédito. |
| `ebitda_margin` | `ebitda / revenue`. `None` si `ebitda` es `None`. |
| `debt_to_ebitda` | `total_debt / ebitda`. Ratio de apalancamiento bruto. |
| `net_debt_to_ebitda` | `net_debt / ebitda`. Apalancamiento neto. |
| `interest_coverage_ebitda` | `ebitda / abs(interest_expense)`. Cobertura de intereses con EBITDA. |

Para empresas con método directo (sin D&A en SMV), el analista puede proveer D&A manualmente desde **notas a los EEFF auditados** (memoria anual, reportes trimestrales) usando ``set_dna()`` y la librería recalcula EBITDA y todas las métricas dependientes.

> **Nota sobre estimación automática:** evaluamos estimar D&A automáticamente vía la identidad contable `D&A ≈ PPE_inicio + Capex − PPE_cierre`. La aproximación da error <10% en industriales (consumo, cementos, energía) pero **falla feo en mineras** (errores hasta ±140% por activos de exploración, desarrollo de minas, costos de remoción que no quedan en la cuenta PP&E estándar). Como las mineras son ~30% del catálogo y el análisis crediticio es donde más importa la precisión, **decidimos no implementar la estimación automática**. La solución correcta para D&A precisa de toda empresa es parsear las notas a los EEFF auditados (donde está siempre explícita) — eso queda como roadmap para v0.2+.

```python
from smv_peru import fetch_eeff, set_dna

datos = fetch_eeff("ALICORC1", desde=2022, hasta=2024)
# datos["periods"][i]["ebitda"] == None (Alicorp usa método directo)

# Provee D&A externo (en miles de soles, desde notas a EEFF auditados):
set_dna(datos, {2022: 420_000, 2023: 440_000, 2024: 460_000})
# Ahora ebitda, ebitda_margin, debt_to_ebitda, etc. están calculados.
```

`set_dna` acepta también un float único (se aplica a todos los períodos del result) o un dict por `(año, quarter)` para datos trimestrales.

### Métricas YoY (Year-over-Year)

| Campo | Descripción |
|---|---|
| `revenue_yoy` | Crecimiento de ingresos vs. año anterior. |
| `net_income_yoy` | Crecimiento de utilidad neta. |
| `equity_yoy` | Crecimiento de patrimonio. |

## Campos del esquema 2F (bancos)

### Estado de Resultados (P&L bancario)

| Campo | Descripción |
|---|---|
| `interest_income` | Ingresos por intereses. |
| `interest_expense` | Gastos por intereses (negativo). |
| `net_interest_income` | "MARGEN BRUTO" oficial SMV: ingresos operacionales totales − costos operacionales totales. **Para holdings con seguros** (BAP, IFS) **incluye primas y siniestros**; **para Scotiabank** incluye otros ingresos/costos de operación. Para bancos puros (BBVA, BCP) coincide con `nii_pure`. |
| `nii_pure` | Net Interest Income puro = `interest_income + interest_expense`. Margen financiero del negocio bancario core, comparable apples-to-apples entre bancos. Para holdings difiere de `net_interest_income`. |
| `loan_loss_provisions` | Provisión para créditos (negativo). |
| `fee_income_net` | Comisiones netas. |
| `trading_income` | Resultado por operaciones financieras (ROF). |
| `operating_expenses` | Gastos de administración (negativo). |
| `operating_income`, `pretax_income`, `income_tax`, `net_income` | Resultados de operación, antes de impuestos, impuesto y utilidad neta. |
| `eps`, `eps_diluted` | Utilidad por acción básica y diluida. |

### Balance bancario

| Campo | Descripción |
|---|---|
| `cash` | Disponibles (caja + BCRP). |
| `interbank_funds` | Fondos interbancarios (activo). |
| `investments_fvtpl`, `investments_afs`, `investments_htm` | Inversiones por categoría contable. |
| `loans_st`, `loans_lt`, `loans_net` | Cartera de créditos neto: corriente, no corriente y total. |
| `performing_loans`, `refinanced_loans`, `overdue_loans`, `judicial_loans` | Componentes brutos de cartera (vigentes, refinanciados, vencidos, judicial). |
| `gross_loans` | Cartera bruta = suma de los 4 componentes anteriores. |
| `ppe`, `intangibles`, `total_assets` | Activos físicos, intangibles y total. |
| `deposits` | Obligaciones con el público (depósitos). |
| `interbank_funds_payable` | Fondos interbancarios (pasivo). |
| `deposits_financial_system` | Depósitos de empresas del sistema financiero. |
| `financial_debt_st`, `financial_debt_lt`, `total_liabilities` | Deuda financiera y total pasivos. |
| `share_capital`, `reserves`, `retained_earnings`, `equity` | Patrimonio. |

### Flujo de Efectivo bancario (método indirecto)

| Campo | Descripción |
|---|---|
| `dna` | Depreciación y amortización. |
| `operating_cf`, `investing_cf`, `financing_cf` | Flujos por actividad. |
| `deposits_change` | Aumento/disminución neto de depósitos en el período. |
| `loans_change` | Cambio neto en cartera de créditos. |
| `dividends_paid_fin` | Dividendos pagados (negativo). |
| `dividends_paid` | Lo anterior, expuesto en valor absoluto positivo. |
| `end_cash` | Efectivo al cierre. |

### Métricas derivadas bancarias

| Campo | Fórmula | Notas |
|---|---|---|
| `nim` | `net_interest_income / avg(loans_net)` | Net Interest Margin (anualizado). Usa promedio con `Monto2`. |
| `efficiency_ratio` | `\|operating_expenses\| / (NII + fee_income_net + trading_income)` | Eficiencia operativa. |
| `npl_ratio` | `(overdue_loans + judicial_loans) / loans_net` | Proxy razonable (cercano al real con tolerancia ~0.1pp). |
| `loan_to_deposit_ratio` | `loans_net / deposits` | Apalancamiento del banco. |
| `equity_to_assets` | `equity / total_assets` | Proxy de solvencia (no es CET1 regulatorio). |
| `effective_tax_rate` | `\|income_tax\| / pretax_income` | Tasa efectiva de impuestos. |
| `cost_of_risk` | `\|loan_loss_provisions\| / avg(loans_net)` | Costo del riesgo crediticio. |
| `roa` | `net_income / avg(total_assets)` | Anualizado. |
| `roe` | `net_income / avg(equity)` | Anualizado. |
| `payout_ratio` | `abs(dividends_paid_T) / net_income_(T-1)` | Convención JGA peruana, igual que en 2D. |
| `interest_income_yoy`, `net_income_yoy`, `loans_yoy`, `deposits_yoy`, `equity_yoy` | crecimiento YoY | Calculados con `Monto2`. |

### Limitaciones del esquema 2F

- **CET1 / capital regulatorio**: no calculable desde SMV (requiere RWA — Activos Ponderados por Riesgo, que no expone). Ver SBS para datos regulatorios. Mientras tanto, `equity_to_assets` sirve como proxy de solvencia.
- **Cobertura de provisiones**: SMV expone "cartera neta" pero no el stock acumulado de provisiones específicas para créditos incobrables (está embebido). No se puede calcular `coverage_ratio` desde este endpoint.
- **`loans_net` se compone**: SMV publica la cartera dividida en corriente (`1F0111`) y no corriente (`1F1902`). La librería las suma para exponer `loans_net` como total fiel al PDF auditado.

### `raw_accounts`: cuentas adicionales no expuestas como amigables

Cada período expone también un dict `raw_accounts` con todas las cuentas que SMV publica y que **no** están cubiertas por un campo amigable (ni con monto cero), usando el `DescripcionCuenta` oficial de SMV:

```python
period["raw_accounts"] == {
    "2D0410": {"nombre": "Diferencias de Cambio Neto",          "monto": 84504.0},
    "1D0114": {"nombre": "Otros Activos Financieros",           "monto": 78224.0},
    "3D0322": {"nombre": "Pasivos por Arrendamiento Financiero","monto": -94535.0},
    # ... ~60 cuentas adicionales en Alicorp 2023
}
```

Esto permite acceder a cuentas raras o sectoriales sin esperar a que la librería las exponga, y deja la puerta abierta a empresas con esquemas distintos (bancos, aseguradoras) cuando los soportemos.

### Auditar el mapeo amigable → código SMV

Cada esquema tiene su propio mapeo:

```python
from smv_peru import FIELDS_TO_CODES_2D, FIELDS_TO_CODES_2F

FIELDS_TO_CODES_2D["cash"]          # "1D0109"  → Efectivo y Equivalentes al Efectivo (industrial)
FIELDS_TO_CODES_2F["cash"]          # "1F0101"  → Disponibles (banco)
FIELDS_TO_CODES_2F["loans_st"]      # "1F0111"  → Cartera de créditos neto (corriente)
```

`FIELDS_TO_CODES` (sin sufijo) es alias de `FIELDS_TO_CODES_2D` por compatibilidad.

Los **derivados** (márgenes, ratios, NIM, NPL, etc.) no están en estos dicts porque se calculan desde otros campos. Sus fórmulas están documentadas en las tablas de "Métricas derivadas" arriba.

## Desarrollo

Este proyecto usa [uv](https://github.com/astral-sh/uv) como gestor de entornos y dependencias.

```bash
uv sync                              # crea el venv e instala el paquete editable
uv run pytest                        # corre los 192 tests con fixtures sintéticos
uv run python                        # entra a un REPL con el paquete disponible
uv run python examples/demo.py       # corre el demo (descarga datos reales)
uv run python scripts/smoke_test.py  # smoke test multi-empresa contra SMV real
```

El [demo](examples/demo.py) muestra los principales casos de uso: descarga anual y trimestral, esquemas 2D y 2F, métricas derivadas, `raw_accounts`, YoY growth y auditoría del mapeo amigable → código SMV.

El [smoke test](scripts/smoke_test.py) ejercita los 27 tickers del catálogo contra el web service real para detectar regresiones que los unitarios con fixtures no pillan. Útil antes de cada release. Cold cache ~5 min, warm <30 s.

## Roadmap

- [x] Estructura inicial de la librería.
- [x] API pública documentada con docstrings.
- [x] Tests unitarios y de integración con fixtures (192 verdes en ~0.3 s).
- [x] Cache configurable (parámetro, env var, o user cache dir del SO).
- [x] Soporte para periodicidad anual y trimestral.
- [x] Selección explícita de estados consolidados o individuales + política de homogeneidad.
- [x] Catálogo de tickers BVL → SMV (27 tickers).
- [x] Cuentas extendidas (~95 campos amigables 2D, 50+ 2F) + métricas derivadas en 7 categorías + `raw_accounts` para cuentas no expuestas.
- [x] Soporte para esquema 2F (bancos: BAP, BBVAC1, CREDITC1, IFS, INTERBC1, SCOTIAC1).
- [x] LTM (Last Twelve Months) automáticas en trimestrales.
- [x] `payout_ratio` con lag T-1 (convención JGA peruana).
- [x] Hardening de seguridad (TLS, formula injection, validación de inputs).
- [x] Smoke test multi-empresa (`scripts/smoke_test.py`).
- [ ] Repo en GitHub público + GitHub Actions (CI).
- [ ] Publicar `0.1.0` en PyPI.
- [ ] (0.2+) Soporte para esquema 2E (aseguradoras: Pacífico, Rímac).
- [ ] (Más adelante) API web HTTP encima de esta librería, como módulo opcional.

## Disclaimer

Este proyecto **no es oficial**. No tiene afiliación, endorsement ni relación con la Superintendencia del Mercado de Valores del Perú (SMV) ni con la Bolsa de Valores de Lima (BVL).

Los datos provienen del portal público de datos abiertos de SMV; esta librería es un cliente que los reformatea. **No se garantiza la exactitud, completitud ni puntualidad de los datos** — pueden contener errores, estar desactualizados, o cambiar de formato sin aviso.

Esta librería se provee con **fines informativos y educativos**. **No constituye recomendación de inversión, asesoría financiera, análisis profesional ni opinión sobre la conveniencia de instrumentos financieros.** Cualquier decisión de inversión basada en los datos provistos es responsabilidad exclusiva del usuario.

## Licencias

- **Código:** MIT (ver `LICENSE`).
- **Datos:** los datos provienen de la SMV Perú. Esta librería es un cliente que reformatea esos datos; la atribución a la fuente es obligatoria al redistribuirlos.
