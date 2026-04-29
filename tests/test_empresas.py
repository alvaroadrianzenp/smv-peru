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


def test_catalog_has_at_least_20_tickers():
    """El catálogo cubre las ~20 acciones más líquidas de BVL con esquema 2D."""
    assert len(EMPRESAS) >= 20


def test_no_duplicate_rpj_in_catalog():
    """Cada RPJ debe ser único: dos tickers no pueden mapear a la misma empresa."""
    rpjs = [info["rpj"] for info in EMPRESAS.values()]
    assert len(rpjs) == len(set(rpjs)), "Hay RPJs duplicados en el catálogo"


def test_resolve_some_new_tickers():
    """Smoke test: los nuevos tickers (incluyendo los que reportan Individual) resuelven."""
    nuevos = ["AENZAC1", "BVN", "CASAGRC1", "CORAREI1", "CVERDEC1",
              "NEXAPEC1", "ORYGENC1", "PLUZC1", "RELAPAC1", "YURAC1"]
    for ticker in nuevos:
        info = resolve_ticker(ticker)
        assert info["rpj"], f"{ticker} sin rpj"
        assert info["nombre"], f"{ticker} sin nombre"


def test_no_sucursal_or_branch_entities_in_catalog():
    """Garantía de integridad: el catálogo no debe incluir sucursales (SCCO fue
    el caso histórico — ticker BVL apuntaba a la matriz NYSE pero los datos
    SMV eran de la sucursal peruana, engañoso)."""
    for ticker, info in EMPRESAS.items():
        nombre_up = info["nombre"].upper()
        assert "SUCURSAL" not in nombre_up, (
            f"Ticker {ticker} parece ser una sucursal ({info['nombre']!r}). "
            f"Las sucursales son entidades operativas, no cotizan; usar "
            f"sucursal cuando el ticker BVL es de la matriz puede engañar."
        )


def test_scco_is_no_longer_in_catalog():
    """SCCO removido en versión post-Tier B: la matriz Southern Copper
    Corporation no reporta a SMV (reporta a SEC americana). Lo único en SMV
    es la sucursal peruana, que no es lo que cotiza el ticker BVL/NYSE.
    Removerla evita engañar al usuario."""
    assert "SCCO" not in EMPRESAS
