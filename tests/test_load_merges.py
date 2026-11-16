"""load_excel_with_merges: значение объединённой ячейки растягивается на весь диапазон."""
from openpyxl import Workbook

from core.excel_io import load_excel_with_merges


def _book(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Лист"
    ws["A1"] = "Терапия"
    ws.merge_cells("A1:C1")
    ws["A3"] = "Иванов"
    ws["B5"] = "хвост"
    ws.merge_cells("A3:A5")
    ws["E2"] = "вне диапазонов"
    wb.save(path)
    return path


def test_merged_ranges_are_filled_across_all_cells(tmp_path):
    df = load_excel_with_merges(_book(str(tmp_path / "m.xlsx")), "Лист")
    assert [df.iloc[0, c] for c in range(3)] == ["Терапия"] * 3
    assert [df.iloc[r, 0] for r in range(2, 5)] == ["Иванов"] * 3
    assert df.iloc[1, 4] == "вне диапазонов"                 # чужие ячейки не затронуты
    assert df.iloc[1, 0] != "Терапия"


def test_result_keeps_object_dtype_and_shape(tmp_path):
    df = load_excel_with_merges(_book(str(tmp_path / "m.xlsx")), "Лист")
    assert all(str(t) == "object" for t in df.dtypes) and df.shape == (5, 5)
