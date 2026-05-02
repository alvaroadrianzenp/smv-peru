"""Tests para los fallbacks de homogeneidad de la serie.

Política: la serie devuelta nunca mezcla Consolidado con Individual.

Cuando se pide `tipo="consolidado"`:
  1) Si solo falta el Balance Consolidado anual y existe Balance Q4
     Consolidado, usa Q4 como sustituto (stock idéntico al cierre anual).
     Mantiene la consistencia "Consolidado". Caso real: BBVA 2022. Cada
     período sustituido expone `balance_source="Q4_consolidado"`.
  2) Si ningún período del rango tiene Consolidado disponible para el RPJ,
     la cascada full-series final cae a Individual completo (toda la serie
     homogénea en I). Caso real: INTERBC1 (Interbank), CVERDEC1, etc.
  3) Si algunos períodos tienen Consolidado y otros no, los que no lo tienen
     se OMITEN (no se rellenan con Individual): mezclar tipos distorsiona la
     lectura del reporte.

Cada período expone `tipo` con su origen real ("consolidado" o "individual").
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
    # El pre-fetch acumula también las calls Individual del fallback;
    # las definimos vacías para que no intenten SOAP real durante el test.
    for op in ("GanciaPerdida", "BalanceGeneral", "FlujoEfectivo"):
        _write_cache(tmp_path, op, 2022, "I", "A", [])

    result = fetch_eeff("BBVAC1", desde=2022, hasta=2022, periodicidad="anual",
                       cache_dir=tmp_path)
    assert result is not None
    p = result["periods"][0]
    assert p["fiscal_year"] == 2022
    assert p["tipo"] == "consolidado"  # se mantuvo, no cayó a Individual
    assert p["balance_source"] == "Q4_consolidado"
    assert p["equity"] == 11_253_374


def test_si_q4_tampoco_existe_y_es_unico_periodo_cae_full_series_a_individual(tmp_path):
    """Si Balance C anual y Balance C Q4 están vacíos para el ÚNICO período
    del rango, periods_data queda vacío y la cascada full-series final cae
    a Individual (toda la serie en I, homogénea)."""
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
    assert "balance_source" not in p
    assert p["equity"] == 5_300_000


def test_periodo_sin_consolidado_se_omite_si_otros_periodos_si_lo_tienen(tmp_path):
    """Política de homogeneidad: si en un rango pedido como Consolidado un
    período NO tiene C disponible, ese período se OMITE — no se rellena con
    Individual. Caso real: trimestre más reciente aún sin publicar en C
    (UNACEM 2026Q1 al momento de pedir 2025Q1..2026Q1).
    """
    rpj = "B80004"

    # 2021 y 2022 anual: Consolidado completo
    for y in (2021, 2022):
        _write_cache(tmp_path, "GanciaPerdida", y, "C", "A", [
            _row(rpj, "2F0101", 1_100_000 + y),
            _row(rpj, "2F2301", 550_000),
        ])
        _write_cache(tmp_path, "BalanceGeneral", y, "C", "A", [
            _row(rpj, "1F3306", 11_000_000 + y),
        ])
        _write_cache(tmp_path, "FlujoEfectivo", y, "C", "A", [
            _row(rpj, "3F0501", 220_000),
        ])

    # 2023 anual: Consolidado vacío (período sin reportar aún en C)
    _write_cache(tmp_path, "GanciaPerdida", 2023, "C", "A", [])
    _write_cache(tmp_path, "BalanceGeneral", 2023, "C", "A", [])
    _write_cache(tmp_path, "FlujoEfectivo", 2023, "C", "A", [])
    _write_cache(tmp_path, "BalanceGeneral", 2023, "C", "4", [])  # Q4 también vacío

    # Individual sí existe para 2023 — la librería lo IGNORA porque hay
    # otros períodos con Consolidado (no se mezcla).
    _write_cache(tmp_path, "GanciaPerdida", 2023, "I", "A", [
        _row(rpj, "2F0101", 200_000),  # holding sola: ~10x menor
    ])
    _write_cache(tmp_path, "BalanceGeneral", 2023, "I", "A", [
        _row(rpj, "1F3306", 1_500_000),
    ])
    _write_cache(tmp_path, "FlujoEfectivo", 2023, "I", "A", [
        _row(rpj, "3F0501", 30_000),
    ])

    result = fetch_eeff("BBVAC1", desde=2021, hasta=2023, periodicidad="anual",
                       cache_dir=tmp_path)
    assert result is not None
    years = [p["fiscal_year"] for p in result["periods"]]
    assert years == [2021, 2022]  # 2023 omitido
    for p in result["periods"]:
        assert p["tipo"] == "consolidado"
    assert (2023, None) in result["info"]["periods_missing"]


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
