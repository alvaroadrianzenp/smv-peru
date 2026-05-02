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
  fetch_eeff(ticker, desde, hasta, tipo, periodicidad) -> dict | None
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import re
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path

from .empresas import resolve_ticker

logger = logging.getLogger("smv_peru")

SMV_ENDPOINT = "https://mvnet.smv.gob.pe/ws_od_eeff/WebServiceInfoFinanciera.asmx"
SMV_NAMESPACE = "http://tempuri.org/"
SMV_TIMEOUT_S = 120

# Límite máximo de workers en paralelo: no saturar el web service de SMV.
MAX_WORKERS_LIMIT = 10
# Reintentos en errores de red transitorios (timeout, connection reset).
SMV_MAX_RETRIES = 3


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
    "fx_gain_loss":      "2D0410",  # Diferencias de Cambio Neto (clave en Perú: empresas con deuda USD)
    "pretax_income":     "2D04ST",  # Ganancia (Pérdida) antes de Impuestos
    "income_tax":        "2D0502",  # Ingreso (Gasto) por Impuesto
    "net_income":        "2D07ST",  # Ganancia (Pérdida) Neta del Ejercicio
    "net_income_to_parent":   "2D0802",  # Ganancia atribuible a propietarios de la controladora
    "minority_interest":      "2D0803",  # Ganancia atribuible a participaciones no controladoras
    "eps":               "2D0911",  # Total Ganancias (Pérdida) Básica por Acción Ordinaria
    "eps_diluted":       "2D0915",  # Total Ganancias (Pérdida) Diluida por Acción Ordinaria

    # Estado de Situación Financiera (Balance)
    "cash":                "1D0109",  # Efectivo y Equivalentes al Efectivo
    "accounts_receivable": "1D0103",  # Cuentas por Cobrar Comerciales
    "inventory":           "1D0106",  # Inventarios
    "biological_assets":   "1D0112",  # Activos Biológicos (clave para agro: Casa Grande, Backus)
    "current_assets":      "1D01ST",  # Total Activos Corrientes
    "ppe":                 "1D0205",  # Propiedades, Planta y Equipo
    "intangibles":         "1D0206",  # Activos Intangibles Distintos de la Plusvalía
    "investment_property": "1D0211",  # Propiedades de Inversión
    "goodwill":            "1D0212",  # Plusvalía (Goodwill)
    "equity_investments":  "1D0214",  # Inversiones contabilizadas por método de la participación
    "noncurrent_assets":   "1D02ST",  # Total Activos No Corrientes
    "total_assets_smv":    "1D020T",  # TOTAL DE ACTIVOS (chequeo de integridad)
    "accounts_payable":    "1D0302",  # Cuentas por Pagar Comerciales
    "debt_short_term":     "1D0309",  # Otros Pasivos Financieros (corriente)
    "employee_benefits":   "1D0313",  # Provisión por Beneficios a los Empleados
    "current_liab":        "1D03ST",  # Total Pasivos Corrientes
    "debt_long_term":      "1D0401",  # Otros Pasivos Financieros (no corriente)
    "noncurrent_liab":     "1D04ST",  # Total Pasivos No Corrientes
    "total_liabilities":   "1D040T",  # Total Pasivos
    "share_capital":       "1D0701",  # Capital Emitido
    "retained_earnings":   "1D0707",  # Resultados Acumulados
    "reserves":            "1D0708",  # Otras Reservas de Patrimonio
    "investment_shares":   "1D0703",  # Acciones de Inversión (especifico Perú)
    "equity_to_parent":    "1D0710",  # Patrimonio Atribuible a Propietarios de la Controladora
    "equity":              "1D07ST",  # Total Patrimonio

    # Estado de Flujos de Efectivo (método directo)
    "cash_from_customers": "3D0101",
    "interest_received_op": "3D0103",  # Intereses recibidos clasificados en operación
    "cash_to_suppliers":   "3D0109",
    "cash_to_employees":   "3D0105",
    "interest_paid_op":    "3D0107",
    "taxes_paid_op":       "3D0120",
    "operating_cf":        "3D01ST",
    "ppe_proceeds":        "3D0202",
    "capex_ppe":           "3D0206",
    "capex_intangibles":   "3D0207",
    "dividends_received":  "3D0211",  # Dividendos recibidos (actividad inversión)
    # M&A en NIC 7: tres cuentas estándar de transacciones estratégicas.
    "subsidiaries_lost_control":     "3D0218",  # (+) pérdida de control: desinversión
    "subsidiaries_purchased":        "3D0219",  # (−) compra menor (sin obtener control)
    "subsidiaries_obtained_control": "3D0232",  # (−) adquisición que da control mayoritario
    "investing_cf":        "3D02ST",
    "dividends_paid_fin":  "3D0305",
    "interest_paid_fin":   "3D0311",
    "debt_issued":         "3D0325",
    "equity_issued":       "3D0327",  # Emisión de Acciones (aumento de capital)
    "debt_repaid":         "3D0330",
    "financing_cf":        "3D03ST",
    "cash_change_pre_fx":  "3D0401",  # Aumento/Disminución neto antes de FX
    "fx_effect_cash":      "3D0404",  # Efecto del tipo de cambio sobre el efectivo
    "net_change_in_cash":  "3D0405",  # Aumento/Disminución neto total
    "start_cash":          "3D0402",  # Efectivo al inicio del período
    "end_cash":            "3D04ST",  # Efectivo al cierre del período
    # D&A: solo aparece cuando la empresa publica CF con MÉTODO INDIRECTO.
    # Para empresas con método directo, esta cuenta no existe en SMV y `dna`
    # quedará None — y por consiguiente `ebitda` y todas las métricas
    # derivadas (ebitda_margin, debt_to_ebitda, net_debt_to_ebitda,
    # interest_coverage_ebitda) también serán None. Para esos casos, el
    # analista puede usar set_dna() para proveer D&A externo (ej. desde
    # notas a EEFF auditados) y la librería recalcula automáticamente.
    "dna":                 "3D0602",  # Depreciación, Amortización y Agotamiento

    # Estado de Flujos de Efectivo (método INDIRECTO).
    # SMV no expone DescripcionCuenta para estos códigos vía web service; los
    # nombres amigables siguen la nomenclatura NIC 7 estándar y fueron
    # validados conceptualmente contra el EEFF auditado de Cementos Pacasmayo
    # (publicado en SMV). Para empresas con método directo, todos estos
    # campos quedan None.
    "ni_before_tax_cf":          "3D05ST",  # Utilidad antes del impuesto a la renta (punto de partida)
    "fx_adjustment_cf":          "3D0605",  # Diferencia en cambio (ajuste no-cash)
    "ppe_disposal_cf":           "3D0610",  # (Ganancia)/pérdida por venta de propiedades, planta y equipo
    "other_non_cash_cf":         "3D0620",  # Otras partidas que no generan flujos operativos
    "change_in_receivables":     "3D0801",  # Variación en cuentas por cobrar comerciales y diversas
    "change_in_other_op_assets": "3D0803",  # Variación en otros activos operativos (incl. gastos pagados por adelantado)
    "change_in_inventory":       "3D0804",  # Variación en inventarios
    "change_in_payables":        "3D0806",  # Variación en cuentas por pagar comerciales y diversas
    "change_in_other_op_liab":   "3D0809",  # Variación en otros pasivos operativos
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
    "repossessed_assets":          "1F1001",  # Bienes realizables, recibidos en pago, adjudicados
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
    "net_interest_income": "2F2301",  # MARGEN BRUTO (oficial SMV)
    # IMPORTANTE: este campo es el "MARGEN BRUTO" oficial de SMV, NO el "Net
    # Interest Income puro". El MARGEN BRUTO se calcula como:
    #   2F01ST (INGRESOS OPERACIONALES) − |2F03ST (COSTOS OPERACIONALES)|
    # En bancos puros (BBVA, BCP) coincide con interest_income + interest_expense
    # porque solo tienen 2F0101 e 2F0301 como ingresos/costos operacionales.
    # En holdings con seguros (BAP, IFS) incluye también primas (2F0102) y
    # siniestros (2F0302). En Scotiabank incluye otros ingresos/costos de
    # operación (2F0221, 2F0304) además de intereses.
    # Para el "NII puro" (solo margen financiero del negocio bancario core),
    # ver el campo derivado `nii_pure` que la librería expone.
    "loan_loss_provisions": "2F2304",  # Provisión para créditos (negativo)
    "nii_after_provisions": "2F2401",  # Margen Financiero Neto (NII − LLP)
    "fee_income_net":      "2F2406",  # Comisiones (netas)
    "trading_income":      "2F2506",  # Resultado por operaciones financieras (ROF)
    "operating_expenses":  "2F2602",  # Gastos de administración (negativo)
    "operating_income":    "2F2801",  # Resultado de operación
    "non_op_items":        "2F2802",  # Otros ingresos y gastos (no operativos)
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
    "cash_change_pre_fx": "3F1002",  # Aumento/Disminución neto antes de FX
    "fx_effect_cash":     "3F1003",  # Efecto del tipo de cambio sobre el efectivo
    "net_change_in_cash": "3F1001",  # Aumento/Disminución neto total
    "start_cash":         "3F1101",  # Efectivo al inicio del período
    "end_cash":         "3F1201",  # Efectivo al cierre del período
}

CODIGOS_USADOS_2F: frozenset[str] = frozenset(FIELDS_TO_CODES_2F.values())


# ---------------------------------------------------------------------------
# Esquema 2F Individual (SBS): los EEFF Individuales de bancos en SMV usan un
# formato distinto al Consolidado, más detallado y alineado a SBS. Los códigos
# que difieren se mapean aquí. Si una empresa cae a Individual (por
# `tipo='individual'` o por la cascada por-período), `_map_period_2f` detecta
# el esquema automáticamente y usa estos overrides.
# ---------------------------------------------------------------------------
_2F_INDIVIDUAL_OVERRIDES: dict[str, str] = {
    "loan_loss_provisions": "2F2306",  # vs 2F2304 en Consolidado
    "pretax_income":        "2F1302",  # vs 2F2809
    "eps":                  "2F2201",  # vs 2F2204
    "eps_diluted":          "2F2202",  # vs 2F2206
    "loans_change":         "3F0418",  # vs 3F0805
    # `1F2401` es el total de "Adeudos y Obligaciones Financieras" sin separar
    # por plazo; lo mapeamos a financial_debt_lt para preservar el monto total
    # (financial_debt_st queda None — ver _2F_INDIVIDUAL_UNAVAILABLE).
    "financial_debt_lt":    "1F2401",
    # Subtotales del P&L bancario que solo expone el esquema Individual SBS
    # (no existen en Consolidado NIIF). En Consolidado quedan None.
    "op_revenue_after_fees":      "2F2505",  # Margen neto de servicios
    "op_revenue_total":           "2F2601",  # Margen operacional (incl. ROF)
    "op_income_pre_op_provisions": "2F2701",  # Margen operacional neto
}

# Campos cuya información no está separada en el esquema Individual SBS.
# `loans_lt` queda None — el total de cartera ya está en loans_st (1F0111).
_2F_INDIVIDUAL_UNAVAILABLE: frozenset[str] = frozenset({
    "loans_lt", "financial_debt_st", "deposits_change",
})

# Campos compuestos: en Individual SBS se desagregan en varios códigos que
# hay que sumar. Los signos vienen ya de SMV (2F2501 ya es negativo).
_2F_INDIVIDUAL_COMPOSITES: dict[str, tuple[str, ...]] = {
    "fee_income_net":     ("2F2402", "2F2501"),
    "operating_expenses": ("2F2603", "2F2604", "2F2605", "2F0906"),
}

# Códigos extra usados por el esquema Individual (para que raw_accounts los
# excluya correctamente cuando el período viene de Individual).
_CODIGOS_USADOS_2F_INDIVIDUAL: frozenset[str] = frozenset(
    list(_2F_INDIVIDUAL_OVERRIDES.values())
    + [c for codes in _2F_INDIVIDUAL_COMPOSITES.values() for c in codes]
)


def _is_2f_individual_schema(pnl_rows: list[dict]) -> bool:
    """Detecta si las filas vienen del esquema Individual SBS.

    Marcadores exclusivos del esquema Individual SBS:
    - `2F1302` ("RESULTADO DEL EJERCICIO ANTES DE IMPUESTO A LA RENTA")
    - `2F2306` ("(-) Provisiones para créditos directos")

    Ambos están confirmados como ausentes del esquema Consolidado NIIF.
    Otros códigos (ej. `2F2201` para EPS básica) aparecen en ambos esquemas
    y NO sirven como marcador.
    """
    markers = ("2F1302", "2F2306")
    return any(any(r.get('Cuenta') == m for r in pnl_rows) for m in markers)


def _resolve_amount_2f(field: str, rows: list[dict], individual: bool):
    """Resuelve el monto de un campo 2F respetando el esquema detectado.

    En Consolidado, los campos que existen solo en Individual SBS (ej.
    op_revenue_total = 2F2601) devuelven None — no hay código equivalente
    en el esquema NIIF Consolidado.
    """
    if individual:
        if field in _2F_INDIVIDUAL_UNAVAILABLE:
            return None
        if field in _2F_INDIVIDUAL_COMPOSITES:
            vals = [_amount(rows, c) for c in _2F_INDIVIDUAL_COMPOSITES[field]]
            non_none = [v for v in vals if v is not None]
            return sum(non_none) if non_none else None
        code = _2F_INDIVIDUAL_OVERRIDES.get(field) or FIELDS_TO_CODES_2F.get(field)
        return _amount(rows, code) if code else None
    code = FIELDS_TO_CODES_2F.get(field)
    return _amount(rows, code) if code else None


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
    """Llama una operación SOAP; cachea en disco. Devuelve la lista de filas.

    El cache se almacena comprimido con gzip (extensión .json.gz). Esto
    reduce ~96% el tamaño en disco vs JSON crudo (las respuestas SMV tienen
    mucha redundancia) sin penalizar la velocidad de lectura (la menor I/O
    compensa el costo de descompresión CPU).

    Compatibilidad: si encuentra archivos .json (formato legacy de versiones
    anteriores), los lee sin problema. Solo escribe en .json.gz.

    Implementa reintentos con backoff exponencial para errores transitorios
    de red (timeouts, connection reset). Errores definitivos (sin Result, JSON
    inválido) NO se reintentan — implican que la respuesta de SMV fue inválida
    semánticamente (ej. año/empresa sin datos).
    """
    import random
    import time as _time

    base_name = f"{operacion}_{ejercicio}_{tipo}_{periodo}"
    cache_gz = cache_dir / f"{base_name}.json.gz"
    cache_json = cache_dir / f"{base_name}.json"  # legacy

    # Leer cache: probar .json.gz primero, fallback a .json legacy
    if cache_gz.exists():
        try:
            with gzip.open(cache_gz, 'rt', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError, EOFError):
            logger.warning(f"Cache corrupto: {cache_gz}, re-descargando")
    elif cache_json.exists():
        try:
            return json.loads(cache_json.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            logger.warning(f"Cache corrupto: {cache_json}, re-descargando")

    req = urllib.request.Request(
        SMV_ENDPOINT,
        data=_soap_envelope(operacion, ejercicio, periodo, tipo),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f'"{SMV_NAMESPACE}{operacion}"',
        },
    )

    raw = None
    for attempt in range(SMV_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=SMV_TIMEOUT_S) as resp:
                raw = resp.read().decode('utf-8', errors='replace')
            break  # éxito
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == SMV_MAX_RETRIES:
                logger.warning(
                    f"SMV {operacion} {ejercicio} {tipo} P={periodo} "
                    f"falló tras {SMV_MAX_RETRIES + 1} intentos: {e}"
                )
                return None
            sleep_s = (2 ** attempt) + random.uniform(0, 0.5)
            logger.info(
                f"SMV {operacion} {ejercicio} {tipo} P={periodo} intento "
                f"{attempt + 1}/{SMV_MAX_RETRIES + 1} falló ({e}); "
                f"reintentando en {sleep_s:.1f}s"
            )
            _time.sleep(sleep_s)

    if raw is None:
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
    with gzip.open(cache_gz, 'wt', encoding='utf-8') as f:
        json.dump(data, f)
    logger.info(f"SMV {operacion} {ejercicio} {tipo} P={periodo}: {len(data)} filas, cacheado (gzip)")
    return data


def _make_progress_writer(total: int, label: str):
    """Devuelve una función `tick()` que avanza una barra de progreso a stderr.

    Diseño minimalista (sin dependencias externas):
    - Si stderr no es TTY (ej. salida redirigida o CI), devuelve un no-op para
      no contaminar logs.
    - Si total < 2, también no-op (no aporta para una sola llamada).
    - Thread-safe: el contador se protege con un Lock para soportar el
      ThreadPoolExecutor de las descargas paralelas.

    Output: ``\\r<label> [████░░░░] 12/24`` actualizado en sitio. Al llegar
    al total, agrega un \\n para liberar la línea.
    """
    if total < 2 or not sys.stderr.isatty():
        return lambda: None

    state = {"done": 0}
    lock = threading.Lock()
    width = 24

    def tick():
        with lock:
            state["done"] += 1
            n = state["done"]
        filled = int(width * n / total)
        bar = "█" * filled + "·" * (width - filled)
        end = "\n" if n >= total else ""
        sys.stderr.write(f"\r{label} [{bar}] {n}/{total}{end}")
        sys.stderr.flush()

    return tick


def _has_rpj_data(rows: list[dict] | None, rpj: str) -> bool:
    """True si la lista contiene al menos una fila con el RPJ dado."""
    if not rows:
        return False
    return any(r.get('RPJ') == rpj for r in rows)


def _detect_currency(rows: list[dict]) -> str | None:
    """Detecta moneda desde el campo 'Moneda' de la primera fila.

    SMV publica como string 'Soles', 'Dolares' (con codificación variable;
    a veces aparece como 'D lares' por encoding). Normaliza a códigos ISO
    'PEN' / 'USD'. Devuelve None si no logra clasificar.
    """
    if not rows:
        return None
    raw = (rows[0].get('Moneda') or '').strip().upper()
    if not raw:
        return None
    # Heurística robusta a problemas de encoding ('Dolares', 'D lares', 'Dólares')
    if 'SOL' in raw:
        return "PEN"
    if 'DOLAR' in raw or 'LARES' in raw:  # 'D lares' tiene 'LARES'
        return "USD"
    return raw  # devolver crudo si no clasificamos


def _detect_cf_method(rows: list[dict]) -> str | None:
    """Lee MetodoFlujoEfectivo de la primera fila y normaliza a 'directo'/'indirecto'.

    SMV publica el método como texto en cada fila ('Método Directo' / 'Método
    Indirecto'). El encoding a veces aparece sin tilde ('M todo Directo'),
    así que la heurística busca la palabra clave 'irect'/'ndirect'.
    """
    if not rows:
        return None
    raw = (rows[0].get('MetodoFlujoEfectivo') or '').strip()
    if 'ndirect' in raw.lower():
        return "indirecto"
    if 'irect' in raw.lower():  # 'directo' o 'Directo'
        return "directo"
    return None


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
        "currency": _detect_currency(pnl_e) or _detect_currency(bal_e),
    }

    period["revenue"] = revenue
    for f in ("cogs", "gross_profit", "admin_expenses", "selling_expenses",
              "other_op_income", "other_op_expenses", "operating_income",
              "interest_income", "interest_expense", "fx_gain_loss",
              "pretax_income", "income_tax", "net_income",
              "net_income_to_parent", "minority_interest",
              "eps", "eps_diluted"):
        period[f] = amt(f, pnl_e)

    for f in ("cash", "accounts_receivable", "inventory", "biological_assets",
              "current_assets",
              "ppe", "intangibles", "investment_property", "goodwill",
              "equity_investments", "noncurrent_assets", "total_assets_smv",
              "accounts_payable", "debt_short_term", "employee_benefits",
              "current_liab",
              "debt_long_term", "noncurrent_liab", "total_liabilities",
              "share_capital", "retained_earnings", "reserves",
              "investment_shares", "equity_to_parent"):
        period[f] = amt(f, bal_e)
    period["equity"] = equity
    # Derivado: patrimonio atribuible a no controladoras = equity total -
    # equity de la controladora. SMV no expone una cuenta separada para esto;
    # se calcula como diferencia.
    if period["equity_to_parent"] is not None:
        period["minority_equity"] = equity - period["equity_to_parent"]
    else:
        period["minority_equity"] = None

    for f in ("cash_from_customers", "interest_received_op",
              "cash_to_suppliers", "cash_to_employees",
              "interest_paid_op", "taxes_paid_op", "operating_cf",
              "ppe_proceeds", "capex_ppe", "capex_intangibles",
              "dividends_received",
              "subsidiaries_lost_control", "subsidiaries_purchased",
              "subsidiaries_obtained_control",
              "investing_cf",
              "dividends_paid_fin", "interest_paid_fin", "debt_issued",
              "equity_issued", "debt_repaid", "financing_cf",
              "cash_change_pre_fx", "fx_effect_cash", "net_change_in_cash",
              "start_cash", "end_cash", "dna",
              "ni_before_tax_cf", "fx_adjustment_cf", "ppe_disposal_cf",
              "other_non_cash_cf", "change_in_receivables",
              "change_in_other_op_assets", "change_in_inventory",
              "change_in_payables", "change_in_other_op_liab"):
        period[f] = amt(f, flow_e)

    # Método de presentación del CF (directo vs indirecto). SMV lo expone
    # explícitamente en el campo MetodoFlujoEfectivo de cada fila. Las
    # empresas con método directo dejan vacíos los 9 campos *_cf y
    # change_in_* del bloque indirecto, y viceversa.
    period["cf_method"] = _detect_cf_method(flow_e)

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

    # EBITDA real (no proxy): solo si SMV expone D&A (cuenta 3D0602, disponible
    # solo en empresas que publican CF con método indirecto). Si la empresa
    # usa método directo (mayoría en Perú), `ebitda` queda None — junto con
    # ebitda_margin, debt_to_ebitda, net_debt_to_ebitda, interest_coverage_ebitda.
    # Para esos casos el analista puede usar set_dna() con D&A externo (notas
    # a EEFF auditados) y la librería recalcula automáticamente.
    dna_v = period["dna"]
    op_inc = period["operating_income"]
    if dna_v is not None and op_inc is not None:
        period["ebitda"] = op_inc + abs(dna_v)
    else:
        period["ebitda"] = None

    period["ebitda_margin"] = _safe_div(period["ebitda"], revenue)
    period["debt_to_ebitda"] = (
        total_debt / period["ebitda"] if period["ebitda"] else None
    )
    period["net_debt_to_ebitda"] = (
        period["net_debt"] / period["ebitda"]
        if (period["ebitda"] and period["net_debt"] is not None) else None
    )

    period["current_ratio"] = _safe_div(period["current_assets"], period["current_liab"])
    quick_num = None
    if period["cash"] is not None and period["accounts_receivable"] is not None:
        quick_num = period["cash"] + period["accounts_receivable"]
    period["quick_ratio"] = _safe_div(quick_num, period["current_liab"])
    # Cash ratio: liquidez más estricta (solo efectivo / pasivos corrientes)
    period["cash_ratio"] = _safe_div(period["cash"], period["current_liab"])

    # Solvencia adicional (stocks/stocks, sin necesidad de LTM)
    period["debt_to_equity"] = _safe_div(total_debt or None, equity)
    period["equity_ratio"] = _safe_div(equity, period["total_assets"])

    # Cobertura de intereses (Times Interest Earned, EBIT-based)
    if period["interest_expense"] is not None and period["interest_expense"] != 0:
        period["interest_coverage"] = _safe_div(
            period["operating_income"], abs(period["interest_expense"])
        )
    else:
        period["interest_coverage"] = None

    # Cobertura con EBITDA real: ebitda / |interest_expense| (None si no hay D&A)
    if (period["ebitda"] is not None and period["interest_expense"] is not None
            and period["interest_expense"] != 0):
        period["interest_coverage_ebitda"] = (
            period["ebitda"] / abs(period["interest_expense"])
        )
    else:
        period["interest_coverage_ebitda"] = None

    if period["income_tax"] is not None and period["pretax_income"]:
        period["effective_tax_rate"] = abs(period["income_tax"]) / period["pretax_income"]
    else:
        period["effective_tax_rate"] = None

    # Pagos en efectivo: mantener el signo natural de SMV (negativo cuando es
    # salida de caja). El Excel muestra los negativos entre paréntesis, así
    # el lector puede sumar mentalmente para verificar el subtotal SMV.
    ip_op = period["interest_paid_op"] or 0
    ip_fin = period["interest_paid_fin"] or 0
    interest_paid_total = ip_op + ip_fin
    period["interest_paid"] = interest_paid_total if interest_paid_total != 0 else None

    period["dividends_paid"] = period["dividends_paid_fin"]
    period["taxes_paid"] = period["taxes_paid_op"]

    # Ratios usan abs() internamente para que no salgan negativos por convención.
    period["payout_ratio"] = _safe_div(
        abs(period["dividends_paid"]) if period["dividends_paid"] else None,
        period["net_income"],
    )

    capex_ppe = period["capex_ppe"] or 0
    capex_int = period["capex_intangibles"] or 0
    capex_total_signed = capex_ppe + capex_int
    period["capex_total"] = capex_total_signed if capex_total_signed != 0 else None
    period["capex_intensity"] = _safe_div(
        abs(period["capex_total"]) if period["capex_total"] else None,
        revenue,
    )

    op_cf = period["operating_cf"]
    if op_cf is None:
        period["fcf"] = None
    else:
        period["fcf"] = op_cf + capex_total_signed

    # ROE, ROIC, ROA con promedios reales (Monto2)
    avg_equity = _avg(equity, equity_prior)
    period["roe"] = _safe_div(period["net_income"], avg_equity)
    if equity_prior is not None and (debt_st_prior is not None or debt_lt_prior is not None):
        ic_prior = equity_prior + (debt_st_prior or 0) + (debt_lt_prior or 0)
        avg_ic = _avg(equity + total_debt, ic_prior)
    else:
        avg_ic = equity + total_debt
    period["roic"] = _safe_div(period["net_income"], avg_ic)
    # ROA con avg_assets si hay total_assets prior; si no, usa el actual
    total_assets_prior = (
        (amt_prior("current_assets", bal_e) or 0)
        + (amt_prior("noncurrent_assets", bal_e) or 0)
    ) or None
    avg_assets = _avg(period["total_assets"], total_assets_prior)
    period["roa"] = _safe_div(period["net_income"], avg_assets)

    # Métricas de Cash Flow (todas son flujo/flujo o flujo/stock; el post-pass
    # LTM las recalcula correctamente para datos trimestrales).
    period["ocf_margin"] = _safe_div(op_cf, revenue)
    period["fcf_margin"] = _safe_div(period["fcf"], revenue)
    period["cash_conversion"] = _safe_div(op_cf, period["net_income"])
    period["fcf_to_net_income"] = _safe_div(period["fcf"], period["net_income"])
    period["cfo_to_debt"] = _safe_div(op_cf, total_debt or None)
    period["fcf_to_debt"] = _safe_div(period["fcf"], total_debt or None)
    period["capex_to_dna"] = _safe_div(
        abs(period["capex_total"]) if period["capex_total"] else None,
        abs(dna_v) if dna_v else None,
    )
    period["dividend_coverage_fcf"] = _safe_div(
        period["fcf"],
        abs(period["dividends_paid"]) if period["dividends_paid"] else None,
    )
    period["cash_interest_coverage"] = _safe_div(
        op_cf,
        abs(period["interest_paid"]) if period["interest_paid"] else None,
    )

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
    """Esquema 2F (bancos): mapea cuentas SMV a campos amigables bancarios.

    Detecta automáticamente si las filas vienen del esquema "Consolidado NIIF"
    o del "Individual SBS". Algunos códigos difieren entre los dos esquemas
    (ej. loan_loss_provisions: 2F2304 vs 2F2306) y otros no existen en
    Individual (loans_lt, financial_debt_st, deposits_change → None).
    """
    if not pnl or not bal:
        return None
    pnl_e = [r for r in pnl if r.get('RPJ') == rpj]
    bal_e = [r for r in bal if r.get('RPJ') == rpj]
    flow_e = [r for r in (flow or []) if r.get('RPJ') == rpj]
    if not pnl_e or not bal_e:
        return None

    is_individual = _is_2f_individual_schema(pnl_e)

    def amt(field: str, rows: list[dict]):
        return _resolve_amount_2f(field, rows, is_individual)

    def amt_prior(field: str, rows: list[dict]):
        # Para promedios usamos Monto2 — solo sobre códigos directos, no
        # composites (los composites son sumas y SMV las publica ya armadas
        # como Monto1; Monto2 puede no ser confiable para sumas multi-código).
        if is_individual:
            if field in _2F_INDIVIDUAL_UNAVAILABLE or field in _2F_INDIVIDUAL_COMPOSITES:
                return None
            code = _2F_INDIVIDUAL_OVERRIDES.get(field) or FIELDS_TO_CODES_2F.get(field)
            return _amount_prior(rows, code) if code else None
        code = FIELDS_TO_CODES_2F.get(field)
        return _amount_prior(rows, code) if code else None

    interest_income = amt("interest_income", pnl_e)
    equity = amt("equity", bal_e)
    if interest_income is None or equity is None:
        return None

    period: dict = {
        "schema": "2F",
        "fiscal_year": fiscal_year,
        "quarter": quarter,
        "currency": _detect_currency(pnl_e) or _detect_currency(bal_e),
    }

    # P&L
    period["interest_income"] = interest_income
    for f in ("interest_expense", "net_interest_income", "loan_loss_provisions",
              "nii_after_provisions",
              "fee_income_net", "op_revenue_after_fees",
              "trading_income", "op_revenue_total",
              "operating_expenses", "op_income_pre_op_provisions",
              "operating_income", "non_op_items",
              "pretax_income", "income_tax", "net_income",
              "eps", "eps_diluted"):
        period[f] = amt(f, pnl_e)

    # Balance
    for f in ("cash", "interbank_funds", "investments_fvtpl", "investments_afs",
              "investments_htm", "loans_st", "performing_loans", "refinanced_loans",
              "overdue_loans", "judicial_loans", "current_assets", "loans_lt",
              "ppe", "intangibles", "repossessed_assets",
              "noncurrent_assets", "total_assets",
              "deposits", "interbank_funds_payable", "deposits_financial_system",
              "financial_debt_st", "current_liab", "financial_debt_lt",
              "noncurrent_liab", "total_liabilities", "share_capital", "reserves",
              "retained_earnings"):
        period[f] = amt(f, bal_e)
    period["equity"] = equity

    # Flujo
    for f in ("dna", "operating_cf", "investing_cf", "financing_cf",
              "deposits_change", "loans_change", "dividends_paid_fin",
              "cash_change_pre_fx", "fx_effect_cash", "net_change_in_cash",
              "start_cash", "end_cash"):
        period[f] = amt(f, flow_e)
    period["cf_method"] = _detect_cf_method(flow_e)

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
    # NII puro: margen financiero del negocio bancario core (solo intereses).
    # Para BBVA/BCP coincide con `net_interest_income`. Para holdings (BAP,
    # IFS) y bancos con servicios mixtos (Scotiabank) difiere porque el
    # `net_interest_income` (= MARGEN BRUTO SMV) incluye además primas/
    # siniestros u otros ingresos/costos operacionales.
    ii_pure = period["interest_income"]
    ie_pure = period["interest_expense"]
    if ii_pure is not None and ie_pure is not None:
        period["nii_pure"] = ii_pure + ie_pure
    else:
        period["nii_pure"] = None

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

    # Dividendos: mantener signo natural de SMV (negativo cuando es salida).
    period["dividends_paid"] = period["dividends_paid_fin"]
    period["payout_ratio"] = _safe_div(
        abs(period["dividends_paid"]) if period["dividends_paid"] else None,
        period["net_income"],
    )

    # YoY growth
    period["interest_income_yoy"] = _yoy(interest_income, interest_income_prior)
    period["net_income_yoy"] = _yoy(period["net_income"], net_income_prior)
    period["loans_yoy"] = _yoy(loans_net or None, loans_net_prior_total)
    period["deposits_yoy"] = _yoy(period["deposits"], deposits_prior)
    period["equity_yoy"] = _yoy(equity, equity_prior)

    # raw_accounts: si el esquema es Individual SBS, también excluimos los
    # códigos extra usados por ese esquema para no duplicar información.
    used = CODIGOS_USADOS_2F | _CODIGOS_USADOS_2F_INDIVIDUAL if is_individual else CODIGOS_USADOS_2F
    raw: dict[str, dict] = {}
    raw.update(_extract_raw_accounts(pnl_e, used))
    raw.update(_extract_raw_accounts(bal_e, used))
    raw.update(_extract_raw_accounts(flow_e, used))
    period["raw_accounts"] = raw

    return period


def _map_period(rpj: str, pnl, bal, flow, fiscal_year: int,
                quarter: int | None) -> dict | None:
    """Alias retro-compatible que despacha a _map_period_2d (esquema legacy)."""
    return _map_period_2d(rpj, pnl, bal, flow, fiscal_year, quarter)


def _quarter_offset(year: int, quarter: int, n: int) -> tuple[int, int]:
    """Devuelve (year, quarter) para `n` trimestres antes del trimestre dado."""
    total = year * 4 + (quarter - 1) - n
    return (total // 4, (total % 4) + 1)


def _ltm_sum(window: list[dict], field: str):
    """Suma `field` sobre los períodos de `window`. None si falta cualquiera."""
    vals = [p.get(field) for p in window]
    if any(v is None for v in vals):
        return None
    return sum(vals)


_LTM_FIELDS_2D = (
    # Rentabilidad
    "roe", "roic", "roa",
    # Cobertura
    "interest_coverage", "interest_coverage_ebitda", "cash_interest_coverage",
    # Solvencia (flujo/stock)
    "debt_to_ebitda", "net_debt_to_ebitda",
    "cfo_to_debt", "fcf_to_debt",
    # Política de capital
    "payout_ratio", "dividend_coverage_fcf",
    # Cash flow (flujo/flujo)
    "ocf_margin", "fcf_margin", "cash_conversion", "fcf_to_net_income",
    "capex_intensity", "capex_to_dna",
)

_LTM_FIELDS_2F = ("nim", "cost_of_risk", "roa", "roe", "payout_ratio")


def _apply_ltm_2d(periods: list[dict]) -> None:
    """Sobrescribe in-place las métricas LTM-sensibles de períodos trimestrales 2D.

    LTM = Last Twelve Months: numeradores (flujos) sumados sobre el trimestre
    actual + 3 anteriores; denominadores (stocks) promediados entre el cierre
    actual y el cierre del mismo trimestre del año anterior. Si falta historia
    suficiente (cualquier trimestre faltante en la ventana o el balance hace
    4 trimestres), todas las métricas LTM del período → None.

    Anuales (`quarter is None`) no se tocan.
    """
    by_key = {(p["fiscal_year"], p["quarter"]): p for p in periods
              if p.get("quarter") is not None}

    for p in periods:
        q = p.get("quarter")
        if q is None:
            continue
        y = p["fiscal_year"]
        prev = [by_key.get(_quarter_offset(y, q, i)) for i in (1, 2, 3)]
        stock_4q_ago = by_key.get(_quarter_offset(y, q, 4))

        if any(pp is None for pp in prev) or stock_4q_ago is None:
            for m in _LTM_FIELDS_2D:
                p[m] = None
            continue

        window = [p, *prev]
        ltm_ni = _ltm_sum(window, "net_income")
        ltm_oi = _ltm_sum(window, "operating_income")
        ltm_ie = _ltm_sum(window, "interest_expense")
        ltm_revenue = _ltm_sum(window, "revenue")
        ltm_ebitda = _ltm_sum(window, "ebitda")
        ltm_capex = _ltm_sum(window, "capex_total")
        ltm_div = _ltm_sum(window, "dividends_paid")
        ltm_dna = _ltm_sum(window, "dna")
        ltm_ocf = _ltm_sum(window, "operating_cf")
        ltm_fcf = _ltm_sum(window, "fcf")
        ltm_int_paid = _ltm_sum(window, "interest_paid")

        avg_equity = _avg(p.get("equity"), stock_4q_ago.get("equity"))
        avg_assets = _avg(p.get("total_assets"), stock_4q_ago.get("total_assets"))
        ic_now = (p.get("equity") or 0) + (p.get("total_debt") or 0)
        ic_prev = (stock_4q_ago.get("equity") or 0) + (stock_4q_ago.get("total_debt") or 0)
        avg_ic = _avg(ic_now, ic_prev)
        total_debt_now = p.get("total_debt")
        net_debt_now = p.get("net_debt")

        # Rentabilidad
        p["roe"] = _safe_div(ltm_ni, avg_equity)
        p["roic"] = _safe_div(ltm_ni, avg_ic)
        p["roa"] = _safe_div(ltm_ni, avg_assets)

        # Cobertura
        if ltm_ie is not None and ltm_ie != 0:
            p["interest_coverage"] = _safe_div(ltm_oi, abs(ltm_ie))
        else:
            p["interest_coverage"] = None

        if ltm_ebitda is not None and ltm_ie is not None and ltm_ie != 0:
            p["interest_coverage_ebitda"] = ltm_ebitda / abs(ltm_ie)
        else:
            p["interest_coverage_ebitda"] = None

        p["cash_interest_coverage"] = _safe_div(
            ltm_ocf,
            abs(ltm_int_paid) if ltm_int_paid is not None else None,
        )

        # Solvencia / apalancamiento
        p["debt_to_ebitda"] = (
            total_debt_now / ltm_ebitda
            if (ltm_ebitda and total_debt_now is not None) else None
        )
        p["net_debt_to_ebitda"] = (
            net_debt_now / ltm_ebitda
            if (ltm_ebitda and net_debt_now is not None) else None
        )
        p["cfo_to_debt"] = _safe_div(ltm_ocf, total_debt_now or None)
        p["fcf_to_debt"] = _safe_div(ltm_fcf, total_debt_now or None)

        # Política de capital
        p["payout_ratio"] = _safe_div(
            abs(ltm_div) if ltm_div is not None else None, ltm_ni
        )
        p["dividend_coverage_fcf"] = _safe_div(
            ltm_fcf,
            abs(ltm_div) if ltm_div is not None else None,
        )

        # Cash flow margins / quality
        p["ocf_margin"] = _safe_div(ltm_ocf, ltm_revenue)
        p["fcf_margin"] = _safe_div(ltm_fcf, ltm_revenue)
        p["cash_conversion"] = _safe_div(ltm_ocf, ltm_ni)
        p["fcf_to_net_income"] = _safe_div(ltm_fcf, ltm_ni)
        p["capex_intensity"] = _safe_div(
            abs(ltm_capex) if ltm_capex is not None else None, ltm_revenue
        )
        p["capex_to_dna"] = _safe_div(
            abs(ltm_capex) if ltm_capex is not None else None,
            abs(ltm_dna) if ltm_dna is not None else None,
        )


def _apply_ltm_2f(periods: list[dict]) -> None:
    """Sobrescribe in-place las métricas LTM-sensibles de períodos trimestrales 2F.

    Misma lógica que `_apply_ltm_2d`. Métricas: nim, cost_of_risk, roa, roe,
    payout_ratio.
    """
    by_key = {(p["fiscal_year"], p["quarter"]): p for p in periods
              if p.get("quarter") is not None}

    for p in periods:
        q = p.get("quarter")
        if q is None:
            continue
        y = p["fiscal_year"]
        prev = [by_key.get(_quarter_offset(y, q, i)) for i in (1, 2, 3)]
        stock_4q_ago = by_key.get(_quarter_offset(y, q, 4))

        if any(pp is None for pp in prev) or stock_4q_ago is None:
            for m in _LTM_FIELDS_2F:
                p[m] = None
            continue

        window = [p, *prev]
        ltm_ni = _ltm_sum(window, "net_income")
        ltm_nii = _ltm_sum(window, "net_interest_income")
        ltm_llp = _ltm_sum(window, "loan_loss_provisions")
        ltm_div = _ltm_sum(window, "dividends_paid")

        avg_loans = _avg(p.get("loans_net"), stock_4q_ago.get("loans_net"))
        avg_assets = _avg(p.get("total_assets"), stock_4q_ago.get("total_assets"))
        avg_equity = _avg(p.get("equity"), stock_4q_ago.get("equity"))

        p["nim"] = _safe_div(ltm_nii, avg_loans)
        if ltm_llp is not None:
            p["cost_of_risk"] = _safe_div(abs(ltm_llp), avg_loans)
        else:
            p["cost_of_risk"] = None
        p["roa"] = _safe_div(ltm_ni, avg_assets)
        p["roe"] = _safe_div(ltm_ni, avg_equity)
        p["payout_ratio"] = _safe_div(
            abs(ltm_div) if ltm_div is not None else None, ltm_ni
        )


def set_dna(result: dict, dna) -> dict:
    """Asigna D&A externo a empresas 2D y recalcula EBITDA + métricas dependientes.

    Útil cuando la empresa publica CF con método directo y SMV no expone
    Depreciación, Amortización y Agotamiento (cuenta 3D0602). El analista
    puede proveer D&A desde notas a los EEFF auditados (memoria anual,
    reportes trimestrales) y la librería recalcula automáticamente:
    ``ebitda``, ``ebitda_margin``, ``debt_to_ebitda``, ``net_debt_to_ebitda``,
    e ``interest_coverage_ebitda``.

    Args:
        result: dict devuelto por ``fetch_eeff`` (mutado in-place).
            Debe tener al menos un período con ``schema='2D'``.
        dna: D&A en miles de soles. Acepta tres formatos:

            - ``float``: se aplica a TODOS los períodos del result. Útil cuando
              el result tiene un solo período.
            - ``dict[int, float]`` mapeo ``{año_fiscal: dna}``: asigna por año.
            - ``dict[(int, int|None), float]`` mapeo ``{(año, quarter): dna}``:
              asigna por período exacto (None para anual; 1-4 para trimestre).

    Returns:
        El mismo ``result`` mutado con métricas recalculadas.

    Ejemplo::

        from smv_peru import fetch_eeff, set_dna
        datos = fetch_eeff("ALICORC1", desde=2022, hasta=2024)
        # D&A de las notas a los EEFF auditados (en miles)
        set_dna(datos, {2022: 420_000, 2023: 450_000, 2024: 480_000})
        # Ahora datos["periods"][i]["ebitda"] está calculado correctamente.
    """
    if not result or not result.get("periods"):
        return result

    def resolver(period: dict):
        year = period.get("fiscal_year")
        quarter = period.get("quarter")
        if isinstance(dna, (int, float)):
            return float(dna)
        if isinstance(dna, dict):
            # Match por (year, quarter)
            if (year, quarter) in dna:
                return float(dna[(year, quarter)])
            # Match por year (anual o ambiguo)
            if year in dna:
                return float(dna[year])
        return None

    for p in result["periods"]:
        if p.get("schema") != "2D":
            continue  # set_dna solo aplica a 2D
        new_dna = resolver(p)
        if new_dna is None:
            continue
        p["dna"] = new_dna
        op_inc = p.get("operating_income")
        if op_inc is None:
            continue
        ebitda = op_inc + abs(new_dna)
        p["ebitda"] = ebitda
        revenue = p.get("revenue")
        p["ebitda_margin"] = (ebitda / revenue) if revenue else None
        total_debt = p.get("total_debt")
        p["debt_to_ebitda"] = (total_debt / ebitda) if ebitda else None
        net_debt = p.get("net_debt")
        p["net_debt_to_ebitda"] = (net_debt / ebitda) if (ebitda and net_debt is not None) else None
        ie = p.get("interest_expense")
        if ie is not None and ie != 0:
            p["interest_coverage_ebitda"] = ebitda / abs(ie)
    return result


# ---------------------------------------------------------------------------
# Coordinación de descargas y normalización trimestral
# ---------------------------------------------------------------------------

def _check_cf_ytd_from_results(results: dict, rpj: str, year: int, tipo_code: str) -> bool:
    """Detecta si el CF viene en YTD acumulado usando resultados ya descargados.
    Compara Q4 vs Anual para una cuenta clave. Si Q4 ≈ Anual → YTD."""
    flow_q4 = results.get((OP_FLOW, year, "4", tipo_code))
    flow_anual = results.get((OP_FLOW, year, "A", tipo_code))
    if not flow_q4 or not flow_anual:
        return True  # default: asumir YTD
    for codigo in ("3D01ST", "3F0501"):
        if _is_ytd(flow_q4, flow_anual, rpj, codigo):
            return True
        q4 = _amount([r for r in flow_q4 if r.get('RPJ') == rpj], codigo)
        anual = _amount([r for r in flow_anual if r.get('RPJ') == rpj], codigo)
        if q4 is not None and anual is not None:
            return False
    return True


def fetch_eeff(
    ticker: str,
    desde: int,
    hasta: int,
    tipo: str = "consolidado",
    periodicidad: str = "anual",
    cache_dir: Path | str | None = None,
    max_workers: int = 10,
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
        max_workers: número máximo de descargas SOAP en paralelo. Default 10.
            Pasa ``max_workers=1`` para descargas secuenciales (modo legacy).
            El cache local elimina la concurrencia para llamadas ya cacheadas,
            así que el paralelismo solo importa en cold cache.

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
    if max_workers < 1 or max_workers > MAX_WORKERS_LIMIT:
        raise ValueError(
            f"max_workers debe estar entre 1 y {MAX_WORKERS_LIMIT} (límite para "
            f"no saturar SMV), recibido: {max_workers}"
        )

    info = resolve_ticker(ticker)
    rpj = info["rpj"]
    esquema = info.get("esquema", "2D")
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

    # ---- Fase 1: planificar todas las llamadas SOAP necesarias -----------
    logger.info(
        f"smv-peru: descargando {ticker} {desde}-{hasta} {periodicidad} ({tipo})..."
    )
    calls_needed: set[tuple[str, int, str, str]] = set()
    for y in range(desde, hasta + 1):
        if periodicidad == "trimestral":
            # Para detección YTD comparamos Q4 Flow vs Anual Flow.
            calls_needed.add((OP_FLOW, y, "A", tipo_code))
        for p in periodos:
            calls_needed.add((OP_PNL, y, p, tipo_code))
            calls_needed.add((OP_BAL, y, p, tipo_code))
            calls_needed.add((OP_FLOW, y, p, tipo_code))
            if periodicidad == "trimestral" and p in ("2", "3", "4"):
                calls_needed.add((OP_FLOW, y, str(int(p) - 1), tipo_code))

    # ---- Fase 2: descargar en paralelo (o serial si max_workers=1) -------
    # Verificar cuántos archivos están en cache para informar al usuario
    cached_count = sum(
        1 for (op, year, period, t) in calls_needed
        if (cache_dir / f"{op}_{year}_{t}_{period}.json").exists()
    )
    if cached_count < len(calls_needed):
        logger.info(
            f"smv-peru: {len(calls_needed)} llamadas SOAP planificadas, "
            f"{cached_count} en cache, {len(calls_needed) - cached_count} a descargar"
        )

    progress_label = f"  {ticker} {desde}-{hasta} {periodicidad}"
    tick = _make_progress_writer(len(calls_needed), progress_label)

    results: dict[tuple[str, int, str, str], list[dict] | None] = {}
    if max_workers > 1 and len(calls_needed) > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        workers = min(max_workers, len(calls_needed))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {
                ex.submit(_call_smv, op, year, period, t, cache_dir): (op, year, period, t)
                for (op, year, period, t) in calls_needed
            }
            for fut in as_completed(futures):
                key = futures[fut]
                try:
                    results[key] = fut.result()
                except Exception as e:
                    logger.warning(f"Llamada SOAP falló para {key}: {e}")
                    results[key] = None
                tick()
    else:
        for (op, year, period, t) in calls_needed:
            results[(op, year, period, t)] = _call_smv(op, year, period, t, cache_dir)
            tick()

    # ---- Early-exit: si el RPJ NO aparece en ningún resultado Consolidado,
    # ir directo a Individual (paralelizado) en vez de hacer cascadas por
    # período secuenciales. Caso típico: INTERBC1 (Interbank), que SMV publica
    # solo en Individual. Sin este check, la cascada por-período haría 3 calls
    # Individual secuenciales por cada año (15+ calls serial → ~2 min) en lugar
    # de una sola descarga paralelizada (~10s).
    if tipo_code == "C":
        any_consolidated = any(
            _has_rpj_data(rows, rpj)
            for (op, year, period, t), rows in results.items()
            if t == "C"
        )
        if not any_consolidated:
            logger.info(
                f"smv-peru: {ticker} no aparece en ningún período Consolidado; "
                f"reintentando con Individual"
            )
            return fetch_eeff(
                ticker, desde, hasta,
                tipo="individual", periodicidad=periodicidad,
                cache_dir=cache_dir, max_workers=max_workers,
            )

    # ---- Fase 2.5: pre-detectar calls de fallback Individual y bajarlas en
    # paralelo. Si dejáramos que la cascada por-período las haga ad-hoc en
    # fase 3, terminaríamos con N calls SOAP sincrónicas (caso conocido:
    # ENGEPEC1 trimestral tiene 2024 C completo pero 2020-2023 vacío en C
    # → 16 quarters × 3 calls = 48 calls serial = ~7 min). Aquí las
    # acumulamos y las bajamos con el mismo executor paralelizado.
    if tipo_code == "C":
        fallback_calls: set[tuple[str, int, str, str]] = set()
        for y_ in range(desde, hasta + 1):
            for p_ in periodos:
                pnl_c = results.get((OP_PNL, y_, p_, "C"))
                bal_c = results.get((OP_BAL, y_, p_, "C"))
                if _has_rpj_data(pnl_c, rpj) and _has_rpj_data(bal_c, rpj):
                    continue
                # Q4 fallback: solo si es anual y solo falta Balance C
                if (p_ == "A" and _has_rpj_data(pnl_c, rpj)
                        and not _has_rpj_data(bal_c, rpj)):
                    fallback_calls.add((OP_BAL, y_, "4", "C"))
                # Cascada Individual completa
                fallback_calls.add((OP_PNL, y_, p_, "I"))
                fallback_calls.add((OP_BAL, y_, p_, "I"))
                fallback_calls.add((OP_FLOW, y_, p_, "I"))
                if periodicidad == "trimestral":
                    if p_ in ("2", "3", "4"):
                        fallback_calls.add((OP_FLOW, y_, str(int(p_) - 1), "I"))
                    fallback_calls.add((OP_FLOW, y_, "4", "I"))
                    fallback_calls.add((OP_FLOW, y_, "A", "I"))
        # Quitar las que ya tenemos en results
        fallback_calls -= set(results.keys())

        if fallback_calls:
            logger.info(
                f"smv-peru: {ticker} requiere {len(fallback_calls)} llamadas SOAP "
                f"adicionales para cubrir fallbacks (Q4 / Individual)"
            )
            tick2 = _make_progress_writer(
                len(fallback_calls), f"  {ticker} fallback"
            )
            if max_workers > 1 and len(fallback_calls) > 1:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                workers = min(max_workers, len(fallback_calls))
                with ThreadPoolExecutor(max_workers=workers) as ex:
                    futures = {
                        ex.submit(_call_smv, op_, y_, pp_, t_, cache_dir):
                            (op_, y_, pp_, t_)
                        for (op_, y_, pp_, t_) in fallback_calls
                    }
                    for fut in as_completed(futures):
                        key = futures[fut]
                        try:
                            results[key] = fut.result()
                        except Exception as e:
                            logger.warning(
                                f"Llamada SOAP de fallback falló para {key}: {e}"
                            )
                            results[key] = None
                        tick2()
            else:
                for (op_, y_, pp_, t_) in fallback_calls:
                    results[(op_, y_, pp_, t_)] = _call_smv(
                        op_, y_, pp_, t_, cache_dir
                    )
                    tick2()

    # ---- Fase 3: procesar usando resultados ya descargados ----------------
    # Cascada por período (no por ticker entero): si Consolidado tiene PNL/Bal
    # incompletos para este RPJ en un año específico, intentamos Individual
    # solo para ese período. Esto resuelve casos como BBVA 2022, donde SMV
    # publicó PNL+Flow Consolidado pero NO Balance Consolidado, mientras que
    # Individual está completo (gap conocido del cargador SMV — el documento
    # consolidado oficial sí existe).
    periods_data = []
    for y in range(desde, hasta + 1):
        cf_is_ytd_c = False
        cf_is_ytd_i: bool | None = None  # lazy: solo se calcula si hay fallback
        if periodicidad == "trimestral":
            cf_is_ytd_c = _check_cf_ytd_from_results(results, rpj, y, tipo_code)

        for p in periodos:
            pnl = results.get((OP_PNL, y, p, tipo_code))
            bal = results.get((OP_BAL, y, p, tipo_code))
            flow = results.get((OP_FLOW, y, p, tipo_code))
            used_tipo = tipo  # "consolidado" o "individual" según el arg

            # Detectar incompletitud por RPJ y aplicar cascada en orden:
            #   1) Si solo falta Balance C anual y existe Balance Q4 C, usar
            #      Q4 como sustituto. El balance es stock: el cierre del Q4
            #      equivale matemáticamente al cierre anual (validado contra
            #      múltiples empresas: coincide al peso). Mantiene la
            #      consistencia "Consolidado" del reporte.
            #   2) Si lo anterior no aplica o falla, caer back a Individual
            #      completo del mismo período.
            consolidated_ok = _has_rpj_data(pnl, rpj) and _has_rpj_data(bal, rpj)
            balance_substituted_from_q4 = False

            if (tipo_code == "C" and not consolidated_ok and p == "A"
                    and _has_rpj_data(pnl, rpj) and not _has_rpj_data(bal, rpj)):
                bal_q4 = _call_smv(OP_BAL, y, "4", "C", cache_dir)
                if _has_rpj_data(bal_q4, rpj):
                    bal = bal_q4
                    consolidated_ok = True
                    balance_substituted_from_q4 = True
                    logger.info(
                        f"smv-peru: {ticker} {y} Balance C anual ausente en "
                        f"SMV; usando Balance C Q4 como sustituto (stock "
                        f"idéntico al cierre anual)"
                    )

            if tipo_code == "C" and not consolidated_ok:
                ind_pnl = _call_smv(OP_PNL, y, p, "I", cache_dir)
                ind_bal = _call_smv(OP_BAL, y, p, "I", cache_dir)
                ind_flow = _call_smv(OP_FLOW, y, p, "I", cache_dir)
                if _has_rpj_data(ind_pnl, rpj) and _has_rpj_data(ind_bal, rpj):
                    pnl, bal, flow = ind_pnl, ind_bal, ind_flow
                    used_tipo = "individual"
                    label_q = f"Q{p}" if p != "A" else ""
                    logger.info(
                        f"smv-peru: {ticker} {y}{label_q} incompleto en "
                        f"Consolidado; usando Individual como fallback"
                    )
                    # Cuando el origen es Individual, recalcular YTD sobre
                    # datos Individuales del mismo año. Cargamos Q4 y Anual
                    # Individual al diccionario de resultados para reutilizar
                    # la lógica canónica de detección.
                    if periodicidad == "trimestral" and p in ("2", "3", "4"):
                        if cf_is_ytd_i is None:
                            results.setdefault(
                                (OP_FLOW, y, "4", "I"),
                                _call_smv(OP_FLOW, y, "4", "I", cache_dir),
                            )
                            results.setdefault(
                                (OP_FLOW, y, "A", "I"),
                                _call_smv(OP_FLOW, y, "A", "I", cache_dir),
                            )
                            cf_is_ytd_i = _check_cf_ytd_from_results(
                                results, rpj, y, "I"
                            )
                        if cf_is_ytd_i and flow is not None:
                            flow_prev = _call_smv(OP_FLOW, y, str(int(p) - 1), "I", cache_dir)
                            if flow_prev is not None:
                                flow = _subtract_rows(flow, flow_prev)
            else:
                # Camino normal: YTD detection sobre Consolidado
                if periodicidad == "trimestral" and p in ("2", "3", "4") and cf_is_ytd_c and flow is not None:
                    prev_p = str(int(p) - 1)
                    flow_prev = results.get((OP_FLOW, y, prev_p, tipo_code))
                    if flow_prev is not None:
                        flow = _subtract_rows(flow, flow_prev)

            quarter = None if p == "A" else int(p)
            yd = mapper(rpj, pnl, bal, flow, y, quarter)
            if yd is not None:
                yd["tipo"] = used_tipo
                if balance_substituted_from_q4:
                    yd["balance_source"] = "Q4_consolidado"
                periods_data.append(yd)

    # Cascada: si no obtuvimos nada con Consolidado, probar Individual
    if not periods_data and tipo_code == "C":
        logger.info(f"SMV: ticker={ticker} no aparece en Consolidado, probando Individual")
        return fetch_eeff(
            ticker, desde, hasta,
            tipo="individual", periodicidad=periodicidad,
            cache_dir=cache_dir, max_workers=max_workers,
        )

    if not periods_data:
        logger.warning(f"SMV: ningún período obtenido para ticker={ticker} (ni C ni I)")
        return None

    # Construir info dict con metadata útil para el consumidor
    periods_returned = [(p["fiscal_year"], p["quarter"]) for p in periods_data]
    all_requested = []
    for y in range(desde, hasta + 1):
        if periodicidad == "anual":
            all_requested.append((y, None))
        else:
            for q in range(1, 5):
                all_requested.append((y, q))
    returned_set = set(periods_returned)
    periods_missing = [pr for pr in all_requested if pr not in returned_set]

    if periods_missing:
        # Formato del aviso: año-Q o solo año, máximo 5 explicitados
        def _label(p):
            y, q = p
            return f"{y}" if q is None else f"{y}Q{q}"
        muestra = [_label(p) for p in periods_missing[:5]]
        extra = "" if len(periods_missing) <= 5 else f" ... y {len(periods_missing) - 5} más"
        logger.warning(
            f"smv-peru: {len(periods_missing)} de {len(all_requested)} períodos "
            f"solicitados no tienen datos en SMV para {ticker}: "
            f"[{', '.join(muestra)}{extra}]"
        )

    # En trimestral, sobrescribir métricas LTM-sensibles (ROE, ROIC, NIM, etc.)
    # con suma móvil de 4 trimestres / promedio de stocks LTM. Si falta historia
    # suficiente, esas métricas → None (opción A: no rellenar con descargas
    # implícitas; el usuario debe pedir un año extra de margen si las quiere).
    if periodicidad == "trimestral":
        if esquema == "2F":
            _apply_ltm_2f(periods_data)
        else:
            _apply_ltm_2d(periods_data)

    # Moneda: tomada del primer período (todas las empresas reportan
    # consistentemente en una sola moneda a lo largo del tiempo).
    currency = periods_data[0].get("currency") if periods_data else None

    return {
        "periods": periods_data,
        "info": {
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ticker": ticker,
            "schema": esquema,
            "tipo": tipo,
            "periodicidad": periodicidad,
            "currency": currency,
            "desde": desde,
            "hasta": hasta,
            "periods_requested": all_requested,
            "periods_returned": periods_returned,
            "periods_missing": periods_missing,
        },
    }


def fetch_multi(
    tickers: list[str],
    desde: int,
    hasta: int,
    tipo: str = "consolidado",
    periodicidad: str = "anual",
    cache_dir: Path | str | None = None,
    max_workers: int = 10,
) -> dict[str, dict | None]:
    """Descarga estados financieros para múltiples empresas.

    Aprovecha el cache compartido: las respuestas SOAP de SMV traen TODAS
    las empresas peruanas en una sola llamada, así que descargar varios
    tickers del mismo año/tipo reusa los mismos archivos cacheados. Cold
    cache, primer ticker llena el cache; los siguientes tickers son
    instantáneos para los mismos períodos.

    Args:
        tickers: lista de tickers BVL (ej. ``["ALICORC1", "BACKUSI1", "FERREYC1"]``).
        desde, hasta: rango de años fiscales (inclusive).
        tipo: ``"consolidado"`` (default) o ``"individual"``. Cascada automática
            por ticker.
        periodicidad: ``"anual"`` (default) o ``"trimestral"``.
        cache_dir: directorio de cache. None = user cache dir del SO.
        max_workers: número máximo de descargas SOAP en paralelo (1-10).

    Returns:
        dict ``{ticker: result | None}`` donde ``result`` tiene el mismo
        shape que ``fetch_eeff`` (``{"periods": [...], "info": {...}}``).
        Si un ticker no está en el catálogo o no tiene datos, su valor es
        ``None`` (no levanta excepción para no abortar la consulta de los demás).

    Ejemplo::

        from smv_peru import fetch_multi, to_excel
        sectorial = fetch_multi(
            ["CPACASC1", "UNACEMC1", "YURAC1"],   # cementeras del catálogo
            desde=2019, hasta=2024,
        )
        to_excel(sectorial, "cementeras_2019_2024.xlsx")
    """
    if not tickers:
        return {}
    if max_workers < 1 or max_workers > MAX_WORKERS_LIMIT:
        raise ValueError(
            f"max_workers debe estar entre 1 y {MAX_WORKERS_LIMIT}, recibido: {max_workers}"
        )

    output: dict[str, dict | None] = {}
    for ticker in tickers:
        try:
            output[ticker] = fetch_eeff(
                ticker, desde=desde, hasta=hasta,
                tipo=tipo, periodicidad=periodicidad,
                cache_dir=cache_dir, max_workers=max_workers,
            )
        except Exception as e:
            logger.warning(f"fetch_multi: error con {ticker}: {e}")
            output[ticker] = None
    return output


# Alias retro-compatible: la función se llamó así originalmente. El nombre
# `fetch_eeff` (más corto, igual de claro con el acrónimo financiero) es el
# preferido a partir de v0.1.0. El alias permanece sin DeprecationWarning
# para no romper código existente.
fetch_estados_financieros = fetch_eeff
