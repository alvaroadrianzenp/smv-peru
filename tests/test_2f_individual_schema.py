"""Tests para el esquema 2F Individual SBS (formato distinto al Consolidado).

SMV publica los EEFF Individuales de bancos con códigos diferentes al esquema
Consolidado NIIF (formato SBS más detallado). La librería detecta el esquema
automáticamente vía marcadores `2F1302`/`2F2306` y aplica los overrides.

Casos cubiertos:
- Detección del esquema cuando hay marcadores Individual.
- Override directo de código (loan_loss_provisions, pretax_income, eps...).
- Campos compuestos (fee_income_net, operating_expenses).
- Campos no disponibles en Individual (loans_lt, financial_debt_st...).
"""
import json

from smv_peru import fetch_eeff
from smv_peru.client import _is_2f_individual_schema


def test_detector_marca_individual_si_tiene_2f1302():
    rows = [{"Cuenta": "2F1302", "Monto1": 1000}]
    assert _is_2f_individual_schema(rows) is True


def test_detector_marca_individual_si_tiene_2f2306():
    rows = [{"Cuenta": "2F2306", "Monto1": -500}]
    assert _is_2f_individual_schema(rows) is True


def test_detector_marca_consolidado_si_solo_tiene_codigos_consolidado():
    rows = [
        {"Cuenta": "2F2809", "Monto1": 1000},  # pretax C
        {"Cuenta": "2F2304", "Monto1": -500},  # LLP C
        {"Cuenta": "2F2201", "Monto1": 0.5},   # eps básica (aparece en ambos)
    ]
    assert _is_2f_individual_schema(rows) is False


def _row(rpj, cuenta, monto, **extra):
    base = {"RPJ": rpj, "Cuenta": cuenta, "Monto1": monto, "Monto2": None,
            "Moneda": "Soles", "MetodoFlujoEfectivo": "Método Indirecto"}
    base.update(extra)
    return base


def _write_cache(cache_dir, op, year, tipo, period, rows):
    path = cache_dir / f"obtener_{op}_{year}_{tipo}_{period}.json"
    path.write_text(json.dumps(rows))


def test_interbank_individual_mapea_overrides_correctamente(tmp_path):
    """Reproduce el caso real: Interbank cae a Individual, los códigos del
    esquema SBS se mapean correctamente a los campos amigables."""
    rpj = "B80020"
    # Cache C vacío para forzar early-exit a Individual
    _write_cache(tmp_path, "GanciaPerdida", 2024, "C", "A", [])
    _write_cache(tmp_path, "BalanceGeneral", 2024, "C", "A", [])
    _write_cache(tmp_path, "FlujoEfectivo", 2024, "C", "A", [])

    # Individual con códigos del esquema SBS
    _write_cache(tmp_path, "GanciaPerdida", 2024, "I", "A", [
        _row(rpj, "2F0101", 5_913_208),     # interest_income (mismo en ambos)
        _row(rpj, "2F0301", -2_124_356),    # interest_expense (mismo)
        _row(rpj, "2F2301", 3_788_852),     # net_interest_income (mismo)
        _row(rpj, "2F2306", -1_769_217),    # ← override: loan_loss_provisions
        _row(rpj, "2F1302", 1_156_769),     # ← override: pretax_income
        _row(rpj, "2F1403", -223_099),      # income_tax (mismo)
        _row(rpj, "2F1901", 933_670),       # net_income (mismo)
        _row(rpj, "2F2201", 0.148),         # ← override: eps
        _row(rpj, "2F2202", 0.148),         # ← override: eps_diluted
        _row(rpj, "2F2402", 1_162_997),     # composite parte 1: ingresos servicios
        _row(rpj, "2F2501", -544_161),      # composite parte 2: gastos servicios
        _row(rpj, "2F2603", -645_971),      # composite operating_expenses parte 1
        _row(rpj, "2F2604", -1_023_204),    # parte 2
        _row(rpj, "2F2605", -30_994),       # parte 3
        _row(rpj, "2F0906", -261_581),      # parte 4 (D&A)
        _row(rpj, "2F2801", 1_134_689),     # operating_income (mismo)
        _row(rpj, "2F2506", 475_190),       # trading_income (mismo)
    ])
    _write_cache(tmp_path, "BalanceGeneral", 2024, "I", "A", [
        _row(rpj, "1F0111", 47_190_332),    # loans_st (CARTERA DE CREDITOS — total)
        _row(rpj, "1F2401", 11_632_841),    # ← override: financial_debt_lt
        _row(rpj, "1F2001", 72_952_708),    # total_assets
        _row(rpj, "1F2101", 50_336_564),    # deposits
        _row(rpj, "1F3306", 8_454_827),     # equity
    ])
    _write_cache(tmp_path, "FlujoEfectivo", 2024, "I", "A", [
        _row(rpj, "3F0501", 4_793_629),     # operating_cf (mismo)
        _row(rpj, "3F0301", 261_581),       # dna (mismo)
        _row(rpj, "3F0418", -4_281_686),    # ← override: loans_change
    ])

    result = fetch_eeff("INTERBC1", desde=2024, hasta=2024, periodicidad="anual",
                       cache_dir=tmp_path)
    assert result is not None
    p = result["periods"][0]
    assert p["tipo"] == "individual"

    # Overrides directos
    assert p["loan_loss_provisions"] == -1_769_217
    assert p["pretax_income"] == 1_156_769
    assert p["eps"] == 0.148
    assert p["eps_diluted"] == 0.148
    assert p["loans_change"] == -4_281_686
    assert p["financial_debt_lt"] == 11_632_841

    # Composites
    assert p["fee_income_net"] == 1_162_997 + (-544_161)  # = 618,836
    assert p["operating_expenses"] == -645_971 + -1_023_204 + -30_994 + -261_581

    # No disponibles en Individual → None
    assert p["loans_lt"] is None
    assert p["financial_debt_st"] is None
    assert p["deposits_change"] is None
