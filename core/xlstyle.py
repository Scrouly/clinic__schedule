"""Быстрая запись стилей ячеек openpyxl.

Присваивание ``cell.fill = fill`` в openpyxl делает так: находит (или добавляет) такую заливку
в общем списке стилей книги и записывает её индекс в массив стиля ячейки. Поиск идёт по
значению: объект целиком хешируется (дважды), и на таблицах в сотни тысяч ячеек это главная
статья расходов. Здесь индекс объекта считается ОДИН раз на книгу, а ячейкам записываются
только числа. Результат тот же, что при обычном присваивании.
"""
from __future__ import annotations

import copy
import weakref

from openpyxl.styles.cell_style import StyleArray

# вид стиля → (список в книге, имя индекса в массиве стиля ячейки)
_KINDS = {
    "font": ("_fonts", "fontId"),
    "fill": ("_fills", "fillId"),
    "border": ("_borders", "borderId"),
    "alignment": ("_alignments", "alignmentId"),
}


def style_array(cell) -> StyleArray:
    """Массив индексов стиля ячейки; у только что созданной ячейки его ещё нет."""
    sa = cell._style
    if sa is None:
        sa = cell._style = StyleArray()
    return sa


class StyleIds:
    """Кэш индексов стилей одной книги: «объект стиля → его номер в списке книги»."""

    def __init__(self, wb):
        self._wb = wb
        self._memo: dict = {}

    def index(self, kind: str, style_obj) -> int:
        key = (kind, id(style_obj))
        hit = self._memo.get(key)
        if hit is None:
            collection = getattr(self._wb, _KINDS[kind][0])
            # В книгу кладём собственную копию объекта, как и при ``cell.fill = copy(fill)``.
            # Сам объект храним в кэше, чтобы его id не мог быть выдан другому объекту.
            hit = (style_obj, collection.add(copy.copy(style_obj)))
            self._memo[key] = hit
        return hit[1]

    def apply(self, cell, *, font=None, fill=None, border=None, alignment=None) -> None:
        """Записать ячейке перечисленные стили (None — не трогать)."""
        sa = style_array(cell)
        if font is not None:
            sa.fontId = self.index("font", font)
        if fill is not None:
            sa.fillId = self.index("fill", fill)
        if border is not None:
            sa.borderId = self.index("border", border)
        if alignment is not None:
            sa.alignmentId = self.index("alignment", alignment)


_PER_BOOK: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def styles_for(wb) -> StyleIds:
    """Общий кэш индексов для книги (живёт, пока жива сама книга)."""
    cache = _PER_BOOK.get(wb)
    if cache is None:
        cache = _PER_BOOK[wb] = StyleIds(wb)
    return cache
