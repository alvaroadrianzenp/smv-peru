"""Tests para _call_smv: lectura desde cache, comportamiento offline."""
import urllib.error
from pathlib import Path

from smv_peru.client import _call_smv

FIXTURES = Path(__file__).parent / "fixtures"


def test_reads_from_cache_when_available():
    """Si el archivo cacheado existe, _call_smv lo lee y devuelve la lista."""
    rows = _call_smv("obtener_BalanceGeneral", 2023, "C", FIXTURES)
    assert rows is not None
    assert isinstance(rows, list)
    assert len(rows) > 0
    assert "RPJ" in rows[0]
    assert "Cuenta" in rows[0]


def test_does_not_hit_network_when_cached(monkeypatch):
    """Cuando hay cache, urlopen NO debe ser invocado."""
    def fail_if_called(*args, **kwargs):
        raise AssertionError("urlopen no debería invocarse cuando hay cache")
    monkeypatch.setattr("urllib.request.urlopen", fail_if_called)
    rows = _call_smv("obtener_GanciaPerdida", 2023, "C", FIXTURES)
    assert rows is not None


def test_returns_none_when_cache_missing_and_network_fails(monkeypatch, tmp_path):
    """Si no hay cache y la red falla, devuelve None (no crashea)."""
    def fake_urlopen(*args, **kwargs):
        raise urllib.error.URLError("simulated network failure")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    # tmp_path está vacío → sin cache. urlopen falla → debe devolver None.
    result = _call_smv("obtener_BalanceGeneral", 2099, "C", tmp_path)
    assert result is None
