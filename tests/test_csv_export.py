"""Tests para to_csv: exportar a CSV sin dependencias externas."""
from pathlib import Path

import pytest

from smv_peru import fetch_estados_financieros, fetch_multi, to_csv

FIXTURES = Path(__file__).parent / "fixtures"


def test_to_csv_raises_on_empty_result(tmp_path):
    with pytest.raises(ValueError):
        to_csv({}, tmp_path / "out.csv")


def test_to_csv_single_empresa_creates_file(tmp_path):
    datos = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )
    out = to_csv(datos, tmp_path / "alicorp.csv", ticker="ALICORC1")
    assert out.exists()
    assert out.stat().st_size > 100


def test_to_csv_single_empresa_contains_revenue(tmp_path):
    datos = fetch_estados_financieros(
        "ALICORC1", desde=2023, hasta=2023, cache_dir=FIXTURES,
    )
    out = to_csv(datos, tmp_path / "alicorp.csv", ticker="ALICORC1")
    content = out.read_text(encoding="utf-8")
    assert "ALICORP" in content.upper() or "ALICORC1" in content
    assert "Revenue" in content
    # 13,655,764 sin separador de miles en CSV
    assert "13655764" in content


def test_to_csv_multi_empresa_creates_file(tmp_path):
    multi = fetch_multi(
        ["ALICORC1", "BBVAC1"], desde=2024, hasta=2024,
        cache_dir=FIXTURES,
    )
    out = to_csv(multi, tmp_path / "multi.csv")
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    # Ambos tickers deben aparecer
    assert "ALICORC1" in content
    assert "BBVAC1" in content


def test_to_csv_2f_uses_banking_layout(tmp_path):
    datos = fetch_estados_financieros(
        "BBVAC1", desde=2024, hasta=2024, cache_dir=FIXTURES,
    )
    out = to_csv(datos, tmp_path / "bbva.csv", ticker="BBVAC1")
    content = out.read_text(encoding="utf-8")
    assert "Interest income" in content
    assert "RATIOS BANCARIOS" in content
