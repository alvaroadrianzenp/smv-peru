"""
client.py
=========
Cliente para el web service de datos abiertos de SMV (Superintendencia del
Mercado de Valores del Perú). Descarga estados financieros (anuales o
trimestrales, consolidados o individuales) de empresas peruanas que cotizan
en BVL y los mapea al schema interno.

Endpoint: https://mvnet.smv.gob.pe/ws_od_eeff/WebServiceInfoFinanciera.asmx
Formato:  SOAP 1.1, devuelve JSON dentro de un string en la respuesta.
Cache:    por defecto en el user cache dir del SO (ej. ~/Library/Caches/smv-peru
          en macOS). Configurable con el argumento `cache_dir` o la variable
          de entorno SMV_PERU_CACHE_DIR.
Unidades: los montos vienen en MILES de la moneda reportada por la empresa
          (típicamente soles peruanos). Los ratios (current_ratio, ROE, ROIC)
          son decimales, no porcentajes.

Cobertura v1: solo empresas con esquema contable 2D (industriales, NIIF
estándar). Bancos (esquema 2F) y aseguradoras (2E) no están soportadas.

API pública:
  fetch_estados_financieros(ticker, desde, hasta, tipo, periodicidad) -> dict | None
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from html import unescape
from pathlib import Path

from .empresas import resolve_ticker

logger = logging.getLogger("smv_peru")

SMV_ENDPOINT = "https://mvnet.smv.gob.pe/ws_od_eeff/WebServiceInfoFinanciera.asmx"
SMV_NAMESPACE = "http://tempuri.org/"
SMV_TIMEOUT_S = 120


def _user_cache_dir(app_name: str) -> Path:
    """Directorio de cache estándar del usuario, según convenciones del SO."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / app_name
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local) / app_name / "Cache"
    # Linux y otros UNIX: XDG Base Directory Specification
    xdg = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(xdg) / app_name


def _default_cache_dir() -> Path:
    """Cache_dir por defecto: env var SMV_PERU_CACHE_DIR → user cache dir del SO."""
    env = os.environ.get("SMV_PERU_CACHE_DIR")
    if env:
        return Path(env).expanduser()
    return _user_cache_dir("smv-peru")


OP_PNL = "obtener_GanciaPerdida"
OP_BAL = "obtener_BalanceGeneral"
OP_FLOW = "obtener_FlujoEfectivo"

# Mapeo cuentas SMV → schema interno (esquema 2D, industriales)
CUENTAS_PNL = {
    "revenue":          "2D01ST",
    "operating_income": "2D03ST",
    "net_income":       "2D07ST",
    "eps":              "2D0911",
}
CUENTAS_BAL = {
    "current_assets":    "1D01ST",
    "noncurrent_assets": "1D02ST",
    "current_liab":      "1D03ST",
    "equity":            "1D07ST",
    "debt_current":      "1D0309",
    "debt_noncurrent":   "1D0401",
}
CUENTAS_FLOW = {
    "operating_cf": "3D01ST",
    "capex":        "3D0206",  # ya viene negativo
}

# Mapeos de la API pública a códigos SMV
_TIPO_CODES = {"consolidado": "C", "individual": "I"}
_PERIODICIDAD_PERIODOS = {"anual": ["A"], "trimestral": ["1", "2", "3", "4"]}


def _soap_envelope(operacion: str, ejercicio: int, periodo: str, tipo: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        '<soap:Body>'
        f'<{operacion} xmlns="{SMV_NAMESPACE}">'
        f'<Ejercicio>{ejercicio}</Ejercicio><Periodo>{periodo}</Periodo><Tipo>{tipo}</Tipo>'
        f'</{operacion}>'
        '</soap:Body></soap:Envelope>'
    ).encode('utf-8')


def _call_smv(operacion: str, ejercicio: int, periodo: str, tipo: str,
              cache_dir: Path) -> list[dict] | None:
    """Llama una operación SOAP; cachea en disco. Devuelve la lista de filas."""
    cache_file = cache_dir / f"{operacion}_{ejercicio}_{tipo}_{periodo}.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            logger.warning(f"Cache corrupto: {cache_file}, re-descargando")

    req = urllib.request.Request(
        SMV_ENDPOINT,
        data=_soap_envelope(operacion, ejercicio, periodo, tipo),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f'"{SMV_NAMESPACE}{operacion}"',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=SMV_TIMEOUT_S) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.warning(f"SMV {operacion} {ejercicio} {tipo} P={periodo} falló: {e}")
        return None

    m = re.search(rf'<{operacion}Result>(.*?)</{operacion}Result>', raw, re.DOTALL)
    if not m:
        logger.warning(f"SMV {operacion} {ejercicio} {tipo} P={periodo}: sin Result")
        return None
    try:
        data = json.loads(unescape(m.group(1)))
    except json.JSONDecodeError as e:
        logger.warning(f"SMV {operacion} {ejercicio} {tipo} P={periodo}: JSON inválido: {e}")
        return None

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(data), encoding='utf-8')
    logger.info(f"SMV {operacion} {ejercicio} {tipo} P={periodo}: {len(data)} filas, cacheado")
    return data


def _amount(rows: list[dict], cuenta: str, monto_field: str = "Monto1"):
    for r in rows:
        if r.get('Cuenta') == cuenta:
            v = r.get(monto_field)
            return float(v) if v is not None else None
    return None


def _map_period(rpj: str, pnl, bal, flow, fiscal_year: int,
                quarter: int | None) -> dict | None:
    """Filtra por RPJ y mapea cuentas. Retorna None si faltan métricas críticas.

    quarter=None indica que es un período anual; quarter=1..4 indica un trimestre.
    """
    if not pnl or not bal:
        return None
    pnl_e = [r for r in pnl if r.get('RPJ') == rpj]
    bal_e = [r for r in bal if r.get('RPJ') == rpj]
    flow_e = [r for r in (flow or []) if r.get('RPJ') == rpj]
    if not pnl_e or not bal_e:
        return None

    revenue = _amount(pnl_e, CUENTAS_PNL['revenue'])
    equity = _amount(bal_e, CUENTAS_BAL['equity'])
    if revenue is None or equity is None:
        return None

    operating_income = _amount(pnl_e, CUENTAS_PNL['operating_income'])
    net_income = _amount(pnl_e, CUENTAS_PNL['net_income'])
    eps = _amount(pnl_e, CUENTAS_PNL['eps'])

    cur_assets = _amount(bal_e, CUENTAS_BAL['current_assets'])
    noncur_assets = _amount(bal_e, CUENTAS_BAL['noncurrent_assets'])
    cur_liab = _amount(bal_e, CUENTAS_BAL['current_liab'])
    debt_cur = _amount(bal_e, CUENTAS_BAL['debt_current']) or 0.0
    debt_noncur = _amount(bal_e, CUENTAS_BAL['debt_noncurrent']) or 0.0

    total_assets = ((cur_assets or 0) + (noncur_assets or 0)) or None
    current_ratio = (cur_assets / cur_liab) if (cur_assets and cur_liab) else None
    total_debt = debt_cur + debt_noncur

    op_cf = _amount(flow_e, CUENTAS_FLOW['operating_cf'])
    capex = _amount(flow_e, CUENTAS_FLOW['capex'])
    fcf = (op_cf + capex) if (op_cf is not None and capex is not None) else None

    # EBITDA aproximado = operating_income (D&A no expuesto por la API)
    ebitda = operating_income

    roe = (net_income / equity) if (net_income and equity) else None
    ic = equity + total_debt
    roic = (net_income / ic) if (net_income and ic) else None

    return {
        "fiscal_year": fiscal_year,
        "quarter": quarter,
        "revenue": revenue,
        "ebitda": ebitda,
        "net_income": net_income,
        "eps": eps,
        "total_debt": total_debt,
        "equity": equity,
        "total_assets": total_assets,
        "current_ratio": current_ratio,
        "fcf": fcf,
        "roe": roe,
        "roic": roic,
    }


def fetch_estados_financieros(
    ticker: str,
    desde: int,
    hasta: int,
    tipo: str = "consolidado",
    periodicidad: str = "anual",
    cache_dir: Path | str | None = None,
) -> dict | None:
    """Descarga estados financieros para una empresa peruana desde SMV.

    Args:
        ticker: ticker BVL (ej. ``"ALICORC1"``). Ver
            ``smv_peru.empresas.EMPRESAS`` para la lista actual.
        desde: año fiscal inicial (inclusive).
        hasta: año fiscal final (inclusive).
        tipo: ``"consolidado"`` (default) o ``"individual"``. Si "consolidado"
            no devuelve datos, se reintenta con "individual" automáticamente.
        periodicidad: ``"anual"`` (default) o ``"trimestral"``.
        cache_dir: directorio donde cachear respuestas SOAP. Si es ``None``,
            usa la variable de entorno ``SMV_PERU_CACHE_DIR``; si tampoco
            está definida, cae al user cache dir estándar del SO (en macOS,
            ``~/Library/Caches/smv-peru``).

    Returns:
        dict con keys:
            ``"periods"``: lista de dicts (un período por entrada), ordenada
                cronológicamente.
            ``"info"``: dict reservado para metadatos futuros.

        Cada período contiene:
            ``fiscal_year`` (int): año fiscal.
            ``quarter`` (int | None): ``None`` para anual; 1, 2, 3 o 4 para
                trimestral.
            ``revenue``, ``ebitda``, ``net_income``, ``total_debt``, ``equity``,
                ``total_assets``, ``fcf`` (float | None): MONTOS EN MILES de la
                moneda reportada (típicamente soles peruanos). Por ejemplo,
                revenue=13_655_764 significa S/. 13.66 mil millones.
            ``eps`` (float | None): utilidad por acción, en unidades base.
            ``current_ratio``, ``roe``, ``roic`` (float | None): ratios
                DECIMALES, no porcentajes. ``roe=0.14`` significa 14%.

        Devuelve ``None`` si no se obtuvieron datos para ningún período (ni en
        Consolidado ni en Individual).

    Raises:
        UnknownTickerError: si el ticker no está en el catálogo.
        ValueError: si tipo o periodicidad son inválidos, o si desde > hasta.
    """
    if tipo not in _TIPO_CODES:
        raise ValueError(
            f"tipo debe ser 'consolidado' o 'individual', recibido: {tipo!r}"
        )
    if periodicidad not in _PERIODICIDAD_PERIODOS:
        raise ValueError(
            f"periodicidad debe ser 'anual' o 'trimestral', recibido: {periodicidad!r}"
        )
    if desde > hasta:
        raise ValueError(f"desde ({desde}) no puede ser mayor que hasta ({hasta})")

    rpj = resolve_ticker(ticker)["rpj"]
    tipo_code = _TIPO_CODES[tipo]
    periodos = _PERIODICIDAD_PERIODOS[periodicidad]

    if cache_dir is None:
        cache_dir = _default_cache_dir()
    else:
        cache_dir = Path(cache_dir).expanduser()

    periods_data = []
    for y in range(desde, hasta + 1):
        for p in periodos:
            pnl = _call_smv(OP_PNL, y, p, tipo_code, cache_dir)
            bal = _call_smv(OP_BAL, y, p, tipo_code, cache_dir)
            flow = _call_smv(OP_FLOW, y, p, tipo_code, cache_dir)
            quarter = None if p == "A" else int(p)
            yd = _map_period(rpj, pnl, bal, flow, y, quarter)
            if yd is not None:
                periods_data.append(yd)

    # Cascada: si no obtuvimos nada con Consolidado, probar Individual
    if not periods_data and tipo_code == "C":
        logger.info(f"SMV: ticker={ticker} no aparece en Consolidado, probando Individual")
        return fetch_estados_financieros(
            ticker, desde, hasta,
            tipo="individual", periodicidad=periodicidad, cache_dir=cache_dir,
        )

    if not periods_data:
        logger.warning(f"SMV: ningún período obtenido para ticker={ticker} (ni C ni I)")
        return None

    return {"periods": periods_data, "info": {}}
