"""parse_source читает только нужный лист: соседние листы книги не влияют на результат."""
import pytest
from openpyxl import Workbook, load_workbook

from core import excel_io
from tests.builders import make_source_book, standard_source_docs

SHEET = "Апрель 2026"


def test_parse_of_a_multi_sheet_book_equals_parse_of_a_single_sheet_book(tmp_path):
    path = make_source_book(str(tmp_path / "src.xlsx"), standard_source_docs())
    alone = excel_io.parse_source(path, SHEET)

    wb = load_workbook(path)
    for name in ("Март 2026", "Май 2026"):
        ws = wb.create_sheet(name)
        ws["A1"], ws["B2"] = "Кабинет", "мусор, который не должен попасть в разбор"
    wb.move_sheet("Март 2026", offset=-1)            # нужный лист оказывается не первым
    multi = str(tmp_path / "multi.xlsx")
    wb.save(multi)

    assert excel_io.parse_source(multi, SHEET) == alone


def test_other_sheets_are_not_parsed(tmp_path, monkeypatch):
    """Страховка скорости: в книге из многих листов разбирается ровно один."""
    path = make_source_book(str(tmp_path / "src.xlsx"), standard_source_docs())
    wb = load_workbook(path)
    wb.create_sheet("Май 2026")
    multi = str(tmp_path / "multi.xlsx")
    wb.save(multi)

    opened = []
    real = excel_io.load_sheet_workbook

    def spy(p, name):
        book = real(p, name)
        opened.append(list(book.sheetnames))
        return book

    monkeypatch.setattr(excel_io, "load_sheet_workbook", spy)
    excel_io.parse_source(multi, SHEET)
    assert opened == [[SHEET]]


def test_unknown_sheet_says_which_sheets_exist(tmp_path):
    wb = Workbook()
    wb.active.title = "Март 2026"
    wb.create_sheet(SHEET)
    path = str(tmp_path / "two.xlsx")
    wb.save(path)
    with pytest.raises(ValueError, match="нет листа «Май 2026».*«Март 2026»"):
        excel_io.parse_source(path, "Май 2026")
