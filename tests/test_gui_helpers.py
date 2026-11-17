"""Чистая логика GUI-страниц (без tkinter): цвета Excel и переносы дней."""
import pytest

from core import holidays
from gui import colorcfg


@pytest.mark.parametrize("raw,expected", [
    ("FFB6C1", "#FFB6C1"),
    ("#ffb6c1", "#ffb6c1"),
    ("", ""),
    (None, None),
])
def test_normalize_color_adds_hash_only_when_missing(raw, expected):
    assert colorcfg.normalize_color(raw) == expected


def test_set_excel_color_creates_section_and_upcases():
    cfg = {}
    colorcfg.set_excel_color(cfg, "holiday", "#ffb6c1")
    assert cfg == {"excel_colors": {"holiday": "#FFB6C1"}}


def test_set_excel_color_keeps_other_keys():
    cfg = {"excel_colors": {"weekend": "#F2F2F2"}}
    colorcfg.set_excel_color(cfg, "holiday", "#aabbcc")
    assert cfg["excel_colors"] == {"weekend": "#F2F2F2", "holiday": "#AABBCC"}


def test_transfers_from_rows_sorts_and_converts_to_ints():
    rows = [(2026, 5, 2), ("2026", "4", "25"), [2025, 12, 31]]
    assert holidays.transfers_from_rows(rows) == [[2025, 12, 31], [2026, 4, 25], [2026, 5, 2]]


def test_transfers_from_rows_skips_broken_rows():
    rows = [(2026, 4, 25), ("abc", 1, 1), (2026, 4), None]
    assert holidays.transfers_from_rows(rows) == [[2026, 4, 25]]


def test_transfers_from_rows_empty():
    assert holidays.transfers_from_rows([]) == []
