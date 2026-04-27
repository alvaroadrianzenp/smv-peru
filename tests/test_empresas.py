"""Tests para el catálogo de tickers BVL y resolve_ticker."""
import pytest

from smv_peru.empresas import EMPRESAS, UnknownTickerError, resolve_ticker


def test_resolve_ticker_returns_dict():
    result = resolve_ticker("ALICORC1")
    assert result == EMPRESAS["ALICORC1"]
    assert result["rpj"] == "B30006"


def test_resolve_ticker_normalizes_to_uppercase():
    """Ticker en minúsculas debe resolverse igual."""
    assert resolve_ticker("alicorc1") == resolve_ticker("ALICORC1")


def test_resolve_ticker_strips_whitespace():
    """Espacios alrededor del ticker deben ignorarse."""
    assert resolve_ticker("  ALICORC1  ") == resolve_ticker("ALICORC1")


def test_unknown_ticker_raises_unknown_ticker_error():
    with pytest.raises(UnknownTickerError):
        resolve_ticker("FAKE99")


def test_unknown_ticker_message_lists_known_tickers():
    """El mensaje de error debe listar los tickers conocidos para ayudar."""
    with pytest.raises(UnknownTickerError, match="ALICORC1"):
        resolve_ticker("FAKE99")


def test_unknown_ticker_error_subclasses_keyerror():
    """Permite atrapar también como KeyError genérico."""
    assert issubclass(UnknownTickerError, KeyError)


def test_all_entries_have_required_fields():
    """Cada empresa del catálogo debe tener rpj, ruc, nombre."""
    for ticker, info in EMPRESAS.items():
        assert "rpj" in info, f"{ticker} sin rpj"
        assert "ruc" in info, f"{ticker} sin ruc"
        assert "nombre" in info, f"{ticker} sin nombre"
        assert info["rpj"], f"{ticker} con rpj vacío"
        assert info["nombre"], f"{ticker} con nombre vacío"
