"""Чтение одного листа без разбора остальных (core/xlsx_slim.py)."""
import datetime

import pytest
from openpyxl import Workbook, load_workbook

from core import xlsx_slim
from core.xlsx_slim import load_sheet_workbook, sheet_names

NAMES = ["Январь 2026", "Апрель 2026", "Тест & «кавычки» 'х'", "Лист <4>"]


def _book(tmp_path):
    wb = Workbook()
    wb.active.title = NAMES[0]
    for name in NAMES[1:]:
        wb.create_sheet(name)
    for i, ws in enumerate(wb.worksheets):
        ws["A1"] = f"лист-{i}"
        ws["B2"], ws["C2"], ws["D2"] = 8, 7.5, datetime.datetime(2026, 4, 1, 9, 30)
        ws["A5"] = "Иванов"
        ws.merge_cells("A5:A7")
        ws["F9"] = True
    wb.worksheets[2].print_area = "A1:C3"                 # имя с привязкой к листу (localSheetId)
    wb.worksheets[3].print_title_rows = "1:2"
    path = tmp_path / "multi.xlsx"
    wb.save(path)
    return str(path)


def _cells(ws):
    return {c.coordinate: c.value for row in ws.iter_rows() for c in row if c.value is not None}


@pytest.mark.parametrize("name", NAMES)
def test_only_the_requested_sheet_is_loaded_and_it_equals_the_full_load(tmp_path, name):
    path = _book(tmp_path)
    slim = load_sheet_workbook(path, name)
    full = load_workbook(path, data_only=True)
    assert slim.sheetnames == [name]
    assert _cells(slim[name]) == _cells(full[name])
    assert sorted(map(str, slim[name].merged_cells.ranges)) == sorted(map(str, full[name].merged_cells.ranges))


def test_sheet_names_are_read_without_parsing_sheets(tmp_path):
    assert sheet_names(_book(tmp_path)) == NAMES


def test_unknown_sheet_is_reported_in_plain_words_before_any_parsing(tmp_path, monkeypatch):
    path = _book(tmp_path)
    monkeypatch.setattr(xlsx_slim, "load_workbook", lambda *a, **k: pytest.fail("книга не должна открываться"))
    with pytest.raises(ValueError, match="нет листа «Май 2026».*«Январь 2026»"):
        load_sheet_workbook(path, "Май 2026")


def test_single_sheet_book_is_opened_as_is(tmp_path):
    wb = Workbook()
    wb.active.title = "Один"
    wb.active["A1"] = 1
    path = str(tmp_path / "one.xlsx")
    wb.save(path)
    assert load_sheet_workbook(path, "Один")["Один"]["A1"].value == 1


def test_unexpected_file_layout_falls_back_to_the_full_load(tmp_path, monkeypatch):
    path = _book(tmp_path)

    def broken(*a, **k):
        raise ValueError("нестандартный файл")

    monkeypatch.setattr(xlsx_slim, "_slim_bytes", broken)
    wb = load_sheet_workbook(path, NAMES[1])
    assert wb.sheetnames == NAMES and wb[NAMES[1]]["A1"].value == "лист-1"


def test_not_an_xlsx_file_gives_the_usual_openpyxl_error(tmp_path):
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes("это не архив".encode("utf-8"))
    assert sheet_names(str(bad)) is None
    with pytest.raises(Exception):
        load_sheet_workbook(str(bad), "Лист")


def test_the_original_file_is_not_modified(tmp_path):
    path = _book(tmp_path)
    before = open(path, "rb").read()
    load_sheet_workbook(path, NAMES[1])
    assert open(path, "rb").read() == before
