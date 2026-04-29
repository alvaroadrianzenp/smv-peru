"""Tests para fetch_multi: descarga de múltiples empresas."""
from pathlib import Path

import pytest

from smv_peru import fetch_multi

FIXTURES = Path(__file__).parent / "fixtures"


def test_fetch_multi_returns_dict_of_results():
    result = fetch_multi(
        ["ALICORC1", "BBVAC1"], desde=2024, hasta=2024,
        cache_dir=FIXTURES,
    )
    assert isinstance(result, dict)
    assert set(result.keys()) == {"ALICORC1", "BBVAC1"}


def test_fetch_multi_each_value_has_periods():
    result = fetch_multi(
        ["ALICORC1"], desde=2023, hasta=2023,
        cache_dir=FIXTURES,
    )
    assert result["ALICORC1"] is not None
    assert "periods" in result["ALICORC1"]
    assert len(result["ALICORC1"]["periods"]) == 1


def test_fetch_multi_empty_list_returns_empty_dict():
    result = fetch_multi([], desde=2023, hasta=2023, cache_dir=FIXTURES)
    assert result == {}


def test_fetch_multi_handles_unknown_ticker_gracefully():
    """Ticker inválido en la lista no aborta los demás; queda como None."""
    result = fetch_multi(
        ["ALICORC1", "FAKE99"], desde=2023, hasta=2023,
        cache_dir=FIXTURES,
    )
    assert result["ALICORC1"] is not None
    assert result["FAKE99"] is None


def test_fetch_multi_validates_max_workers_upper_bound():
    with pytest.raises(ValueError, match="max_workers"):
        fetch_multi(
            ["ALICORC1"], desde=2023, hasta=2023,
            cache_dir=FIXTURES, max_workers=11,  # > MAX_WORKERS_LIMIT
        )


def test_fetch_estados_financieros_validates_max_workers_upper_bound():
    """Mismo límite aplica al fetch single."""
    from smv_peru import fetch_estados_financieros
    with pytest.raises(ValueError, match="max_workers"):
        fetch_estados_financieros(
            "ALICORC1", desde=2023, hasta=2023,
            cache_dir=FIXTURES, max_workers=15,
        )
