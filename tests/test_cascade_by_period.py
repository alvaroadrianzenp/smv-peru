"""Tests para la cascada Consolidado→Individual por período.

Cuando SMV publica P&L y Flow Consolidados pero NO Balance Consolidado para
un RPJ en un año específico (caso conocido: BBVA Perú 2022), la librería cae
back a Individual solo para ese período. El resto de períodos del rango
mantienen su origen Consolidado. Cada período expone `tipo` con su origen real.
"""
import json
from pathlib import Path

from smv_peru import fetch_eeff
from smv_peru.client import _has_rpj_data


# ---------------------------------------------------------------------------
# _has_rpj_data
# ---------------------------------------------------------------------------

def test_has_rpj_data_lista_vacia():
    assert _has_rpj_data([], "B80004") is False
    assert _has_rpj_data(None, "B80004") is False


def test_has_rpj_data_rpj_presente():
    rows = [{"RPJ": "B80004", "Cuenta": "2F0101"}, {"RPJ": "OTRO", "Cuenta": "X"}]
    assert _has_rpj_data(rows, "B80004") is True


def test_has_rpj_data_rpj_ausente():
    rows = [{"RPJ": "OTRO1"}, {"RPJ": "OTRO2"}]
    assert _has_rpj_data(rows, "B80004") is False


# ---------------------------------------------------------------------------
# Cascada por período: BBVA 2022 simulado con fixtures sintéticos
# ---------------------------------------------------------------------------

def _row(rpj, cuenta, monto, **extra):
    """Fila SMV mínima."""
    base = {"RPJ": rpj, "Cuenta": cuenta, "Monto1": str(monto), "Monto2": None,
            "Moneda": "Soles", "MetodoFlujoEfectivo": "Método Indirecto"}
    base.update(extra)
    return base


def _write_cache(cache_dir, op, year, tipo, period, rows):
    """Escribe un fixture en el formato que el cliente lee."""
    path = cache_dir / f"obtener_{op}_{year}_{tipo}_{period}.json"
    path.write_text(json.dumps(rows))


def test_bbva_2022_consolidado_sin_balance_cae_a_individual(tmp_path):
    """Reproduce el bug real: PNL+Flow C presentes, Balance C vacío para BBVA;
    Individual completo. Esperamos que el período se recupere desde Individual
    y que `period["tipo"] == "individual"`. Otros años (con Consolidado completo)
    deben mantener `tipo == "consolidado"`."""
    rpj = "B80004"  # BBVA Perú según catálogo

    # 2021 — Consolidado completo (PNL, BAL, FLOW)
    _write_cache(tmp_path, "GanciaPerdida", 2021, "C", "A", [
        _row(rpj, "2F0101", 1_000_000),  # interest_income
        _row(rpj, "2F2301", 500_000),    # net_interest_income
    ])
    _write_cache(tmp_path, "BalanceGeneral", 2021, "C", "A", [
        _row(rpj, "1F3306", 5_000_000),  # equity
    ])
    _write_cache(tmp_path, "FlujoEfectivo", 2021, "C", "A", [
        _row(rpj, "3F0501", 200_000),  # operating_cf
    ])

    # 2022 — Consolidado INCOMPLETO: PNL y FLOW poblados, BAL VACÍO
    _write_cache(tmp_path, "GanciaPerdida", 2022, "C", "A", [
        _row(rpj, "2F0101", 1_100_000),
        _row(rpj, "2F2301", 550_000),
    ])
    _write_cache(tmp_path, "BalanceGeneral", 2022, "C", "A", [])  # ← gap SMV
    _write_cache(tmp_path, "FlujoEfectivo", 2022, "C", "A", [
        _row(rpj, "3F0501", 220_000),
    ])

    # 2022 — Individual COMPLETO (los tres). Esto es lo que SMV sí publica.
    _write_cache(tmp_path, "GanciaPerdida", 2022, "I", "A", [
        _row(rpj, "2F0101", 1_050_000),
        _row(rpj, "2F2301", 525_000),
    ])
    _write_cache(tmp_path, "BalanceGeneral", 2022, "I", "A", [
        _row(rpj, "1F3306", 5_300_000),
    ])
    _write_cache(tmp_path, "FlujoEfectivo", 2022, "I", "A", [
        _row(rpj, "3F0501", 210_000),
    ])

    # Pedimos 2021-2022 anuales en Consolidado
    result = fetch_eeff("BBVAC1", desde=2021, hasta=2022, periodicidad="anual",
                       cache_dir=tmp_path)
    assert result is not None
    by_year = {p["fiscal_year"]: p for p in result["periods"]}

    # 2021: Consolidado normal
    assert 2021 in by_year
    assert by_year[2021]["tipo"] == "consolidado"
    assert by_year[2021]["equity"] == 5_000_000

    # 2022: rescatado vía Individual
    assert 2022 in by_year, "2022 debería recuperarse via cascada por período"
    assert by_year[2022]["tipo"] == "individual"
    assert by_year[2022]["equity"] == 5_300_000  # valor de Individual, no Consolidado


def test_consolidado_completo_marca_tipo_consolidado(tmp_path):
    """Caso normal: si Consolidado tiene todo, period['tipo'] == 'consolidado'."""
    rpj = "B80004"
    _write_cache(tmp_path, "GanciaPerdida", 2023, "C", "A", [
        _row(rpj, "2F0101", 1_200_000), _row(rpj, "2F2301", 600_000),
    ])
    _write_cache(tmp_path, "BalanceGeneral", 2023, "C", "A", [
        _row(rpj, "1F3306", 5_500_000),
    ])
    _write_cache(tmp_path, "FlujoEfectivo", 2023, "C", "A", [
        _row(rpj, "3F0501", 240_000),
    ])

    result = fetch_eeff("BBVAC1", desde=2023, hasta=2023, periodicidad="anual",
                       cache_dir=tmp_path)
    assert result is not None
    assert result["periods"][0]["tipo"] == "consolidado"
