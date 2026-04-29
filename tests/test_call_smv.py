"""Tests para _call_smv: lectura desde cache, comportamiento offline."""
import urllib.error
from pathlib import Path

from smv_peru.client import _call_smv

FIXTURES = Path(__file__).parent / "fixtures"


def test_reads_from_cache_when_available_anual():
    """Si el archivo cacheado anual existe, _call_smv lo lee."""
    rows = _call_smv("obtener_BalanceGeneral", 2023, "A", "C", FIXTURES)
    assert rows is not None
    assert isinstance(rows, list)
    assert len(rows) > 0
    assert "RPJ" in rows[0]


def test_reads_from_cache_when_available_trimestral():
    """Funciona también con periodos trimestrales (1-4)."""
    rows = _call_smv("obtener_BalanceGeneral", 2023, "1", "C", FIXTURES)
    assert rows is not None
    assert len(rows) > 0


def test_does_not_hit_network_when_cached(monkeypatch):
    """Cuando hay cache, urlopen NO debe ser invocado."""
    def fail_if_called(*args, **kwargs):
        raise AssertionError("urlopen no debería invocarse cuando hay cache")
    monkeypatch.setattr("urllib.request.urlopen", fail_if_called)
    rows = _call_smv("obtener_GanciaPerdida", 2023, "A", "C", FIXTURES)
    assert rows is not None


def test_returns_none_when_cache_missing_and_network_fails(monkeypatch, tmp_path):
    """Si no hay cache y la red falla (incluyendo todos los reintentos),
    devuelve None (no crashea). Mockeamos time.sleep para no demorar el test."""
    def fake_urlopen(*args, **kwargs):
        raise urllib.error.URLError("simulated network failure")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    # Saltamos los sleeps del backoff para que el test sea rápido.
    monkeypatch.setattr("time.sleep", lambda *a, **kw: None)
    result = _call_smv("obtener_BalanceGeneral", 2099, "A", "C", tmp_path)
    assert result is None


def test_retries_on_transient_network_failure(monkeypatch, tmp_path):
    """Si la red falla 2 veces y luego responde, debería tener éxito al 3er intento."""
    import urllib.request
    from unittest.mock import MagicMock

    call_count = {"n": 0}
    def flaky_urlopen(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise urllib.error.URLError("simulated transient failure")
        # Tercera vez, responder con un Result válido (lista vacía OK)
        mock_resp = MagicMock()
        mock_resp.read.return_value = (
            b'<obtener_BalanceGeneralResult>[]</obtener_BalanceGeneralResult>'
        )
        mock_resp.__enter__ = lambda self: self
        mock_resp.__exit__ = lambda self, *a: None
        return mock_resp

    monkeypatch.setattr("urllib.request.urlopen", flaky_urlopen)
    monkeypatch.setattr("time.sleep", lambda *a, **kw: None)
    result = _call_smv("obtener_BalanceGeneral", 2099, "A", "C", tmp_path)
    assert call_count["n"] == 3
    assert result == []
