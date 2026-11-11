"""Баг №1: расхождения compare() и GUI; плюс is_doctor_name_row в compare_schedules."""
import os

import pytest
from openpyxl import Workbook

from core import compare_schedules
from core.compare_schedules import build_output_path, parse_full_sheet_data


def _make_book(path, hours_day1=8, time_day1="09:00-17:00"):
    wb = Workbook()
    ws = wb.active
    ws.title = "Терапия"
    ws["A1"] = "ГРАФИК РАБОТЫ НА АПРЕЛЬ 2026 г."
    day_row = 4
    ws.cell(row=day_row, column=1, value="Врачи")
    ws.cell(row=day_row, column=2, value="Должность (ставка)")
    for d in range(1, 32):
        ws.cell(row=day_row, column=2 + d, value=d)
    ws.cell(row=day_row, column=34, value="Расчетная норма")
    ws.cell(row=day_row, column=35, value="Часы")
    # строка шапки, по форме совпадающая с ФИО
    ws.cell(row=day_row + 3, column=1, value="Фамилия И.О.")
    doc = day_row + 5
    ws.cell(row=doc, column=1, value="Иванов И.И.")
    ws.cell(row=doc, column=2, value="Терапевт (1,0 ст.)")
    ws.cell(row=doc, column=3, value=hours_day1)
    ws.cell(row=doc + 1, column=3, value=time_day1)
    ws.cell(row=doc, column=34, value=159.7)
    ws.cell(row=doc, column=35, value=hours_day1)
    wb.save(path)


@pytest.fixture
def books(tmp_path):
    return str(tmp_path / "auto.xlsx"), str(tmp_path / "manual.xlsx")


def test_parse_skips_header_row_that_looks_like_a_name(books):
    _make_book(books[0])
    db = parse_full_sheet_data(books[0])
    assert [d["name"] for d in db["Терапия"]["doctors"]] == ["Иванов И.И."]


def test_compare_reports_zero_diffs_for_identical_books(books):
    _make_book(books[0])
    _make_book(books[1])
    result = compare_schedules.compare(*books)
    assert result.diffs == 0
    assert os.path.exists(result.path)


def test_compare_counts_hours_and_time_differences(books):
    _make_book(books[0])
    _make_book(books[1], hours_day1=7, time_day1="09:00-16:00")
    result = compare_schedules.compare(*books)
    assert result.diffs == 2


def test_compare_path_matches_build_output_path(books):
    _make_book(books[0])
    _make_book(books[1])
    result = compare_schedules.compare(*books)
    assert result.path == build_output_path(books[0])


@pytest.mark.parametrize("name", ["График.xlsx", "График.XLSX", "График.xls"])
def test_build_output_path_handles_any_extension(tmp_path, name):
    out = build_output_path(str(tmp_path / name))
    assert os.path.basename(out) == "График_СРАВНЕНИЕ_СТРУКТУРНОЕ.xlsx"


def test_compare_raises_when_report_cannot_be_saved(books, monkeypatch):
    _make_book(books[0])
    _make_book(books[1])

    def boom(self, filename):
        raise PermissionError("файл открыт в Excel")

    monkeypatch.setattr("openpyxl.workbook.workbook.Workbook.save", boom)
    with pytest.raises(PermissionError):
        compare_schedules.compare(*books)
