"""Catálogo de tickers BVL → identificadores SMV.

Mapea el ticker que conoce el usuario (ej. ``"ALICORC1"``) a los códigos
internos que usa SMV: el RPJ (identificador interno), el RUC, el nombre
y el esquema contable.

Esquemas contables soportados:
- ``"2D"``: industriales y similares (NIIF estándar). Ver ``FIELDS_TO_CODES_2D``.
- ``"2F"``: bancos y financieras. Ver ``FIELDS_TO_CODES_2F``.
- ``"2E"`` (futuro): aseguradoras.

Algunas empresas reportan en modo Consolidado (matrices con subsidiarias)
y otras solo en Individual (subsidiarias de matrices extranjeras como
Cerro Verde, PLUZ, Nexa); la cascada automática del cliente prueba primero
Consolidado y cae a Individual si no hay datos.
"""
from __future__ import annotations


EMPRESAS: dict[str, dict[str, str]] = {
    # --- Esquema 2D (industriales / NIIF estándar) -------------------------
    "AENZAC1":  {"rpj": "023106", "ruc": "20332600592", "esquema": "2D",
                 "nombre": "AENZA (ex Graña y Montero)"},
    "ALICORC1": {"rpj": "B30006", "ruc": "20100055237", "esquema": "2D",
                 "nombre": "Alicorp S.A.A."},
    "BACKUSI1": {"rpj": "B30021", "ruc": "20100113610", "esquema": "2D",
                 "nombre": "Backus & Johnston"},
    "BVN":      {"rpj": "B20003", "ruc": "20100079501", "esquema": "2D",
                 "nombre": "Buenaventura"},
    "CASAGRC1": {"rpj": "B08361", "ruc": "20131823020", "esquema": "2D",
                 "nombre": "Casa Grande"},
    "CORAREI1": {"rpj": "CI0003", "ruc": "20370146994", "esquema": "2D",
                 "nombre": "Aceros Arequipa"},
    "CPACASC1": {"rpj": "CD0005", "ruc": "20419387658", "esquema": "2D",
                 "nombre": "Cementos Pacasmayo"},
    "CVERDEC1": {"rpj": "CM0006", "ruc": "20170072465", "esquema": "2D",
                 "nombre": "Sociedad Minera Cerro Verde"},
    "ENGEPEC1": {"rpj": "002829", "ruc": "20333363900", "esquema": "2D",
                 "nombre": "Engie Perú"},
    "FERREYC1": {"rpj": "B60001", "ruc": "20100027292", "esquema": "2D",
                 "nombre": "Ferreycorp"},
    "INRETC1":  {"rpj": "OE5087", "ruc": "0",           "esquema": "2D",
                 "nombre": "InRetail Perú"},
    "LUSURC1":  {"rpj": "B40008", "ruc": "20331898008", "esquema": "2D",
                 "nombre": "Luz del Sur"},
    "MINSURI1": {"rpj": "A20032", "ruc": "20100136741", "esquema": "2D",
                 "nombre": "Minsur"},
    "NEXAPEC1": {"rpj": "B20010", "ruc": "20100110513", "esquema": "2D",
                 "nombre": "Nexa Resources Perú (ex Milpo)"},
    "ORYGENC1": {"rpj": "B40009", "ruc": "20330791412", "esquema": "2D",
                 "nombre": "Orygen Perú (ex Enel Generación)"},
    "PLUZC1":   {"rpj": "B40010", "ruc": "20269985900", "esquema": "2D",
                 "nombre": "Pluz Energía Perú (ex Enel Distribución)"},
    "RELAPAC1": {"rpj": "002766", "ruc": "20259829594", "esquema": "2D",
                 "nombre": "Refinería La Pampilla"},
    "UNACEMC1": {"rpj": "B30121", "ruc": "20100137390", "esquema": "2D",
                 "nombre": "UNACEM"},
    "VOLCABC1": {"rpj": "CM0001", "ruc": "20383045267", "esquema": "2D",
                 "nombre": "Volcan Compañía Minera"},
    "YURAC1":   {"rpj": "023490", "ruc": "20312372895", "esquema": "2D",
                 "nombre": "Yura"},

    # --- Esquema 2F (bancos) -----------------------------------------------
    "BBVAC1":   {"rpj": "B80004", "ruc": "20100130204", "esquema": "2F",
                 "nombre": "BBVA Perú"},
    "CREDITC1": {"rpj": "B80005", "ruc": "20100047218", "esquema": "2F",
                 "nombre": "Banco de Crédito del Perú (BCP)"},
    "SCOTIAC1": {"rpj": "B80012", "ruc": "20100043140", "esquema": "2F",
                 "nombre": "Scotiabank Perú"},
}


class UnknownTickerError(KeyError):
    """Se levanta cuando el ticker solicitado no está en el catálogo."""


def resolve_ticker(ticker: str) -> dict[str, str]:
    """Devuelve los datos SMV (rpj, ruc, esquema, nombre) de un ticker BVL.

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
