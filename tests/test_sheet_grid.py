"""Чтение листа в сетку значений (то, что раньше делал pandas.read_excel(header=None, dtype=object)).

Правила совпадают с pandas: пустое и «NA-подобное» → None, целые числа → int,
хвостовые пустые строки и столбцы отрезаются, ведущие остаются, строки выравниваются по ширине."""
import datetime
import sys
import zipfile

import pytest
from openpyxl import Workbook
from openpyxl.styles import PatternFill

from core.excel_io import load_excel_with_merges


def grid_of(tmp_path, fill, sheet="Лист"):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    fill(ws)
    path = str(tmp_path / "g.xlsx")
    wb.save(path)
    return load_excel_with_merges(path, sheet)


def test_empty_sheet_gives_empty_grid(tmp_path):
    assert grid_of(tmp_path, lambda ws: None) == []


def test_whole_numbers_become_int_and_fractions_stay_float(tmp_path):
    def fill(ws):
        ws["A1"], ws["B1"], ws["C1"] = 8.0, 7.5, 12
    row = grid_of(tmp_path, fill)[0]
    assert row == [8, 7.5, 12]
    assert [type(v) for v in row] == [int, float, int]
    assert str(row[0]) == "8"                      # не «8.0»: от этого зависят тексты смен


@pytest.mark.parametrize("text", ["NA", "N/A", "n/a", "NULL", "null", "NaN", "nan", "None", "#N/A", "<NA>"])
def test_na_like_strings_are_empty(tmp_path, text):
    def fill(ws):
        ws["A1"], ws["B1"] = "x", text
    assert grid_of(tmp_path, fill) == [["x", None]]


def test_other_strings_are_kept_as_is(tmp_path):
    def fill(ws):
        ws["A1"], ws["B1"], ws["C1"], ws["D1"] = " ", "NAN", "-", "Na"
    assert grid_of(tmp_path, fill) == [[" ", "NAN", "-", "Na"]]


def test_error_cells_are_empty(tmp_path):
    def fill(ws):
        ws["A1"], ws["B1"] = "x", "#DIV/0!"
    assert grid_of(tmp_path, fill) == [["x", None]]


def test_dates_times_and_bools_are_kept(tmp_path):
    def fill(ws):
        ws["A1"] = datetime.datetime(2026, 4, 1, 9, 30)
        ws["B1"] = True
        ws["C1"] = datetime.time(8, 15)
    assert grid_of(tmp_path, fill) == [[datetime.datetime(2026, 4, 1, 9, 30), True, datetime.time(8, 15)]]


def test_leading_blanks_are_kept_trailing_blanks_are_trimmed(tmp_path):
    def fill(ws):
        ws["B2"] = "a"
        ws["C3"] = "b"
        ws["E6"].value = None               # пустая ячейка за данными
        ws["A9"].fill = PatternFill("solid", start_color="FF0000")
    grid = grid_of(tmp_path, fill)
    assert grid == [[None, None, None], [None, "a", None], [None, None, "b"]]


def test_rows_are_padded_to_the_widest_row(tmp_path):
    def fill(ws):
        ws["A1"] = "x"
        ws["D2"] = "y"
    assert grid_of(tmp_path, fill) == [["x", None, None, None], [None, None, None, "y"]]


def test_formula_without_cached_value_is_empty(tmp_path):
    def fill(ws):
        ws["A1"], ws["B1"] = 1, "=A1+1"
    assert grid_of(tmp_path, fill) == [[1]]             # без кэша ячейка пуста, а хвост отрезается


def test_merged_range_outside_the_data_is_ignored(tmp_path):
    def fill(ws):
        ws["A1"] = "x"
        ws["A3"] = "y"
        ws.merge_cells("A3:F4")
    grid = grid_of(tmp_path, fill)
    assert grid == [["x"], [None], ["y"]]          # размер сетки задают данные, а не объединение


def test_pandas_is_not_needed_to_read_a_sheet(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pandas", None)     # import pandas → ImportError
    grid = grid_of(tmp_path, lambda ws: ws.__setitem__("A1", "ok"))
    assert grid == [["ok"]]


def test_merged_range_starting_beyond_the_data_is_ignored(tmp_path):
    def fill(ws):
        ws["A1"] = "x"
        ws["H9"] = "z"
        ws.merge_cells("J12:L13")
    grid = grid_of(tmp_path, fill)
    assert len(grid) == 9 and grid[0][0] == "x" and grid[8][7] == "z"


def test_numbers_stored_with_a_fraction_part_in_xml_become_int_when_whole(tmp_path):
    """Некоторые программы пишут целое как «8.0»: для разбора это должно быть то же «8»."""
    wb = Workbook()
    wb.active.title = "Лист"
    wb.active["A1"] = 8
    wb.active["B1"] = 7.25
    path = str(tmp_path / "w.xlsx")
    wb.save(path)
    patched = str(tmp_path / "p.xlsx")
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(patched, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                assert b"<v>8</v>" in data
                data = data.replace(b"<v>8</v>", b"<v>8.0</v>")
            zout.writestr(item, data)
    row = load_excel_with_merges(patched, "Лист")[0]
    assert row == [8, 7.25] and type(row[0]) is int
