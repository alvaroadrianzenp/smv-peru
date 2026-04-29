"""smv-peru: cliente Python para los datos financieros públicos de la
Superintendencia del Mercado de Valores del Perú (SMV).
"""

from .client import (
    FIELDS_TO_CODES,
    FIELDS_TO_CODES_2D,
    FIELDS_TO_CODES_2F,
    fetch_eeff,
    fetch_estados_financieros,  # alias retro-compatible
    fetch_multi,
    set_dna,
)
from .empresas import EMPRESAS, UnknownTickerError, resolve_ticker
from .excel import to_excel
from .csv_export import to_csv

__all__ = [
    "fetch_eeff",
    "fetch_estados_financieros",
    "fetch_multi",
    "set_dna",
    "to_excel",
    "to_csv",
    "FIELDS_TO_CODES",
    "FIELDS_TO_CODES_2D",
    "FIELDS_TO_CODES_2F",
    "EMPRESAS",
    "UnknownTickerError",
    "resolve_ticker",
]
