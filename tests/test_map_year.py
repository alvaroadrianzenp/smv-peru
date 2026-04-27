"""Tests para _map_year: filtra filas por RPJ y mapea cuentas SMV al schema interno."""
import pytest

from smv_peru.client import CUENTAS_BAL, CUENTAS_FLOW, CUENTAS_PNL, _map_year


# ---------------------------------------------------------------------------
# Helpers para armar filas SMV en los tests
# ---------------------------------------------------------------------------

def _row(rpj, cuenta, monto):
    return {"RPJ": rpj, "Cuenta": cuenta, "Monto1": str(monto) if monto is not None else None}


def _make_pnl(rpj, revenue=1_000_000, operating_income=200_000, net_income=100_000, eps=2.5):
    return [
        _row(rpj, CUENTAS_PNL["revenue"], revenue),
        _row(rpj, CUENTAS_PNL["operating_income"], operating_income),
        _row(rpj, CUENTAS_PNL["net_income"], net_income),
        _row(rpj, CUENTAS_PNL["eps"], eps),
    ]


def _make_bal(rpj, current_assets=500_000, noncurrent_assets=1_500_000, current_liab=200_000,
              equity=800_000, debt_current=100_000, debt_noncurrent=400_000):
    return [
        _row(rpj, CUENTAS_BAL["current_assets"], current_assets),
        _row(rpj, CUENTAS_BAL["noncurrent_assets"], noncurrent_assets),
        _row(rpj, CUENTAS_BAL["current_liab"], current_liab),
        _row(rpj, CUENTAS_BAL["equity"], equity),
        _row(rpj, CUENTAS_BAL["debt_current"], debt_current),
        _row(rpj, CUENTAS_BAL["debt_noncurrent"], debt_noncurrent),
    ]


def _make_flow(rpj, operating_cf=300_000, capex=-100_000):
    return [
        _row(rpj, CUENTAS_FLOW["operating_cf"], operating_cf),
        _row(rpj, CUENTAS_FLOW["capex"], capex),
    ]


# ---------------------------------------------------------------------------
# Casos donde debe devolver None (datos faltantes o RPJ ausente)
# ---------------------------------------------------------------------------

def test_returns_none_when_pnl_is_none():
    assert _map_year("RPJ1", None, _make_bal("RPJ1"), None, 2023) is None


def test_returns_none_when_bal_is_none():
    assert _map_year("RPJ1", _make_pnl("RPJ1"), None, None, 2023) is None


def test_returns_none_when_pnl_is_empty():
    assert _map_year("RPJ1", [], _make_bal("RPJ1"), None, 2023) is None


def test_returns_none_when_rpj_not_in_pnl():
    assert _map_year("RPJ_X", _make_pnl("RPJ1"), _make_bal("RPJ_X"), None, 2023) is None


def test_returns_none_when_revenue_missing():
    pnl_sin_revenue = [r for r in _make_pnl("RPJ1") if r["Cuenta"] != CUENTAS_PNL["revenue"]]
    assert _map_year("RPJ1", pnl_sin_revenue, _make_bal("RPJ1"), None, 2023) is None


def test_returns_none_when_equity_missing():
    bal_sin_equity = [r for r in _make_bal("RPJ1") if r["Cuenta"] != CUENTAS_BAL["equity"]]
    assert _map_year("RPJ1", _make_pnl("RPJ1"), bal_sin_equity, None, 2023) is None


# ---------------------------------------------------------------------------
# Happy path y cálculos derivados
# ---------------------------------------------------------------------------

def test_happy_path_returns_dict_with_expected_keys():
    result = _map_year("RPJ1", _make_pnl("RPJ1"), _make_bal("RPJ1"), _make_flow("RPJ1"), 2023)
    assert result is not None
    assert result["fiscal_year"] == 2023
    assert result["revenue"] == 1_000_000
    assert result["net_income"] == 100_000
    assert result["equity"] == 800_000
    assert result["eps"] == 2.5


def test_total_debt_is_sum_of_current_and_noncurrent():
    result = _map_year(
        "RPJ1",
        _make_pnl("RPJ1"),
        _make_bal("RPJ1", debt_current=100_000, debt_noncurrent=400_000),
        _make_flow("RPJ1"),
        2023,
    )
    assert result["total_debt"] == 500_000


def test_total_assets_is_sum_of_current_and_noncurrent():
    result = _map_year(
        "RPJ1",
        _make_pnl("RPJ1"),
        _make_bal("RPJ1", current_assets=500_000, noncurrent_assets=1_500_000),
        _make_flow("RPJ1"),
        2023,
    )
    assert result["total_assets"] == 2_000_000


def test_current_ratio_is_assets_over_liabilities():
    result = _map_year(
        "RPJ1",
        _make_pnl("RPJ1"),
        _make_bal("RPJ1", current_assets=600_000, current_liab=200_000),
        _make_flow("RPJ1"),
        2023,
    )
    assert result["current_ratio"] == 3.0


def test_fcf_is_operating_cf_plus_capex():
    """capex viene negativo en SMV; FCF = OCF + capex_negativo."""
    result = _map_year(
        "RPJ1",
        _make_pnl("RPJ1"),
        _make_bal("RPJ1"),
        _make_flow("RPJ1", operating_cf=300_000, capex=-100_000),
        2023,
    )
    assert result["fcf"] == 200_000


def test_roe_is_net_income_over_equity():
    result = _map_year(
        "RPJ1",
        _make_pnl("RPJ1", net_income=100_000),
        _make_bal("RPJ1", equity=800_000),
        _make_flow("RPJ1"),
        2023,
    )
    assert result["roe"] == pytest.approx(0.125)


def test_roic_is_net_income_over_equity_plus_debt():
    result = _map_year(
        "RPJ1",
        _make_pnl("RPJ1", net_income=100_000),
        _make_bal("RPJ1", equity=800_000, debt_current=100_000, debt_noncurrent=100_000),
        _make_flow("RPJ1"),
        2023,
    )
    # invested capital = 800_000 + 200_000 = 1_000_000
    assert result["roic"] == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# Robustez
# ---------------------------------------------------------------------------

def test_works_without_flow():
    """Si flow es None, no falla; los campos derivados de flow quedan None."""
    result = _map_year("RPJ1", _make_pnl("RPJ1"), _make_bal("RPJ1"), None, 2023)
    assert result is not None
    assert result["fcf"] is None


def test_filters_by_rpj_correctly():
    """Filas de otras empresas en el mismo dataset no se deben mezclar."""
    pnl_mixed = _make_pnl("RPJ1", revenue=1_000_000) + _make_pnl("RPJ_OTRO", revenue=999_999_999)
    bal_mixed = _make_bal("RPJ1") + _make_bal("RPJ_OTRO")
    result = _map_year("RPJ1", pnl_mixed, bal_mixed, None, 2023)
    assert result["revenue"] == 1_000_000
