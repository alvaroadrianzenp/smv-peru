"""Tests para raw_accounts: cuentas crudas (no expuestas como amigables).

Verifica que:
- el dict existe y se puebla con datos reales,
- excluye los códigos ya cubiertos por algún campo amigable (cero duplicación),
- excluye cuentas con monto cero,
- preserva el `DescripcionCuenta` oficial de SMV.
"""
from pathlib import Path

from smv_peru import FIELDS_TO_CODES, fetch_estados_financieros
from smv_peru.client import CODIGOS_USADOS, _extract_raw_accounts

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Tests unitarios sobre _extract_raw_accounts
# ---------------------------------------------------------------------------

def test_excludes_codes_used_by_friendly_fields():
    """Códigos en CODIGOS_USADOS NO deben aparecer en raw_accounts."""
    rows = [
        {"Cuenta": "2D01ST", "DescripcionCuenta": "Ingresos", "Monto1": 100},
        {"Cuenta": "2D9999", "DescripcionCuenta": "Cuenta rara", "Monto1": 50},
    ]
    raw = _extract_raw_accounts(rows)
    assert "2D01ST" not in raw   # 2D01ST alimenta `revenue` (amigable)
    assert "2D9999" in raw       # no expuesta amigable, sí entra


def test_excludes_zero_amounts():
    rows = [
        {"Cuenta": "2D9999", "DescripcionCuenta": "Cero", "Monto1": 0},
        {"Cuenta": "2D9998", "DescripcionCuenta": "Cero negativo", "Monto1": -0.0},
        {"Cuenta": "2D9997", "DescripcionCuenta": "Real", "Monto1": 123},
    ]
    raw = _extract_raw_accounts(rows)
    assert "2D9999" not in raw
    assert "2D9998" not in raw
    assert "2D9997" in raw


def test_handles_missing_fields_gracefully():
    rows = [
        {"Cuenta": None, "DescripcionCuenta": "Sin código", "Monto1": 100},
        {"Cuenta": "2D9996", "DescripcionCuenta": "Sin monto", "Monto1": None},
        {"Cuenta": "2D9995", "DescripcionCuenta": "Texto inválido", "Monto1": "not-a-number"},
        {"Cuenta": "2D9994", "DescripcionCuenta": "OK", "Monto1": 999},
    ]
    raw = _extract_raw_accounts(rows)
    assert raw == {"2D9994": {"nombre": "OK", "monto": 999.0}}


def test_uses_codigo_as_fallback_when_descripcion_empty():
    rows = [
        {"Cuenta": "2D9993", "DescripcionCuenta": "", "Monto1": 50},
        {"Cuenta": "2D9992", "DescripcionCuenta": None, "Monto1": 60},
    ]
    raw = _extract_raw_accounts(rows)
    assert raw["2D9993"]["nombre"] == "2D9993"
    assert raw["2D9992"]["nombre"] == "2D9992"


def test_first_occurrence_wins_for_duplicates():
    """Si una cuenta aparece dos veces, gana la primera ocurrencia."""
    rows = [
        {"Cuenta": "2D9991", "DescripcionCuenta": "Primera", "Monto1": 100},
        {"Cuenta": "2D9991", "DescripcionCuenta": "Segunda", "Monto1": 200},
    ]
    raw = _extract_raw_accounts(rows)
    assert raw["2D9991"]["monto"] == 100
    assert raw["2D9991"]["nombre"] == "Primera"


# ---------------------------------------------------------------------------
# Integración con fetch_estados_financieros (datos reales de Alicorp 2023)
# ---------------------------------------------------------------------------

def test_raw_accounts_present_in_each_period():
    result = fetch_estados_financieros(
        "ALICORC1", desde=2021, hasta=2023, cache_dir=FIXTURES,
    )
    for p in result["periods"]:
        assert "raw_accounts" in p
        assert isinstance(p["raw_accounts"], dict)
        assert len(p["raw_accounts"]) > 0  # Alicorp publica decenas de cuentas extras


def test_raw_accounts_never_contains_friendly_field_codes():
    """Garantía estructural: ningún código amigable debe estar en raw_accounts."""
    result = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )
    p = result["periods"][0]
    intersection = set(p["raw_accounts"].keys()) & CODIGOS_USADOS
    assert intersection == set(), (
        f"Estos códigos están duplicados en raw_accounts y FIELDS_TO_CODES: {intersection}"
    )


def test_raw_accounts_entries_have_correct_structure():
    result = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )
    p = result["periods"][0]
    for codigo, info in p["raw_accounts"].items():
        assert isinstance(codigo, str)
        assert codigo[0] in {"1", "2", "3"}  # estado: balance, p&l, flujo
        assert "nombre" in info and isinstance(info["nombre"], str)
        assert "monto" in info and isinstance(info["monto"], float)
        assert info["monto"] != 0


def test_raw_accounts_includes_known_extra_account():
    """1D0114 (Otros Activos Financieros) NO está en amigables → debe estar en raw."""
    result = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )
    p = result["periods"][0]
    assert "1D0114" in p["raw_accounts"]
    assert "Otros Activos" in p["raw_accounts"]["1D0114"]["nombre"]


def test_fields_to_codes_is_complete_and_unique():
    """Sanity: el mapeo no tiene códigos duplicados (varios amigables al mismo
    código romperían la regla 1:1 y la lógica de exclusión de raw_accounts)."""
    codigos = list(FIELDS_TO_CODES.values())
    assert len(codigos) == len(set(codigos)), "Códigos duplicados en FIELDS_TO_CODES"
