# Conceptos clave

Esta página centraliza los conceptos que necesitas conocer para usar la librería con confianza. Si vienes del [README](../README.md), aquí encontrás el porqué de cada decisión técnica.

## Esquemas contables: 2D vs 2F

SMV publica los estados financieros con códigos de cuenta distintos según el tipo de empresa:

- **2D** — empresas industriales bajo NIIF (21 tickers en el catálogo: Alicorp, UNACEM, Buenaventura, etc.).
- **2F** — bancos y holdings financieros (6 tickers: BBVA, BCP, IFS, etc.).
- **2E** — aseguradoras (no soportado todavía; previsto para 0.2+).

Cada `period` del output expone una key `"schema"` (`"2D"` o `"2F"`) para que sepas qué set de campos esperar. La librería despacha automáticamente al esquema correcto según el ticker.

## Consolidado vs Individual

Algunas empresas reportan en modo **Consolidado** (matrices con subsidiarias) y otras solo en **Individual** (subsidiarias de matrices extranjeras como Cerro Verde, PLUZ Energía, Interbank).

### Política de homogeneidad C/I

La serie devuelta **nunca mezcla Consolidado con Individual**. Las reglas son:

1. Si el ticker tiene Consolidado para todo el rango, se devuelve toda la serie en C.
2. Si el ticker NO aparece en Consolidado para ningún período del rango, se devuelve toda la serie en Individual (early-exit paralelizado, ~10s en cold cache).
3. Si algunos períodos tienen C y otros no (caso típico: trimestre más reciente aún sin publicar), los períodos sin C se **omiten** — no se rellenan con Individual. Aparecen en `info["periods_missing"]`.

Mezclar tipos en la misma serie distorsiona la lectura (la matriz consolidante puede tener Revenue ~10x mayor que la holding sola), por eso preferimos serie homogénea aunque sea parcial.

### Caso BBVA 2022

Cuando solo falta el Balance Consolidado anual y el Q4 Consolidado sí existe, la librería usa Q4 como sustituto del cierre anual (stock idéntico). Mantiene `tipo="consolidado"` y marca `period["balance_source"] = "Q4_consolidado"` para auditoría.

## Convenciones

### Montos en miles

Todos los montos están en **miles** de la moneda reportada por la empresa. Cada período expone `period["currency"]` con código ISO (`"PEN"` soles, `"USD"` dólares):

- **Industriales y bancos** (Alicorp, BBVA, UNACEM, etc.): reportan en **PEN**.
- **Mineras** (Buenaventura, Cerro Verde, Volcan, Minsur, Nexa): reportan en **USD** (sus ventas son commodities denominados en dólares).

> [!IMPORTANT]
> Sumar o comparar revenue entre PEN y USD sin convertir es incorrecto. Verifica siempre `period["currency"]` antes de hacer comparativos sectoriales.

### Ratios en decimales

Los ratios se expresan en decimales, **no porcentajes**. Ej: `roe = 0.14` significa 14%.

### Signos por convención SMV

Algunos campos siguen la convención SMV (gastos y salidas de caja vienen negativos):

- Negativos: `cogs`, `interest_expense`, `income_tax`, `capex_ppe`, `capex_intangibles`, `debt_repaid`.
- Positivos (agregados de "salidas"): `dividends_paid`, `interest_paid`, `taxes_paid`, `capex_total`.

## Datos trimestrales: siempre period-only

SMV publica el Cash Flow trimestral en modo **YTD acumulado** (Q1 = enero-marzo, Q2 = enero-junio, ..., Q4 = enero-diciembre). La librería **detecta el régimen automáticamente** y devuelve siempre datos **period-only**:

- Para Q2-Q4 con CF YTD, descarga el trimestre anterior y resta.
- Para Q1 no se transforma (ya es period-only).
- El balance (cuentas de stock) nunca se transforma — es un saldo puntual al cierre del trimestre.

## Promedios para ROE/ROIC/ROA/NIM (uso de `Monto2`)

SMV envía en cada respuesta `Monto1` (período actual) y `Monto2` (comparativo del período anterior). Las métricas de rentabilidad usan `avg(stock) = (Monto1 + Monto2) / 2` para producir ratios anualizados estándar sin llamadas SOAP adicionales.

## LTM (Last Twelve Months) en trimestrales

En trimestrales, las métricas que mezclan flujo y stock se calculan como **LTM**: el numerador es la suma móvil de 4 trimestres y el denominador es el promedio del stock al inicio y al final de esa ventana.

Métricas LTM en 2D: `roe`, `roic`, `roa`, `interest_coverage`, `interest_coverage_ebitda`, `debt_to_ebitda`, `net_debt_to_ebitda`, `payout_ratio`, `capex_intensity`, `cfo_to_debt`, `fcf_to_debt`, etc.

Métricas LTM en 2F: `nim`, `cost_of_risk`, `roa`, `roe`, `payout_ratio`.

> [!NOTE]
> Las LTM necesitan al menos 4 trimestres de historia. Si pides un rango muy corto, los primeros trimestres mostrarán `None` en métricas LTM. Para `payout_ratio` LTM se necesitan **8** trimestres (4 actuales + 4 lagged).

## `payout_ratio` con lag T-1

La Ley General de Sociedades del Perú exige que la **Junta General de Accionistas (JGA)** apruebe la distribución de dividendos sobre las **utilidades del ejercicio cerrado anterior**. Por eso:

- En anuales: `payout_T = abs(dividends_paid_T) / net_income_(T-1)`.
- En trimestrales LTM: el denominador es la suma de los 4 trimestres que terminan **4Q antes** de T.

Si pides `desde=2024 hasta=2024`, el `payout_ratio` de 2024 será `None` (no hay 2023 en la serie). Si pides `desde=2023 hasta=2024`, sí se calcula.

## EBITDA y D&A

SMV publica D&A (Depreciación, Amortización y Agotamiento) **solo cuando la empresa elige método indirecto** para su Estado de Flujos de Efectivo. La práctica peruana es mixta:

- **Con método indirecto** (D&A disponible): Backus, Cerro Verde, Cementos Pacasmayo, AENZA, Nexa, PLUZ.
- **Con método directo** (D&A no expuesto en SMV): la mayoría restante.

Cuando la empresa publica con método directo, `ebitda` viene como `None` para no inducir errores en análisis de crédito. Las métricas dependientes (`ebitda_margin`, `debt_to_ebitda`, `net_debt_to_ebitda`, `interest_coverage_ebitda`) también quedan en `None`.

Para llenarlo, usa `set_dna()` con datos desde notas a EEFF auditados:

```python
from smv_peru import fetch_eeff, set_dna

datos = fetch_eeff("ALICORC1", desde=2022, hasta=2024)
set_dna(datos, {2022: 420_000, 2023: 440_000, 2024: 460_000})
# Ahora ebitda, ebitda_margin, debt_to_ebitda están calculados
```

`set_dna` acepta también un float único (se aplica a todos los períodos) o un dict por `(año, quarter)` para datos trimestrales.

> [!NOTE]
> Evaluamos estimar D&A automáticamente vía la identidad contable
> `D&A ≈ PPE_inicio + Capex − PPE_cierre`. Funciona en industriales (error <10%)
> pero falla en mineras (errores hasta ±140%). Por eso no estimamos
> automáticamente — la solución correcta es parsear notas auditadas, lo cual
> queda como roadmap para v0.2+.

## Estructura del output

`fetch_eeff` retorna un dict con dos keys: `periods` (lista de dicts, uno por período) e `info` (metadata). Si no hay datos, retorna `None`.

### `info`

```python
result["info"] == {
    "fetched_at": "2026-04-29T15:30:00+00:00",
    "ticker": "ALICORC1",
    "schema": "2D",
    "tipo": "consolidado",
    "periodicidad": "anual",
    "desde": 2021,
    "hasta": 2023,
    "periods_requested": [(2021, None), (2022, None), (2023, None)],
    "periods_returned":  [(2021, None), (2022, None), (2023, None)],
    "periods_missing":   [],
}
```

`periods_missing` lista los períodos pedidos pero no devueltos (por gaps de SMV o por la política de homogeneidad C/I).

### `period`

Cada elemento de `periods` es un dict con identificadores comunes y campos específicos del esquema:

| Campo | Tipo | Descripción |
|---|---|---|
| `schema` | str | `"2D"` o `"2F"`. |
| `fiscal_year` | int | Año fiscal del período. |
| `quarter` | int \| None | `None` si es anual; `1`–`4` si es trimestral. |
| `tipo` | str | `"consolidado"` o `"individual"` (post-cascada). |
| `currency` | str | `"PEN"` o `"USD"`. |
| `balance_source` | str (opcional) | `"Q4_consolidado"` cuando se usa Q4 como sustituto del Anual. |
| `cf_method` | str | `"directo"` o `"indirecto"`. |
| `raw_accounts` | dict | Cuentas adicionales no expuestas como amigables. |

Los campos amigables específicos de cada esquema están documentados en:

- [Campos del esquema 2D (industriales)](campos-2d.md)
- [Campos del esquema 2F (bancos)](campos-2f.md)

## `raw_accounts`: cuentas adicionales

Aplica a **ambos esquemas**. Cada período expone también un dict `raw_accounts` con todas las cuentas que SMV publica y que **no** están cubiertas por un campo amigable (excluye montos cero), usando el `DescripcionCuenta` oficial de SMV:

```python
period["raw_accounts"] == {
    "2D0410": {"nombre": "Diferencias de Cambio Neto",          "monto": 84504.0},
    "1D0114": {"nombre": "Otros Activos Financieros",           "monto": 78224.0},
    "3D0322": {"nombre": "Pasivos por Arrendamiento Financiero","monto": -94535.0},
    # ... ~60 cuentas adicionales en Alicorp 2023
}
```

Esto permite acceder a cuentas raras o sectoriales sin esperar a que la librería las exponga.

## Auditar el mapeo amigable → código SMV

Cada esquema tiene su propio mapeo expuesto:

```python
from smv_peru import FIELDS_TO_CODES_2D, FIELDS_TO_CODES_2F

FIELDS_TO_CODES_2D["cash"]      # "1D0109"  → Efectivo y Equivalentes (industrial)
FIELDS_TO_CODES_2F["cash"]      # "1F0101"  → Disponibles (banco)
FIELDS_TO_CODES_2F["loans_st"]  # "1F0111"  → Cartera de créditos neto (corriente)
```

`FIELDS_TO_CODES` (sin sufijo) es alias de `FIELDS_TO_CODES_2D` por compatibilidad.

> [!NOTE]
> Los **derivados** (márgenes, ratios, NIM, NPL, etc.) no están en estos dicts
> porque se calculan desde otros campos. Sus fórmulas están en
> [campos-2d.md](campos-2d.md) y [campos-2f.md](campos-2f.md).
