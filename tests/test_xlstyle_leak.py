"""Кэш индексов стилей не должен удерживать книгу в памяти."""
import gc
import weakref

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from core.xlstyle import styles_for


def test_style_cache_does_not_keep_the_workbook_alive():
    wb = Workbook()
    ws = wb.active
    styles_for(wb).apply(ws["A1"], fill=PatternFill("solid", start_color="FF0000"))
    ref = weakref.ref(wb)
    del wb, ws
    gc.collect()
    assert ref() is None


def test_apply_gives_the_same_result_as_plain_assignment():
    fill = PatternFill("solid", start_color="FFCAFFCA")
    font = Font(name="Times New Roman", size=9, bold=True)
    border = Border(bottom=Side(style="medium", color="444444"))
    alignment = Alignment(horizontal="center", wrap_text=True)

    wb = Workbook()
    ws = wb.active
    styles_for(wb).apply(ws["A1"], font=font, fill=fill, border=border, alignment=alignment)
    ws["B1"].font, ws["B1"].fill, ws["B1"].border, ws["B1"].alignment = font, fill, border, alignment

    # прокси-объекты openpyxl между собой не сравниваются, поэтому сверяем индексы стиля
    # (то, что реально попадёт в файл) и значения
    assert ws["A1"]._style == ws["B1"]._style
    assert ws["A1"].fill.start_color.rgb == ws["B1"].fill.start_color.rgb == "FFCAFFCA"
    assert ws["A1"].font.name == "Times New Roman" and ws["A1"].font.b is True
    assert ws["A1"].border.bottom.style == "medium"
    assert ws["A1"].alignment.wrap_text is True


def test_cache_is_shared_per_workbook_and_separate_between_books():
    a, b = Workbook(), Workbook()
    assert styles_for(a) is styles_for(a)
    assert styles_for(a) is not styles_for(b)
