"""Tests para la cascada de fallbacks por período.

Orden de fallbacks cuando Consolidado anual está incompleto para un RPJ:
  1) Si solo falta el Balance Consolidado y existe Balance Q4 Consolidado,
     usa Q4 como sustituto (stock idéntico al cierre anual). Mantiene la
     consistencia "Consolidado" del reporte. Caso real: BBVA 2022.
  2) Si lo anterior no aplica o también falla, cascada a Individual completo
     del mismo período. Caso real hipotético / casos edge.

Cada período expone `tipo` con su origen real ("consolidado" o "individual")
y, opcionalmente, `balance_source="Q4_consolidado"` cuando hubo sustitución.
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


def test_bbva_2022_balance_anual_ausente_usa_q4_consolidado(tmp_path):
    """Caso real BBVA 2022: PNL+Flow C anuales OK, Balance C anual vacío,
    pero Balance C Q4 SÍ existe. La librería usa Q4 C como sustituto y
    mantiene `tipo='consolidado'` con marca `balance_source='Q4_consolidado'`.
    """
    rpj = "B80004"

    # 2022 anual: PNL y Flow C OK, Balance C anual vacío
    _write_cache(tmp_path, "GanciaPerdida", 2022, "C", "A", [
        _row(rpj, "2F0101", 1_100_000), _row(rpj, "2F2301", 550_000),
    ])
    _write_cache(tmp_path, "BalanceGeneral", 2022, "C", "A", [])  # ← gap SMV
    _write_cache(tmp_path, "FlujoEfectivo", 2022, "C", "A", [
        _row(rpj, "3F0501", 220_000),
    ])
    # Balance C Q4 SÍ existe (esto es lo que SMV publica para BBVA 2022)
    _write_cache(tmp_path, "BalanceGeneral", 2022, "C", "4", [
        _row(rpj, "1F3306", 11_253_374),  # equity = patrimonio cierre Q4
    ])

    result = fetch_eeff("BBVAC1", desde=2022, hasta=2022, periodicidad="anual",
                       cache_dir=tmp_path)
    assert result is not None
    p = result["periods"][0]
    assert p["fiscal_year"] == 2022
    assert p["tipo"] == "consolidado"  # se mantuvo, no cayó a Individual
    assert p["balance_source"] == "Q4_consolidado"
    assert p["equity"] == 11_253_374


def test_si_q4_tampoco_existe_cae_a_individual(tmp_path):
    """Si Balance C anual y Balance C Q4 ambos están vacíos, se intenta
    Individual completo (segundo fallback)."""
    rpj = "B80004"

    _write_cache(tmp_path, "GanciaPerdida", 2022, "C", "A", [
        _row(rpj, "2F0101", 1_100_000), _row(rpj, "2F2301", 550_000),
    ])
    _write_cache(tmp_path, "BalanceGeneral", 2022, "C", "A", [])
    _write_cache(tmp_path, "FlujoEfectivo", 2022, "C", "A", [
        _row(rpj, "3F0501", 220_000),
    ])
    # Q4 también vacío
    _write_cache(tmp_path, "BalanceGeneral", 2022, "C", "4", [])

    # Individual COMPLETO
    _write_cache(tmp_path, "GanciaPerdida", 2022, "I", "A", [
        _row(rpj, "2F0101", 1_050_000), _row(rpj, "2F2301", 525_000),
    ])
    _write_cache(tmp_path, "BalanceGeneral", 2022, "I", "A", [
        _row(rpj, "1F3306", 5_300_000),
    ])
    _write_cache(tmp_path, "FlujoEfectivo", 2022, "I", "A", [
        _row(rpj, "3F0501", 210_000),
    ])

    result = fetch_eeff("BBVAC1", desde=2022, hasta=2022, periodicidad="anual",
                       cache_dir=tmp_path)
    assert result is not None
    p = result["periods"][0]
    assert p["tipo"] == "individual"
    assert "balance_source" not in p  # no aplica cuando es Individual
    assert p["equity"] == 5_300_000


def test_early_exit_a_individual_si_rpj_nunca_aparece_en_consolidado(tmp_path):
    """Cuando el RPJ NO está en ningún resultado Consolidado del rango (caso
    INTERBC1, que SMV publica solo en Individual), la librería debe ir directo
    a Individual sin pasar por cascadas por período. Antes este caso degradaba
    a cascadas serial = ~15 calls SOAP secuenciales por ticker.
    """
    rpj = "B80020"  # INTERBC1

    # 3 años de Consolidado completamente vacíos para este RPJ
    for y in (2020, 2021, 2022):
        _write_cache(tmp_path, "GanciaPerdida", y, "C", "A", [])
        _write_cache(tmp_path, "BalanceGeneral", y, "C", "A", [])
        _write_cache(tmp_path, "FlujoEfectivo", y, "C", "A", [])

    # Individual completo (lo que SMV sí publica para Interbank)
    for y in (2020, 2021, 2022):
        _write_cache(tmp_path, "GanciaPerdida", y, "I", "A", [
            _row(rpj, "2F0101", 1_000_000 + y), _row(rpj, "2F2301", 500_000),
        ])
        _write_cache(tmp_path, "BalanceGeneral", y, "I", "A", [
            _row(rpj, "1F3306", 5_000_000 + y),
        ])
        _write_cache(tmp_path, "FlujoEfectivo", y, "I", "A", [
            _row(rpj, "3F0501", 200_000),
        ])

    result = fetch_eeff("INTERBC1", desde=2020, hasta=2022, periodicidad="anual",
                       cache_dir=tmp_path)
    assert result is not None
    assert len(result["periods"]) == 3
    for p in result["periods"]:
        assert p["tipo"] == "individual"
        assert "balance_source" not in p
    assert result["info"]["tipo"] == "individual"


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
