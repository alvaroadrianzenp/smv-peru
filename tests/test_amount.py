"""Tests para _amount: extrae el monto de una cuenta dentro de una lista de filas SMV."""
from smv_peru.client import _amount


def test_returns_float_when_cuenta_found():
    rows = [{"Cuenta": "2D01ST", "Monto1": "1000000"}]
    assert _amount(rows, "2D01ST") == 1_000_000.0


def test_returns_none_when_cuenta_not_found():
    rows = [{"Cuenta": "OTRA", "Monto1": "1000"}]
    assert _amount(rows, "2D01ST") is None


def test_returns_none_for_empty_rows():
    assert _amount([], "2D01ST") is None


def test_returns_none_when_monto_is_null():
    rows = [{"Cuenta": "2D01ST", "Monto1": None}]
    assert _amount(rows, "2D01ST") is None


def test_uses_custom_monto_field():
    rows = [{"Cuenta": "2D01ST", "Monto1": "100", "Monto2": "200"}]
    assert _amount(rows, "2D01ST", monto_field="Monto2") == 200.0


def test_returns_first_match_when_duplicates():
    """Si hay duplicados, devuelve el primero (comportamiento actual)."""
    rows = [
        {"Cuenta": "2D01ST", "Monto1": "100"},
        {"Cuenta": "2D01ST", "Monto1": "200"},
    ]
    assert _amount(rows, "2D01ST") == 100.0
