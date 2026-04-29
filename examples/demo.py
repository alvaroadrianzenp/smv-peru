"""Demo de smv-peru: descarga estados financieros de empresas peruanas.

Ejecuta con:
    uv run python examples/demo.py

Este demo muestra:
1. Listado del catálogo de empresas soportadas.
2. Descarga anual de un industrial (Alicorp).
3. Descarga de un banco (BBVA Perú) con métricas bancarias.
4. Descarga trimestral con normalización period-only.
5. Acceso a `raw_accounts` (cuentas adicionales no expuestas como amigables).
6. Auditoría del mapeo amigable → código SMV.

Las descargas SOAP a SMV demoran ~9 segundos por respuesta. El cache local
(en `~/Library/Caches/smv-peru/` por defecto en macOS) acelera consultas
repetidas. La primera ejecución tarda; las siguientes son instantáneas.
"""
from __future__ import annotations

from smv_peru import (
    EMPRESAS,
    FIELDS_TO_CODES_2D,
    FIELDS_TO_CODES_2F,
    fetch_eeff,
)


def seccion(titulo: str) -> None:
    print()
    print("=" * 78)
    print(titulo)
    print("=" * 78)


# ---------------------------------------------------------------------------
# 1) Catálogo soportado
# ---------------------------------------------------------------------------
seccion("1) Catálogo de empresas soportadas")

por_esquema: dict[str, list[str]] = {}
for ticker, info in sorted(EMPRESAS.items()):
    por_esquema.setdefault(info["esquema"], []).append(ticker)

for esq in sorted(por_esquema):
    label = {"2D": "Industriales", "2F": "Bancos / holdings financieros"}.get(esq, esq)
    print(f"\n{label} ({len(por_esquema[esq])} tickers):")
    print("  " + ", ".join(por_esquema[esq]))


# ---------------------------------------------------------------------------
# 2) Industrial: Alicorp 2023
# ---------------------------------------------------------------------------
seccion("2) Industrial: Alicorp 2023 (esquema 2D)")

resultado = fetch_eeff("ALICORC1", desde=2023, hasta=2023)
p = resultado["periods"][0]

print(f"  Schema:         {p['schema']}")
print(f"  Año:            {p['fiscal_year']}")
print(f"  Revenue:        S/. {p['revenue']/1_000:,.0f} M")
print(f"  Gross profit:   S/. {p['gross_profit']/1_000:,.0f} M  (margen {p['gross_margin']:.1%})")
print(f"  Net income:     S/. {p['net_income']/1_000:,.0f} M  (margen {p['net_margin']:.1%})")
print(f"  Total assets:   S/. {p['total_assets']/1_000:,.0f} M")
print(f"  Net debt:       S/. {p['net_debt']/1_000:,.0f} M")
print(f"  ROE:            {p['roe']:.2%}")
print(f"  Current ratio:  {p['current_ratio']:.2f}x")
print(f"  FCF:            S/. {p['fcf']/1_000:,.0f} M")


# ---------------------------------------------------------------------------
# 3) Banco: BBVA Perú 2024
# ---------------------------------------------------------------------------
seccion("3) Banco: BBVA Perú 2024 (esquema 2F)")

resultado = fetch_eeff("BBVAC1", desde=2024, hasta=2024)
p = resultado["periods"][0]

print(f"  Schema:                 {p['schema']}")
print(f"  Año:                    {p['fiscal_year']}")
print(f"  Cartera de créditos:    S/. {p['loans_net']/1_000:,.0f} M")
print(f"  Depósitos del público:  S/. {p['deposits']/1_000:,.0f} M")
print(f"  Total activos:          S/. {p['total_assets']/1_000:,.0f} M")
print(f"  Patrimonio:             S/. {p['equity']/1_000:,.0f} M")
print(f"  Net interest income:    S/. {p['net_interest_income']/1_000:,.0f} M")
print(f"  Utilidad neta:          S/. {p['net_income']/1_000:,.0f} M")
print()
print(f"  Métricas bancarias:")
print(f"    NIM (vs avg loans):        {p['nim']:.2%}")
print(f"    Efficiency ratio:          {p['efficiency_ratio']:.2%}")
print(f"    NPL ratio (proxy):         {p['npl_ratio']:.2%}")
print(f"    Loan-to-deposit:           {p['loan_to_deposit_ratio']:.2%}")
print(f"    Equity/Assets (solvencia): {p['equity_to_assets']:.2%}")
print(f"    ROA:                       {p['roa']:.2%}")
print(f"    ROE:                       {p['roe']:.2%}")


# ---------------------------------------------------------------------------
# 4) Trimestral: Alicorp 2023 (CF normalizado a period-only)
# ---------------------------------------------------------------------------
seccion("4) Trimestral: Alicorp 2023 — CF normalizado a period-only")

resultado = fetch_eeff(
    "ALICORC1", desde=2023, hasta=2023, periodicidad="trimestral",
)

print(f"  {'Q':<3} {'revenue (M S/.)':>16} {'operating_cf (M S/.)':>22} {'capex_ppe (M S/.)':>20}")
for p in resultado["periods"]:
    print(
        f"  Q{p['quarter']} "
        f"{p['revenue']/1_000:>16,.0f} "
        f"{p['operating_cf']/1_000:>22,.0f} "
        f"{p['capex_ppe']/1_000:>20,.0f}"
    )

# Verificación: la suma de los 4 trimestres debe coincidir con el anual
anual = fetch_eeff("ALICORC1", desde=2023, hasta=2023)["periods"][0]
suma_op = sum(p["operating_cf"] for p in resultado["periods"])
print()
print(f"  Suma Q1+Q2+Q3+Q4 operating_cf: S/. {suma_op/1_000:,.0f} M")
print(f"  Operating_cf anual:            S/. {anual['operating_cf']/1_000:,.0f} M")
print(f"  Diferencia:                    {abs(suma_op - anual['operating_cf']):,.0f} (debería ser 0)")


# ---------------------------------------------------------------------------
# 5) raw_accounts: cuentas adicionales que SMV publica
# ---------------------------------------------------------------------------
seccion("5) raw_accounts: cuentas no expuestas como amigables")

p = fetch_eeff("ALICORC1", desde=2023, hasta=2023)["periods"][0]
print(f"  Total cuentas en raw_accounts (Alicorp 2023): {len(p['raw_accounts'])}")
print()
print(f"  Algunas cuentas raras del esquema 2D que SMV publica:")
ejemplos = ["2D0410", "1D0114", "3D0322"]
for codigo in ejemplos:
    if codigo in p["raw_accounts"]:
        info = p["raw_accounts"][codigo]
        print(f"    {codigo}: {info['nombre']:<55} {info['monto']:>15,.0f}")


# ---------------------------------------------------------------------------
# 6) Auditoría del mapeo
# ---------------------------------------------------------------------------
seccion("6) Auditoría: qué código SMV alimenta cada campo amigable")

print(f"  Industriales (2D): {len(FIELDS_TO_CODES_2D)} campos amigables 1:1 con SMV")
print(f"  Bancos (2F):       {len(FIELDS_TO_CODES_2F)} campos amigables 1:1 con SMV")
print()
print(f"  Ejemplos de mapeo 2D:")
for field in ["revenue", "cash", "gross_profit", "operating_cf"]:
    print(f"    {field:<20} → {FIELDS_TO_CODES_2D[field]}")
print()
print(f"  Ejemplos de mapeo 2F:")
for field in ["interest_income", "loans_st", "deposits", "operating_cf"]:
    print(f"    {field:<20} → {FIELDS_TO_CODES_2F[field]}")


# ---------------------------------------------------------------------------
# 7) YoY growth: usando Monto2 (cierre del período anterior)
# ---------------------------------------------------------------------------
seccion("7) YoY growth: crecimiento vs período anterior")

p = fetch_eeff("BBVAC1", desde=2024, hasta=2024)["periods"][0]
print(f"  BBVA Perú 2024 vs 2023:")
for field in ["interest_income_yoy", "net_income_yoy", "loans_yoy", "deposits_yoy", "equity_yoy"]:
    if p.get(field) is not None:
        print(f"    {field:<25} {p[field]:+.2%}")

print()
print("Demo completo. Para más detalles, ver README.md o consultar:")
print("  https://github.com/<TU_USUARIO>/smv-peru")
