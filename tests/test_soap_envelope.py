"""Tests para _soap_envelope: construye el body XML del request SOAP a SMV."""
import xml.etree.ElementTree as ET

from smv_peru.client import _soap_envelope


def test_returns_bytes():
    """El envelope se manda por HTTP como bytes."""
    assert isinstance(_soap_envelope("obtener_GanciaPerdida", 2023, "A", "C"), bytes)


def test_contains_operacion():
    body = _soap_envelope("obtener_GanciaPerdida", 2023, "A", "C").decode()
    assert "<obtener_GanciaPerdida" in body
    assert "</obtener_GanciaPerdida>" in body


def test_contains_ejercicio():
    body = _soap_envelope("obtener_GanciaPerdida", 2023, "A", "C").decode()
    assert "<Ejercicio>2023</Ejercicio>" in body


def test_periodo_anual():
    body = _soap_envelope("obtener_GanciaPerdida", 2023, "A", "C").decode()
    assert "<Periodo>A</Periodo>" in body


def test_periodo_trimestrales():
    """Códigos 1-4 corresponden a los trimestres Q1-Q4."""
    for q in ["1", "2", "3", "4"]:
        body = _soap_envelope("obtener_GanciaPerdida", 2023, q, "C").decode()
        assert f"<Periodo>{q}</Periodo>" in body


def test_tipo_consolidado():
    body = _soap_envelope("obtener_GanciaPerdida", 2023, "A", "C").decode()
    assert "<Tipo>C</Tipo>" in body


def test_tipo_individual():
    body = _soap_envelope("obtener_BalanceGeneral", 2023, "A", "I").decode()
    assert "<Tipo>I</Tipo>" in body


def test_is_valid_xml():
    """El envelope generado es XML parseable, sin escapes rotos."""
    body = _soap_envelope("obtener_GanciaPerdida", 2023, "A", "C")
    ET.fromstring(body)
