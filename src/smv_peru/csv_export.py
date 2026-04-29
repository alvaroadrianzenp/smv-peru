"""csv_export.py — exportar resultados a CSV (sin dependencias externas).

Alternativa liviana a ``to_excel`` que usa solo ``csv`` de stdlib. Útil cuando
no quieres instalar openpyxl o necesitas un formato universal procesable
por cualquier herramienta (Excel, Numbers, Google Sheets, scripts).

Layout: filas = campos amigables agrupados por sección (con líneas de
sección como ``"=== SECCIÓN ==="``). Columnas = períodos cronológicos.

Ejemplo::

    from smv_peru import fetch_estados_financieros, to_csv
    datos = fetch_estados_financieros("ALICORC1", desde=2019, hasta=2024)
    to_csv(datos, "alicorp_2019_2024.csv")
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from .empresas import EMPRESAS
from .excel import SECTIONS_2D, SECTIONS_2F, _period_label


def _csv_value(value, fmt: str):
    """Formatea valores para CSV. Devuelve string."""
    if value is None:
        return ""
    if fmt == "money":
        return f"{value:.0f}"
    if fmt == "pct":
        return f"{value * 100:.4f}%"
    if fmt == "ratio":
        return f"{value:.4f}"
    if fmt == "decimal":
        return f"{value:.4f}"
    return str(value)


def _write_single_csv(writer, periods: list[dict], ticker: str | None) -> None:
    """Escribe los datos de una empresa al writer de CSV."""
    schema = periods[0].get("schema", "2D")
    sections = SECTIONS_2D if schema == "2D" else SECTIONS_2F

    nombre_emp = ""
    if ticker and ticker in EMPRESAS:
        nombre_emp = EMPRESAS[ticker]["nombre"]
    elif ticker:
        nombre_emp = ticker
    titulo = nombre_emp + (f" ({ticker})" if ticker and nombre_emp != ticker else "")

    # Header de metadata
    writer.writerow([titulo or "Estados Financieros"])
    schema_label = {"2D": "2D — Industriales", "2F": "2F — Bancos"}.get(schema, schema)
    writer.writerow([f"Esquema: {schema_label}"])
    currency = periods[0].get("currency") or "—"
    currency_full = {"PEN": "Soles peruanos (PEN)", "USD": "Dólares (USD)"}.get(currency, currency)
    writer.writerow([f"Moneda: {currency_full}"])
    writer.writerow([f"Generado: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"])
    writer.writerow(["Montos en miles. Ratios como porcentajes."])
    writer.writerow([])

    # Header de columnas
    period_labels = [_period_label(p) for p in periods]
    writer.writerow([""] + period_labels)

    # Cuerpo
    for section_name, fields in sections:
        writer.writerow([f"=== {section_name} ==="])
        for field_key, label, fmt in fields:
            row = [label]
            for p in periods:
                row.append(_csv_value(p.get(field_key), fmt))
            writer.writerow(row)
        writer.writerow([])  # línea vacía entre secciones


def to_csv(
    result: dict,
    filepath: str | Path,
    ticker: str | None = None,
) -> Path:
    """Exporta el resultado a CSV (sin dependencias externas).

    Detecta automáticamente single-empresa (output de ``fetch_estados_financieros``)
    vs multi-empresa (output de ``fetch_multi``).

    **Single empresa:** un CSV con todos los campos.
    **Multi-empresa:** un CSV con secciones por ticker, separadas por líneas.

    Args:
        result: dict de ``fetch_estados_financieros`` o ``fetch_multi``.
        filepath: ruta del archivo CSV a generar.
        ticker: ticker BVL (opcional, solo single-empresa).

    Returns:
        Path absoluto del archivo generado.

    Raises:
        ValueError: si ``result`` está vacío.
    """
    if not result:
        raise ValueError("'result' está vacío")

    is_multi = "periods" not in result
    filepath = Path(filepath)

    with filepath.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_multi:
            valid_items = [(t, r) for t, r in result.items() if r and r.get("periods")]
            if not valid_items:
                raise ValueError(
                    "'result' multi-empresa no tiene ningún ticker con datos"
                )
            for i, (ticker_i, single_result) in enumerate(valid_items):
                if i > 0:
                    # Separador entre empresas
                    writer.writerow([])
                    writer.writerow(["#" * 80])
                    writer.writerow([])
                _write_single_csv(writer, single_result["periods"], ticker_i)
        else:
            if not result.get("periods"):
                raise ValueError("'result' no contiene 'periods'")
            _write_single_csv(writer, result["periods"], ticker)

    return filepath
