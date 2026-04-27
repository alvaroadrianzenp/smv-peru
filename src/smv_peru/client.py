"""
smv_client.py
=============
Cliente para el web service de datos abiertos de SMV (Superintendencia del
Mercado de Valores del Perú). Descarga estados financieros anuales de
empresas peruanas que cotizan en BVL y los mapea al schema interno.

Endpoint: https://mvnet.smv.gob.pe/ws_od_eeff/WebServiceInfoFinanciera.asmx
Formato:  SOAP 1.1, devuelve JSON dentro de un string en la respuesta.
Cache:    cada operación-año se guarda como data/raw/smv/{op}_{anio}.json

Cobertura v1: solo empresas con esquema contable 2D (industriales, NIIF
estándar). Bancos (esquema 2F) y aseguradoras (2E) no están soportadas
y deben caer a mock vía la lógica del llamador.

API pública:
  fetch_smv_fundamentals(rpj, years_back=10) -> dict | None
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from datetime import datetime
from html import unescape
from pathlib import Path

logger = logging.getLogger("smv_client")

SMV_ENDPOINT = "https://mvnet.smv.gob.pe/ws_od_eeff/WebServiceInfoFinanciera.asmx"
SMV_NAMESPACE = "http://tempuri.org/"
SMV_TIMEOUT_S = 120

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "smv"

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


def _soap_envelope(operacion: str, ejercicio: int, tipo: str = "C") -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        '<soap:Body>'
        f'<{operacion} xmlns="{SMV_NAMESPACE}">'
        f'<Ejercicio>{ejercicio}</Ejercicio><Periodo>A</Periodo><Tipo>{tipo}</Tipo>'
        f'</{operacion}>'
        '</soap:Body></soap:Envelope>'
    ).encode('utf-8')


def _call_smv(operacion: str, ejercicio: int, tipo: str = "C") -> list[dict] | None:
    """Llama una operación SOAP para un ejercicio anual; cachea en disco."""
    cache_file = CACHE_DIR / f"{operacion}_{ejercicio}_{tipo}.json"
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            logger.warning(f"Cache corrupto: {cache_file}, re-descargando")

    req = urllib.request.Request(
        SMV_ENDPOINT,
        data=_soap_envelope(operacion, ejercicio, tipo),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f'"{SMV_NAMESPACE}{operacion}"',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=SMV_TIMEOUT_S) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.warning(f"SMV {operacion} {ejercicio} {tipo} falló: {e}")
        return None

    m = re.search(rf'<{operacion}Result>(.*?)</{operacion}Result>', raw, re.DOTALL)
    if not m:
        logger.warning(f"SMV {operacion} {ejercicio} {tipo}: respuesta sin Result")
        return None
    try:
        data = json.loads(unescape(m.group(1)))
    except json.JSONDecodeError as e:
        logger.warning(f"SMV {operacion} {ejercicio} {tipo}: JSON inválido: {e}")
        return None

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(data), encoding='utf-8')
    logger.info(f"SMV {operacion} {ejercicio} {tipo}: {len(data)} filas, cacheado")
    return data


def _amount(rows: list[dict], cuenta: str, monto_field: str = "Monto1"):
    for r in rows:
        if r.get('Cuenta') == cuenta:
            v = r.get(monto_field)
            return float(v) if v is not None else None
    return None


def _map_year(rpj: str, pnl, bal, flow, fiscal_year: int) -> dict | None:
    """Filtra por RPJ y mapea cuentas. Retorna None si faltan métricas críticas."""
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


def fetch_smv_fundamentals(rpj: str, years_back: int = 10,
                           current_year: int | None = None,
                           tipo: str = "C") -> dict | None:
    """
    Descarga fundamentales anuales para una empresa peruana desde SMV.

    Intenta primero EEFF Consolidados (Tipo C). Si la empresa no aparece
    en consolidados (típico en empresas sin subsidiarias), cae automáticamente
    a Individual (Tipo I).

    Args:
        rpj: identificador SMV de la empresa (campo 'smv_rpj' en config).
        years_back: cuántos años hacia atrás (default 10).
        current_year: año más reciente; si None, usa el año actual.
        tipo: "C" (consolidado) o "I" (individual). Default "C" con cascada a "I".
    """
    if current_year is None:
        current_year = datetime.now().year

    end_year = current_year - 1
    start_year = end_year - years_back + 1

    years_data = []
    for y in range(start_year, end_year + 1):
        pnl = _call_smv(OP_PNL, y, tipo)
        bal = _call_smv(OP_BAL, y, tipo)
        flow = _call_smv(OP_FLOW, y, tipo)
        yd = _map_year(rpj, pnl, bal, flow, y)
        if yd is not None:
            years_data.append(yd)

    # Cascada: si no obtuvimos nada con Consolidado, probar Individual
    if not years_data and tipo == "C":
        logger.info(f"SMV: RPJ={rpj} no aparece en Consolidado, probando Individual")
        return fetch_smv_fundamentals(rpj, years_back, current_year, tipo="I")

    if not years_data:
        logger.warning(f"SMV: ningún año obtenido para RPJ={rpj} (ni C ni I)")
        return None

    return {"years": years_data, "info": {}}
