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
    """Cuando hay cache, el opener HTTP NO debe ser invocado."""
    def fail_if_called(*args, **kwargs):
        raise AssertionError("opener.open no debería invocarse cuando hay cache")
    monkeypatch.setattr("smv_peru.client._SMV_OPENER.open", fail_if_called)
    rows = _call_smv("obtener_GanciaPerdida", 2023, "A", "C", FIXTURES)
    assert rows is not None


def test_returns_none_when_cache_missing_and_network_fails(monkeypatch, tmp_path):
    """Si no hay cache y la red falla (incluyendo todos los reintentos),
    devuelve None (no crashea). Mockeamos time.sleep para no demorar el test."""
    def fake_open(*args, **kwargs):
        raise urllib.error.URLError("simulated network failure")
    monkeypatch.setattr("smv_peru.client._SMV_OPENER.open", fake_open)
    # Saltamos los sleeps del backoff para que el test sea rápido.
    monkeypatch.setattr("time.sleep", lambda *a, **kw: None)
    result = _call_smv("obtener_BalanceGeneral", 2099, "A", "C", tmp_path)
    assert result is None


def _make_mock_response(body_bytes: bytes,
                       url: str = "https://mvnet.smv.gob.pe/ws_od_eeff/WebServiceInfoFinanciera.asmx"):
    """Construye una respuesta mock con .url configurado para pasar la
    validación de host del cliente."""
    from unittest.mock import MagicMock
    mock_resp = MagicMock()
    mock_resp.read.return_value = body_bytes
    mock_resp.url = url
    mock_resp.__enter__ = lambda self: self
    mock_resp.__exit__ = lambda self, *a: None
    return mock_resp


def test_writes_cache_as_gzip(monkeypatch, tmp_path):
    """Después de descargar exitosamente, el cache se escribe como .json.gz
    (no .json). Reduce ~96% el tamaño en disco."""
    def fake_open(*args, **kwargs):
        return _make_mock_response(
            b'<obtener_BalanceGeneralResult>'
            b'[{"RPJ":"X","Cuenta":"1D01ST","Monto1":100}]'
            b'</obtener_BalanceGeneralResult>'
        )

    monkeypatch.setattr("smv_peru.client._SMV_OPENER.open", fake_open)
    result = _call_smv("obtener_BalanceGeneral", 2024, "A", "C", tmp_path)
    assert result is not None

    # Verificar que se creó .json.gz (no .json)
    gz_file = tmp_path / "obtener_BalanceGeneral_2024_C_A.json.gz"
    json_file = tmp_path / "obtener_BalanceGeneral_2024_C_A.json"
    assert gz_file.exists(), "Cache nuevo debe escribirse como .json.gz"
    assert not json_file.exists(), "No debe escribir formato .json legacy"


def test_reads_cache_legacy_json_format(tmp_path):
    """Cache pre-existente en formato .json (versión <0.1.0) debe leerse igual."""
    import json
    legacy_file = tmp_path / "obtener_BalanceGeneral_2024_C_A.json"
    legacy_file.write_text(
        json.dumps([{"RPJ": "X", "Cuenta": "1D01ST", "Monto1": 100}]),
        encoding="utf-8",
    )
    result = _call_smv("obtener_BalanceGeneral", 2024, "A", "C", tmp_path)
    assert result == [{"RPJ": "X", "Cuenta": "1D01ST", "Monto1": 100}]


def test_retries_on_transient_network_failure(monkeypatch, tmp_path):
    """Si la red falla 2 veces y luego responde, debería tener éxito al 3er intento."""
    call_count = {"n": 0}
    def flaky_open(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise urllib.error.URLError("simulated transient failure")
        return _make_mock_response(
            b'<obtener_BalanceGeneralResult>[]</obtener_BalanceGeneralResult>'
        )

    monkeypatch.setattr("smv_peru.client._SMV_OPENER.open", flaky_open)
    monkeypatch.setattr("time.sleep", lambda *a, **kw: None)
    result = _call_smv("obtener_BalanceGeneral", 2099, "A", "C", tmp_path)
    assert call_count["n"] == 3
    assert result == []


def test_rechaza_respuesta_de_host_distinto(monkeypatch, tmp_path):
    """Si la URL final tras la respuesta no apunta a mvnet.smv.gob.pe,
    descartar la respuesta y NO cachearla. Defensa contra cache poisoning
    via redirect / MITM con CA comprometida.
    """
    def attacker_open(*args, **kwargs):
        return _make_mock_response(
            b'<obtener_BalanceGeneralResult>'
            b'[{"RPJ":"FALSE","Cuenta":"1D01ST","Monto1":99999}]'
            b'</obtener_BalanceGeneralResult>',
            url="https://attacker.example.com/evil",
        )

    monkeypatch.setattr("smv_peru.client._SMV_OPENER.open", attacker_open)
    monkeypatch.setattr("time.sleep", lambda *a, **kw: None)
    result = _call_smv("obtener_BalanceGeneral", 2099, "A", "C", tmp_path)
    assert result is None
    # Verificar que NO se escribió cache envenenado
    assert not (tmp_path / "obtener_BalanceGeneral_2099_C_A.json.gz").exists()
