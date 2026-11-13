"""«Золотые» дампы: содержимое книги в JSON, чтобы рефакторинг и ускорение
не могли незаметно изменить результат.

Дамп намеренно не зависит от версии openpyxl: значения, цвет заливки, объединения,
комментарии, высоты строк. Условное форматирование вынесено в ОТДЕЛЬНЫЙ дамп —
пакет «perf-core» сознательно переписывает правила (объединяет диапазоны), и тогда
обновляется только он, а дамп ячеек обязан остаться прежним.

Обновить эталоны после намеренного изменения:
    UPDATE_GOLDEN=1 python -m pytest tests -k golden
и просмотреть diff в git: он и есть список изменений поведения.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

GOLDEN_DIR = Path(__file__).parent / "golden"


def _fill_hex(cell) -> str | None:
    f = cell.fill
    if f is None or f.fill_type in (None, "none"):
        return None
    color = f.start_color
    return color.rgb if isinstance(getattr(color, "rgb", None), str) else f"theme:{color.theme}"


def dump_cells(wb) -> dict:
    """{лист: {"cells": {"A1": {...}}, "merged": [...], "row_heights": {...}}}"""
    out: dict[str, Any] = {}
    for ws in wb.worksheets:
        cells = {}
        for row in ws.iter_rows():
            for c in row:
                fill = _fill_hex(c)
                comment = c.comment.text if c.comment else None
                if c.value is None and fill is None and comment is None:
                    continue
                item: dict[str, Any] = {}
                if c.value is not None:
                    item["v"] = c.value
                if fill is not None:
                    item["fill"] = fill
                if comment is not None:
                    item["comment"] = comment
                cells[c.coordinate] = item
        heights = {str(r): d.height for r, d in sorted(ws.row_dimensions.items()) if d.height}
        out[ws.title] = {
            "cells": cells,
            "merged": sorted(str(m) for m in ws.merged_cells.ranges),
            "row_heights": heights,
        }
    return out


def dump_conditional_formatting(wb) -> dict:
    """{лист: [{"range", "type", "operator", "formula", "fill"}]}, отсортировано."""
    out: dict[str, Any] = {}
    for ws in wb.worksheets:
        rules = []
        for cf in ws.conditional_formatting:
            for rule in cf.rules:
                fill = None
                if rule.dxf is not None and rule.dxf.fill is not None:
                    bg = rule.dxf.fill.bgColor
                    fg = rule.dxf.fill.fgColor
                    fill = (bg.rgb if isinstance(getattr(bg, "rgb", None), str) else None) or \
                           (fg.rgb if isinstance(getattr(fg, "rgb", None), str) else None)
                rules.append({
                    "range": str(cf.sqref),
                    "type": rule.type,
                    "operator": rule.operator,
                    "formula": list(rule.formula or []),
                    "fill": fill,
                })
        out[ws.title] = sorted(rules, key=lambda r: json.dumps(r, sort_keys=True, ensure_ascii=False))
    return out


def dump_records(records) -> list:
    """Список DoctorRecord → JSON-совместимые словари (ключи дней строками)."""
    return [
        {
            "name": r.name, "direction": r.direction, "cabinet": r.cabinet, "spec_hint": r.spec_hint,
            "schedule": {str(d): {"time": s.time, "hours": s.hours} for d, s in sorted(r.schedule.items())},
        }
        for r in records
    ]


def assert_matches_golden(name: str, data: Any) -> None:
    path = GOLDEN_DIR / f"{name}.json"
    text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN_DIR.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return
    if not path.exists():
        pytest.fail(f"Нет эталона {path.name}. Создайте его: UPDATE_GOLDEN=1 python -m pytest tests -k golden")
    expected = path.read_text(encoding="utf-8")
    if text != expected:
        # Показываем первые отличающиеся строки, а не весь дамп.
        import difflib
        diff = list(difflib.unified_diff(expected.splitlines(), text.splitlines(),
                                         "эталон", "получено", lineterm="", n=1))
        pytest.fail(f"Результат отличается от эталона {path.name}:\n" + "\n".join(diff[:40]))
