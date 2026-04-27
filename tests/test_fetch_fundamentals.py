"""Tests end-to-end para fetch_smv_fundamentals usando fixtures de Alicorp.

Las fixtures están en tests/fixtures/ y contienen solo las filas
correspondientes a Alicorp (RPJ=B30006) extraídas de los JSONs reales
de SMV para los años 2021-2023, Consolidado.
"""
from pathlib import Path

from smv_peru import fetch_smv_fundamentals

FIXTURES = Path(__file__).parent / "fixtures"
ALICORP_RPJ = "B30006"


def test_returns_dict_with_years():
    result = fetch_smv_fundamentals(
        ALICORP_RPJ, years_back=3, current_year=2024, cache_dir=FIXTURES,
    )
    assert result is not None
    assert "years" in result
    assert len(result["years"]) == 3


def test_returns_years_in_chronological_order():
    result = fetch_smv_fundamentals(
        ALICORP_RPJ, years_back=3, current_year=2024, cache_dir=FIXTURES,
    )
    fiscal_years = [y["fiscal_year"] for y in result["years"]]
    assert fiscal_years == [2021, 2022, 2023]


def test_each_year_has_complete_schema():
    result = fetch_smv_fundamentals(
        ALICORP_RPJ, years_back=3, current_year=2024, cache_dir=FIXTURES,
    )
    expected_keys = {
        "fiscal_year", "revenue", "ebitda", "net_income", "eps",
        "total_debt", "equity", "total_assets", "current_ratio",
        "fcf", "roe", "roic",
    }
    for year_data in result["years"]:
        assert expected_keys.issubset(year_data.keys())


def test_alicorp_metrics_have_expected_magnitude():
    """Sanity check de magnitud para Alicorp consolidado.

    Importante: los montos de SMV se reportan en MILES de la moneda base (soles
    en el caso de Alicorp). Un revenue de 13_655_764 equivale a ~S/. 13.66 mil
    millones, lo cual coincide con los reportes públicos de Alicorp 2023.
    """
    result = fetch_smv_fundamentals(
        ALICORP_RPJ, years_back=3, current_year=2024, cache_dir=FIXTURES,
    )
    y2023 = next(y for y in result["years"] if y["fiscal_year"] == 2023)
    assert y2023["revenue"] > 1_000_000  # >1B soles (en miles)
    assert y2023["equity"] > 0
    assert y2023["total_assets"] > y2023["total_debt"]
