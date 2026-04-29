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

## Tickers soportados

La librería despacha automáticamente al esquema correcto según el ticker:
- **Esquema 2D** (industriales / NIIF estándar): Alicorp, UNACEM, Buenaventura, etc.
- **Esquema 2F** (bancos): BBVA Perú, BCP, Scotiabank Perú.

Cada período del output expone una key `"schema"` (`"2D"` o `"2F"`) para que sepas qué set de campos esperar. Algunas empresas reportan en modo **Consolidado** (matrices con subsidiarias) y otras solo en **Individual** (subsidiarias de matrices extranjeras como Cerro Verde, PLUZ Energía, Nexa). La librería prueba primero Consolidado y cae automáticamente a Individual si no hay datos.

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
| `SCCO` | Southern Peru Copper Corporation (Sucursal) | minería de cobre |
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

Por otro lado, hay empresas que cotizan en BVL pero **no publican EEFF en el endpoint SMV usado por esta librería** (ya sea porque su matriz consolidante reporta en otro país o por régimen especial). En esos casos `fetch_estados_financieros` retornaría `None`. Ejemplos detectados: Telefónica del Perú (deslistada de trading activo), Southern Copper (ADR sin EEFF en SMV).

## Formato del output

El dict devuelto tiene dos keys: `periods` (lista de dicts, uno por período) e `info` (reservado para metadata futura). Si la API no encuentra datos (ni en consolidado ni individual), retorna `None`.

**Convenciones de unidades:**
- Montos en **miles** de la moneda reportada por la empresa (típicamente soles). Ej. `revenue = 13_655_764` ≈ S/. 13.66 mil millones.
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
| `ebitda` | Aproximado a `operating_income` (D&A no expuesto por la API SMV). |

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
| `payout_ratio` | `dividends_paid / net_income` |
| `capex_intensity` | `capex_total / revenue` |
| `roe` | `net_income / equity` |
| `roic` | `net_income / (equity + total_debt)` |

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
| `net_interest_income` | NII = ingresos − gastos por intereses (margen bruto). |
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
| `payout_ratio` | `dividends_paid / net_income` | |
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
uv sync                          # crea el venv e instala el paquete editable
uv run pytest                    # corre los tests
uv run python                    # entra a un REPL con el paquete disponible
uv run python examples/demo.py   # corre el demo (descarga datos reales)
```

El [demo](examples/demo.py) muestra los principales casos de uso: descarga anual y trimestral, esquemas 2D y 2F, métricas derivadas, `raw_accounts`, YoY growth y auditoría del mapeo amigable → código SMV.

## Roadmap

- [x] Estructura inicial de la librería.
- [x] API pública documentada con docstrings.
- [x] Tests unitarios y de integración con fixtures.
- [x] Cache configurable (parámetro, env var, o user cache dir del SO).
- [x] Soporte para periodicidad anual y trimestral.
- [x] Selección explícita de estados consolidados o individuales.
- [x] Catálogo de tickers BVL → SMV.
- [x] Cuentas extendidas (~50 campos amigables) + métricas derivadas (márgenes, ratios) + `raw_accounts` para cuentas no expuestas.
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
