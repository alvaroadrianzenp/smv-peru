"""smv-peru: cliente Python para los datos financieros públicos de la
Superintendencia del Mercado de Valores del Perú (SMV).
"""

from .client import fetch_smv_fundamentals

__all__ = ["fetch_smv_fundamentals"]
