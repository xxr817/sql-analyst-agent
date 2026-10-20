"""Tests for the two evaluation metrics (no API key needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from run_eval import answer_contains, numbers_in_text, results_match  # noqa: E402


def test_strict_match_ignores_order_and_extra_columns():
    assert results_match([("a", 1), ("b", 2)], [("b", 2), ("a", 1)])
    assert results_match([("BMW", 5)], [(5, "bmw", "extra column")])


def test_strict_match_rejects_extra_rows_and_wrong_values():
    assert not results_match([("NRW", 1)], [("NRW", 1), ("Bayern", 2)])
    assert not results_match([("BMW", 5)], [("BMW", 6)])
    assert not results_match([(1,)], None)


def test_german_and_english_number_formats():
    nums = numbers_in_text("VW: 137.134 Stück, Anteil 98,1 %, Preis 66 700 €, total 1,234.5")
    assert {137134.0, 98.1, 66700.0, 1234.5} <= nums


def test_answer_contains_names_and_numbers():
    answer = "Nordrhein-Westfalen hatte 2024 die meisten BMW-Neuzulassungen, nämlich 15.689."
    assert answer_contains([("Nordrhein-Westfalen", 15689)], answer)
    assert not answer_contains([("Bayern", 15689)], answer)
    assert not answer_contains([("Nordrhein-Westfalen", 15690)], answer)
    assert not answer_contains([("x", 1)], "")
