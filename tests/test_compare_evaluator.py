"""Вычислитель формул (xlcalculator) в compare строится только когда он нужен."""
import pytest

from core import compare_schedules
from tests.builders import TplDoc, make_template_book

SHEETS = {"Терапия": [TplDoc("Иванов И.И.", "Врач-терапевт (1,0 ст.)",
                             {1: ("09:00-17:00", 8), 2: ("09:00-17:00", 8)})]}


@pytest.fixture
def builds(monkeypatch):
    calls = []
    real = compare_schedules.build_formula_evaluator

    def counting(path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(compare_schedules, "build_formula_evaluator", counting)
    return calls


def test_evaluator_is_not_built_when_totals_are_already_stored(tmp_path, builds):
    path = make_template_book(str(tmp_path / "saved.xlsx"), SHEETS, totals_as_values=True)
    db = compare_schedules.parse_full_sheet_data(path)
    assert builds == []
    assert db["Терапия"]["doctors"][0]["totals"] == [160.0, 16]


def test_evaluator_is_built_once_when_formulas_have_no_stored_value(tmp_path, builds):
    path = make_template_book(str(tmp_path / "formulas.xlsx"), SHEETS)       # итог — формула SUM
    db = compare_schedules.parse_full_sheet_data(path)
    assert len(builds) == 1
    assert db["Терапия"]["doctors"][0]["totals"][-1] == 16                  # вычислено xlcalculator


def test_broken_evaluator_gives_empty_totals_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(compare_schedules, "build_formula_evaluator", lambda p: None)
    path = make_template_book(str(tmp_path / "formulas.xlsx"), SHEETS)
    db = compare_schedules.parse_full_sheet_data(path)
    assert db["Терапия"]["doctors"][0]["totals"][-1] == ""


def test_workbook_is_closed_even_if_parsing_fails(tmp_path, monkeypatch):
    closed = []
    real_load = compare_schedules.load_workbook

    def tracking_load(*a, **k):
        wb = real_load(*a, **k)
        original_close = wb.close
        wb.close = lambda: (closed.append(True), original_close())
        return wb

    monkeypatch.setattr(compare_schedules, "load_workbook", tracking_load)
    monkeypatch.setattr(compare_schedules, "_parse_workbook",
                        lambda wb, path: (_ for _ in ()).throw(RuntimeError("boom")))
    path = make_template_book(str(tmp_path / "x.xlsx"), SHEETS)
    with pytest.raises(RuntimeError):
        compare_schedules.parse_full_sheet_data(path)
    assert closed == [True]


def test_totals_use_hours_row_value_and_skip_time_row_when_present(tmp_path, builds):
    """Если у строки часов есть значение, строка времени в итогах не участвует."""
    path = make_template_book(str(tmp_path / "saved.xlsx"), SHEETS, totals_as_values=True)
    totals = compare_schedules.parse_full_sheet_data(path)["Терапия"]["doctors"][0]["totals"]
    assert len(totals) == 2 and "" not in totals
