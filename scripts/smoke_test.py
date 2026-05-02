"""Smoke test multi-empresa: ejercita los tickers del catálogo contra el
web service real de SMV para detectar regresiones antes de un release.

Uso:
    uv run python scripts/smoke_test.py

Verifica para cada ticker:
  - fetch_eeff anual y trimestral no levantan excepción
  - al menos 1 período devuelto con campos críticos no-None
  - esquema correcto (2D industriales, 2F bancos)
  - info["tipo"] coherente

Casos especiales que valida explícitamente:
  - Tickers que SMV solo publica en Individual deben caer al early-exit
    full-series y devolver info["tipo"] == "individual".
  - BBVA 2022 anual debe traer balance_source == "Q4_consolidado" (gap
    conocido del cargador SMV cubierto por la cascada Q4 → Anual).

El test es lento en cold cache (~3-5 min). Cache caliente: ~10s.
"""
from __future__ import annotations

import sys
import time
import traceback

from smv_peru import EMPRESAS, fetch_eeff


# Tickers que SMV publica SIEMPRE en Individual (matriz consolidante en el
# extranjero). El cliente debe detectar y caer al early-exit full-series.
#
# Casos históricos de "solo Individual" que evolucionaron y ahora publican
# Consolidado al menos parcialmente (verificado 2026-05-01 — NO incluir aquí):
#   - NEXAPEC1: tiene C completo en anuales 2020-2023 y trimestrales 2023-2024.
#   - ENGEPEC1: anuales 2020-2024 vienen en I, pero trimestrales 2024 en C
#     (Engie Energía Perú empezó a publicar Consolidado en 2024).
SOLO_INDIVIDUAL = {
    "CVERDEC1", "INTERBC1", "PLUZC1", "PORTINC1",
}

# Configuración de la prueba
ANUAL_DESDE, ANUAL_HASTA = 2020, 2024
TRIM_DESDE, TRIM_HASTA = 2023, 2024


def critical_field(esquema: str) -> str:
    """Campo de flujo que debe estar poblado en al menos un período."""
    return "net_interest_income" if esquema == "2F" else "revenue"


def check_periods(periods: list[dict], esquema: str) -> list[str]:
    """Devuelve lista de problemas (vacía si todo ok)."""
    issues: list[str] = []
    if not periods:
        return ["sin períodos"]

    # Esquema correcto en cada período
    schemas = {p.get("schema") for p in periods}
    if schemas != {esquema}:
        issues.append(f"schemas inconsistentes: {schemas} (esperado {{{esquema}}})")

    # Al menos un período con flujo crítico
    flow_field = critical_field(esquema)
    has_flow = any(p.get(flow_field) is not None for p in periods)
    if not has_flow:
        issues.append(f"ningún período con {flow_field} poblado")

    # Al menos un período con stocks
    has_equity = any(p.get("equity") is not None for p in periods)
    has_assets = any(p.get("total_assets") is not None for p in periods)
    if not has_equity:
        issues.append("ningún período con equity poblado")
    if not has_assets:
        issues.append("ningún período con total_assets poblado")

    return issues


def run_one(ticker: str, esquema: str) -> dict:
    """Corre los 2 fetches y devuelve un resumen."""
    summary = {
        "ticker": ticker,
        "esquema": esquema,
        "anual_ok": False,
        "anual_issues": [],
        "anual_tipo": None,
        "anual_periods": 0,
        "anual_q4_substituted": [],
        "trim_ok": False,
        "trim_issues": [],
        "trim_tipo": None,
        "trim_periods": 0,
        "error": None,
    }

    try:
        a = fetch_eeff(ticker, desde=ANUAL_DESDE, hasta=ANUAL_HASTA,
                       periodicidad="anual")
        if a is None:
            summary["anual_issues"].append("fetch devolvió None")
        else:
            summary["anual_periods"] = len(a["periods"])
            summary["anual_tipo"] = a["info"]["tipo"]
            summary["anual_q4_substituted"] = [
                p["fiscal_year"] for p in a["periods"]
                if p.get("balance_source") == "Q4_consolidado"
            ]
            summary["anual_issues"] = check_periods(a["periods"], esquema)
            summary["anual_ok"] = not summary["anual_issues"]
    except Exception as e:
        summary["error"] = f"anual: {type(e).__name__}: {e}"
        traceback.print_exc(file=sys.stderr)

    try:
        t = fetch_eeff(ticker, desde=TRIM_DESDE, hasta=TRIM_HASTA,
                       periodicidad="trimestral")
        if t is None:
            summary["trim_issues"].append("fetch devolvió None")
        else:
            summary["trim_periods"] = len(t["periods"])
            summary["trim_tipo"] = t["info"]["tipo"]
            summary["trim_issues"] = check_periods(t["periods"], esquema)
            summary["trim_ok"] = not summary["trim_issues"]
    except Exception as e:
        summary["error"] = (summary["error"] or "") + \
            f" | trim: {type(e).__name__}: {e}"
        traceback.print_exc(file=sys.stderr)

    return summary


def print_row(s: dict) -> None:
    a_mark = "OK" if s["anual_ok"] else "FAIL"
    t_mark = "OK" if s["trim_ok"] else "FAIL"
    a_extra = f"({s['anual_periods']} per, {s['anual_tipo']})" if s["anual_tipo"] else "-"
    t_extra = f"({s['trim_periods']} per, {s['trim_tipo']})" if s["trim_tipo"] else "-"
    q4_note = ""
    if s["anual_q4_substituted"]:
        q4_note = f"  [Q4-substituted: {s['anual_q4_substituted']}]"

    print(f"{s['ticker']:10} {s['esquema']}  anual:{a_mark} {a_extra:30}  "
          f"trim:{t_mark} {t_extra}{q4_note}")
    for issue in s["anual_issues"]:
        print(f"    anual: {issue}")
    for issue in s["trim_issues"]:
        print(f"    trim:  {issue}")
    if s["error"]:
        print(f"    EXCEPTION: {s['error']}")


def main() -> int:
    print(f"Smoke test sobre {len(EMPRESAS)} tickers del catálogo")
    print(f"  Anual:      {ANUAL_DESDE}..{ANUAL_HASTA}")
    print(f"  Trimestral: {TRIM_DESDE}..{TRIM_HASTA}")
    print()

    t0 = time.time()
    summaries = []
    for ticker, info in sorted(EMPRESAS.items()):
        esquema = info["esquema"]
        s = run_one(ticker, esquema)
        summaries.append(s)
        print_row(s)

    elapsed = time.time() - t0
    print()
    print(f"Tiempo total: {elapsed:.1f}s")
    print()

    # Resumen agregado
    n_total = len(summaries)
    n_anual_ok = sum(1 for s in summaries if s["anual_ok"])
    n_trim_ok = sum(1 for s in summaries if s["trim_ok"])
    n_full_ok = sum(1 for s in summaries if s["anual_ok"] and s["trim_ok"])
    n_errors = sum(1 for s in summaries if s["error"])

    print(f"Anual:       {n_anual_ok}/{n_total}")
    print(f"Trimestral:  {n_trim_ok}/{n_total}")
    print(f"Ambos OK:    {n_full_ok}/{n_total}")
    if n_errors:
        print(f"Excepciones: {n_errors}")
    print()

    # Checks especiales
    print("Checks especiales:")
    failures: list[str] = []

    # 1. Tickers solo-Individual
    for ticker in sorted(SOLO_INDIVIDUAL):
        s = next((x for x in summaries if x["ticker"] == ticker), None)
        if s is None:
            failures.append(f"{ticker}: no está en el catálogo")
            continue
        for label, key in (("anual", "anual_tipo"), ("trim", "trim_tipo")):
            if s[key] != "individual" and s[key] is not None:
                failures.append(
                    f"{ticker} {label}: tipo={s[key]!r} (esperado 'individual')"
                )
            else:
                print(f"  {ticker} {label}: tipo={s[key]} ✓")

    # 2. BBVA 2022 con balance_source=Q4_consolidado
    bbva = next((x for x in summaries if x["ticker"] == "BBVAC1"), None)
    if bbva and 2022 in bbva["anual_q4_substituted"]:
        print(f"  BBVAC1 anual 2022: balance_source=Q4_consolidado ✓")
    elif bbva:
        failures.append(
            f"BBVAC1 anual: 2022 no aparece como Q4-substituted "
            f"(actual: {bbva['anual_q4_substituted']})"
        )

    print()
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1

    if n_full_ok == n_total:
        print(f"✓ Todos los {n_total} tickers pasaron.")
        return 0

    print(f"⚠ {n_total - n_full_ok} tickers con issues.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
