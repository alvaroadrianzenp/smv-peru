"""Catálogo de tickers BVL → identificadores SMV.

Mapea el ticker que conoce el usuario (ej. ``"ALICORC1"``) a los códigos
internos que usa SMV: el RPJ (identificador interno), el RUC y el nombre.

El catálogo cubre por ahora las empresas que reportan EEFF a SMV con
esquema contable 2D (industriales, NIIF estándar). Algunas reportan en
modo Consolidado (matrices con subsidiarias) y otras solo en Individual
(subsidiarias de matrices extranjeras como Cerro Verde, PLUZ, Nexa);
la cascada automática del cliente prueba primero Consolidado y cae a
Individual si no hay datos. Se irá ampliando conforme se añada soporte
para más esquemas (bancos = 2F, aseguradoras = 2E).
"""
from __future__ import annotations


EMPRESAS: dict[str, dict[str, str]] = {
    "AENZAC1":  {"rpj": "023106", "ruc": "20332600592", "nombre": "AENZA (ex Graña y Montero)"},
    "ALICORC1": {"rpj": "B30006", "ruc": "20100055237", "nombre": "Alicorp S.A.A."},
    "BACKUSI1": {"rpj": "B30021", "ruc": "20100113610", "nombre": "Backus & Johnston"},
    "BVN":      {"rpj": "B20003", "ruc": "20100079501", "nombre": "Buenaventura"},
    "CASAGRC1": {"rpj": "B08361", "ruc": "20131823020", "nombre": "Casa Grande"},
    "CORAREI1": {"rpj": "CI0003", "ruc": "20370146994", "nombre": "Aceros Arequipa"},
    "CPACASC1": {"rpj": "CD0005", "ruc": "20419387658", "nombre": "Cementos Pacasmayo"},
    "CVERDEC1": {"rpj": "CM0006", "ruc": "20170072465", "nombre": "Sociedad Minera Cerro Verde"},
    "ENGEPEC1": {"rpj": "002829", "ruc": "20333363900", "nombre": "Engie Perú"},
    "FERREYC1": {"rpj": "B60001", "ruc": "20100027292", "nombre": "Ferreycorp"},
    "INRETC1":  {"rpj": "OE5087", "ruc": "0",           "nombre": "InRetail Perú"},
    "LUSURC1":  {"rpj": "B40008", "ruc": "20331898008", "nombre": "Luz del Sur"},
    "MINSURI1": {"rpj": "A20032", "ruc": "20100136741", "nombre": "Minsur"},
    "NEXAPEC1": {"rpj": "B20010", "ruc": "20100110513", "nombre": "Nexa Resources Perú (ex Milpo)"},
    "ORYGENC1": {"rpj": "B40009", "ruc": "20330791412", "nombre": "Orygen Perú (ex Enel Generación)"},
    "PLUZC1":   {"rpj": "B40010", "ruc": "20269985900", "nombre": "Pluz Energía Perú (ex Enel Distribución)"},
    "RELAPAC1": {"rpj": "002766", "ruc": "20259829594", "nombre": "Refinería La Pampilla"},
    "UNACEMC1": {"rpj": "B30121", "ruc": "20100137390", "nombre": "UNACEM"},
    "VOLCABC1": {"rpj": "CM0001", "ruc": "20383045267", "nombre": "Volcan Compañía Minera"},
    "YURAC1":   {"rpj": "023490", "ruc": "20312372895", "nombre": "Yura"},
}


class UnknownTickerError(KeyError):
    """Se levanta cuando el ticker solicitado no está en el catálogo."""


def resolve_ticker(ticker: str) -> dict[str, str]:
    """Devuelve los datos SMV (rpj, ruc, nombre) de un ticker BVL.

    El ticker se normaliza a mayúsculas y se le quitan espacios. Si no está
    en el catálogo, se levanta UnknownTickerError con la lista de tickers
    conocidos en el mensaje.
    """
    t = ticker.upper().strip()
    if t not in EMPRESAS:
        conocidos = ", ".join(sorted(EMPRESAS))
        raise UnknownTickerError(
            f"Ticker {t!r} no está en el catálogo. Conocidos: {conocidos}"
        )
    return EMPRESAS[t]
