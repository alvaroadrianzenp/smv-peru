"""
client.py
=========
Cliente para el web service de datos abiertos de SMV (Superintendencia del
Mercado de Valores del Perú). Descarga estados financieros (anuales o
trimestrales, consolidados o individuales) de empresas peruanas que cotizan
en BVL y los mapea al schema interno apropiado según el esquema contable.

Endpoint: https://mvnet.smv.gob.pe/ws_od_eeff/WebServiceInfoFinanciera.asmx
Formato:  SOAP 1.1, devuelve JSON dentro de un string en la respuesta.
Cache:    por defecto en el user cache dir del SO (ej. ~/Library/Caches/smv-peru
          en macOS). Configurable con el argumento `cache_dir` o la variable
          de entorno SMV_PERU_CACHE_DIR.
Unidades: los montos vienen en MILES de la moneda reportada por la empresa
          (típicamente soles peruanos). Los ratios son decimales, no porcentajes.

Esquemas contables soportados:
- Esquema 2D: industriales y similares (Alicorp, UNACEM, Volcan, etc.).
  Mapeo: ``FIELDS_TO_CODES_2D``. Lógica: ``_map_period_2d``.
- Esquema 2F: bancos (BBVA Perú, BCP, Scotiabank).
  Mapeo: ``FIELDS_TO_CODES_2F``. Lógica: ``_map_period_2f``.
- Esquema 2E (futuro): aseguradoras.

Cada período del output expone una key ``"schema"`` ("2D" | "2F") para
discriminar el esquema y por ende el set de campos disponibles.

Normalización trimestral:
SMV publica el Cash Flow trimestral en modo YTD (acumulado al cierre del
trimestre). El Estado de Resultados generalmente viene period-only. Esta
librería **detecta automáticamente** el régimen y devuelve siempre datos
**period-only** cuando ``periodicidad="trimestral"``: si detecta YTD,
descarga el trimestre anterior y resta. Para Q1 no se transforma (ya es
period-only por definición). El balance (cuentas de stock) nunca se
transforma — es un saldo puntual al cierre del trimestre.

Promedios para métricas con stocks (ROE, ROIC, ROA, NIM):
SMV publica en cada respuesta el ``Monto1`` (período actual) y ``Monto2``
(comparativo del período anterior). Esto permite calcular promedios de
balance ((Monto1 + Monto2) / 2) sin llamadas adicionales. Para datos
trimestrales, ``Monto2`` del balance es el cierre del año anterior (no el
mismo trimestre); por convención esto produce métricas de rentabilidad
"anualizadas" estándar.

Métricas YoY (Year-over-Year):
También usando ``Monto2``, se calculan growth rates como ``revenue_yoy``,
``net_income_yoy``, ``loans_yoy``, ``deposits_yoy``, ``equity_yoy``.

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
FIELDS_TO_CODES_2D: dict[str, str] = {
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
    "cash_from_customers": "3D0101",
    "cash_to_suppliers":   "3D0109",
    "cash_to_employees":   "3D0105",
    "interest_paid_op":    "3D0107",
    "taxes_paid_op":       "3D0120",
    "operating_cf":        "3D01ST",
    "ppe_proceeds":        "3D0202",
    "capex_ppe":           "3D0206",
    "capex_intangibles":   "3D0207",
    "investing_cf":        "3D02ST",
    "dividends_paid_fin":  "3D0305",
    "interest_paid_fin":   "3D0311",
    "debt_issued":         "3D0325",
    "debt_repaid":         "3D0330",
    "financing_cf":        "3D03ST",
    "end_cash":            "3D04ST",
}

CODIGOS_USADOS_2D: frozenset[str] = frozenset(FIELDS_TO_CODES_2D.values())


# ---------------------------------------------------------------------------
# Mapeo: campo amigable → código SMV (esquema 2F, bancos).
# Validado contra EEFF auditados consolidados de BBVA Perú 2024 (5 valores
# críticos coinciden exactos).
# ---------------------------------------------------------------------------
FIELDS_TO_CODES_2F: dict[str, str] = {
    # Estado de Situación Financiera (1F)
    "cash":                       "1F0101",  # Disponibles
    "interbank_funds":             "1F0201",  # Fondos interbancarios (activo)
    "investments_fvtpl":           "1F0301",  # Inversiones a valor razonable con cambios en resultados
    "investments_afs":             "1F0135",  # Inversiones disponibles para la venta
    "investments_htm":             "1F0306",  # Inversiones a vencimiento
    "loans_st":                    "1F0111",  # Cartera de créditos neto (corriente)
    "performing_loans":            "1F0115",  # Cartera de créditos vigentes
    "refinanced_loans":            "1F0117",  # Cartera de créditos refinanciados
    "overdue_loans":               "1F0118",  # Cartera de créditos vencidos
    "judicial_loans":              "1F0119",  # Cartera de créditos en cobranza judicial
    "current_assets":              "1F01ST",  # Total Activo Corriente
    "loans_lt":                    "1F1902",  # Cartera de créditos neto (no corriente)
    "ppe":                         "1F1701",  # Inmuebles, mobiliario y equipo
    "intangibles":                 "1F1907",  # Activo intangible
    "noncurrent_assets":           "1F19ST",  # Total Activo No Corriente
    "total_assets":                "1F2001",  # TOTAL ACTIVO
    "deposits":                    "1F2101",  # Obligaciones con el público
    "interbank_funds_payable":     "1F2301",  # Fondos interbancarios (pasivo)
    "deposits_financial_system":   "1F2703",  # Depósitos de empresas del sistema financiero
    "financial_debt_st":           "1F2704",  # Adeudados y obligaciones financieras (corriente)
    "current_liab":                "1F2902",  # Total Pasivo Corriente
    "financial_debt_lt":           "1F3002",  # Adeudados y obligaciones financieras (no corriente)
    "noncurrent_liab":             "1F30ST",  # Total Pasivo No Corriente
    "total_liabilities":           "1F3101",  # TOTAL PASIVO
    "share_capital":               "1F3301",  # Capital social
    "reserves":                    "1F3303",  # Reservas
    "retained_earnings":           "1F3304",  # Resultados acumulados
    "equity":                      "1F3306",  # TOTAL PATRIMONIO

    # Estado de Resultados (2F)
    "interest_income":     "2F0101",  # Ingresos por intereses
    "interest_expense":    "2F0301",  # Gastos por intereses (negativo)
    "net_interest_income": "2F2301",  # MARGEN BRUTO (NII)
    "loan_loss_provisions": "2F2304",  # Provisión para créditos (negativo)
    "fee_income_net":      "2F2406",  # Comisiones (netas)
    "trading_income":      "2F2506",  # Resultado por operaciones financieras (ROF)
    "operating_expenses":  "2F2602",  # Gastos de administración (negativo)
    "operating_income":    "2F2801",  # Resultado de operación
    "pretax_income":       "2F2809",  # Resultado antes de impuestos
    "income_tax":          "2F1403",  # Gasto por impuesto a las ganancias (negativo)
    "net_income":          "2F1901",  # Resultado neto del ejercicio
    "eps":                 "2F2204",  # Ganancia básica por acción
    "eps_diluted":         "2F2206",  # Ganancia diluida por acción

    # Estado de Flujos de Efectivo (3F, método indirecto)
    "dna":              "3F0301",  # Depreciación y amortización
    "operating_cf":     "3F0501",  # Flujo neto de operación
    "investing_cf":     "3F0701",  # Flujo neto de inversión
    "financing_cf":     "3F0901",  # Flujo neto de financiación
    "deposits_change":  "3F0801",  # Aumento neto de depósitos
    "loans_change":     "3F0805",  # Cambio neto en cartera de créditos
    "dividends_paid_fin": "3F0808",  # Dividendos pagados (negativo)
    "end_cash":         "3F1201",  # Efectivo al cierre
}

CODIGOS_USADOS_2F: frozenset[str] = frozenset(FIELDS_TO_CODES_2F.values())


# Alias de compatibilidad: FIELDS_TO_CODES apunta a 2D (esquema legacy default).
FIELDS_TO_CODES = FIELDS_TO_CODES_2D
CODIGOS_USADOS = CODIGOS_USADOS_2D


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
    """Lee el monto de una cuenta. monto_field='Monto1' (actual) o 'Monto2' (anterior)."""
    for r in rows:
        if r.get('Cuenta') == cuenta:
            v = r.get(monto_field)
            return float(v) if v is not None else None
    return None


def _amount_prior(rows: list[dict], cuenta: str):
    """Lee el monto del período anterior (Monto2) de una cuenta."""
    return _amount(rows, cuenta, monto_field="Monto2")


def _avg(current, prior):
    """Promedio None-safe de dos stocks. Si ambos son None, devuelve None.
    Si uno es None, devuelve el otro (proxy razonable)."""
    if current is None and prior is None:
        return None
    if current is None:
        return prior
    if prior is None:
        return current
    return (current + prior) / 2


def _yoy(current, prior):
    """Crecimiento year-over-year. None si falta data o si prior es 0."""
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / abs(prior)


def _safe_div(num, den):
    """División None-safe; devuelve None si numerador o denominador son falsy."""
    if num is None or den is None or den == 0:
        return None
    return num / den


def _extract_raw_accounts(rows: list[dict],
                          codigos_usados: frozenset[str] | None = None) -> dict[str, dict]:
    """Construye el dict de cuentas crudas excluyendo las que ya son amigables.

    Filtra: códigos en `codigos_usados` y cuentas con monto cero. Conserva el
    `DescripcionCuenta` oficial de SMV. Si la descripción viene vacía, usa
    el código como fallback.

    Si `codigos_usados` es None, usa CODIGOS_USADOS_2D por compatibilidad.
    """
    if codigos_usados is None:
        codigos_usados = CODIGOS_USADOS_2D
    raw: dict[str, dict] = {}
    for r in rows:
        codigo = r.get('Cuenta')
        if not codigo or codigo in codigos_usados or codigo in raw:
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


# ---------------------------------------------------------------------------
# Normalización trimestral: convierte CF/PnL trimestral a period-only.
# SMV publica el CF en YTD acumulado (confirmado para Alicorp 2D y BBVA 2F).
# ---------------------------------------------------------------------------

def _is_ytd(rows_q4: list[dict], rows_anual: list[dict],
            rpj: str, codigo_referencia: str, tolerance: float = 0.01) -> bool:
    """Detecta si los datos trimestrales vienen en modo YTD acumulado.

    Compara el `Monto1` de Q4 contra el del Anual para una cuenta de referencia.
    Si Q4 ≈ Anual → YTD. Si difiere significativamente → period-only.

    El argumento `codigo_referencia` debe ser una cuenta de flujo cuyo agregado
    anual esté disponible (ej. operating_cf en CF, revenue en PnL).
    """
    q4 = _amount([r for r in rows_q4 if r.get('RPJ') == rpj], codigo_referencia)
    anual = _amount([r for r in rows_anual if r.get('RPJ') == rpj], codigo_referencia)
    if q4 is None or anual is None or anual == 0:
        return True  # default conservador: asumir YTD si no podemos detectar
    return abs(q4 - anual) / abs(anual) < tolerance


def _subtract_rows(rows_qn: list[dict], rows_qn_minus_1: list[dict]) -> list[dict]:
    """Devuelve filas con Monto1 = Qn - Q(n-1) para todas las cuentas en común.
    Se usa para convertir CF/PnL YTD a period-only.

    Mantiene `Monto2` del Qn original (comparativo del año anterior).
    Las filas que están solo en Qn (no en Q(n-1)) se conservan tal cual.
    """
    # Index por (RPJ, Cuenta) para cruce eficiente
    prev_index = {}
    for r in rows_qn_minus_1:
        prev_index[(r.get('RPJ'), r.get('Cuenta'))] = r

    result = []
    for r in rows_qn:
        clave = (r.get('RPJ'), r.get('Cuenta'))
        m1 = r.get('Monto1')
        prev_row = prev_index.get(clave)
        prev_m1 = prev_row.get('Monto1') if prev_row else None

        if m1 is not None and prev_m1 is not None:
            try:
                new_m1 = float(m1) - float(prev_m1)
            except (TypeError, ValueError):
                new_m1 = m1
            new_row = dict(r)
            new_row['Monto1'] = new_m1
            result.append(new_row)
        else:
            result.append(r)
    return result


def _map_period_2d(rpj: str, pnl, bal, flow, fiscal_year: int,
                   quarter: int | None,
                   pnl_prior=None, bal_prior=None, flow_prior=None) -> dict | None:
    """Esquema 2D (industriales): mapea cuentas SMV a campos amigables.

    Argumentos `*_prior` se reservan para pasar respuestas del período
    anterior (no usado actualmente; los promedios usan Monto2 dentro de
    las mismas filas via `_amount_prior`).
    """
    if not pnl or not bal:
        return None
    pnl_e = [r for r in pnl if r.get('RPJ') == rpj]
    bal_e = [r for r in bal if r.get('RPJ') == rpj]
    flow_e = [r for r in (flow or []) if r.get('RPJ') == rpj]
    if not pnl_e or not bal_e:
        return None

    def amt(field: str, rows: list[dict]):
        return _amount(rows, FIELDS_TO_CODES_2D[field])

    def amt_prior(field: str, rows: list[dict]):
        return _amount_prior(rows, FIELDS_TO_CODES_2D[field])

    revenue = amt("revenue", pnl_e)
    equity = amt("equity", bal_e)
    if revenue is None or equity is None:
        return None

    period: dict = {
        "schema": "2D",
        "fiscal_year": fiscal_year,
        "quarter": quarter,
    }

    period["revenue"] = revenue
    for f in ("cogs", "gross_profit", "admin_expenses", "selling_expenses",
              "other_op_income", "other_op_expenses", "operating_income",
              "interest_income", "interest_expense", "pretax_income",
              "income_tax", "net_income", "eps"):
        period[f] = amt(f, pnl_e)

    for f in ("cash", "accounts_receivable", "inventory", "current_assets",
              "ppe", "intangibles", "noncurrent_assets", "total_assets_smv",
              "accounts_payable", "debt_short_term", "current_liab",
              "debt_long_term", "noncurrent_liab", "total_liabilities",
              "share_capital", "retained_earnings", "reserves"):
        period[f] = amt(f, bal_e)
    period["equity"] = equity

    for f in ("cash_from_customers", "cash_to_suppliers", "cash_to_employees",
              "interest_paid_op", "taxes_paid_op", "operating_cf",
              "ppe_proceeds", "capex_ppe", "capex_intangibles", "investing_cf",
              "dividends_paid_fin", "interest_paid_fin", "debt_issued",
              "debt_repaid", "financing_cf", "end_cash"):
        period[f] = amt(f, flow_e)

    # --- Stocks del período anterior (Monto2) para promedios y YoY ---------
    equity_prior = amt_prior("equity", bal_e)
    revenue_prior = amt_prior("revenue", pnl_e)
    net_income_prior = amt_prior("net_income", pnl_e)
    debt_st_prior = amt_prior("debt_short_term", bal_e)
    debt_lt_prior = amt_prior("debt_long_term", bal_e)

    # --- Métricas derivadas ------------------------------------------------
    debt_st = period["debt_short_term"] or 0.0
    debt_lt = period["debt_long_term"] or 0.0
    total_debt = debt_st + debt_lt
    period["total_debt"] = total_debt

    if period["total_assets_smv"] is not None:
        period["total_assets"] = period["total_assets_smv"]
    else:
        ca = period["current_assets"] or 0
        nca = period["noncurrent_assets"] or 0
        period["total_assets"] = (ca + nca) or None

    period["net_debt"] = (
        total_debt - period["cash"] if period["cash"] is not None else None
    )

    period["gross_margin"] = _safe_div(period["gross_profit"], revenue)
    period["operating_margin"] = _safe_div(period["operating_income"], revenue)
    period["net_margin"] = _safe_div(period["net_income"], revenue)

    period["ebitda"] = period["operating_income"]

    period["current_ratio"] = _safe_div(period["current_assets"], period["current_liab"])
    quick_num = None
    if period["cash"] is not None and period["accounts_receivable"] is not None:
        quick_num = period["cash"] + period["accounts_receivable"]
    period["quick_ratio"] = _safe_div(quick_num, period["current_liab"])

    if period["interest_expense"] is not None and period["interest_expense"] != 0:
        period["interest_coverage"] = _safe_div(
            period["operating_income"], abs(period["interest_expense"])
        )
    else:
        period["interest_coverage"] = None

    if period["income_tax"] is not None and period["pretax_income"]:
        period["effective_tax_rate"] = abs(period["income_tax"]) / period["pretax_income"]
    else:
        period["effective_tax_rate"] = None

    ip_op = period["interest_paid_op"] or 0
    ip_fin = period["interest_paid_fin"] or 0
    interest_paid = abs(ip_op) + abs(ip_fin)
    period["interest_paid"] = interest_paid if interest_paid > 0 else None

    div_fin = period["dividends_paid_fin"]
    period["dividends_paid"] = abs(div_fin) if div_fin else None

    tx_op = period["taxes_paid_op"]
    period["taxes_paid"] = abs(tx_op) if tx_op else None

    period["payout_ratio"] = _safe_div(period["dividends_paid"], period["net_income"])

    capex_ppe = period["capex_ppe"] or 0
    capex_int = period["capex_intangibles"] or 0
    capex_total_signed = capex_ppe + capex_int
    period["capex_total"] = (
        abs(capex_total_signed) if capex_total_signed != 0 else None
    )
    period["capex_intensity"] = _safe_div(period["capex_total"], revenue)

    op_cf = period["operating_cf"]
    if op_cf is None:
        period["fcf"] = None
    else:
        period["fcf"] = op_cf + capex_total_signed

    # ROE y ROIC con promedios reales (Monto2)
    avg_equity = _avg(equity, equity_prior)
    period["roe"] = _safe_div(period["net_income"], avg_equity)
    if equity_prior is not None and (debt_st_prior is not None or debt_lt_prior is not None):
        ic_prior = equity_prior + (debt_st_prior or 0) + (debt_lt_prior or 0)
        avg_ic = _avg(equity + total_debt, ic_prior)
    else:
        avg_ic = equity + total_debt
    period["roic"] = _safe_div(period["net_income"], avg_ic)

    # YoY growth
    period["revenue_yoy"] = _yoy(revenue, revenue_prior)
    period["net_income_yoy"] = _yoy(period["net_income"], net_income_prior)
    period["equity_yoy"] = _yoy(equity, equity_prior)

    # raw_accounts
    raw: dict[str, dict] = {}
    raw.update(_extract_raw_accounts(pnl_e, CODIGOS_USADOS_2D))
    raw.update(_extract_raw_accounts(bal_e, CODIGOS_USADOS_2D))
    raw.update(_extract_raw_accounts(flow_e, CODIGOS_USADOS_2D))
    period["raw_accounts"] = raw

    return period


def _map_period_2f(rpj: str, pnl, bal, flow, fiscal_year: int,
                   quarter: int | None) -> dict | None:
    """Esquema 2F (bancos): mapea cuentas SMV a campos amigables bancarios."""
    if not pnl or not bal:
        return None
    pnl_e = [r for r in pnl if r.get('RPJ') == rpj]
    bal_e = [r for r in bal if r.get('RPJ') == rpj]
    flow_e = [r for r in (flow or []) if r.get('RPJ') == rpj]
    if not pnl_e or not bal_e:
        return None

    def amt(field: str, rows: list[dict]):
        return _amount(rows, FIELDS_TO_CODES_2F[field])

    def amt_prior(field: str, rows: list[dict]):
        return _amount_prior(rows, FIELDS_TO_CODES_2F[field])

    interest_income = amt("interest_income", pnl_e)
    equity = amt("equity", bal_e)
    if interest_income is None or equity is None:
        return None

    period: dict = {
        "schema": "2F",
        "fiscal_year": fiscal_year,
        "quarter": quarter,
    }

    # P&L
    period["interest_income"] = interest_income
    for f in ("interest_expense", "net_interest_income", "loan_loss_provisions",
              "fee_income_net", "trading_income", "operating_expenses",
              "operating_income", "pretax_income", "income_tax", "net_income",
              "eps", "eps_diluted"):
        period[f] = amt(f, pnl_e)

    # Balance
    for f in ("cash", "interbank_funds", "investments_fvtpl", "investments_afs",
              "investments_htm", "loans_st", "performing_loans", "refinanced_loans",
              "overdue_loans", "judicial_loans", "current_assets", "loans_lt",
              "ppe", "intangibles", "noncurrent_assets", "total_assets",
              "deposits", "interbank_funds_payable", "deposits_financial_system",
              "financial_debt_st", "current_liab", "financial_debt_lt",
              "noncurrent_liab", "total_liabilities", "share_capital", "reserves",
              "retained_earnings"):
        period[f] = amt(f, bal_e)
    period["equity"] = equity

    # Flujo
    for f in ("dna", "operating_cf", "investing_cf", "financing_cf",
              "deposits_change", "loans_change", "dividends_paid_fin", "end_cash"):
        period[f] = amt(f, flow_e)

    # --- Stocks del período anterior (Monto2) ------------------------------
    equity_prior = amt_prior("equity", bal_e)
    total_assets_prior = amt_prior("total_assets", bal_e)
    loans_st_prior = amt_prior("loans_st", bal_e)
    loans_lt_prior = amt_prior("loans_lt", bal_e)
    deposits_prior = amt_prior("deposits", bal_e)
    interest_income_prior = amt_prior("interest_income", pnl_e)
    net_income_prior = amt_prior("net_income", pnl_e)

    # --- Composites --------------------------------------------------------
    loans_st_v = period["loans_st"] or 0
    loans_lt_v = period["loans_lt"] or 0
    loans_net = loans_st_v + loans_lt_v
    period["loans_net"] = loans_net if loans_net else None

    loans_net_prior_total = (loans_st_prior or 0) + (loans_lt_prior or 0)
    if loans_net_prior_total == 0:
        loans_net_prior_total = None

    # Cartera bruta = vigente + refinanciada + vencida + judicial (solo lo que SMV expone)
    gross_loans = (
        (period["performing_loans"] or 0)
        + (period["refinanced_loans"] or 0)
        + (period["overdue_loans"] or 0)
        + (period["judicial_loans"] or 0)
    )
    period["gross_loans"] = gross_loans if gross_loans > 0 else None

    # --- Métricas derivadas ------------------------------------------------
    nii = period["net_interest_income"]

    # Eficiencia operativa = |gastos operación| / (NII + comisiones netas + ROF)
    op_exp_abs = abs(period["operating_expenses"]) if period["operating_expenses"] else None
    rev_total = (
        (nii or 0) + (period["fee_income_net"] or 0) + (period["trading_income"] or 0)
    )
    period["efficiency_ratio"] = _safe_div(op_exp_abs, rev_total) if rev_total else None

    # NPL ratio = (vencidos + judicial) / cartera_neta (proxy)
    nonperforming = (period["overdue_loans"] or 0) + (period["judicial_loans"] or 0)
    period["npl_ratio"] = _safe_div(nonperforming, loans_net) if loans_net else None

    # Loan-to-deposit
    period["loan_to_deposit_ratio"] = _safe_div(loans_net, period["deposits"])

    # Solvencia (proxy de equity / total assets, no es CET1 regulatorio)
    period["equity_to_assets"] = _safe_div(equity, period["total_assets"])

    # Tax rate efectiva
    if period["income_tax"] is not None and period["pretax_income"]:
        period["effective_tax_rate"] = abs(period["income_tax"]) / period["pretax_income"]
    else:
        period["effective_tax_rate"] = None

    # Promedios y métricas con stocks promedio (Monto2)
    avg_loans = _avg(loans_net or None, loans_net_prior_total)
    avg_assets = _avg(period["total_assets"], total_assets_prior)
    avg_equity = _avg(equity, equity_prior)

    # NIM = NII / avg_loans (cartera promedio = activos rentables proxy)
    period["nim"] = _safe_div(nii, avg_loans)

    # Cost of risk = |loan_loss_provisions| / avg_loans
    if period["loan_loss_provisions"] is not None:
        period["cost_of_risk"] = _safe_div(
            abs(period["loan_loss_provisions"]), avg_loans
        )
    else:
        period["cost_of_risk"] = None

    period["roa"] = _safe_div(period["net_income"], avg_assets)
    period["roe"] = _safe_div(period["net_income"], avg_equity)

    # Dividendos
    div_fin = period["dividends_paid_fin"]
    period["dividends_paid"] = abs(div_fin) if div_fin else None
    period["payout_ratio"] = _safe_div(period["dividends_paid"], period["net_income"])

    # YoY growth
    period["interest_income_yoy"] = _yoy(interest_income, interest_income_prior)
    period["net_income_yoy"] = _yoy(period["net_income"], net_income_prior)
    period["loans_yoy"] = _yoy(loans_net or None, loans_net_prior_total)
    period["deposits_yoy"] = _yoy(period["deposits"], deposits_prior)
    period["equity_yoy"] = _yoy(equity, equity_prior)

    # raw_accounts
    raw: dict[str, dict] = {}
    raw.update(_extract_raw_accounts(pnl_e, CODIGOS_USADOS_2F))
    raw.update(_extract_raw_accounts(bal_e, CODIGOS_USADOS_2F))
    raw.update(_extract_raw_accounts(flow_e, CODIGOS_USADOS_2F))
    period["raw_accounts"] = raw

    return period


def _map_period(rpj: str, pnl, bal, flow, fiscal_year: int,
                quarter: int | None) -> dict | None:
    """Alias retro-compatible que despacha a _map_period_2d (esquema legacy)."""
    return _map_period_2d(rpj, pnl, bal, flow, fiscal_year, quarter)


# ---------------------------------------------------------------------------
# Coordinación de descargas y normalización trimestral
# ---------------------------------------------------------------------------

def _detect_cf_ytd(rpj: str, year: int, tipo_code: str, cache_dir: Path) -> bool:
    """Detecta si el CF para esa empresa-año-tipo viene en YTD acumulado.
    Compara Q4 vs Anual para una cuenta clave. Si Q4 ≈ Anual → YTD.
    Cachea las respuestas como efecto colateral."""
    flow_q4 = _call_smv(OP_FLOW, year, "4", tipo_code, cache_dir)
    flow_anual = _call_smv(OP_FLOW, year, "A", tipo_code, cache_dir)
    if not flow_q4 or not flow_anual:
        return True  # default: asumir YTD
    # Tomamos cualquier código de subtotal de operación: 3D01ST o 3F0501.
    # Probamos ambos hasta encontrar uno con datos.
    for codigo in ("3D01ST", "3F0501"):
        if _is_ytd(flow_q4, flow_anual, rpj, codigo):
            return True
        # Si encontramos datos pero no es YTD, retornamos False
        q4 = _amount([r for r in flow_q4 if r.get('RPJ') == rpj], codigo)
        anual = _amount([r for r in flow_anual if r.get('RPJ') == rpj], codigo)
        if q4 is not None and anual is not None:
            return False
    return True  # si no encontramos datos, default YTD


def fetch_estados_financieros(
    ticker: str,
    desde: int,
    hasta: int,
    tipo: str = "consolidado",
    periodicidad: str = "anual",
    cache_dir: Path | str | None = None,
) -> dict | None:
    """Descarga estados financieros para una empresa peruana desde SMV.

    Despacha automáticamente al esquema correcto (2D industriales o 2F bancos)
    según el ticker. Cada período del output expone una key ``"schema"``.

    Para datos trimestrales: el Cash Flow se devuelve **siempre period-only**
    (no acumulado YTD), incluso si SMV lo publica en YTD. La librería detecta
    el régimen automáticamente y resta el trimestre anterior cuando corresponde.

    Args:
        ticker: ticker BVL (ej. ``"ALICORC1"``, ``"BBVAC1"``).
        desde: año fiscal inicial (inclusive).
        hasta: año fiscal final (inclusive).
        tipo: ``"consolidado"`` (default) o ``"individual"``. Cascada automática.
        periodicidad: ``"anual"`` (default) o ``"trimestral"``.
        cache_dir: directorio de cache. None = user cache dir del SO.

    Returns:
        dict con keys ``"periods"`` (lista) e ``"info"``. Cada período tiene
        ``"schema"`` ("2D" o "2F") y los campos correspondientes a ese esquema.

    Raises:
        UnknownTickerError: ticker no en el catálogo.
        ValueError: argumentos inválidos.
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

    info = resolve_ticker(ticker)
    rpj = info["rpj"]
    esquema = info.get("esquema", "2D")  # default 2D para entradas legacy
    tipo_code = _TIPO_CODES[tipo]
    periodos = _PERIODICIDAD_PERIODOS[periodicidad]

    if cache_dir is None:
        cache_dir = _default_cache_dir()
    else:
        cache_dir = Path(cache_dir).expanduser()

    if esquema == "2D":
        mapper = _map_period_2d
    elif esquema == "2F":
        mapper = _map_period_2f
    else:
        raise ValueError(f"Esquema {esquema!r} no soportado todavía")

    periods_data = []
    for y in range(desde, hasta + 1):
        # Detectar régimen YTD del CF para este año (solo si pidieron trimestral).
        # Esta detección descarga Q4 + Anual (cacheados), una vez por (empresa, año, tipo).
        cf_is_ytd = False
        if periodicidad == "trimestral":
            cf_is_ytd = _detect_cf_ytd(rpj, y, tipo_code, cache_dir)

        # Cache de respuestas para Qn-1 (necesarios si normalizamos)
        # Pre-descarga lo que necesitamos por trimestre
        for p in periodos:
            pnl = _call_smv(OP_PNL, y, p, tipo_code, cache_dir)
            bal = _call_smv(OP_BAL, y, p, tipo_code, cache_dir)
            flow = _call_smv(OP_FLOW, y, p, tipo_code, cache_dir)

            # Normalización trimestral: si el CF es YTD y este es Q2-Q4,
            # restar el trimestre anterior para obtener period-only.
            if periodicidad == "trimestral" and p in ("2", "3", "4") and cf_is_ytd and flow is not None:
                prev_p = str(int(p) - 1)
                flow_prev = _call_smv(OP_FLOW, y, prev_p, tipo_code, cache_dir)
                if flow_prev is not None:
                    flow = _subtract_rows(flow, flow_prev)

            quarter = None if p == "A" else int(p)
            yd = mapper(rpj, pnl, bal, flow, y, quarter)
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
