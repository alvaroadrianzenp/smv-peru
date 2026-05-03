# Campos del esquema 2F (bancos)

Referencia completa de los campos amigables que la librería expone para bancos y holdings financieros (6 tickers del catálogo: BAP, BBVAC1, CREDITC1, IFS, INTERBC1, SCOTIAC1).

Para conceptos como "qué es 2F", política Consolidado/Individual, convenciones de signos y unidades, y `raw_accounts`, ver [conceptos.md](conceptos.md).

## Estado de Resultados (P&L bancario)

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

## Balance bancario

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

## Flujo de Efectivo bancario (método indirecto)

| Campo | Descripción |
|---|---|
| `dna` | Depreciación y amortización. |
| `operating_cf`, `investing_cf`, `financing_cf` | Flujos por actividad. |
| `deposits_change` | Aumento/disminución neto de depósitos en el período. |
| `loans_change` | Cambio neto en cartera de créditos. |
| `dividends_paid_fin` | Dividendos pagados (negativo). |
| `dividends_paid` | Lo anterior, expuesto en valor absoluto positivo. |
| `end_cash` | Efectivo al cierre. |

## Métricas derivadas bancarias

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

## Limitaciones del esquema 2F

- **CET1 / capital regulatorio**: no calculable desde SMV (requiere RWA — Activos Ponderados por Riesgo, que no expone). Ver SBS para datos regulatorios. Mientras tanto, `equity_to_assets` sirve como proxy de solvencia.
- **Cobertura de provisiones**: SMV expone "cartera neta" pero no el stock acumulado de provisiones específicas para créditos incobrables (está embebido). No se puede calcular `coverage_ratio` desde este endpoint.
- **`loans_net` se compone**: SMV publica la cartera dividida en corriente (`1F0111`) y no corriente (`1F1902`). La librería las suma para exponer `loans_net` como total fiel al PDF auditado.
