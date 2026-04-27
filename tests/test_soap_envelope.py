"""Tests para _soap_envelope: construye el body XML del request SOAP a SMV."""
import xml.etree.ElementTree as ET

from smv_peru.client import _soap_envelope


def test_returns_bytes():
    """El envelope se manda por HTTP como bytes."""
    assert isinstance(_soap_envelope("obtener_GanciaPerdida", 2023), bytes)


def test_contains_operacion():
    body = _soap_envelope("obtener_GanciaPerdida", 2023).decode()
    assert "<obtener_GanciaPerdida" in body
    assert "</obtener_GanciaPerdida>" in body


def test_contains_ejercicio():
    body = _soap_envelope("obtener_GanciaPerdida", 2023).decode()
    assert "<Ejercicio>2023</Ejercicio>" in body


def test_default_tipo_is_consolidado():
    body = _soap_envelope("obtener_GanciaPerdida", 2023).decode()
    assert "<Tipo>C</Tipo>" in body


def test_tipo_individual():
    body = _soap_envelope("obtener_BalanceGeneral", 2023, tipo="I").decode()
    assert "<Tipo>I</Tipo>" in body


def test_periodo_is_hardcoded_anual():
    """La librería solo soporta periodicidad anual; el envelope siempre lleva 'A'."""
    body = _soap_envelope("obtener_GanciaPerdida", 2023).decode()
    assert "<Periodo>A</Periodo>" in body


def test_is_valid_xml():
    """El envelope generado es XML parseable, sin escapes rotos."""
    body = _soap_envelope("obtener_GanciaPerdida", 2023)
    ET.fromstring(body)  # lanza si no es XML válido
