"""Tests end-to-end para fetch_estados_financieros usando fixtures de Alicorp."""
from pathlib import Path

import pytest

from smv_peru import UnknownTickerError, fetch_estados_financieros

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Anual (default)
# ---------------------------------------------------------------------------

def test_anual_returns_dict_with_periods():
    result = fetch_estados_financieros(
        "ALICORC1", desde=2021, hasta=2023, cache_dir=FIXTURES,
    )
    assert result is not None
    assert "periods" in result
    assert len(result["periods"]) == 3


def test_anual_returns_periods_in_chronological_order():
    result = fetch_estados_financieros(
        "ALICORC1", desde=2021, hasta=2023, cache_dir=FIXTURES,
    )
    fiscal_years = [p["fiscal_year"] for p in result["periods"]]
    assert fiscal_years == [2021, 2022, 2023]
    # quarter es None en periodicidad anual
    assert all(p["quarter"] is None for p in result["periods"])


def test_anual_each_period_has_complete_schema():
    """Schema completo: 13 campos legacy + nuevos amigables + métricas derivadas
    + raw_accounts."""
    result = fetch_estados_financieros(
        "ALICORC1", desde=2021, hasta=2023, cache_dir=FIXTURES,
    )
    expected_keys = {
        # Identificadores
        "fiscal_year", "quarter",
        # Legacy (compatibilidad con la versión anterior)
        "revenue", "ebitda", "net_income", "eps", "total_debt", "equity",
        "total_assets", "current_ratio", "fcf", "roe", "roic",
        # Nuevos: P&L
        "cogs", "gross_profit", "admin_expenses", "selling_expenses",
        "operating_income", "interest_income", "interest_expense",
        "pretax_income", "income_tax",
        # Nuevos: Balance
        "cash", "accounts_receivable", "inventory", "ppe", "intangibles",
        "accounts_payable", "total_liabilities", "debt_short_term",
        "debt_long_term", "share_capital", "retained_earnings", "reserves",
        # Nuevos: Flujo de Efectivo
        "operating_cf", "capex_ppe", "capex_intangibles", "capex_total",
        "investing_cf", "financing_cf", "debt_issued", "debt_repaid",
        "dividends_paid", "interest_paid", "taxes_paid",
        # Métricas derivadas
        "gross_margin", "operating_margin", "net_margin", "net_debt",
        "quick_ratio", "interest_coverage", "effective_tax_rate",
        "payout_ratio", "capex_intensity",
        # Cuentas crudas
        "raw_accounts",
    }
    for period in result["periods"]:
        missing = expected_keys - period.keys()
        assert not missing, f"Faltan campos en período {period['fiscal_year']}: {missing}"


# ---------------------------------------------------------------------------
# Validación contra valores del PDF auditado de Alicorp 2023
# Los 5 valores críticos que cruzamos contra el informe SMV publicado.
# ---------------------------------------------------------------------------

def test_alicorp_2023_cash_matches_audited_pdf():
    """Efectivo y Equivalentes al 31-dic-2023 según PDF auditado: 1,493,778."""
    p = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )["periods"][0]
    assert p["cash"] == 1_493_778


def test_alicorp_2023_gross_profit_matches_audited_pdf():
    """Ganancia Bruta 2023 según PDF auditado: 2,419,162."""
    p = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )["periods"][0]
    assert p["gross_profit"] == 2_419_162


def test_alicorp_2023_interest_expense_matches_audited_pdf():
    """Gastos Financieros 2023 según PDF auditado: -509,525."""
    p = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )["periods"][0]
    assert p["interest_expense"] == -509_525


def test_alicorp_2023_dividends_paid_matches_audited_pdf():
    """Dividendos Pagados 2023 según PDF auditado: 214,021 (negativo, salida).

    SMV publica los pagos como negativos (salidas de caja); la librería
    mantiene ese signo natural para que el lector pueda sumar mentalmente y
    verificar el subtotal de financiamiento.
    """
    p = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )["periods"][0]
    assert p["dividends_paid"] == -214_021


def test_alicorp_2023_total_liabilities_matches_audited_pdf():
    """Total Pasivos al 31-dic-2023 según PDF auditado: 10,049,162."""
    p = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )["periods"][0]
    assert p["total_liabilities"] == 10_049_162


# ---------------------------------------------------------------------------
# Sanity checks de métricas derivadas
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Currency: industriales y bancos en PEN, mineras en USD
# ---------------------------------------------------------------------------

def test_alicorp_currency_is_pen():
    """Alicorp (industrial) reporta en soles."""
    r = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )
    assert r["periods"][0]["currency"] == "PEN"
    assert r["info"]["currency"] == "PEN"


def test_currency_in_info_dict():
    """info dict expone currency a nivel del result completo."""
    r = fetch_estados_financieros(
        "ALICORC1", desde=2021, hasta=2023, cache_dir=FIXTURES,
    )
    assert "currency" in r["info"]


# ---------------------------------------------------------------------------
# Cuentas adicionales agregadas en versión Tier B (Opción B)
# ---------------------------------------------------------------------------

def test_alicorp_2023_has_goodwill_and_attributable_fields():
    """Goodwill, equity_to_parent, minority_equity, fx_gain_loss y EPS diluida
    deben estar presentes para Alicorp 2023."""
    p = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )["periods"][0]
    # Tier A
    assert p.get("goodwill") is not None
    assert p.get("net_income_to_parent") is not None
    assert p.get("minority_interest") is not None
    assert p.get("eps_diluted") is not None
    # Tier B
    assert p.get("fx_gain_loss") is not None
    assert p.get("employee_benefits") is not None
    assert p.get("equity_to_parent") is not None


def test_alicorp_2023_minority_equity_is_derived_correctly():
    """minority_equity = equity total − equity_to_parent."""
    p = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )["periods"][0]
    expected = p["equity"] - p["equity_to_parent"]
    assert p["minority_equity"] == expected


def test_alicorp_2023_net_income_decomposition_cuadra():
    """net_income = net_income_to_parent + minority_interest (con tolerancia)."""
    p = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )["periods"][0]
    if p["net_income_to_parent"] is not None and p["minority_interest"] is not None:
        suma = p["net_income_to_parent"] + p["minority_interest"]
        # Pueden diferir por unos pocos miles por redondeo
        assert abs(suma - p["net_income"]) < 100


def test_alicorp_2023_derived_metrics_make_sense():
    p = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )["periods"][0]

    # gross_margin = gross_profit / revenue ≈ 2.42M / 13.66M ≈ 17.7%
    assert 0.15 < p["gross_margin"] < 0.20

    # net_debt = total_debt - cash, debe ser positivo (Alicorp tiene más deuda que caja)
    assert p["net_debt"] > 0
    assert p["net_debt"] == p["total_debt"] - p["cash"]

    # current_ratio cercano a 1 (Alicorp opera con liquidez ajustada)
    assert 1.0 < p["current_ratio"] < 1.5

    # quick_ratio < current_ratio (excluye inventarios)
    assert p["quick_ratio"] < p["current_ratio"]

    # ROE positivo, ROIC < ROE (porque ROIC divide por equity + deuda)
    assert p["roe"] > 0
    assert p["roic"] < p["roe"]


def test_alicorp_2024_subsidiaries_purchased():
    """Alicorp 2024: SMV publica `3D0219` = -517,616 (compra menor de
    subsidiarias). Validamos que el campo amigable lo expone con su signo
    natural negativo (es salida de caja)."""
    p = fetch_estados_financieros(
        "ALICORC1", desde=2024, hasta=2024, cache_dir=FIXTURES,
    )["periods"][0]
    assert p["subsidiaries_purchased"] == -517_616
    # Los otros 2 son 0 ese año → la librería los normaliza a None
    # vía _amount (que devuelve None si Monto1 es 0 o ausente).
    # Aquí solo nos aseguramos de que el campo existe en el dict.
    assert "subsidiaries_obtained_control" in p
    assert "subsidiaries_lost_control" in p


def test_cash_change_quadrature_alicorp_2023():
    """Verifica la cuadratura de la sección de cierre del CF:
    `start_cash + net_change_in_cash == end_cash`. SMV expone los 3 valores
    de forma independiente, así que esta es una validación directa contra el
    propio web service."""
    p = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )["periods"][0]
    assert p["start_cash"] is not None
    assert p["net_change_in_cash"] is not None
    assert p["end_cash"] is not None
    # Tolerancia mínima por redondeo (los valores vienen en miles enteros).
    assert abs(p["start_cash"] + p["net_change_in_cash"] - p["end_cash"]) < 1


def test_capex_total_is_signed_sum_of_ppe_and_intangibles():
    """capex_total mantiene el signo natural de SMV (negativo cuando es salida)
    para que sume coherentemente con los demás items del bloque de inversión."""
    p = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )["periods"][0]
    expected = (p["capex_ppe"] or 0) + (p["capex_intangibles"] or 0)
    assert p["capex_total"] == expected


def test_fcf_subtracts_total_capex():
    """FCF = OCF + capex_ppe + capex_intangibles (capex viene negativo)."""
    p = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )["periods"][0]
    expected = p["operating_cf"] + p["capex_ppe"] + p["capex_intangibles"]
    assert p["fcf"] == expected


def test_anual_alicorp_2023_has_realistic_magnitudes():
    """Sanity check: revenue de Alicorp 2023 en miles de soles >1B."""
    result = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )
    p = result["periods"][0]
    assert p["revenue"] > 1_000_000   # >1B soles (en miles)
    assert p["equity"] > 0
    assert p["total_assets"] > p["total_debt"]


# ---------------------------------------------------------------------------
# Trimestral
# ---------------------------------------------------------------------------

def test_trimestral_returns_4_periods_per_year():
    result = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023,
        periodicidad="trimestral", cache_dir=FIXTURES,
    )
    assert len(result["periods"]) == 4


def test_trimestral_quarters_are_1_to_4():
    result = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023,
        periodicidad="trimestral", cache_dir=FIXTURES,
    )
    quarters = [p["quarter"] for p in result["periods"]]
    assert quarters == [1, 2, 3, 4]


def test_trimestral_revenues_sum_close_to_annual():
    """La suma de los 4 trimestres de Alicorp 2023 ≈ revenue anual de 2023."""
    annual = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )["periods"][0]
    quarterly = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023,
        periodicidad="trimestral", cache_dir=FIXTURES,
    )["periods"]
    sum_q = sum(p["revenue"] for p in quarterly)
    # tolerancia 1% por redondeos
    assert abs(sum_q - annual["revenue"]) / annual["revenue"] < 0.01


# ---------------------------------------------------------------------------
# Normalizacion trimestral: el CF debe ser period-only (no YTD)
# ---------------------------------------------------------------------------

def test_trimestral_cf_is_period_only_not_ytd():
    """El CF trimestral debe ser period-only despues de normalizacion.
    SMV publica YTD; la libreria detecta y resta el trimestre anterior.
    Verificacion: suma(Q1..Q4 CF) = Anual CF.
    """
    annual = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )["periods"][0]
    quarterly = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023,
        periodicidad="trimestral", cache_dir=FIXTURES,
    )["periods"]
    # operating_cf
    sum_op = sum(p["operating_cf"] for p in quarterly)
    assert abs(sum_op - annual["operating_cf"]) < 1
    # capex_ppe
    sum_capex = sum(p["capex_ppe"] for p in quarterly)
    assert abs(sum_capex - annual["capex_ppe"]) < 1
    # cash_from_customers
    sum_customers = sum(p["cash_from_customers"] for p in quarterly)
    assert abs(sum_customers - annual["cash_from_customers"]) < 100  # tolerancia minima


def test_trimestral_q1_cf_unchanged():
    """Para Q1 no hay normalizacion (ya es period-only por definicion,
    no hay Q0 anterior)."""
    quarterly = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023,
        periodicidad="trimestral", cache_dir=FIXTURES,
    )["periods"]
    q1 = next(p for p in quarterly if p["quarter"] == 1)
    # Alicorp Q1 2023 operating_cf = -18,937 (segun fixtures)
    assert q1["operating_cf"] == -18937


def test_trimestral_q4_cf_is_period_only_after_normalization():
    """Antes de la normalizacion, Q4 CF era YTD acumulado = Anual CF.
    Despues de normalizacion, Q4 = solo Q4 (Anual − Q3 YTD original).
    Para Alicorp: Q4_only = 1,626,530 ≠ Anual 1,518,758.
    """
    quarterly = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023,
        periodicidad="trimestral", cache_dir=FIXTURES,
    )["periods"]
    q4 = next(p for p in quarterly if p["quarter"] == 4)
    annual = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )["periods"][0]
    assert q4["operating_cf"] != annual["operating_cf"]  # Q4 != Anual ahora
    # El valor especifico de Q4 only para Alicorp:
    assert q4["operating_cf"] == 1626530


# ---------------------------------------------------------------------------
# Validaciones de input
# ---------------------------------------------------------------------------

def test_unknown_ticker_raises():
    with pytest.raises(UnknownTickerError):
        fetch_estados_financieros("FAKE99", desde=2023, hasta=2023, cache_dir=FIXTURES)


def test_invalid_tipo_raises():
    with pytest.raises(ValueError, match="tipo"):
        fetch_estados_financieros(
            "ALICORC1", desde=2023, hasta=2023,
            tipo="invalido", cache_dir=FIXTURES,
        )


def test_invalid_periodicidad_raises():
    with pytest.raises(ValueError, match="periodicidad"):
        fetch_estados_financieros(
            "ALICORC1", desde=2023, hasta=2023,
            periodicidad="mensual", cache_dir=FIXTURES,
        )


def test_desde_greater_than_hasta_raises():
    with pytest.raises(ValueError, match="desde"):
        fetch_estados_financieros(
            "ALICORC1", desde=2024, hasta=2020, cache_dir=FIXTURES,
        )


def test_fetch_estados_financieros_is_alias_of_fetch_eeff():
    """Backward-compat: el nombre antiguo debe seguir funcionando idéntico al nuevo."""
    from smv_peru import fetch_eeff, fetch_estados_financieros
    assert fetch_eeff is fetch_estados_financieros


def test_max_workers_zero_raises():
    with pytest.raises(ValueError, match="max_workers"):
        fetch_estados_financieros(
            "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES, max_workers=0,
        )


# ---------------------------------------------------------------------------
# Equivalencia serial vs paralelo
# ---------------------------------------------------------------------------

def test_serial_and_parallel_produce_identical_results_anual():
    """max_workers=1 (serial) y max_workers>1 (paralelo) deben dar el mismo
    resultado bit-exacto."""
    serial = fetch_estados_financieros(
        "ALICORC1", desde=2021, hasta=2023,
        cache_dir=FIXTURES, max_workers=1,
    )
    parallel = fetch_estados_financieros(
        "ALICORC1", desde=2021, hasta=2023,
        cache_dir=FIXTURES, max_workers=10,
    )
    assert len(serial["periods"]) == len(parallel["periods"])
    for ps, pp in zip(serial["periods"], parallel["periods"]):
        for k in ps:
            assert ps[k] == pp[k], f"Diferencia en campo {k!r}: serial={ps[k]} parallel={pp[k]}"


# ---------------------------------------------------------------------------
# info dict: metadata de la consulta
# ---------------------------------------------------------------------------

def test_info_contains_metadata_keys():
    r = fetch_estados_financieros(
        "ALICORC1", desde=2021, hasta=2023, cache_dir=FIXTURES,
    )
    info = r["info"]
    expected = {"fetched_at", "ticker", "schema", "tipo", "periodicidad",
                "desde", "hasta", "periods_requested", "periods_returned",
                "periods_missing"}
    assert expected.issubset(info.keys())
    assert info["ticker"] == "ALICORC1"
    assert info["schema"] == "2D"
    assert info["periodicidad"] == "anual"
    assert info["desde"] == 2021
    assert info["hasta"] == 2023


def test_info_periods_returned_matches_periods():
    r = fetch_estados_financieros(
        "ALICORC1", desde=2021, hasta=2023, cache_dir=FIXTURES,
    )
    actual_periods = [(p["fiscal_year"], p["quarter"]) for p in r["periods"]]
    assert r["info"]["periods_returned"] == actual_periods


def test_info_periods_missing_empty_when_all_data_available():
    r = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )
    assert r["info"]["periods_missing"] == []


def test_info_trimestral_lists_all_4_quarters():
    r = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, periodicidad="trimestral",
        cache_dir=FIXTURES,
    )
    requested = r["info"]["periods_requested"]
    assert requested == [(2023, 1), (2023, 2), (2023, 3), (2023, 4)]


def test_serial_and_parallel_produce_identical_results_trimestral():
    """Idem pero con datos trimestrales (incluye normalización period-only,
    que requiere coordinación entre llamadas paralelas y la fase de procesamiento)."""
    serial = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, periodicidad="trimestral",
        cache_dir=FIXTURES, max_workers=1,
    )
    parallel = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, periodicidad="trimestral",
        cache_dir=FIXTURES, max_workers=10,
    )
    assert len(serial["periods"]) == len(parallel["periods"])
    for ps, pp in zip(serial["periods"], parallel["periods"]):
        # Comparar campos amigables (no raw_accounts que podría tener orden distinto)
        for k in ps:
            if k == "raw_accounts":
                assert set(ps[k].keys()) == set(pp[k].keys())
            else:
                assert ps[k] == pp[k], f"Q{ps['quarter']} campo {k!r}: serial={ps[k]} parallel={pp[k]}"
