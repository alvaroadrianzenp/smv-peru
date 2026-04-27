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
    result = fetch_estados_financieros(
        "ALICORC1", desde=2021, hasta=2023, cache_dir=FIXTURES,
    )
    expected_keys = {
        "fiscal_year", "quarter", "revenue", "ebitda", "net_income", "eps",
        "total_debt", "equity", "total_assets", "current_ratio",
        "fcf", "roe", "roic",
    }
    for period in result["periods"]:
        assert expected_keys.issubset(period.keys())


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
