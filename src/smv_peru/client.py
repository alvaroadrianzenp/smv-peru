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
          (típicamente soles peruanos). Los ratios (current_ratio, ROE, ROIC,
          gross_margin, etc.) son decimales, no porcentajes.

Cobertura v1: solo empresas con esquema contable 2D (industriales, NIIF
estándar). Bancos (esquema 2F) y aseguradoras (2E) no están soportadas.

Diseño del output:
- Cada período expone ~50 "campos amigables" en inglés (revenue, cash, ...)
  más métricas derivadas (gross_margin, net_debt, ROE, ...).
- Cada período también expone `raw_accounts`: dict {código_smv: {nombre, monto}}
  con TODAS las cuentas que SMV publicó y que NO están expuestas como amigable
  (filtrando montos cero). Esto permite acceder a cuentas raras o sectoriales
  sin esperar a que la librería las exponga.
- `FIELDS_TO_CODES` documenta el mapeo amigable → código SMV (auditoría).

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


# ---------------------------------------------------------------------------
# Mapeo único: campo amigable → código SMV (esquema 2D, industriales NIIF).
# Códigos validados contra la taxonomía oficial CONASEV/SMV. Es la "única
# fuente de verdad": agregar/cambiar un campo amigable solo requiere editar
# este dict.
# ---------------------------------------------------------------------------
FIELDS_TO_CODES: dict[str, str] = {
    # Estado de Resultados (P&L)
    "revenue":           "2D01ST",  # Ingresos de Actividades Ordinarias
    "cogs":              "2D0201",  # Costo de Ventas
    "gross_profit":      "2D02ST",  # Ganancia (Pérdida) Bruta
    "admin_expenses":    "2D0301",  # Gastos de Administración
    "selling_expenses":  "2D0302",  # Gastos de Ventas y Distribución
    "other_op_income":   "2D0403",  # Otros Ingresos Operativos
    "other_op_expenses": "2D0404",  # Otros Gastos Operativos
    "operating_income":  "2D03ST",  # Ganancia (Pérdida) Operativa
    "interest_income":   "2D0401",  # Ingresos Financieros
    "interest_expense":  "2D0402",  # Gastos Financieros
    "pretax_income":     "2D04ST",  # Ganancia (Pérdida) antes de Impuestos
    "income_tax":        "2D0502",  # Ingreso (Gasto) por Impuesto
    "net_income":        "2D07ST",  # Ganancia (Pérdida) Neta del Ejercicio
    "eps":               "2D0911",  # Total Ganancias (Pérdida) Básica por Acción Ordinaria

    # Estado de Situación Financiera (Balance)
    "cash":                "1D0109",  # Efectivo y Equivalentes al Efectivo
    "accounts_receivable": "1D0103",  # Cuentas por Cobrar Comerciales
    "inventory":           "1D0106",  # Inventarios
    "current_assets":      "1D01ST",  # Total Activos Corrientes
    "ppe":                 "1D0205",  # Propiedades, Planta y Equipo
    "intangibles":         "1D0206",  # Activos Intangibles Distintos de la Plusvalía
    "noncurrent_assets":   "1D02ST",  # Total Activos No Corrientes
    "total_assets_smv":    "1D020T",  # TOTAL DE ACTIVOS (chequeo de integridad)
    "accounts_payable":    "1D0302",  # Cuentas por Pagar Comerciales
    "debt_short_term":     "1D0309",  # Otros Pasivos Financieros (corriente)
    "current_liab":        "1D03ST",  # Total Pasivos Corrientes
    "debt_long_term":      "1D0401",  # Otros Pasivos Financieros (no corriente)
    "noncurrent_liab":     "1D04ST",  # Total Pasivos No Corrientes
    "total_liabilities":   "1D040T",  # Total Pasivos
    "share_capital":       "1D0701",  # Capital Emitido
    "retained_earnings":   "1D0707",  # Resultados Acumulados
    "reserves":            "1D0708",  # Otras Reservas de Patrimonio
    "equity":              "1D07ST",  # Total Patrimonio

    # Estado de Flujos de Efectivo (método directo)
    "cash_from_customers": "3D0101",  # Venta de Bienes y Prestación de Servicios
    "cash_to_suppliers":   "3D0109",  # Proveedores de Bienes y Servicios
    "cash_to_employees":   "3D0105",  # Pagos a y por Cuenta de los Empleados
    "interest_paid_op":    "3D0107",  # Intereses Pagados (operación)
    "taxes_paid_op":       "3D0120",  # Impuestos a las Ganancias (Pagados) Reembolsados
    "operating_cf":        "3D01ST",  # Flujo de Efectivo Actividades de Operación
    "ppe_proceeds":        "3D0202",  # Venta de Propiedades, Planta y Equipo
    "capex_ppe":           "3D0206",  # Compra de Propiedades, Planta y Equipo (negativo)
    "capex_intangibles":   "3D0207",  # Compra de Activos Intangibles (negativo)
    "investing_cf":        "3D02ST",  # Flujo de Efectivo Actividades de Inversión
    "dividends_paid_fin":  "3D0305",  # Dividendos Pagados (negativo)
    "interest_paid_fin":   "3D0311",  # Intereses Pagados (financiación, negativo)
    "debt_issued":         "3D0325",  # Obtención de Préstamos
    "debt_repaid":         "3D0330",  # Amortización o Pago de Préstamos (negativo)
    "financing_cf":        "3D03ST",  # Flujo de Efectivo Actividades de Financiación
    "end_cash":            "3D04ST",  # Efectivo y Equivalente al Efectivo al Finalizar
}

# Set de códigos cubiertos por algún campo amigable. Se usa para excluirlos
# de raw_accounts y evitar duplicación.
CODIGOS_USADOS: frozenset[str] = frozenset(FIELDS_TO_CODES.values())

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


def _extract_raw_accounts(rows: list[dict]) -> dict[str, dict]:
    """Construye el dict de cuentas crudas excluyendo las que ya son amigables.

    Filtra: códigos en CODIGOS_USADOS y cuentas con monto cero. Conserva el
    `DescripcionCuenta` oficial de SMV. Si la descripción viene vacía, usa
    el código como fallback.
    """
    raw: dict[str, dict] = {}
    for r in rows:
        codigo = r.get('Cuenta')
        if not codigo or codigo in CODIGOS_USADOS or codigo in raw:
            continue
        v = r.get('Monto1')
        if v is None:
            continue
        try:
            monto = float(v)
        except (TypeError, ValueError):
            continue
        if monto == 0:
            continue
        nombre = (r.get('DescripcionCuenta') or '').strip() or codigo
        raw[codigo] = {"nombre": nombre, "monto": monto}
    return raw


def _safe_div(num, den):
    """División None-safe; devuelve None si numerador o denominador son falsy."""
    if num is None or den is None or den == 0:
        return None
    return num / den


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

    # Helper local: lee el monto de un campo amigable usando FIELDS_TO_CODES.
    def amt(field: str, rows: list[dict]):
        return _amount(rows, FIELDS_TO_CODES[field])

    # --- Lectura directa de campos amigables --------------------------------
    revenue = amt("revenue", pnl_e)
    equity = amt("equity", bal_e)
    if revenue is None or equity is None:
        return None  # mismas precondiciones que la versión anterior

    period: dict = {
        "fiscal_year": fiscal_year,
        "quarter": quarter,
    }

    # P&L
    period["revenue"] = revenue
    for f in ("cogs", "gross_profit", "admin_expenses", "selling_expenses",
              "other_op_income", "other_op_expenses", "operating_income",
              "interest_income", "interest_expense", "pretax_income",
              "income_tax", "net_income", "eps"):
        period[f] = amt(f, pnl_e)

    # Balance
    for f in ("cash", "accounts_receivable", "inventory", "current_assets",
              "ppe", "intangibles", "noncurrent_assets", "total_assets_smv",
              "accounts_payable", "debt_short_term", "current_liab",
              "debt_long_term", "noncurrent_liab", "total_liabilities",
              "share_capital", "retained_earnings", "reserves"):
        period[f] = amt(f, bal_e)
    period["equity"] = equity

    # Flujo de Efectivo
    for f in ("cash_from_customers", "cash_to_suppliers", "cash_to_employees",
              "interest_paid_op", "taxes_paid_op", "operating_cf",
              "ppe_proceeds", "capex_ppe", "capex_intangibles", "investing_cf",
              "dividends_paid_fin", "interest_paid_fin", "debt_issued",
              "debt_repaid", "financing_cf", "end_cash"):
        period[f] = amt(f, flow_e)

    # --- Métricas derivadas -------------------------------------------------
    # total_debt: suma de deuda corto + largo plazo (ambos son "Otros Pasivos
    # Financieros" en CONASEV — solo deuda con costo, no comerciales).
    debt_st = period["debt_short_term"] or 0.0
    debt_lt = period["debt_long_term"] or 0.0
    total_debt = debt_st + debt_lt
    period["total_debt"] = total_debt

    # total_assets: prefiere el subtotal oficial 1D020T; si falta, suma corrientes
    # + no corrientes. Mantiene compatibilidad con la versión anterior.
    if period["total_assets_smv"] is not None:
        period["total_assets"] = period["total_assets_smv"]
    else:
        ca = period["current_assets"] or 0
        nca = period["noncurrent_assets"] or 0
        period["total_assets"] = (ca + nca) or None

    # net_debt = total_debt − cash
    period["net_debt"] = (
        total_debt - period["cash"] if period["cash"] is not None else None
    )

    # Márgenes
    period["gross_margin"] = _safe_div(period["gross_profit"], revenue)
    period["operating_margin"] = _safe_div(period["operating_income"], revenue)
    period["net_margin"] = _safe_div(period["net_income"], revenue)

    # EBITDA aproximado = operating_income (D&A no expuesto por la API SMV).
    # Se mantiene el campo para compatibilidad con la versión anterior.
    period["ebitda"] = period["operating_income"]

    # Liquidez
    period["current_ratio"] = _safe_div(period["current_assets"], period["current_liab"])
    quick_num = None
    if period["cash"] is not None and period["accounts_receivable"] is not None:
        quick_num = period["cash"] + period["accounts_receivable"]
    period["quick_ratio"] = _safe_div(quick_num, period["current_liab"])

    # Cobertura de intereses: operating_income / |interest_expense|
    if period["interest_expense"] is not None and period["interest_expense"] != 0:
        period["interest_coverage"] = _safe_div(
            period["operating_income"], abs(period["interest_expense"])
        )
    else:
        period["interest_coverage"] = None

    # Tasa efectiva de impuestos: |income_tax| / pretax_income (income_tax viene
    # negativo cuando es gasto).
    if period["income_tax"] is not None and period["pretax_income"]:
        period["effective_tax_rate"] = abs(period["income_tax"]) / period["pretax_income"]
    else:
        period["effective_tax_rate"] = None

    # Intereses pagados (caja, total): suma de operación + financiación, en
    # valor absoluto. Empresas reportan en una u otra sección según política.
    ip_op = period["interest_paid_op"] or 0
    ip_fin = period["interest_paid_fin"] or 0
    interest_paid = abs(ip_op) + abs(ip_fin)
    period["interest_paid"] = interest_paid if interest_paid > 0 else None

    # Dividendos pagados (caja, positivo)
    div_fin = period["dividends_paid_fin"]
    period["dividends_paid"] = abs(div_fin) if div_fin else None

    # Impuestos pagados (caja, positivo)
    tx_op = period["taxes_paid_op"]
    period["taxes_paid"] = abs(tx_op) if tx_op else None

    # Payout ratio
    period["payout_ratio"] = _safe_div(period["dividends_paid"], period["net_income"])

    # Capex total y FCF
    capex_ppe = period["capex_ppe"] or 0
    capex_int = period["capex_intangibles"] or 0
    capex_total_signed = capex_ppe + capex_int  # vienen negativos
    period["capex_total"] = (
        abs(capex_total_signed) if capex_total_signed != 0 else None
    )
    period["capex_intensity"] = _safe_div(period["capex_total"], revenue)

    # FCF = operating_cf + capex_signed (capex negativo => resta). Si flow es
    # vacío y operating_cf es None, fcf queda None.
    op_cf = period["operating_cf"]
    if op_cf is None:
        period["fcf"] = None
    else:
        period["fcf"] = op_cf + capex_total_signed

    # ROE y ROIC
    period["roe"] = _safe_div(period["net_income"], equity)
    invested_capital = equity + total_debt
    period["roic"] = _safe_div(period["net_income"], invested_capital)

    # --- raw_accounts: cuentas no expuestas como amigables ------------------
    raw: dict[str, dict] = {}
    raw.update(_extract_raw_accounts(pnl_e))
    raw.update(_extract_raw_accounts(bal_e))
    raw.update(_extract_raw_accounts(flow_e))
    period["raw_accounts"] = raw

    return period


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

        Cada período contiene ~50 campos amigables (revenue, cash, gross_profit,
        gross_margin, net_debt, ROE, etc.) más una key ``"raw_accounts"`` con
        las cuentas adicionales que SMV publica y que no están expuestas como
        amigables. Ver ``FIELDS_TO_CODES`` para auditar el mapeo.

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
