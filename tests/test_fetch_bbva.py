"""Tests para esquema 2F (bancos) usando fixtures de BBVA Perú 2024 anual.

Validamos:
- El dispatch automático lee el esquema del catálogo y usa _map_period_2f.
- El output expone schema='2F' y los campos específicos de bancos.
- Los 8 valores críticos coinciden con el PDF auditado de BBVA Perú 2024.
- Las métricas derivadas (NIM, NPL, ROA, ROE, etc.) tienen valores razonables.
- raw_accounts excluye códigos amigables y filtra ceros.
"""
from pathlib import Path

import pytest

from smv_peru import FIELDS_TO_CODES_2F, fetch_estados_financieros
from smv_peru.client import CODIGOS_USADOS_2F

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Schema y dispatch
# ---------------------------------------------------------------------------

def test_bbva_returns_schema_2f():
    """El dispatch automatico debe identificar BBVAC1 como esquema 2F."""
    result = fetch_estados_financieros(
        "BBVAC1", desde=2024, hasta=2024, cache_dir=FIXTURES,
    )
    assert result is not None
    assert len(result["periods"]) == 1
    p = result["periods"][0]
    assert p["schema"] == "2F"


def test_bbva_period_has_banking_fields_not_industrial():
    """El period 2F tiene campos bancarios y NO los del esquema 2D."""
    p = fetch_estados_financieros(
        "BBVAC1", desde=2024, hasta=2024, cache_dir=FIXTURES,
    )["periods"][0]
    # Debe tener campos de bancos
    for field in ("interest_income", "interest_expense", "net_interest_income",
                  "deposits", "loans_net", "loans_st", "loans_lt", "nim",
                  "npl_ratio", "loan_to_deposit_ratio", "efficiency_ratio"):
        assert field in p, f"Campo bancario faltante: {field}"
    # NO debe tener campos exclusivos de industriales
    for field in ("revenue", "cogs", "gross_profit", "fcf", "capex_total"):
        assert field not in p, f"Campo industrial no debería estar en 2F: {field}"


# ---------------------------------------------------------------------------
# Validacion contra PDF auditado BBVA Peru 2024
# ---------------------------------------------------------------------------

@pytest.fixture
def bbva_2024():
    return fetch_estados_financieros(
        "BBVAC1", desde=2024, hasta=2024, cache_dir=FIXTURES,
    )["periods"][0]


def test_bbva_2024_cash_matches_pdf(bbva_2024):
    """Disponibles al 31-dic-2024: 13,551,708 (PDF auditado)."""
    assert bbva_2024["cash"] == 13_551_708


def test_bbva_2024_loans_net_sum_matches_pdf(bbva_2024):
    """Cartera de creditos neto total: 74,118,352 (PDF auditado)."""
    assert bbva_2024["loans_net"] == 74_118_352
    assert bbva_2024["loans_st"] == 34_393_677
    assert bbva_2024["loans_lt"] == 39_724_675


def test_bbva_2024_deposits_matches_pdf(bbva_2024):
    """Obligaciones con el publico: 79,421,807 (PDF auditado)."""
    assert bbva_2024["deposits"] == 79_421_807


def test_bbva_2024_total_assets_matches_pdf(bbva_2024):
    """Total Activo: 111,188,992 (PDF auditado)."""
    assert bbva_2024["total_assets"] == 111_188_992


def test_bbva_2024_equity_matches_pdf(bbva_2024):
    """Total Patrimonio: 13,300,346 (PDF auditado)."""
    assert bbva_2024["equity"] == 13_300_346


def test_bbva_2024_total_liabilities_matches_pdf(bbva_2024):
    """Total Pasivo: 97,888,646 (PDF auditado)."""
    assert bbva_2024["total_liabilities"] == 97_888_646


def test_bbva_2024_interest_income_matches_pdf(bbva_2024):
    """Ingresos por intereses 2024: 8,083,186 (PDF auditado)."""
    assert bbva_2024["interest_income"] == 8_083_186


def test_bbva_2024_interest_expense_matches_pdf(bbva_2024):
    """Gastos por intereses 2024: -2,233,177 (PDF auditado)."""
    assert bbva_2024["interest_expense"] == -2_233_177


def test_bbva_2024_net_income_matches_pdf(bbva_2024):
    """Resultado neto 2024: 1,882,772 (PDF auditado)."""
    assert bbva_2024["net_income"] == 1_882_772


# ---------------------------------------------------------------------------
# Sanity de metricas derivadas
# ---------------------------------------------------------------------------

def test_bbva_2024_efficiency_ratio_in_normal_range(bbva_2024):
    """Eficiencia operativa de un banco peruano grande: 30%-50% tipicamente."""
    assert 0.25 < bbva_2024["efficiency_ratio"] < 0.55


def test_bbva_2024_npl_ratio_close_to_pdf(bbva_2024):
    """NPL ratio (proxy con cartera neta): cercano al ~3.73% del PDF."""
    # Proxy: (overdue + judicial) / loans_net = (721,872 + 2,143,414) / 74,118,352 ≈ 3.87%
    assert 0.03 < bbva_2024["npl_ratio"] < 0.045


def test_bbva_2024_roe_uses_average_equity(bbva_2024):
    """ROE = net_income / avg(equity). Para BBVA 2024 deberia ser ~14-15%
    si avg(equity) usa Monto2 (cierre 2023 = 12,375,747)."""
    assert 0.13 < bbva_2024["roe"] < 0.16


def test_bbva_2024_yoy_growth_metrics_present(bbva_2024):
    """YoY growth se calcula con Monto2."""
    for field in ("interest_income_yoy", "net_income_yoy", "loans_yoy",
                  "deposits_yoy", "equity_yoy"):
        assert bbva_2024[field] is not None, f"YoY missing: {field}"


def test_bbva_2024_loan_to_deposit_makes_sense(bbva_2024):
    """Loan-to-deposit ratio: BBVA tipicamente 90-95%."""
    assert 0.85 < bbva_2024["loan_to_deposit_ratio"] < 1.05


# ---------------------------------------------------------------------------
# raw_accounts en 2F
# ---------------------------------------------------------------------------

def test_bbva_raw_accounts_excludes_friendly_codes(bbva_2024):
    """raw_accounts no debe tener codigos cubiertos por campos amigables 2F."""
    intersection = set(bbva_2024["raw_accounts"].keys()) & CODIGOS_USADOS_2F
    assert intersection == set(), (
        f"Códigos duplicados entre raw_accounts y FIELDS_TO_CODES_2F: {intersection}"
    )


def test_bbva_raw_accounts_has_known_extra_account(bbva_2024):
    """1F3401 (Cuentas Contingentes Deudoras) NO está en amigables 2F → debe estar en raw."""
    assert "1F3401" in bbva_2024["raw_accounts"]
    assert "Contingentes" in bbva_2024["raw_accounts"]["1F3401"]["nombre"]


def test_bbva_raw_accounts_entries_have_correct_structure(bbva_2024):
    for codigo, info in bbva_2024["raw_accounts"].items():
        assert codigo[:2] in {"1F", "2F", "3F"}
        assert "nombre" in info
        assert "monto" in info
        assert info["monto"] != 0


# ---------------------------------------------------------------------------
# Sanidad de FIELDS_TO_CODES_2F
# ---------------------------------------------------------------------------

def test_fields_to_codes_2f_is_unique():
    codigos = list(FIELDS_TO_CODES_2F.values())
    assert len(codigos) == len(set(codigos)), "Codigos duplicados en FIELDS_TO_CODES_2F"


def test_fields_to_codes_2f_has_expected_size():
    """~49 campos amigables 2F (sanity check)."""
    assert 40 <= len(FIELDS_TO_CODES_2F) <= 60
