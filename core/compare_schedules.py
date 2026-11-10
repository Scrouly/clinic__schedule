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
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.formatting.rule import CellIsRule
from openpyxl.utils import get_column_letter

try:
    from xlcalculator import ModelCompiler, Evaluator as XLEvaluator

    _XLCALC_AVAILABLE = True
except ImportError:
    _XLCALC_AVAILABLE = False

from core.utils import DR_RE, yo_to_ye, parse_time_intervals, format_intervals

logger = logging.getLogger("compare_schedules")


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
    evaluator = build_formula_evaluator(filepath)
    sheets = [s for s in wb.sheetnames if 'ознакомление' not in s.lower() and 'отчет_по_ошибкам' not in s.lower()]
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
            if v and isinstance(v, str) and DR_RE.match(v.strip()):
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
                    val_t = ws.cell(row=time_row, column=col).value
                    if val_h is None:
                        val_h = eval_cell(evaluator, sheet_name, hours_row, col)
                    if val_t is None:
                        val_t = eval_cell(evaluator, sheet_name, time_row, col)
                    totals_list.append(val_h if val_h is not None else (val_t if val_t is not None else ""))

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
    wb.close()
    return db


def copy_cell_styles(src_cell, dst_cell):
    """Копирует стили оформления из одной ячейки openpyxl в другую."""
    if src_cell.has_style:
        dst_cell.font = copy.copy(src_cell.font)
        dst_cell.border = copy.copy(src_cell.border)
        dst_cell.fill = copy.copy(src_cell.fill)
        dst_cell.alignment = copy.copy(src_cell.alignment)
        dst_cell.number_format = src_cell.number_format


def merge_and_style_range(ws, start_row, start_col, end_row, end_col, value, font, alignment, fill, border):
    """Безопасно форматирует и объединяет диапазон ячеек."""
    get_safe_cell(ws, start_row, start_col).value = value
    for r in range(start_row, end_row + 1):
        for c in range(start_col, end_col + 1):
            cell = get_safe_cell(ws, r, c)
            if font: cell.font = copy.copy(font)
            if alignment: cell.alignment = copy.copy(alignment)
            if fill: cell.fill = copy.copy(fill)
            if border: cell.border = copy.copy(border)
            if r != start_row or c != start_col:
                cell.value = None
    ws.merge_cells(start_row=start_row, start_column=start_col, end_row=end_row, end_column=end_col)


def style_single_cell(ws, row, col, value, font, alignment, fill, border):
    """Стилизует одну ячейку без объединения (для итогов, которые в шаблоне не мёржатся,
    например 'Ночные часы' на листе МИБС)."""
    cell = get_safe_cell(ws, row, col)
    cell.value = value
    if font: cell.font = copy.copy(font)
    if alignment: cell.alignment = copy.copy(alignment)
    if fill: cell.fill = copy.copy(fill)
    if border: cell.border = copy.copy(border)


def build_formula_evaluator(filepath: str):
    """Строит вычислитель формул xlcalculator."""
    if not _XLCALC_AVAILABLE:
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


def compare(auto_path: str, manual_path: str):
    """Главная функция сравнения с генерацией графического отчета."""
    logger.info("§HDR§ ЗАПУСК СТРУКТУРНОГО СРАВНЕНИЯ ГРАФИКОВ")

    auto_db = parse_full_sheet_data(auto_path)
    manual_db = parse_full_sheet_data(manual_path)

    wb_report = load_workbook(auto_path)

    for sheet_name in wb_report.sheetnames:
        wb_report[sheet_name].conditional_formatting.__init__()

    for s in list(wb_report.sheetnames):
        if 'ознакомление' in s.lower() or 'отчет_по_ошибкам' in s.lower():
            del wb_report[s]

    diff_fill = PatternFill(start_color="FFE4B5", end_color="FFE4B5", fill_type="solid")
    red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")

    left_center_align = Alignment(horizontal='left', vertical='center', wrap_text=True)
    center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)

    font_a_name = Font(name="Segoe UI", size=10, italic=True, color="555555")
    font_m_name = Font(name="Segoe UI", size=10, bold=True, color="000000")
    total_diffs_found = 0

    for sheet_name in wb_report.sheetnames:
        if sheet_name not in auto_db:
            continue

        ws = wb_report[sheet_name]
        day_row_num = auto_db[sheet_name]['day_row_num']
        day_col_map = auto_db[sheet_name]['day_col_map']
        total_cols = auto_db[sheet_name]['total_cols']

        is_mibs = (sheet_name.upper() == 'МИБС')
        last_table_col = max(total_cols) if total_cols else max(day_col_map.values())

        # ВАЖНО: на листе МИБС между шапкой и первым врачом есть дополнительная
        # строка подзаголовка ("Ночные часы"), которой нет на других листах.
        # Поэтому нельзя жёстко считать day_row_num+3 первой строкой врача —
        # ищем её по факту, иначе стили/шрифты/границы берутся с чужой строки.
        first_doc_row = None
        for r in range(day_row_num + 3, ws.max_row + 1):
            v = ws.cell(row=r, column=1).value
            if v and isinstance(v, str) and DR_RE.match(v.strip()):
                first_doc_row = r
                break
        if first_doc_row is None:
            first_doc_row = day_row_num + 3

        sample_hours_cells = [ws.cell(row=first_doc_row, column=c) for c in range(1, last_table_col + 1)]
        sample_times_cells = [ws.cell(row=first_doc_row + 1, column=c) for c in range(1, last_table_col + 1)]
        sample_night_cells = [ws.cell(row=first_doc_row + 2, column=c) for c in
                              range(1, last_table_col + 1)] if is_mibs else None

        orig_hours_row = first_doc_row
        start_clear_row = first_doc_row

        norm_col = None
        for col in total_cols:
            val_header = ws.cell(row=day_row_num, column=col).value
            if val_header and "норма" in str(val_header).lower():
                norm_col = col
                break
        if not norm_col and total_cols:
            norm_col = total_cols[0]

        hours_total_col = None
        for col in total_cols:
            v1 = str(ws.cell(row=day_row_num, column=col).value or "").lower()
            v2 = str(ws.cell(row=day_row_num + 1, column=col).value or "").lower()
            if "часы" in v1 or "часы" in v2 or "час" in v2:
                if "норма" not in v1 and "норма" not in v2:
                    hours_total_col = col
                    break
        if not hours_total_col and len(total_cols) >= 3:
            hours_total_col = total_cols[2]
        elif not hours_total_col and total_cols:
            hours_total_col = total_cols[-1]

        norm_col_letter = get_column_letter(norm_col) if norm_col else None
        h_col_letter = get_column_letter(hours_total_col) if hours_total_col else None

        last_doc_row = start_clear_row
        for r in range(start_clear_row, ws.max_row + 1):
            v = ws.cell(row=r, column=1).value
            if v and isinstance(v, str) and DR_RE.match(v.strip()):
                last_doc_row = r + (2 if is_mibs else 1)

        footer_rows = []
        if last_doc_row < ws.max_row:
            for r in range(last_doc_row + 1, ws.max_row + 1):
                row_cells = [ws.cell(row=r, column=c) for c in range(1, ws.max_column + 1)]
                footer_rows.append({
                    'height': ws.row_dimensions[r].height,
                    'cells': [(c.value, c.has_style, copy.copy(c.font), copy.copy(c.border),
                               copy.copy(c.fill), copy.copy(c.alignment), c.number_format) for c in row_cells]
                })

        ranges_to_remove = [r for r in ws.merged_cells.ranges if r.min_row >= start_clear_row]
        for r in ranges_to_remove:
            try:
                ws.unmerge_cells(start_row=r.min_row, start_column=r.min_col, end_row=r.max_row, end_column=r.max_col)
            except Exception:
                ws.merged_cells.remove(r)

        ws.delete_rows(start_clear_row, amount=ws.max_row - start_clear_row + 2)

        auto_list = auto_db[sheet_name]['doctors']
        manual_list = manual_db.get(sheet_name, {}).get('doctors', [])

        paired_docs = []
        used_manual_indices = set()

        for a_data in auto_list:
            m_match = None
            for idx, m_data in enumerate(manual_list):
                if idx not in used_manual_indices and m_data['name'] == a_data['name'] and m_data['title'] == a_data[
                    'title']:
                    m_match = m_data
                    used_manual_indices.add(idx)
                    break
            if not m_match:
                for idx, m_data in enumerate(manual_list):
                    if idx not in used_manual_indices and m_data['name'] == a_data['name']:
                        m_match = m_data
                        used_manual_indices.add(idx)
                        break
            paired_docs.append({'name': a_data['name'], 'auto': a_data, 'manual': m_match})

        for idx, m_data in enumerate(manual_list):
            if idx not in used_manual_indices:
                paired_docs.append({'name': m_data['name'], 'auto': None, 'manual': m_data})

        current_row = start_clear_row

        for pair in paired_docs:
            a_data = pair['auto']
            m_data = pair['manual']
            doc_name = pair['name']
            title = a_data['title'] if a_data else (m_data['title'] if m_data else "")

            a_hours_r = current_row
            a_times_r = current_row + 1
            a_night_r = current_row + 2 if is_mibs else None

            m_hours_r = current_row + 3 if is_mibs else current_row + 2
            m_times_r = current_row + 4 if is_mibs else current_row + 3
            m_night_r = current_row + 5 if is_mibs else None

            # РЕНДЕРИНГ БЛОКА АВТО
            for col_idx in range(1, last_table_col + 1):
                copy_cell_styles(sample_hours_cells[col_idx - 1], get_safe_cell(ws, a_hours_r, col_idx))
                copy_cell_styles(sample_times_cells[col_idx - 1], get_safe_cell(ws, a_times_r, col_idx))
                if is_mibs:
                    copy_cell_styles(sample_night_cells[col_idx - 1], get_safe_cell(ws, a_night_r, col_idx))

            if a_data:
                for day, col in day_col_map.items():
                    get_safe_cell(ws, a_hours_r, col).value = to_numeric_if_possible(a_data['hours'][day])
                    get_safe_cell(ws, a_times_r, col).value = a_data['times'][day]
                    if is_mibs:
                        get_safe_cell(ws, a_night_r, col).value = to_numeric_if_possible(a_data['night'][day])

            merge_and_style_range(ws, a_hours_r, 1, a_night_r if is_mibs else a_times_r, 1,
                                  f"{doc_name} (АВТО)" if a_data else f"{doc_name} (АВТО) — Отсутствует",
                                  font_a_name, left_center_align, sample_hours_cells[0].fill,
                                  sample_hours_cells[0].border)
            merge_and_style_range(ws, a_hours_r, 2, a_night_r if is_mibs else a_times_r, 2, title,
                                  font_a_name, left_center_align, sample_hours_cells[1].fill,
                                  sample_hours_cells[1].border)

            for idx, col in enumerate(total_cols):
                orig_sample_cell = sample_hours_cells[col - 1]
                if orig_sample_cell.value and str(orig_sample_cell.value).startswith("="):
                    val = shift_formula_rows(orig_sample_cell.value, orig_hours_row, a_hours_r)
                else:
                    val = a_data['totals'][idx] if (a_data and idx < len(a_data['totals'])) else ""

                if is_mibs and col == hours_total_col:
                    # В шаблоне колонка "Часы" объединена только на строках
                    # Часы/Время, а строка "Ночные часы" — отдельная ячейка
                    # со своим значением (не часть объединённого диапазона).
                    merge_and_style_range(ws, a_hours_r, col, a_times_r, col, val,
                                          font_a_name, center_align, sample_hours_cells[col - 1].fill,
                                          sample_hours_cells[col - 1].border)

                    night_sample_cell = sample_night_cells[col - 1]
                    if night_sample_cell.value and str(night_sample_cell.value).startswith("="):
                        night_val = shift_formula_rows(night_sample_cell.value, orig_hours_row + 2, a_night_r)
                    else:
                        night_totals = a_data.get('night_totals', []) if a_data else []
                        night_val = night_totals[idx] if idx < len(night_totals) else ""

                    style_single_cell(ws, a_night_r, col, night_val, font_a_name, center_align,
                                      night_sample_cell.fill, night_sample_cell.border)
                else:
                    merge_and_style_range(ws, a_hours_r, col, a_night_r if is_mibs else a_times_r, col, val,
                                          font_a_name, center_align, sample_hours_cells[col - 1].fill,
                                          sample_hours_cells[col - 1].border)

            if norm_col_letter and h_col_letter and a_data:
                norm_range_a = f"{norm_col_letter}{a_hours_r}:{norm_col_letter}{a_hours_r}"
                rule_over_a = CellIsRule(operator='lessThan', formula=[f'${h_col_letter}${a_hours_r}'], fill=red_fill)
                rule_under_a = CellIsRule(operator='greaterThan', formula=[f'${h_col_letter}${a_hours_r}'],
                                          fill=green_fill)
                ws.conditional_formatting.add(norm_range_a, rule_over_a)
                ws.conditional_formatting.add(norm_range_a, rule_under_a)

            # РЕНДЕРИНГ БЛОКА РУЧНОЙ
            for col_idx in range(1, last_table_col + 1):
                copy_cell_styles(sample_hours_cells[col_idx - 1], get_safe_cell(ws, m_hours_r, col_idx))
                copy_cell_styles(sample_times_cells[col_idx - 1], get_safe_cell(ws, m_times_r, col_idx))
                if is_mibs:
                    copy_cell_styles(sample_night_cells[col_idx - 1], get_safe_cell(ws, m_night_r, col_idx))

            if m_data:
                for day, col in day_col_map.items():
                    get_safe_cell(ws, m_hours_r, col).value = to_numeric_if_possible(m_data['hours'][day])
                    get_safe_cell(ws, m_times_r, col).value = m_data['times'][day]
                    if is_mibs:
                        get_safe_cell(ws, m_night_r, col).value = to_numeric_if_possible(m_data['night'][day])

            merge_and_style_range(ws, m_hours_r, 1, m_night_r if is_mibs else m_times_r, 1,
                                  f"{doc_name} (РУЧНОЙ)" if m_data else f"{doc_name} (РУЧНОЙ) — Отсутствует",
                                  font_m_name, left_center_align, sample_hours_cells[0].fill,
                                  sample_hours_cells[0].border)
            merge_and_style_range(ws, m_hours_r, 2, m_night_r if is_mibs else m_times_r, 2, title,
                                  font_m_name, left_center_align, sample_hours_cells[1].fill,
                                  sample_hours_cells[1].border)

            for idx, col in enumerate(total_cols):
                orig_sample_cell = sample_hours_cells[col - 1]
                if orig_sample_cell.value and str(orig_sample_cell.value).startswith("="):
                    val = shift_formula_rows(orig_sample_cell.value, orig_hours_row, m_hours_r)
                else:
                    val = m_data['totals'][idx] if (m_data and idx < len(m_data['totals'])) else ""

                if is_mibs and col == hours_total_col:
                    merge_and_style_range(ws, m_hours_r, col, m_times_r, col, val,
                                          font_m_name, center_align, sample_hours_cells[col - 1].fill,
                                          sample_hours_cells[col - 1].border)

                    night_sample_cell = sample_night_cells[col - 1]
                    if night_sample_cell.value and str(night_sample_cell.value).startswith("="):
                        night_val = shift_formula_rows(night_sample_cell.value, orig_hours_row + 2, m_night_r)
                    else:
                        night_totals = m_data.get('night_totals', []) if m_data else []
                        night_val = night_totals[idx] if idx < len(night_totals) else ""

                    style_single_cell(ws, m_night_r, col, night_val, font_m_name, center_align,
                                      night_sample_cell.fill, night_sample_cell.border)
                else:
                    merge_and_style_range(ws, m_hours_r, col, m_night_r if is_mibs else m_times_r, col, val,
                                          font_m_name, center_align, sample_hours_cells[col - 1].fill,
                                          sample_hours_cells[col - 1].border)

            if norm_col_letter and h_col_letter and m_data:
                norm_range_m = f"{norm_col_letter}{m_hours_r}:{norm_col_letter}{m_hours_r}"
                rule_over_m = CellIsRule(operator='lessThan', formula=[f'${h_col_letter}${m_hours_r}'], fill=red_fill)
                rule_under_m = CellIsRule(operator='greaterThan', formula=[f'${h_col_letter}${m_hours_r}'],
                                          fill=green_fill)
                ws.conditional_formatting.add(norm_range_m, rule_over_m)
                ws.conditional_formatting.add(norm_range_m, rule_under_m)

            # СВЕРКА ИТОГОВ СУММ
            for col in total_cols:
                col_letter = get_column_letter(col)
                tot_coord_a = f"{col_letter}{a_hours_r}"
                tot_coord_m = f"{col_letter}{m_hours_r}"

                rule_tot_a = CellIsRule(operator='notEqual', formula=[f'${col_letter}${m_hours_r}'], fill=diff_fill)
                ws.conditional_formatting.add(f"{tot_coord_a}:{tot_coord_a}", rule_tot_a)

                rule_tot_m = CellIsRule(operator='notEqual', formula=[f'${col_letter}${a_hours_r}'], fill=diff_fill)
                ws.conditional_formatting.add(f"{tot_coord_m}:{tot_coord_m}", rule_tot_m)

                if is_mibs and col == hours_total_col:
                    # Отдельная сверка итога "Ночные часы" (своя ячейка, не мёрж)
                    tot_coord_a_n = f"{col_letter}{a_night_r}"
                    tot_coord_m_n = f"{col_letter}{m_night_r}"

                    rule_tot_a_n = CellIsRule(operator='notEqual', formula=[f'${col_letter}${m_night_r}'],
                                              fill=diff_fill)
                    ws.conditional_formatting.add(f"{tot_coord_a_n}:{tot_coord_a_n}", rule_tot_a_n)

                    rule_tot_m_n = CellIsRule(operator='notEqual', formula=[f'${col_letter}${a_night_r}'],
                                              fill=diff_fill)
                    ws.conditional_formatting.add(f"{tot_coord_m_n}:{tot_coord_m_n}", rule_tot_m_n)

            # СВЕРКА И ПОДСВЕТКА РАСХОЖДЕНИЙ ДНЕЙ (1-31)
            for day, col in day_col_map.items():
                a_h = a_data['hours'][day] if a_data else ""
                m_h = m_data['hours'][day] if m_data else ""
                a_t = a_data['times'][day] if a_data else ""
                m_t = m_data['times'][day] if m_data else ""

                if clean_hours(a_h) != clean_hours(m_h):
                    get_safe_cell(ws, a_hours_r, col).fill = diff_fill
                    get_safe_cell(ws, m_hours_r, col).fill = diff_fill
                    total_diffs_found += 1

                if clean_time(a_t) != clean_time(m_t):
                    get_safe_cell(ws, a_times_r, col).fill = diff_fill
                    get_safe_cell(ws, m_times_r, col).fill = diff_fill
                    total_diffs_found += 1

                if is_mibs:
                    a_n = a_data['night'][day] if a_data else ""
                    m_n = m_data['night'][day] if m_data else ""
                    if clean_hours(a_n) != clean_hours(m_n):
                        get_safe_cell(ws, a_night_r, col).fill = diff_fill
                        get_safe_cell(ws, m_night_r, col).fill = diff_fill
                        total_diffs_found += 1

            has_mult_auto = False
            if a_data:
                for t_val in a_data['times'].values():
                    if '/' in str(t_val) or '\\' in str(t_val):
                        has_mult_auto = True
                        break

            has_mult_manual = False
            if m_data:
                for t_val in m_data['times'].values():
                    if '/' in str(t_val) or '\\' in str(t_val):
                        has_mult_manual = True
                        break

            ws.row_dimensions[a_hours_r].height = 15
            ws.row_dimensions[a_times_r].height = 45.0 if has_mult_auto else 22.5
            if is_mibs: ws.row_dimensions[a_night_r].height = 15

            ws.row_dimensions[m_hours_r].height = 15
            ws.row_dimensions[m_times_r].height = 45.0 if has_mult_manual else 22.5
            if is_mibs: ws.row_dimensions[m_night_r].height = 15

            last_card_row = m_night_r if is_mibs else m_times_r
            for col_idx in range(1, last_table_col + 1):
                cell = ws.cell(row=last_card_row, column=col_idx)
                cell.border = Border(
                    left=cell.border.left, right=cell.border.right,
                    top=cell.border.top, bottom=Side(style='medium', color='444444')
                )

            current_row = last_card_row + 1

            ws.row_dimensions[current_row].height = 8.0
            for col_idx in range(1, last_table_col + 1):
                cell = get_safe_cell(ws, current_row, col_idx)
                cell.value = None
                cell.fill = PatternFill(fill_type=None)
                cell.border = Border()

            current_row += 1

        for f_row in footer_rows:
            ws.row_dimensions[current_row].height = f_row['height']
            for c_idx, c_data in enumerate(f_row['cells'], 1):
                cell = get_safe_cell(ws, current_row, c_idx)
                cell.value = c_data[0]
                if c_data[1]:
                    cell.font = c_data[2]
                    cell.border = c_data[3]
                    cell.fill = c_data[4]
                    cell.alignment = c_data[5]
                    cell.number_format = c_data[6]
            current_row += 1

    base_dir = os.path.dirname(auto_path)
    base_name = os.path.basename(auto_path).replace(".xlsx", "")
    output_path = os.path.join(base_dir, f"{base_name}_СРАВНЕНИЕ_СТРУКТУРНОЕ.xlsx")

    try:
        wb_report.save(output_path)

        # 1. ЧИСТЫЕ СТРОКИ ДЛЯ ДВИЖКА GUI (чтобы GUI смог распарсить число ошибок и предложить открыть файл)
        logger.info("График-сравнение успешно сгенерирован!")
        logger.info(f"Найдено расхождений в ячейках: {total_diffs_found}")

        # 2. СТРОКИ С ПРЕФИКСАМИ ДЛЯ ЦВЕТНОЙ РАЗМЕТКИ В КОНСОЛИ
        logger.info("§SEP§")
        logger.info(f"§OK§ График-сравнение успешно сгенерирован!")
        logger.info(f"§DETAIL§ Найдено расхождений в ячейках: {total_diffs_found}")
        logger.info(f"§DETAIL§ Файл: {os.path.basename(output_path)}")

        return output_path

    except Exception as e:
        logger.error(f"Сбой сохранения файла сравнения: {e}")
        return -1