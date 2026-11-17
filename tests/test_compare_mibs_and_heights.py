"""compare(): ночные часы МИБС, высота строк с несколькими интервалами, формулы итогов."""
import pytest
from openpyxl import load_workbook

from core import compare_schedules
from tests.builders import DAY_ROW, FIRST_DAY_COL, HOURS_COL, make_compare_pair

FIRST_DOC_ROW = DAY_ROW + 5            # в make_template_book врач стоит в DAY_ROW + 5


@pytest.fixture
def pair(tmp_path):
    return make_compare_pair(str(tmp_path / "auto.xlsx"), str(tmp_path / "manual.xlsx"))


def edit(path, sheet, changes):
    wb = load_workbook(path)
    for (row, col), value in changes.items():
        wb[sheet].cell(row, col, value)
    wb.save(path)


def test_baseline_has_only_the_two_planted_differences(pair):
    assert compare_schedules.compare(*pair).diffs == 2


def test_night_hours_difference_on_mibs_is_counted_and_highlighted(pair):
    night_row = FIRST_DOC_ROW + 2
    edit(pair[1], "МИБС", {(night_row, FIRST_DAY_COL): 8})
    result = compare_schedules.compare(*pair)
    assert result.diffs == 3                                   # +1 за ночные часы

    ws = load_workbook(result.path)["МИБС"]
    auto_night, manual_night = FIRST_DOC_ROW + 2, FIRST_DOC_ROW + 5
    assert ws.cell(manual_night, FIRST_DAY_COL).value == 8
    for row in (auto_night, manual_night):
        assert ws.cell(row, FIRST_DAY_COL).fill.start_color.rgb.endswith("FFE4B5")


def test_multi_interval_shift_gets_a_taller_times_row(pair):
    edit(pair[1], "Терапия", {(FIRST_DOC_ROW + 1, FIRST_DAY_COL): "09:00-12:00/13:00-17:00"})
    ws = load_workbook(compare_schedules.compare(*pair).path)["Терапия"]
    assert ws.row_dimensions[FIRST_DOC_ROW + 1].height == 22.5      # АВТО: один интервал
    assert ws.row_dimensions[FIRST_DOC_ROW + 3].height == 45.0      # РУЧНОЙ: два интервала
    assert ws.row_dimensions[FIRST_DOC_ROW].height == 15
    assert ws.row_dimensions[FIRST_DOC_ROW + 2].height == 15


def test_night_total_formula_is_shifted_to_each_block(pair):
    night_row = FIRST_DOC_ROW + 2
    edit(pair[0], "МИБС", {(night_row, HOURS_COL): f"=SUM(C{night_row}:AG{night_row})"})
    ws = load_workbook(compare_schedules.compare(*pair).path)["МИБС"]
    assert ws.cell(FIRST_DOC_ROW + 2, HOURS_COL).value == f"=SUM(C{FIRST_DOC_ROW + 2}:AG{FIRST_DOC_ROW + 2})"
    assert ws.cell(FIRST_DOC_ROW + 5, HOURS_COL).value == f"=SUM(C{FIRST_DOC_ROW + 5}:AG{FIRST_DOC_ROW + 5})"
