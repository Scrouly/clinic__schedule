#!/usr/bin/env python3
"""
compare_schedules.py — Структурное сравнение автозаполненного и ручного табелей.
Удваивает блоки врачей (Авто / Ручной) внутри оригинальной формы графика,
подсвечивает расхождения по всем типам часов (включая ночные на листе МИБС).
100% СОВМЕСТИМОСТЬ С WPS OFFICE И MS EXCEL ЗА СЧЕТ ИСПОЛЬЗОВАНИЯ CELLISRULE.
"""

import logging
import os
import copy
import re
from dataclasses import dataclass
from typing import Any, NamedTuple, Optional
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.formatting.formatting import ConditionalFormattingList
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles.cell_style import StyleArray
from openpyxl.utils import get_column_letter

from core.utils import is_doctor_name_row, yo_to_ye, parse_time_intervals, format_intervals
from core.xlstyle import style_array, styles_for

# Имя логгера = имя модуля ("core.compare_schedules"): GUI привязывает лог страницы
# «Сравнение» именно к нему (см. gui/log_handler.py: COMPARE_LOGGERS).
logger = logging.getLogger(__name__)


class CompareResult(NamedTuple):
    """Результат сравнения: путь к отчёту и число найденных расхождений."""
    path: str
    diffs: int


def build_output_path(auto_path: str) -> str:
    """Путь отчёта сравнения рядом с авто-шаблоном. Единственное место, где
    формируется имя файла: его же использует GUI для проверки перезаписи."""
    base_dir = os.path.dirname(auto_path)
    base_name = os.path.splitext(os.path.basename(auto_path))[0]
    return os.path.join(base_dir, f"{base_name}_СРАВНЕНИЕ_СТРУКТУРНОЕ.xlsx")


def get_safe_cell(ws, row, col):
    """Возвращает нормальную рабочую ячейку, защищая от MergedCell багов openpyxl."""
    cell = ws.cell(row=row, column=col)
    if type(cell).__name__ == 'MergedCell':
        if (row, col) in ws._cells:
            del ws._cells[(row, col)]
        cell = ws.cell(row=row, column=col)
    return cell


def to_numeric_if_possible(val_str):
    """Преобразует строку в число, чтобы Excel-формулы её видели."""
    if not val_str:
        return None
    try:
        num = float(str(val_str).replace(",", ".").strip())
        return int(num) if num.is_integer() else num
    except ValueError:
        return val_str


def parse_full_sheet_data(filepath: str) -> dict:
    """Парсит файл и собирает полную информацию о врачах, включая ночные смены МИБС."""
    wb = load_workbook(filepath, data_only=True)
    try:
        return _parse_workbook(wb, filepath)
    finally:
        wb.close()


class _LazyEvaluator:
    """Вычислитель формул, который строится при ПЕРВОМ обращении.

    Он нужен только для ячеек без сохранённого значения (файл, записанный openpyxl: у формул
    нет кэша). Табель, сохранённый в Excel или WPS, хранит значения формул, и разбор всей
    книги вторым проходом (xlcalculator) для него не нужен."""

    def __init__(self, filepath: str):
        self._filepath = filepath
        self._built = False
        self._evaluator = None

    def evaluate(self, ref: str):
        if not self._built:
            self._built = True
            self._evaluator = build_formula_evaluator(self._filepath)
        if self._evaluator is None:
            return None
        return self._evaluator.evaluate(ref)


def _parse_workbook(wb, filepath: str) -> dict:
    evaluator = _LazyEvaluator(filepath)
    sheets =[s for s in wb.sheetnames if 'ознакомление' not in s.lower() and 'отчет_по_ошибкам' not in s.lower()]
    db = {}

    for sheet_name in sheets:
        ws = wb[sheet_name]
        day_row_num = None
        day_col_map = {}

        for row in ws.iter_rows(min_row=1, max_row=15):
            nums = [(c.column, int(c.value)) for c in row if isinstance(c.value, (int, float)) and 1 <= c.value <= 31]
            if len(nums) >= 10:
                day_row_num = row[0].row
                for col, d in nums:
                    day_col_map[d] = col
                break

        if not day_row_num:
            continue

        if 1 in day_col_map:
            base_col = day_col_map[1]
            for d in range(1, 32):
                day_col_map[d] = base_col + (d - 1)

        max_day_col = max(day_col_map.values())
        total_cols = []

        for c in range(max_day_col + 1, ws.max_column + 1):
            if any(ws.cell(row=r, column=c).value is not None for r in range(day_row_num, day_row_num + 3)):
                total_cols.append(c)

        db[sheet_name] = {
            'day_row_num': day_row_num,
            'day_col_map': day_col_map,
            'total_cols': total_cols,
            'doctors': []
        }

        is_mibs = (sheet_name.upper() == 'МИБС')

        for row in ws.iter_rows(min_row=day_row_num + 3):
            v = row[0].value
            if is_doctor_name_row(v):
                doc_name = yo_to_ye(v.strip())
                hours_row = row[0].row
                time_row = hours_row + 1
                night_row = hours_row + 2 if is_mibs else None

                title_val = ws.cell(row=hours_row, column=2).value

                hours_dict = {}
                times_dict = {}
                night_dict = {}

                for day, col in day_col_map.items():
                    h_cell = ws.cell(row=hours_row, column=col).value
                    t_cell = ws.cell(row=time_row, column=col).value
                    hours_dict[day] = str(h_cell).strip() if h_cell is not None else ""
                    times_dict[day] = str(t_cell).strip() if t_cell is not None else ""

                    if is_mibs and night_row:
                        n_cell = ws.cell(row=night_row, column=col).value
                        night_dict[day] = str(n_cell).strip() if n_cell is not None else ""

                totals_list = []
                for col in total_cols:
                    val_h = ws.cell(row=hours_row, column=col).value
                    if val_h is None:
                        val_h = eval_cell(evaluator, sheet_name, hours_row, col)
                    if val_h is not None:
                        totals_list.append(val_h)
                        continue
                    # Значение строки времени нужно, только если у строки часов его нет: так не
                    # вызывается вычислитель формул для файлов, где итоги уже сохранены.
                    val_t = ws.cell(row=time_row, column=col).value
                    if val_t is None:
                        val_t = eval_cell(evaluator, sheet_name, time_row, col)
                    totals_list.append(val_t if val_t is not None else "")

                # На листе МИБС строка "ночные часы" содержит СВОЙ отдельный итог
                # (например, отдельная сумма SUM(...) в колонке "Часы"), который
                # нельзя путать с итогом дневной строки — собираем его отдельно.
                night_totals_list = []
                if is_mibs and night_row:
                    for col in total_cols:
                        val_n = ws.cell(row=night_row, column=col).value
                        if val_n is None:
                            val_n = eval_cell(evaluator, sheet_name, night_row, col)
                        night_totals_list.append(val_n if val_n is not None else "")

                db[sheet_name]['doctors'].append({
                    'name': doc_name,
                    'title': title_val,
                    'hours': hours_dict,
                    'times': times_dict,
                    'night': night_dict,
                    'totals': totals_list,
                    'night_totals': night_totals_list
                })
    return db


def copy_cell_styles(src_cell, dst_cell):
    """Копирует стили оформления (шрифт, границы, заливку, выравнивание, формат числа)
    из одной ячейки openpyxl в другую.

    Внутри одной книги достаточно перенести пять индексов стиля: openpyxl хранит
    одинаковые стили в общих списках книги, и присваивание объекта ``cell.font = ...``
    в итоге делает ровно это же, но сначала копирует и сравнивает сам объект
    (на сотнях тысяч ячеек это было основным временем compare). Защита ячейки
    и именованный стиль, как и раньше, не копируются."""
    if not src_cell.has_style:
        return
    if src_cell.parent.parent is dst_cell.parent.parent:
        s, d = src_cell._style, dst_cell._style
        if d is None:                       # у только что созданной ячейки массива стиля ещё нет
            d = dst_cell._style = StyleArray()
        d.fontId = s.fontId
        d.borderId = s.borderId
        d.fillId = s.fillId
        d.alignmentId = s.alignmentId
        d.numFmtId = s.numFmtId
        return
    # Ячейки из разных книг: индексы не переносимы, копируем сами объекты.
    dst_cell.font = copy.copy(src_cell.font)
    dst_cell.border = copy.copy(src_cell.border)
    dst_cell.fill = copy.copy(src_cell.fill)
    dst_cell.alignment = copy.copy(src_cell.alignment)
    dst_cell.number_format = src_cell.number_format


def merge_and_style_range(ws, start_row, start_col, end_row, end_col, value, font, alignment, fill, border):
    """Безопасно форматирует и объединяет диапазон ячеек."""
    get_safe_cell(ws, start_row, start_col).value = value
    styles = styles_for(ws.parent)          # индексы стилей считаются один раз, а не на каждую ячейку
    font, alignment, fill, border = font or None, alignment or None, fill or None, border or None
    for r in range(start_row, end_row + 1):
        for c in range(start_col, end_col + 1):
            cell = get_safe_cell(ws, r, c)
            styles.apply(cell, font=font, alignment=alignment, fill=fill, border=border)
            if r != start_row or c != start_col:
                cell.value = None
    ws.merge_cells(start_row=start_row, start_column=start_col, end_row=end_row, end_column=end_col)


def style_single_cell(ws, row, col, value, font, alignment, fill, border):
    """Стилизует одну ячейку без объединения (для итогов, которые в шаблоне не мёржатся,
    например 'Ночные часы' на листе МИБС)."""
    cell = get_safe_cell(ws, row, col)
    cell.value = value
    styles_for(ws.parent).apply(cell, font=font or None, alignment=alignment or None,
                                fill=fill or None, border=border or None)


def build_formula_evaluator(filepath: str):
    """Строит вычислитель формул xlcalculator.

    Библиотека тянет за собой pandas, numpy и scipy (около 0,3 с загрузки), поэтому
    подключается только здесь, при первом реальном обращении, а не при запуске программы."""
    try:
        from xlcalculator import ModelCompiler, Evaluator as XLEvaluator
    except ImportError:
        return None
    try:
        compiler = ModelCompiler()
        model = compiler.read_and_parse_archive(filepath)
        return XLEvaluator(model)
    except Exception as e:
        logger.warning(f"§WARN§ xlcalculator не смог разобрать файл: {e}")
        return None


def eval_cell(evaluator, sheet_name: str, row: int, col: int):
    """Вычисляет значение ячейки через xlcalculator."""
    if evaluator is None:
        return None
    try:
        ref = f"{sheet_name}!{get_column_letter(col)}{row}"
        val = evaluator.evaluate(ref)
        if val is None:
            return None
        if hasattr(val, 'value'):
            return val.value
        return val
    except Exception:
        return None


def shift_formula_rows(formula_str: str, old_row: int, new_row: int) -> str:
    """Умный сдвиг строковых индексов внутри формул Excel."""
    if not isinstance(formula_str, str) or not formula_str.startswith("="):
        return formula_str
    pattern = rf"([A-Za-z]+|:){old_row}(\b|[^0-9])"

    def repl(match):
        return f"{match.group(1)}{new_row}{match.group(2)}"

    return re.sub(pattern, repl, formula_str)


def clean_time(t_str):
    """Приводит время к единому стандарту для исключения ложных срабатываний."""
    if not t_str: return ""
    intervals = parse_time_intervals(str(t_str))
    if not intervals: return str(t_str).strip().replace(" ", "").lower().strip(':.,;')
    return format_intervals(intervals)


def clean_hours(h_str):
    """Приводит часы к единому стандарту чисел для сверки."""
    if not h_str: return ""
    try:
        val = float(str(h_str).replace(",", ".").strip())
        if val == 0.0: return ""
        return f"{val:.2f}".rstrip('0').rstrip('.')
    except ValueError:
        return str(h_str).strip().replace(" ", "").lower()


_DIFF_FILL = PatternFill(start_color="FFE4B5", end_color="FFE4B5", fill_type="solid")
_RED_FILL = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
_GREEN_FILL = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
_LEFT_ALIGN = Alignment(horizontal='left', vertical='center', wrap_text=True)
_CENTER_ALIGN = Alignment(horizontal='center', vertical='center', wrap_text=True)
_FONT_AUTO = Font(name="Segoe UI", size=10, italic=True, color="555555")
_FONT_MANUAL = Font(name="Segoe UI", size=10, bold=True, color="000000")
_SPACER_HEIGHT = 8.0


@dataclass(frozen=True)
class _SheetCtx:
    """Раскладка одного листа: образцы стилей из шаблона и колонки итогов."""
    ws: Any
    is_mibs: bool
    last_table_col: int
    day_col_map: dict
    total_cols: list
    hours_total_col: Optional[int]
    norm_col_letter: Optional[str]
    h_col_letter: Optional[str]
    orig_hours_row: int
    sample_hours: list
    sample_times: list
    sample_night: Optional[list]


@dataclass(frozen=True)
class _CardRows:
    """Номера строк одного блока врача (АВТО или РУЧНОЙ)."""
    hours: int
    times: int
    night: Optional[int]

    @property
    def last(self) -> int:
        return self.night if self.night is not None else self.times


def _card_rows(start_row: int, is_mibs: bool):
    """Строки двух блоков карточки врача: сначала АВТО, сразу под ним РУЧНОЙ."""
    step = 3 if is_mibs else 2
    def block(first):
        return _CardRows(first, first + 1, first + 2 if is_mibs else None)
    return block(start_row), block(start_row + step)


def _find_first_doctor_row(ws, day_row_num: int) -> int:
    """Первая строка врача.

    ВАЖНО: на листе МИБС между шапкой и первым врачом есть дополнительная строка
    подзаголовка («Ночные часы»), которой нет на других листах, поэтому нельзя
    жёстко считать day_row_num+3: стили/шрифты/границы брались бы с чужой строки."""
    for r in range(day_row_num + 3, ws.max_row + 1):
        if is_doctor_name_row(ws.cell(row=r, column=1).value):
            return r
    return day_row_num + 3


def _find_norm_column(ws, day_row_num: int, total_cols: list):
    for col in total_cols:
        val_header = ws.cell(row=day_row_num, column=col).value
        if val_header and "норма" in str(val_header).lower():
            return col
    return total_cols[0] if total_cols else None


def _find_hours_total_column(ws, day_row_num: int, total_cols: list):
    for col in total_cols:
        v1 = str(ws.cell(row=day_row_num, column=col).value or "").lower()
        v2 = str(ws.cell(row=day_row_num + 1, column=col).value or "").lower()
        if "часы" in v1 or "часы" in v2 or "час" in v2:
            if "норма" not in v1 and "норма" not in v2:
                return col
    if len(total_cols) >= 3:
        return total_cols[2]
    return total_cols[-1] if total_cols else None


def _sheet_context(ws, sheet_info: dict) -> _SheetCtx:
    day_row_num = sheet_info['day_row_num']
    day_col_map = sheet_info['day_col_map']
    total_cols = sheet_info['total_cols']
    is_mibs = ws.title.upper() == 'МИБС'
    last_table_col = max(total_cols) if total_cols else max(day_col_map.values())

    first_doc_row = _find_first_doctor_row(ws, day_row_num)
    cols = range(1, last_table_col + 1)
    norm_col = _find_norm_column(ws, day_row_num, total_cols)
    hours_total_col = _find_hours_total_column(ws, day_row_num, total_cols)
    return _SheetCtx(
        ws=ws, is_mibs=is_mibs, last_table_col=last_table_col,
        day_col_map=day_col_map, total_cols=total_cols,
        hours_total_col=hours_total_col,
        norm_col_letter=get_column_letter(norm_col) if norm_col else None,
        h_col_letter=get_column_letter(hours_total_col) if hours_total_col else None,
        orig_hours_row=first_doc_row,
        sample_hours=[ws.cell(row=first_doc_row, column=c) for c in cols],
        sample_times=[ws.cell(row=first_doc_row + 1, column=c) for c in cols],
        sample_night=[ws.cell(row=first_doc_row + 2, column=c) for c in cols] if is_mibs else None,
    )


def _capture_footer(ws, first_doc_row: int, is_mibs: bool) -> list:
    """Запоминает «подвал» (строки после последнего врача), чтобы вернуть его
    после пересборки таблицы."""
    last_doc_row = first_doc_row
    for r in range(first_doc_row, ws.max_row + 1):
        if is_doctor_name_row(ws.cell(row=r, column=1).value):
            last_doc_row = r + (2 if is_mibs else 1)

    footer_rows = []
    for r in range(last_doc_row + 1, ws.max_row + 1):
        row_cells = [ws.cell(row=r, column=c) for c in range(1, ws.max_column + 1)]
        footer_rows.append({
            'height': ws.row_dimensions[r].height,
            'cells': [(c.value, c.has_style, copy.copy(c.font), copy.copy(c.border),
                       copy.copy(c.fill), copy.copy(c.alignment), c.number_format) for c in row_cells]
        })
    return footer_rows


def _restore_footer(ws, footer_rows: list, row: int) -> int:
    """Переносит «подвал» с строки ``row``; возвращает следующую свободную строку."""
    for f_row in footer_rows:
        ws.row_dimensions[row].height = f_row['height']
        for c_idx, (value, has_style, font, border, fill, alignment, number_format) in enumerate(f_row['cells'], 1):
            cell = get_safe_cell(ws, row, c_idx)
            cell.value = value
            if has_style:
                cell.font = font
                cell.border = border
                cell.fill = fill
                cell.alignment = alignment
                cell.number_format = number_format
        row += 1
    return row


def _clear_table_area(ws, start_row: int) -> None:
    """Снимает объединения и удаляет всё, начиная со строки первого врача."""
    for r in [r for r in ws.merged_cells.ranges if r.min_row >= start_row]:
        try:
            ws.unmerge_cells(start_row=r.min_row, start_column=r.min_col, end_row=r.max_row, end_column=r.max_col)
        except Exception:
            ws.merged_cells.remove(r)
    ws.delete_rows(start_row, amount=ws.max_row - start_row + 2)


def _pair_doctors(auto_list: list, manual_list: list) -> list:
    """Сопоставляет врачей авто- и ручного файла: сначала по ФИО и должности, затем
    по одному ФИО; оставшиеся ручные записи добавляются в конец."""
    paired, used = [], set()

    def take(a_data, same_title):
        for idx, m_data in enumerate(manual_list):
            if idx in used or m_data['name'] != a_data['name']:
                continue
            if same_title and m_data['title'] != a_data['title']:
                continue
            used.add(idx)
            return m_data
        return None

    for a_data in auto_list:
        paired.append({'name': a_data['name'], 'auto': a_data,
                       'manual': take(a_data, True) or take(a_data, False)})
    for idx, m_data in enumerate(manual_list):
        if idx not in used:
            paired.append({'name': m_data['name'], 'auto': None, 'manual': m_data})
    return paired


def _shifted_or_stored(sample_cell, orig_row: int, new_row: int, stored):
    """Формула из шаблона со сдвигом строки либо сохранённое значение итога."""
    if sample_cell.value and str(sample_cell.value).startswith("="):
        return shift_formula_rows(sample_cell.value, orig_row, new_row)
    return stored


def _render_block(sc: _SheetCtx, rows: _CardRows, data, label: str, doc_name: str,
                  title: str, font: Font) -> None:
    """Рисует один блок врача (АВТО либо РУЧНОЙ): стили, значения дней, ФИО,
    должность, итоги и подсветку «норма против часов»."""
    ws, is_mibs = sc.ws, sc.is_mibs
    for col_idx in range(1, sc.last_table_col + 1):
        copy_cell_styles(sc.sample_hours[col_idx - 1], get_safe_cell(ws, rows.hours, col_idx))
        copy_cell_styles(sc.sample_times[col_idx - 1], get_safe_cell(ws, rows.times, col_idx))
        if is_mibs:
            copy_cell_styles(sc.sample_night[col_idx - 1], get_safe_cell(ws, rows.night, col_idx))

    if data:
        for day, col in sc.day_col_map.items():
            get_safe_cell(ws, rows.hours, col).value = to_numeric_if_possible(data['hours'][day])
            get_safe_cell(ws, rows.times, col).value = data['times'][day]
            if is_mibs:
                get_safe_cell(ws, rows.night, col).value = to_numeric_if_possible(data['night'][day])

    name_cell, title_cell = sc.sample_hours[0], sc.sample_hours[1]
    merge_and_style_range(ws, rows.hours, 1, rows.last, 1,
                          f"{doc_name} ({label})" if data else f"{doc_name} ({label}) — Отсутствует",
                          font, _LEFT_ALIGN, name_cell.fill, name_cell.border)
    merge_and_style_range(ws, rows.hours, 2, rows.last, 2, title,
                          font, _LEFT_ALIGN, title_cell.fill, title_cell.border)

    for idx, col in enumerate(sc.total_cols):
        sample = sc.sample_hours[col - 1]
        stored = data['totals'][idx] if (data and idx < len(data['totals'])) else ""
        val = _shifted_or_stored(sample, sc.orig_hours_row, rows.hours, stored)

        if is_mibs and col == sc.hours_total_col:
            # В шаблоне колонка "Часы" объединена только на строках Часы/Время,
            # а строка "Ночные часы" — отдельная ячейка со своим значением.
            merge_and_style_range(ws, rows.hours, col, rows.times, col, val,
                                  font, _CENTER_ALIGN, sample.fill, sample.border)
            night_sample = sc.sample_night[col - 1]
            night_totals = data.get('night_totals', []) if data else []
            night_stored = night_totals[idx] if idx < len(night_totals) else ""
            night_val = _shifted_or_stored(night_sample, sc.orig_hours_row + 2, rows.night, night_stored)
            style_single_cell(ws, rows.night, col, night_val, font, _CENTER_ALIGN,
                              night_sample.fill, night_sample.border)
        else:
            merge_and_style_range(ws, rows.hours, col, rows.last, col, val,
                                  font, _CENTER_ALIGN, sample.fill, sample.border)

    if sc.norm_col_letter and sc.h_col_letter and data:
        norm_range = f"{sc.norm_col_letter}{rows.hours}:{sc.norm_col_letter}{rows.hours}"
        hours_ref = f'${sc.h_col_letter}${rows.hours}'
        ws.conditional_formatting.add(norm_range, CellIsRule(operator='lessThan', formula=[hours_ref], fill=_RED_FILL))
        ws.conditional_formatting.add(norm_range, CellIsRule(operator='greaterThan', formula=[hours_ref], fill=_GREEN_FILL))


def _highlight_total_mismatches(sc: _SheetCtx, a: _CardRows, m: _CardRows) -> None:
    """Условное форматирование итогов: ячейка подсвечивается, если не равна парной."""
    ws = sc.ws

    def pair(col_letter, row_a, row_m):
        for here, other in ((row_a, row_m), (row_m, row_a)):
            ws.conditional_formatting.add(
                f"{col_letter}{here}:{col_letter}{here}",
                CellIsRule(operator='notEqual', formula=[f'${col_letter}${other}'], fill=_DIFF_FILL))

    for col in sc.total_cols:
        letter = get_column_letter(col)
        pair(letter, a.hours, m.hours)
        if sc.is_mibs and col == sc.hours_total_col:
            pair(letter, a.night, m.night)       # «Ночные часы» — своя ячейка, не мёрж


def _mark_day_differences(sc: _SheetCtx, a_data, m_data, a: _CardRows, m: _CardRows) -> int:
    """Закрашивает расхождения по дням 1–31; возвращает их число."""
    ws, found = sc.ws, 0
    kinds = [('hours', clean_hours, 'hours'), ('times', clean_time, 'times')]
    if sc.is_mibs:
        kinds.append(('night', clean_hours, 'night'))
    for day, col in sc.day_col_map.items():
        for key, clean, row_attr in kinds:
            a_val = a_data[key][day] if a_data else ""
            m_val = m_data[key][day] if m_data else ""
            if clean(a_val) != clean(m_val):
                get_safe_cell(ws, getattr(a, row_attr), col).fill = _DIFF_FILL
                get_safe_cell(ws, getattr(m, row_attr), col).fill = _DIFF_FILL
                found += 1
    return found


def _has_multiple_intervals(data) -> bool:
    return bool(data) and any('/' in str(t) or '\\' in str(t) for t in data['times'].values())


def _set_card_heights(sc: _SheetCtx, rows: _CardRows, data) -> None:
    ws = sc.ws
    ws.row_dimensions[rows.hours].height = 15
    ws.row_dimensions[rows.times].height = 45.0 if _has_multiple_intervals(data) else 22.5
    if sc.is_mibs:
        ws.row_dimensions[rows.night].height = 15


def _underline_card(sc: _SheetCtx, last_row: int, cache: dict) -> None:
    """Нижняя граница карточки. Результат зависит только от прежней границы ячейки,
    а их немного: запоминаем по номеру прежней границы (``cache``)."""
    ws = sc.ws
    for col_idx in range(1, sc.last_table_col + 1):
        cell = ws.cell(row=last_row, column=col_idx)
        old_border_id = cell._style.borderId if cell._style is not None else 0
        new_border_id = cache.get(old_border_id)
        if new_border_id is None:
            cell.border = Border(left=cell.border.left, right=cell.border.right,
                                 top=cell.border.top, bottom=Side(style='medium', color='444444'))
            cache[old_border_id] = cell._style.borderId
        else:
            style_array(cell).borderId = new_border_id


def _add_spacer_row(sc: _SheetCtx, row: int) -> None:
    ws = sc.ws
    ws.row_dimensions[row].height = _SPACER_HEIGHT
    no_fill, no_border = PatternFill(fill_type=None), Border()
    for col_idx in range(1, sc.last_table_col + 1):
        cell = get_safe_cell(ws, row, col_idx)
        cell.value = None
        styles_for(ws.parent).apply(cell, fill=no_fill, border=no_border)


def _render_sheet(ws, auto_info: dict, manual_info: dict) -> int:
    """Пересобирает лист: каждый врач — блок АВТО и под ним РУЧНОЙ. Возвращает число расхождений."""
    sc = _sheet_context(ws, auto_info)
    start_row = sc.orig_hours_row
    footer_rows = _capture_footer(ws, start_row, sc.is_mibs)
    _clear_table_area(ws, start_row)

    border_cache: dict = {}
    found, current_row = 0, start_row
    for pair in _pair_doctors(auto_info['doctors'], manual_info.get('doctors', [])):
        a_data, m_data = pair['auto'], pair['manual']
        title = a_data['title'] if a_data else (m_data['title'] if m_data else "")
        a_rows, m_rows = _card_rows(current_row, sc.is_mibs)

        _render_block(sc, a_rows, a_data, "АВТО", pair['name'], title, _FONT_AUTO)
        _render_block(sc, m_rows, m_data, "РУЧНОЙ", pair['name'], title, _FONT_MANUAL)
        _highlight_total_mismatches(sc, a_rows, m_rows)
        found += _mark_day_differences(sc, a_data, m_data, a_rows, m_rows)
        _set_card_heights(sc, a_rows, a_data)
        _set_card_heights(sc, m_rows, m_data)
        _underline_card(sc, m_rows.last, border_cache)

        current_row = m_rows.last + 1
        _add_spacer_row(sc, current_row)
        current_row += 1

    _restore_footer(ws, footer_rows, current_row)
    return found


def compare(auto_path: str, manual_path: str) -> CompareResult:
    """Главная функция сравнения с генерацией графического отчета.

    Возвращает CompareResult(path, diffs). При ошибке сохранения отчёта
    выбрасывает исключение (раньше возвращала -1, и GUI показывал «найдены
    расхождения»)."""
    logger.info("§HDR§ ЗАПУСК СТРУКТУРНОГО СРАВНЕНИЯ ГРАФИКОВ")

    auto_db = parse_full_sheet_data(auto_path)
    manual_db = parse_full_sheet_data(manual_path)

    wb_report = load_workbook(auto_path)
    for sheet_name in wb_report.sheetnames:
        wb_report[sheet_name].conditional_formatting = ConditionalFormattingList()
    for s in list(wb_report.sheetnames):
        if 'ознакомление' in s.lower() or 'отчет_по_ошибкам' in s.lower():
            del wb_report[s]

    total_diffs_found = 0
    for sheet_name in wb_report.sheetnames:
        if sheet_name in auto_db:
            total_diffs_found += _render_sheet(wb_report[sheet_name], auto_db[sheet_name],
                                               manual_db.get(sheet_name, {}))

    output_path = build_output_path(auto_path)

    try:
        wb_report.save(output_path)

        # Результат GUI получает из возвращаемого CompareResult, а не из текста лога:
        # прежние «чистые» дубли строк убраны, чтобы в окне не было повторов.
        logger.info("§SEP§")
        logger.info("§OK§ График-сравнение успешно сгенерирован!")
        logger.info(f"§DETAIL§ Найдено расхождений в ячейках: {total_diffs_found}")
        logger.info(f"§DETAIL§ Файл: {os.path.basename(output_path)}")

        return CompareResult(path=output_path, diffs=total_diffs_found)

    except PermissionError:
        msg = f"Закройте файл '{os.path.basename(output_path)}' в Excel и попробуйте снова."
        logger.error(f"Сбой сохранения файла сравнения: {msg}")
        raise PermissionError(msg)
    except Exception as e:
        logger.error(f"Сбой сохранения файла сравнения: {e}")
        raise
