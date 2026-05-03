# Guía de uso

Ejemplos de los casos más comunes de análisis financiero con `smv-peru`. Todos asumen que la librería está instalada (`pip install smv-peru` o `pip install "smv-peru[excel]"` para los exports a Excel).

Si vienes del [README](../README.md) y ya viste el Quick Start, esta página te lleva más allá. Para el "porqué" detrás de cada decisión técnica (esquemas, política C/I, LTM, payout T-1, EBITDA), ver [conceptos.md](conceptos.md).

## Descarga anual de una empresa

```python
from smv_peru import fetch_eeff

datos = fetch_eeff(
    "ALICORC1",
    desde=2021,
    hasta=2023,
)

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

Por default `tipo="consolidado"` y `periodicidad="anual"`. Para Individual: `tipo="individual"`. Para trimestral: `periodicidad="trimestral"`.

## Trimestral con LTM

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

## Descargar un sector entero a Excel

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

## Comparar bancos peruanos

```python
from smv_peru import fetch_multi, to_excel

bancos = fetch_multi(
    ["BBVAC1", "CREDITC1", "INTERBC1", "SCOTIAC1"],
    desde=2020, hasta=2024,
    periodicidad="anual",
)
to_excel(bancos, "bancos_peruanos.xlsx")
```

Cada hoja trae métricas bancarias específicas (NIM, NPL, ROE, ROA, eficiencia operativa, costo del riesgo) calculadas con promedios usando `Monto2`.

## Tendencia anual de payout_ratio

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

El año 2019 mostrará `payout=—` porque no hay 2018 en la serie. Los siguientes sí se calculan: dividendos del año / utilidad del año anterior (convención JGA peruana).

## Inyectar D&A externo cuando SMV no lo expone

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

## Detectar gaps de SMV

```python
from smv_peru import fetch_eeff

# Datos hasta 2026 — al momento de la consulta, Q2-Q4 2026 aún no publicados
datos = fetch_eeff("UNACEMC1", desde=2024, hasta=2026, periodicidad="trimestral")

print(f"Pedidos: {datos['info']['periods_requested']}")
print(f"Recibidos: {datos['info']['periods_returned']}")
print(f"Faltantes: {datos['info']['periods_missing']}")
```

`periods_missing` también incluye los períodos donde se pidió Consolidado pero solo había Individual disponible (omitidos por la política de homogeneidad C/I).

## Exportar a CSV (sin dependencias externas)

```python
from smv_peru import fetch_eeff, to_csv

datos = fetch_eeff("ALICORC1", desde=2019, hasta=2024)
to_csv(datos, "alicorp_2019_2024.csv", ticker="ALICORC1")
```

Solo usa `csv` de stdlib. Universal: abre en Excel, Numbers, Google Sheets, scripts. Soporta single y multi-empresa.

## Auditar el mapeo amigable → código SMV

```python
from smv_peru import FIELDS_TO_CODES_2D, FIELDS_TO_CODES_2F

print(f"cash (industrial): {FIELDS_TO_CODES_2D['cash']}")          # "1D0109"
print(f"cash (banco):      {FIELDS_TO_CODES_2F['cash']}")          # "1F0101"
print(f"loans_st (banco):  {FIELDS_TO_CODES_2F['loans_st']}")      # "1F0111"
```

Útil para verificar contra los PDFs auditados oficiales o el Manual SMV/CONASEV. Los **derivados** (márgenes, ratios, NIM, NPL, etc.) no están en estos dicts porque se calculan desde otros campos — ver fórmulas en [campos-2d.md](campos-2d.md) y [campos-2f.md](campos-2f.md).
