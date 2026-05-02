"""Tests para el post-pass LTM (Last Twelve Months) en datos trimestrales.

LTM sobrescribe métricas flujo/flujo y flujo/stock (ROE, ROIC, NIM, etc.) usando
suma móvil de 4 trimestres y promedio de stocks. Si falta historia suficiente
en el dataset, las métricas LTM → None (opción A: la librería no descarga
trimestres extra implícitos).
"""
from smv_peru.client import (
    _apply_ltm_2d,
    _apply_ltm_2f,
    _quarter_offset,
)


# ---------------------------------------------------------------------------
# _quarter_offset: aritmética de trimestres
# ---------------------------------------------------------------------------

def test_quarter_offset_mismo_anho():
    assert _quarter_offset(2024, 3, 1) == (2024, 2)
    assert _quarter_offset(2024, 4, 2) == (2024, 2)


def test_quarter_offset_wrap_a_anho_anterior():
    assert _quarter_offset(2024, 1, 1) == (2023, 4)
    assert _quarter_offset(2024, 2, 3) == (2023, 3)


def test_quarter_offset_4q_atras_es_mismo_q_anho_anterior():
    assert _quarter_offset(2024, 3, 4) == (2023, 3)
    assert _quarter_offset(2024, 1, 4) == (2023, 1)


# ---------------------------------------------------------------------------
# _apply_ltm_2d: cálculos LTM en industriales
# ---------------------------------------------------------------------------

def _period_2d(year, quarter, **overrides):
    """Período 2D mínimo con valores plausibles para cubrir todas las LTM."""
    base = {
        "fiscal_year": year,
        "quarter": quarter,
        "revenue": 1000.0,
        "operating_income": 200.0,
        "interest_expense": -20.0,
        "ebitda": 250.0,
        "net_income": 100.0,
        "capex_total": 80.0,
        "dividends_paid": 30.0,
        "equity": 5000.0,
        "total_debt": 2000.0,
        "net_debt": 1500.0,
        # Las métricas LTM se sobrescriben; valores "viejos" para detectar updates:
        "roe": 9999,
        "roic": 9999,
        "interest_coverage": 9999,
        "interest_coverage_ebitda": 9999,
        "debt_to_ebitda": 9999,
        "net_debt_to_ebitda": 9999,
        "payout_ratio": 9999,
        "capex_intensity": 9999,
    }
    base.update(overrides)
    return base


def test_2d_sin_historia_todas_las_ltm_son_none():
    # Solo 4 trimestres consecutivos sin Q4 año-1 → ningún trimestre tiene LTM
    periods = [_period_2d(2023, q) for q in (1, 2, 3, 4)]
    _apply_ltm_2d(periods)
    for p in periods:
        for m in ("roe", "roic", "interest_coverage", "interest_coverage_ebitda",
                  "debt_to_ebitda", "net_debt_to_ebitda",
                  "payout_ratio", "capex_intensity"):
            assert p[m] is None, f"{p['fiscal_year']}Q{p['quarter']} {m} debería ser None"


def test_2d_anuales_no_se_tocan():
    periods = [
        _period_2d(2022, None, roe=0.123, roic=0.111),
        _period_2d(2023, None, roe=0.456, roic=0.222),
    ]
    _apply_ltm_2d(periods)
    assert periods[0]["roe"] == 0.123
    assert periods[0]["roic"] == 0.111
    assert periods[1]["roe"] == 0.456
    assert periods[1]["roic"] == 0.222


def test_2d_q3_2023_con_historia_completa_calcula_ltm():
    # Para LTM en Q3 2023 necesitamos: Q4 2022, Q1 2023, Q2 2023, Q3 2023 (flujos)
    # y un balance 4Q ago = Q3 2022 (stock).
    periods = [
        _period_2d(2022, 3, equity=4000, total_debt=1500),  # stock 4Q ago
        _period_2d(2022, 4, net_income=110, ebitda=260, interest_expense=-22,
                   operating_income=210, revenue=1100, capex_total=90,
                   dividends_paid=35),
        _period_2d(2023, 1, net_income=120, ebitda=270, interest_expense=-24,
                   operating_income=220, revenue=1200, capex_total=100,
                   dividends_paid=40),
        _period_2d(2023, 2, net_income=130, ebitda=280, interest_expense=-26,
                   operating_income=230, revenue=1300, capex_total=110,
                   dividends_paid=45),
        _period_2d(2023, 3, net_income=140, ebitda=290, interest_expense=-28,
                   operating_income=240, revenue=1400, capex_total=120,
                   dividends_paid=50, equity=5500, total_debt=2100, net_debt=1600),
    ]
    _apply_ltm_2d(periods)
    q3_2023 = periods[-1]

    ltm_ni = 110 + 120 + 130 + 140  # 500
    ltm_oi = 210 + 220 + 230 + 240  # 900
    ltm_ie = -22 + -24 + -26 + -28  # -100
    ltm_ebitda = 260 + 270 + 280 + 290  # 1100
    ltm_capex = 90 + 100 + 110 + 120  # 420
    ltm_div = 35 + 40 + 45 + 50  # 170
    ltm_revenue = 1100 + 1200 + 1300 + 1400  # 5000
    avg_equity = (5500 + 4000) / 2  # 4750
    avg_ic = ((5500 + 2100) + (4000 + 1500)) / 2  # 6550

    assert q3_2023["roe"] == ltm_ni / avg_equity
    assert q3_2023["roic"] == ltm_ni / avg_ic
    assert q3_2023["interest_coverage"] == ltm_oi / abs(ltm_ie)
    assert q3_2023["interest_coverage_ebitda"] == ltm_ebitda / abs(ltm_ie)
    assert q3_2023["debt_to_ebitda"] == 2100 / ltm_ebitda
    assert q3_2023["net_debt_to_ebitda"] == 1600 / ltm_ebitda
    assert q3_2023["capex_intensity"] == ltm_capex / ltm_revenue
    # payout requiere 4Q de historia lagged (Q3 2021..Q2 2022); este dataset
    # solo provee desde Q3 2022, así que payout queda None.
    assert q3_2023["payout_ratio"] is None


def test_2d_periodos_sin_suficiente_historia_quedan_none():
    # Q3 2022 no tiene historia → None. Q3 2023 sí (igual al test anterior).
    periods = [
        _period_2d(2022, 3),
        _period_2d(2022, 4),
        _period_2d(2023, 1),
        _period_2d(2023, 2),
        _period_2d(2023, 3),
    ]
    _apply_ltm_2d(periods)
    assert periods[0]["roe"] is None  # Q3 2022 sin historia
    assert periods[-1]["roe"] is not None  # Q3 2023 con historia completa


# ---------------------------------------------------------------------------
# _apply_ltm_2f: cálculos LTM en bancos
# ---------------------------------------------------------------------------

def _period_2f(year, quarter, **overrides):
    base = {
        "fiscal_year": year,
        "quarter": quarter,
        "net_interest_income": 500.0,
        "loan_loss_provisions": -50.0,
        "net_income": 150.0,
        "dividends_paid": 40.0,
        "loans_net": 20000.0,
        "total_assets": 30000.0,
        "equity": 4000.0,
        "nim": 9999, "cost_of_risk": 9999, "roa": 9999, "roe": 9999,
        "payout_ratio": 9999,
    }
    base.update(overrides)
    return base


def test_2f_sin_historia_todas_las_ltm_son_none():
    periods = [_period_2f(2024, q) for q in (1, 2, 3, 4)]
    _apply_ltm_2f(periods)
    for p in periods:
        for m in ("nim", "cost_of_risk", "roa", "roe", "payout_ratio"):
            assert p[m] is None


def test_2f_q4_con_historia_completa_calcula_ltm():
    # Para Q4 2024 LTM: Q1-Q4 2024 (flujos) + balance Q4 2023 (stock 4Q ago)
    periods = [
        _period_2f(2023, 4, loans_net=18000, total_assets=28000, equity=3800),
        _period_2f(2024, 1, net_interest_income=510, loan_loss_provisions=-52,
                   net_income=155, dividends_paid=42),
        _period_2f(2024, 2, net_interest_income=520, loan_loss_provisions=-54,
                   net_income=160, dividends_paid=44),
        _period_2f(2024, 3, net_interest_income=530, loan_loss_provisions=-56,
                   net_income=165, dividends_paid=46),
        _period_2f(2024, 4, net_interest_income=540, loan_loss_provisions=-58,
                   net_income=170, dividends_paid=48,
                   loans_net=22000, total_assets=32000, equity=4400),
    ]
    _apply_ltm_2f(periods)
    q4 = periods[-1]

    ltm_nii = 510 + 520 + 530 + 540  # 2100
    ltm_llp = -52 + -54 + -56 + -58  # -220
    ltm_ni = 155 + 160 + 165 + 170  # 650
    ltm_div = 42 + 44 + 46 + 48  # 180
    avg_loans = (22000 + 18000) / 2  # 20000
    avg_assets = (32000 + 28000) / 2  # 30000
    avg_equity = (4400 + 3800) / 2  # 4100

    assert q4["nim"] == ltm_nii / avg_loans
    assert q4["cost_of_risk"] == abs(ltm_llp) / avg_loans
    assert q4["roa"] == ltm_ni / avg_assets
    assert q4["roe"] == ltm_ni / avg_equity
    # payout requiere NI lagged (Q4 2022..Q3 2023); este dataset solo llega
    # hasta Q4 2023, así que payout queda None.
    assert q4["payout_ratio"] is None


def test_2f_anuales_no_se_tocan():
    periods = [_period_2f(2023, None, roe=0.18, nim=0.05)]
    _apply_ltm_2f(periods)
    assert periods[0]["roe"] == 0.18
    assert periods[0]["nim"] == 0.05


# ---------------------------------------------------------------------------
# payout_ratio con lag T-1 (convención peruana JGA)
# ---------------------------------------------------------------------------

from smv_peru.client import _apply_payout_lagged_annual


def test_payout_ratio_anual_usa_ni_del_ano_anterior():
    """payout_T = |dividendos_T| / NI_(T-1). Refleja la JGA peruana que aprueba
    distribución sobre el ejercicio cerrado anterior.
    """
    periods = [
        {"fiscal_year": 2022, "quarter": None,
         "net_income": 500.0, "dividends_paid": -100.0, "payout_ratio": None},
        {"fiscal_year": 2023, "quarter": None,
         "net_income": 600.0, "dividends_paid": -150.0, "payout_ratio": None},
        {"fiscal_year": 2024, "quarter": None,
         "net_income": 700.0, "dividends_paid": -200.0, "payout_ratio": None},
    ]
    _apply_payout_lagged_annual(periods)
    # 2022: no hay 2021 en la serie → None
    assert periods[0]["payout_ratio"] is None
    # 2023: 150 / 500 (NI 2022) = 0.3
    assert periods[1]["payout_ratio"] == 150.0 / 500.0
    # 2024: 200 / 600 (NI 2023) ≈ 0.333
    assert periods[2]["payout_ratio"] == 200.0 / 600.0


def test_payout_ratio_anual_dividendos_signo_natural_se_normaliza():
    """SMV publica dividends_paid con signo natural (negativo = salida). El
    payout_ratio debe ser positivo."""
    periods = [
        {"fiscal_year": 2022, "quarter": None,
         "net_income": 1000.0, "dividends_paid": -250.0, "payout_ratio": None},
        {"fiscal_year": 2023, "quarter": None,
         "net_income": 1100.0, "dividends_paid": -300.0, "payout_ratio": None},
    ]
    _apply_payout_lagged_annual(periods)
    assert periods[1]["payout_ratio"] == 300.0 / 1000.0  # positivo


def test_payout_ratio_anual_no_toca_trimestrales():
    """_apply_payout_lagged_annual solo opera sobre períodos con quarter=None."""
    periods = [
        {"fiscal_year": 2023, "quarter": 1,
         "net_income": 100, "dividends_paid": -20, "payout_ratio": 0.999},
        {"fiscal_year": 2023, "quarter": None,
         "net_income": 500, "dividends_paid": -100, "payout_ratio": None},
    ]
    _apply_payout_lagged_annual(periods)
    assert periods[0]["payout_ratio"] == 0.999  # trimestral intacto


def test_payout_ratio_2d_ltm_usa_ni_lagged_4q_atras():
    """En trimestrales 2D, payout_ratio = |dividendos LTM (T)| / NI LTM lagged
    (los 4Q que terminan 4 trimestres antes de T). Necesita 8 trimestres de
    historia (4 actuales + 4 lagged).

    Para T=Q3 2024, la ventana lagged es Q4 2022..Q3 2023.
    """
    periods = [
        # Lagged window (NI base): Q4 2022..Q3 2023
        _period_2d(2022, 4, net_income=90, dividends_paid=10),
        _period_2d(2023, 1, net_income=100, dividends_paid=10),
        _period_2d(2023, 2, net_income=110, dividends_paid=10),
        # Q3 2023 también es stock 4Q ago para Q3 2024
        _period_2d(2023, 3, net_income=120, dividends_paid=10,
                   equity=4000, total_debt=1500),
        # Current LTM window (dividendos numerador)
        _period_2d(2023, 4, net_income=130, dividends_paid=50),
        _period_2d(2024, 1, net_income=140, dividends_paid=50),
        _period_2d(2024, 2, net_income=150, dividends_paid=50),
        _period_2d(2024, 3, net_income=160, dividends_paid=50,
                   equity=5500, total_debt=2100, net_debt=1600),
    ]
    _apply_ltm_2d(periods)
    q3_2024 = periods[-1]

    ltm_div_current = 50 + 50 + 50 + 50  # 200
    ltm_ni_lagged = 90 + 100 + 110 + 120  # 420 (Q4 2022..Q3 2023)
    assert q3_2024["payout_ratio"] == ltm_div_current / ltm_ni_lagged


def test_payout_ratio_2f_ltm_usa_ni_lagged_4q_atras():
    """En trimestrales 2F (bancos), misma convención: dividendos LTM (T) / NI
    LTM lagged. Para T=Q4 2024, la ventana lagged es Q1 2023..Q4 2023 (= año
    fiscal cerrado anterior).
    """
    periods = [
        # Lagged window: Q1 2023..Q4 2023 (= NI 2023 completo)
        _period_2f(2023, 1, net_income=110, dividends_paid=20),
        _period_2f(2023, 2, net_income=120, dividends_paid=20),
        _period_2f(2023, 3, net_income=130, dividends_paid=20),
        # Q4 2023 también es stock 4Q ago para Q4 2024
        _period_2f(2023, 4, net_income=140, dividends_paid=20,
                   loans_net=18000, total_assets=28000, equity=3800),
        # Current LTM window: Q1..Q4 2024
        _period_2f(2024, 1, net_income=150, dividends_paid=60),
        _period_2f(2024, 2, net_income=160, dividends_paid=60),
        _period_2f(2024, 3, net_income=170, dividends_paid=60),
        _period_2f(2024, 4, net_income=180, dividends_paid=60,
                   loans_net=22000, total_assets=32000, equity=4400),
    ]
    _apply_ltm_2f(periods)
    q4_2024 = periods[-1]

    ltm_div_current = 60 * 4  # 240
    ltm_ni_lagged = 110 + 120 + 130 + 140  # 500 (NI 2023 completo)
    assert q4_2024["payout_ratio"] == ltm_div_current / ltm_ni_lagged
