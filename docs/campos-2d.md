# Campos del esquema 2D (industriales)

Referencia completa de los campos amigables que la librería expone para empresas industriales bajo NIIF (21 tickers del catálogo: Alicorp, UNACEM, Buenaventura, Backus, Cementos Pacasmayo, etc.).

Para conceptos como "qué es 2D", política Consolidado/Individual, convenciones de signos y unidades, y `raw_accounts`, ver [conceptos.md](conceptos.md).

## Estado de Resultados

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
| `ebitda` | `operating_income + abs(dna)` cuando la empresa publica CF indirecto. `None` si no — ver [EBITDA y métricas de crédito](#ebitda-y-métricas-de-crédito). |

## Estado de Situación Financiera (Balance)

| Campo | Descripción |
|---|---|
| `cash`, `accounts_receivable`, `inventory` | Efectivo, cuentas por cobrar comerciales, inventarios. |
| `current_assets`, `noncurrent_assets`, `total_assets` | Subtotales y total de activos. |
| `ppe`, `intangibles` | Propiedades planta y equipo, intangibles distintos de plusvalía. |
| `accounts_payable` | Cuentas por pagar comerciales. |
| `debt_short_term`, `debt_long_term`, `total_debt` | Deuda con costo (Otros Pasivos Financieros) corriente, no corriente y total. |
| `current_liab`, `noncurrent_liab`, `total_liabilities` | Subtotales y total de pasivos. |
| `share_capital`, `retained_earnings`, `reserves`, `equity` | Capital emitido, resultados acumulados, otras reservas, patrimonio total. |

## Flujo de Efectivo (método directo)

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

## Métricas derivadas

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
| `payout_ratio` | `abs(dividends_paid_T) / net_income_(T-1)`. Convención peruana JGA. `None` para el primer período del rango si no hay T-1. |
| `capex_intensity` | `capex_total / revenue` |
| `roe` | `net_income / equity` |
| `roic` | `net_income / (equity + total_debt)` |

> [!NOTE]
> Sobre `payout_ratio` con lag T-1, ver [conceptos.md → payout_ratio con lag T-1](conceptos.md#payout_ratio-con-lag-t-1).

## EBITDA y métricas de crédito

SMV publica D&A solo cuando la empresa elige método indirecto. Para empresas con método directo, los campos siguientes salen `None` hasta que el analista provea D&A externo con `set_dna()` — ver [conceptos.md → EBITDA y D&A](conceptos.md#ebitda-y-da).

| Campo | Notas |
|---|---|
| `dna` | D&A real desde SMV (cuenta `3D0602`). `None` si la empresa publica con método directo. |
| `ebitda` | `operating_income + abs(dna)`. **`None` si `dna` no está disponible** — la librería NO usa proxy para no inducir errores en análisis de crédito. |
| `ebitda_margin` | `ebitda / revenue`. `None` si `ebitda` es `None`. |
| `debt_to_ebitda` | `total_debt / ebitda`. Apalancamiento bruto. |
| `net_debt_to_ebitda` | `net_debt / ebitda`. Apalancamiento neto. |
| `interest_coverage_ebitda` | `ebitda / abs(interest_expense)`. Cobertura de intereses con EBITDA. |

## Métricas YoY (Year-over-Year)

| Campo | Descripción |
|---|---|
| `revenue_yoy` | Crecimiento de ingresos vs. año anterior. |
| `net_income_yoy` | Crecimiento de utilidad neta. |
| `equity_yoy` | Crecimiento de patrimonio. |

Calculados con `Monto2` que SMV envía en cada respuesta — sin descargas extra.
