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

Por ahora la librería soporta empresas que reportan a SMV con esquema contable **2D** (industriales, NIIF estándar). Algunas reportan en modo **Consolidado** (matrices con subsidiarias) y otras solo en **Individual** (subsidiarias de matrices extranjeras como Cerro Verde, PLUZ Energía, Nexa). La librería prueba primero Consolidado y cae automáticamente a Individual si no hay datos, así que no necesitas preocuparte por la diferencia al consumir la API.

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
| `RELAPAC1` | Refinería La Pampilla | refinación de petróleo |
| `UNACEMC1` | UNACEM | cementos |
| `VOLCABC1` | Volcan Compañía Minera | minería polimetálica |
| `YURAC1` | Yura | cementos |

Si el ticker no está en el catálogo, se levanta `UnknownTickerError` con la lista completa en el mensaje.

### Soporte futuro

Estas empresas son muy líquidas en BVL pero usan **otros esquemas contables** que la librería todavía no parsea:

- **Bancos (esquema 2F):** Credicorp / BCP, BBVA Perú, Interbank, Scotiabank Perú.
- **Aseguradoras (esquema 2E):** Pacífico Seguros, Rímac Seguros.

Cuando se añada soporte para 2F y 2E, estos tickers entrarán al catálogo. Mientras tanto, intentar usarlos no funcionaría aunque estuvieran listados — por eso quedan fuera por ahora.

Por otro lado, hay empresas que cotizan en BVL pero **no publican EEFF en el endpoint SMV usado por esta librería** (ya sea porque su matriz consolidante reporta en otro país o por régimen especial). En esos casos `fetch_estados_financieros` retornaría `None`. Ejemplos detectados: Telefónica del Perú (deslistada de trading activo), Southern Copper (ADR sin EEFF en SMV).

## Formato del output

El dict devuelto tiene dos keys: `periods` (lista de dicts, uno por período) e `info` (reservado para metadata futura). Si la API no encuentra datos (ni en consolidado ni individual), retorna `None`.

**Convenciones de unidades:**
- Montos en **miles** de la moneda reportada por la empresa (típicamente soles). Ej. `revenue = 13_655_764` ≈ S/. 13.66 mil millones.
- Ratios en **decimales**, NO porcentajes. Ej. `roe = 0.14` significa 14%.
- Algunos signos siguen la convención SMV (gastos y salidas de caja vienen negativos): `cogs`, `interest_expense`, `income_tax`, `capex_ppe`, `capex_intangibles`, `debt_repaid`. Los campos derivados de "salidas" agregadas (`dividends_paid`, `interest_paid`, `taxes_paid`, `capex_total`) se exponen en valor absoluto positivo.

Cada período contiene los siguientes grupos de campos:

### Identificadores

| Campo | Tipo | Descripción |
|---|---|---|
| `fiscal_year` | int | Año fiscal del período. |
| `quarter` | int \| None | `None` si es anual; `1`–`4` si es trimestral. |

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

Cada campo amigable con origen 1:1 en SMV está en `FIELDS_TO_CODES`:

```python
from smv_peru import FIELDS_TO_CODES

FIELDS_TO_CODES["cash"]          # "1D0109"  → Efectivo y Equivalentes al Efectivo
FIELDS_TO_CODES["gross_profit"]  # "2D02ST"  → Ganancia (Pérdida) Bruta
FIELDS_TO_CODES["dividends_paid_fin"]  # "3D0305"  → Dividendos Pagados
```

Los **derivados** (márgenes, ratios, totales agregados) no están en `FIELDS_TO_CODES` porque se calculan desde otros campos. Su fórmula está documentada en la tabla de "Métricas derivadas" arriba.

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
