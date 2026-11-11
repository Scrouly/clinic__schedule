"""
excel_io.py — Чтение источника и запись в шаблон.
Изолирует работу с pandas и openpyxl от бизнес-логики.
100% СОВМЕСТИМОСТЬ С WPS OFFICE И MS EXCEL ЗА СЧЕТ ЗЕРКАЛЬНОЙ ЛОГИКИ СРАВНЕНИЯ.
"""

import calendar
import logging
import re
from typing import List, Optional

import pandas as pd
from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import PatternFill, Alignment
from openpyxl.utils import get_column_letter
from pydantic import ValidationError

from .config import CONFIG
from .models import DoctorRecord, Shift
from .utils import (combine_times, calculate_total_hours, normalize_time_legacy, yo_to_ye, calculate_monthly_norm,
                    is_holiday, normalize_name)

logger = logging.getLogger(__name__)


def load_excel_with_merges(file_path: str, sheet_name: str) -> pd.DataFrame:
    df = pd.read_excel(file_path, sheet_name=sheet_name, header=None, dtype=object)
    wb = load_workbook(file_path, data_only=True)
    ws = wb[sheet_name]

    for merged_cell in ws.merged_cells.ranges:
        min_col, min_row, max_col, max_row = merged_cell.bounds
        start_row, end_row = min_row - 1, max_row
        start_col, end_col = min_col - 1, max_col

        if start_row < len(df) and start_col < len(df.columns):
            end_row = min(end_row, len(df))
            end_col = min(end_col, len(df.columns))
            top_left_value = df.iloc[start_row, start_col]
            df.iloc[start_row:end_row, start_col:end_col] = top_left_value

    wb.close()
    return df


def _detect_source_rows(df: pd.DataFrame) -> dict:
    LABEL_KEYS = {'отделение': 'department', 'кабинет': 'cabinet', 'специалист': 'specialist', 'дата': 'header', }
    found = {}
    for i in range(min(20, len(df))):
        cell = df.iloc[i, 0]
        if pd.isna(cell): continue
        label = str(cell).strip().lower()
        for key, role in LABEL_KEYS.items():
            if label == key:
                found[role] = i
                break
    return found


def parse_source(source_file: str, month_sheet: str, progress_cb=None) -> List[DoctorRecord]:
    def _prog(v):
        if progress_cb: progress_cb(v)

    try:
        _prog(0.05)
        df = load_excel_with_merges(source_file, month_sheet)
        _prog(0.20)
    except Exception as e:
        logger.error(f"Ошибка загрузки листа '{month_sheet}': {e}")
        raise

    struct = _detect_source_rows(df)
    required = ['cabinet', 'specialist', 'header']
    missing = [k for k in required if k not in struct]
    if missing:
        # Показываем подписи строк так, как они выглядят в Excel, а не внутренние ключи.
        row_labels = {'cabinet': 'Кабинет', 'specialist': 'Специалист', 'header': 'Дата'}
        names = ", ".join(f"«{row_labels[k]}»" for k in missing)
        raise ValueError(
            f"Лист '{month_sheet}': в первом столбце не найдены строки {names}. "
            f"Возможно, лист этого месяца ещё не заполнен — проверьте выбранный месяц и год."
        )

    dept_idx = struct.get('department')
    cab_idx = struct['cabinet']
    name_idx = struct['specialist']
    hdr_idx = struct['header']
    data_start_idx = hdr_idx + 1

    department_row = df.iloc[dept_idx] if dept_idx is not None else pd.Series([pd.NA] * len(df.columns), dtype=object)
    cabinet_row = df.iloc[cab_idx]
    header_row = df.iloc[hdr_idx]

    name_row_raw = df.iloc[name_idx].replace(r'^\s*$', pd.NA, regex=True)
    name_row = name_row_raw.copy()
    for ci in range(3, len(name_row)):
        if pd.isna(name_row_raw.iloc[ci]):
            hdr_val = str(header_row.iloc[ci]).lower().strip() if pd.notna(header_row.iloc[ci]) else ''
            if any(k in hdr_val for k in ['смен', 'опер', 'прием', 'приём', 'час']):
                prev = name_row.iloc[ci - 1]
                if pd.notna(prev):
                    name_row.iloc[ci] = prev

    doctors_map = {}
    current_block_id = 0
    prev_raw_val = None

    for ci in range(2, len(name_row)):
        val = name_row.iloc[ci]
        if pd.isna(val):
            prev_raw_val = None
            continue

        s = str(val).strip()
        if not s or 'итого' in s.lower():
            prev_raw_val = None
            continue

        name = normalize_name(s)
        if not name:
            prev_raw_val = None
            continue

        if val != prev_raw_val:
            current_block_id += 1
            prev_raw_val = val

        raw_str = str(val).replace('\n', ' ').strip()
        hint_m = re.search(r'[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(.*)$', raw_str)
        spec_hint = hint_m.group(1).strip() if hint_m else ""

        cabinet = str(cabinet_row.iloc[ci]).strip() if pd.notna(cabinet_row.iloc[ci]) and str(
            cabinet_row.iloc[ci]).strip().lower() != 'кабинет' else ''
        direction = str(department_row.iloc[ci]).strip() if pd.notna(department_row.iloc[ci]) and str(
            department_row.iloc[ci]).strip().lower() not in ('отделение', 'направление') else ''

        doc_key = (direction, cabinet, name, spec_hint, current_block_id)
        if doc_key not in doctors_map:
            doctors_map[doc_key] = {'time_cols': [], 'hours_cols': []}

        own_hdr = str(header_row.iloc[ci]).lower().strip() if pd.notna(header_row.iloc[ci]) else ''

        if any(k in own_hdr for k in ['смен', 'опер', 'прием', 'приём']):
            doctors_map[doc_key]['time_cols'].append(ci)
        elif 'час' in own_hdr:
            doctors_map[doc_key]['hours_cols'].append(ci)
        else:
            if len(doctors_map[doc_key]['time_cols']) == len(doctors_map[doc_key]['hours_cols']):
                doctors_map[doc_key]['time_cols'].append(ci)
            else:
                doctors_map[doc_key]['hours_cols'].append(ci)

    DEPT_TYPO_MAP = {'хиругическое': 'Хирургическое', 'хирургическое': 'Хирургическое',
                     'гинекологическое': 'Гинекологическое', 'консультативное': 'Консультативное',
                     'диагностическое': 'Диагностическое', 'мибс': 'МИБС'}

    records: List[DoctorRecord] = []
    for (direction, cabinet, name, spec_hint, block_id), cols in doctors_map.items():
        direction = DEPT_TYPO_MAP.get(direction.lower().strip(), direction)

        if not cols['time_cols'] and not cols['hours_cols']:
            continue

        sched = {}
        for day in range(1, 32):
            ri = data_start_idx + (day - 1)
            if ri >= len(df): break

            hours_val = 0.0
            for h_col in cols['hours_cols']:
                if h_col < df.shape[1]:
                    try:
                        hours_str = str(df.iloc[ri, h_col]).replace(',', '.').strip()
                        hours_val += float(hours_str) if hours_str and hours_str.lower() != 'nan' else 0.0
                    except ValueError:
                        pass

            daily_times = []
            for t_col in cols['time_cols']:
                if t_col < df.shape[1]:
                    t_str = str(df.iloc[ri, t_col]).strip()
                    if t_str and t_str.lower() not in ['nan', '0', '-', '']:
                        daily_times.append(t_str)

            if not daily_times and hours_val == 0.0: continue

            combined_time = ""
            for t_str in daily_times:
                combined_time = t_str if not combined_time else combine_times(combined_time, t_str)

            try:
                sched[day] = Shift(time=combined_time, hours=hours_val)
            except ValidationError:
                sched[day] = Shift(time=combined_time, hours=0.0)

        records.append(DoctorRecord(name=yo_to_ye(name), direction=direction, cabinet=cabinet, spec_hint=spec_hint,
                                    schedule=sched))

    _prog(0.30)
    return records


# ── Вспомогательные функции для write_sheet_data ─────────────────────────────

def _update_sheet_headers(wb, month_str: str) -> None:
    """Обновляет строки «ГРАФИК РАБОТЫ НА …» и «на … года» на всех листах."""
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        for row_idx in range(1, 8):
            for col_idx in range(1, 4):
                cell = ws.cell(row=row_idx, column=col_idx)
                if not isinstance(cell.value, str):
                    continue
                val = cell.value
                if "ГРАФИК РАБОТЫ" in val.upper() and "НА " in val.upper():
                    cell.value = re.sub(r'(?i)(НА\s+)[А-ЯЁа-яё]+\s+\d{4}(\s*Г\.?)?', f'\\g<1>{month_str.upper()} г.',
                                        val, )
                elif "ОЗНАКОМЛЕНИ" in val.upper() or "ПРИЛОЖЕНИЕ" in val.upper():
                    cell.value = re.sub(r'(?i)(на\s+)[А-ЯЁа-яё]+\s+\d{4}(\s*года?)?', f'на {month_str.lower()} года',
                                        val, )


def _find_norm_col(ws, sheet_name: str) -> int:
    """Ищет столбец «Расчетная норма» в строках 1–15. При неудаче — фолбэк на 34."""
    for row_idx in range(1, 16):
        for cell in ws[row_idx]:
            if cell.value and "Расчетная норма" in str(cell.value):
                return cell.column
    logger.warning(f"§WARN§ Лист «{sheet_name}»: заголовок «Расчетная норма» не найден "
                   f"в строках 1–15. Используется столбец 34 по умолчанию. Проверьте шаблон.")
    return 34


def get_daily_hours_norm(title: str) -> Optional[float]:
    """Определяет БАЗОВУЮ норму часов в день для врача по его специальности
    (норма, соответствующая ставке 1,0). Ставка здесь не учитывается —
    это делает отдельно get_rate_from_title(); итоговая формула подсветки
    (недоработка / переработка) строится в _fill_doctor_role в зависимости от ставки.

    Специальности с нормой:
    - УЗД: 5,6 часа/день
    - ОЛО (ЛОР): 6,16 часа/день
    - Гинеколог: 6,16 часа/день
    - Хирург: 6,16 часа/день
    - Травматолог-ортопед: 6,16 часа/день

    Возвращает None, если специальность не в списке выше.
    """
    if not title or not isinstance(title, str):
        return None

    title_lower = title.lower()

    if any(kw in title_lower for kw in ['узи', 'ультразвуков']):
        return 5.6
    elif any(kw in title_lower for kw in ['лор', 'оториноларинголог']):
        return 6.16
    elif any(kw in title_lower for kw in ['гинеколог', 'гинекология']):
        return 6.16
    elif 'хирург' in title_lower:
        return 6.16
    elif any(kw in title_lower for kw in ['ортопед', 'травматолог']):
        return 6.16

    return None


def get_rate_from_title(title: str) -> Optional[str]:
    """Определяет ставку врача по тексту должности: '1.0', '0.75', '0.5', '0.25'.
    Возвращает None, если ставка не распознана (в этом случае подсветка нормы
    часов не применяется вовсе — не с чем сравнивать порог)."""
    if not title or not isinstance(title, str):
        return None

    if '1,0' in title or '1.0' in title:
        return '1.0'
    if '0,75' in title or '0.75' in title:
        return '0.75'
    if '0,5' in title or '0.5' in title:
        return '0.5'
    if '0,25' in title or '0.25' in title:
        return '0.25'
    return None


def _find_hours_total_col(ws, day_row_num: int) -> int:
    """Динамически находит столбец общего количества фактически отработанных часов."""
    for col in range(1, ws.max_column + 1):
        # Сканируем три смежные строки заголовков (например, 7, 8 и 9)
        for delta in range(3):
            val = str(ws.cell(row=day_row_num + delta, column=col).value or "").lower()
            if "час" in val:  # покрывает «часы», «часов», «час»
                if "норма" not in val:
                    return col
    return 36  # Безопасный фолбэк


def _day_type(year_num: int, month_num: int, day: int, transfers_work: list, transfers_rest: list):
    """Возвращает (is_hol, is_weekend) для конкретного дня с учётом переносов."""
    is_hol = is_holiday(day, month_num)
    is_weekend = (calendar.weekday(year_num, month_num, day) >= 5 or [year_num, month_num,
                                                                      day] in transfers_rest) and not is_hol
    if [year_num, month_num, day] in transfers_work:
        is_hol = is_weekend = False
    return is_hol, is_weekend


def _paint_day_header(ws, day_row_num: int, days_in_month: int, get_col, year_num: int, month_num: int,
                      transfers_work: list, transfers_rest: list, pink_fill, gray_fill) -> None:
    from openpyxl.styles import Alignment
    header_alignment = Alignment(horizontal='center', vertical='center')

    for day in range(1, 32):
        col = get_col(day)
        if not col:
            continue

        cell = ws.cell(row=day_row_num, column=col)

        if day <= days_in_month:
            cell.value = day
            cell.alignment = header_alignment

            is_hol, is_weekend = _day_type(year_num, month_num, day, transfers_work, transfers_rest)
            if is_hol:
                cell.fill = pink_fill
            elif is_weekend:
                cell.fill = gray_fill
        else:
            cell.value = None


# ─── ИЗМЕНЕНИЕ В excel_io.py ───────────────────────────────────────────────

def _fill_doctor_role(ws, role: dict, has_records: bool, days_in_month: int, get_col, year_num: int, month_num: int,
                      transfers_work: list, transfers_rest: list, pink_fill, gray_fill, clear_fill, mismatch_fill,
                      light_gray_fill, fit_alignment, norm_col: int, hours_total_col: int, base_norm: float,
                      uzd_norm: float, highlight_enabled: bool, red_fill, green_fill) -> None:
    """Записывает расписание одного врача, включая ночные часы, и накладывает стили."""
    sched = role['assigned_schedule']
    data_r = role['data_r']
    time_r = role['time_r']
    night_r = role.get('night_r')  # Извлекаем строку ночных часов для МИБС
    title = role.get('title', '')
    norm_name = role.get('norm_name', '')

    total_hours = 0.0
    has_time_written = False
    row_has_multiple_shifts = False

    for day in range(1, days_in_month + 1):
        col = get_col(day)
        if col is None:
            continue

        dc = ws.cell(row=data_r, column=col)
        tc = ws.cell(row=time_r, column=col)
        nc = ws.cell(row=night_r, column=col) if night_r else None

        is_hol, is_weekend = _day_type(year_num, month_num, day, transfers_work, transfers_rest)

        current_fill = pink_fill if is_hol else (gray_fill if is_weekend else clear_fill)
        dc.fill = tc.fill = current_fill
        dc.alignment = tc.alignment = fit_alignment

        if nc:
            nc.fill = current_fill
            nc.alignment = fit_alignment

        if has_records:
            add = sched.get(day, Shift())
            special = CONFIG["special_codes"].get((add.time or "").lower())

            if add.hours > 0:
                dc.value = add.hours
                time_str = normalize_time_legacy(add.time) if add.time else None
                tc.value = time_str
                total_hours += add.hours

                if tc.value and str(tc.value).strip():
                    has_time_written = True
                    if '/' in str(time_str) or '\\' in str(time_str):
                        row_has_multiple_shifts = True

                # ─── АВТОМАТИЧЕСКИЙ ПОДЧЕТ НОЧНЫХ ЧАСОВ (22:00 - 06:00) ───
                if nc and time_str:
                    from .utils import parse_time_intervals
                    intervals = parse_time_intervals(str(time_str))
                    total_night_minutes = 0

                    night_ranges = [(0, 360),  # 00:00 - 06:00
                        (1320, 1440),  # 22:00 - 24:00
                        (1440, 1800)  # 24:00 - 30:00 (для переходящих смен)
                    ]

                    for start, end in intervals:
                        for n_start, n_end in night_ranges:
                            overlap_start = max(start, n_start)
                            overlap_end = min(end, n_end)
                            if overlap_start < overlap_end:
                                total_night_minutes += (overlap_end - overlap_start)

                    if total_night_minutes > 0:
                        night_hours = total_night_minutes / 60.0
                        nc.value = int(night_hours) if night_hours.is_integer() else night_hours
                    else:
                        nc.value = None
                elif nc:
                    nc.value = None

                if time_str:
                    calc_h = calculate_total_hours(str(time_str))
                    if abs(calc_h - add.hours) > 0.04:
                        dc.fill = mismatch_fill
                        diff = round(calc_h - add.hours, 2)
                        logger.warning(f"§WARN§ Расхождение ч/время — {norm_name}, "
                                       f"день {day:02d}: в графике {add.hours} ч., "
                                       f"по времени ({time_str}) = {calc_h} ч. "
                                       f"(разница {diff:+.2f} ч.)")
                        dc.comment = Comment(f"Расхождение!\nВ графике: {add.hours} ч.\n"
                                             f"По времени ({time_str}): {calc_h} ч.\n"
                                             f"Разница: {diff:+.2f} ч.", "Система", )
                        dc.comment.width = 240
                        dc.comment.height = 80
            elif special and special != 'В':
                dc.value, tc.value = special, None
                if nc: nc.value = None
            else:
                dc.value, tc.value = ('П' if is_hol else 'В'), None
                if nc: nc.value = None
        else:
            dc.value = tc.value = None
            if nc: nc.value = None

    if has_time_written:
        if row_has_multiple_shifts:
            ws.row_dimensions[time_r].height = 45.0
        else:
            ws.row_dimensions[time_r].height = 22.5

    light_gray = PatternFill(start_color="FFD9D9D9", end_color="FFD9D9D9", fill_type="solid")
    for day in range(days_in_month + 1, 32):
        col = get_col(day)
        if col:
            ws.cell(row=data_r, column=col).fill = light_gray
            ws.cell(row=time_r, column=col).fill = light_gray
            ws.cell(row=data_r, column=col).value = None
            ws.cell(row=time_r, column=col).value = None
            if night_r:
                ws.cell(row=night_r, column=col).fill = light_gray
                ws.cell(row=night_r, column=col).value = None

    calculated_norm = calculate_monthly_norm(title, base_norm, uzd_norm, year_num, month_num)
    cell_norm = ws.cell(row=data_r, column=norm_col)
    cell_norm.value = calculated_norm

    # ─── ИСПРАВЛЕННЫЙ БЛОК УСЛОВНОГО ФОРМАТИРОВАНИЯ (ДОБАВЛЕН ЗНАК "=") ───
    if highlight_enabled:
        norm_col_letter = get_column_letter(norm_col)
        h_col_letter = get_column_letter(hours_total_col) if hours_total_col else None

        if norm_col_letter and h_col_letter:
            norm_range = f"{norm_col_letter}{data_r}:{norm_col_letter}{data_r}"

            # Знак "=" НЕ нужен в формулах CellIsRule для WPS! Только ссылка на ячейку
            rule_over = CellIsRule(operator='lessThan', formula=[f'${h_col_letter}${data_r}'], fill=red_fill)
            rule_under = CellIsRule(operator='greaterThan', formula=[f'${h_col_letter}${data_r}'], fill=green_fill)

            ws.conditional_formatting.add(norm_range, rule_over)
            ws.conditional_formatting.add(norm_range, rule_under)

    # ─── УСЛОВНОЕ ФОРМАТИРОВАНИЕ ДЛЯ ЧАСОВ (ОРАНЖЕВОЕ) ───
    # Не зависит от highlight_enabled — работает всегда, если для должности задана дневная норма
    # и распознана ставка.
    #
    # Ставка 1,0  → подсвечиваем НЕДОРАБОТКУ: часы < норма (как раньше).
    # Ставка 0,25 / 0,5 / 0,75 → логика другая: используем ту же норму (как для 1,0),
    # но подсвечиваем ПЕРЕРАБОТКУ — случай, когда врач на неполной ставке фактически
    # отработал почти как на полной. Порог — (норма - 0.1), подсветка при hours > порог.
    daily_norm = get_daily_hours_norm(title)
    rate = get_rate_from_title(title)
    if daily_norm and rate and data_r and time_r:
        from openpyxl.formatting.rule import FormulaRule

        hours_col_start = 3
        hours_col_end = min(33, hours_col_start + days_in_month - 1)
        hours_range_start = get_column_letter(hours_col_start)
        hours_range_end = get_column_letter(hours_col_end)

        # Целевой диапазон заливки — строка времени (time_r)
        time_range = f"{hours_range_start}{time_r}:{hours_range_end}{time_r}"

        orange_hex = "FFA500"
        orange_fill = PatternFill(start_color=orange_hex, end_color=orange_hex, fill_type="solid")

        # ISNUMBER отсекает текст (В, П, О, Б) и предотвращает ошибки при парсинге пустых ячеек.
        if rate == '1.0':
            formula = f'AND(ISNUMBER({hours_range_start}${data_r}), {hours_range_start}${data_r}<{daily_norm})'
        else:
            threshold = round(daily_norm - 0.1, 2)
            formula = f'AND(ISNUMBER({hours_range_start}${data_r}), {hours_range_start}${data_r}>{threshold})'

        rule_hours_low = FormulaRule(formula=[formula], fill=orange_fill)
        ws.conditional_formatting.add(time_range, rule_hours_low)


# ── Оркестратор ───────────────────────────────────────────────────────────────

def write_sheet_data(wb, sheets, sheet_configs, template_docs, doctor_found_map, month_num, year_num, days_in_month,
                     pink_fill, gray_fill, clear_fill, month_str=""):
    """Физическая запись готовых данных обратно на листы Excel."""

    if month_str:
        _update_sheet_headers(wb, month_str)

    hours_ctrl = CONFIG.get("hours_control", {})
    highlight_enabled = hours_ctrl.get("highlight_diff", True)
    base_norm = hours_ctrl.get("base_norm", 38.5)
    uzd_norm = hours_ctrl.get("uzd_norm", 35.0)

    red_hex = CONFIG.get("excel_colors", {}).get("overwork_red", "FFC7CE").replace("#", "")
    green_hex = CONFIG.get("excel_colors", {}).get("underwork_green", "C6EFCE").replace("#", "")
    red_fill = PatternFill(start_color=red_hex, end_color=red_hex, fill_type="solid")
    green_fill = PatternFill(start_color=green_hex, end_color=green_hex, fill_type="solid")
    mismatch_fill = PatternFill(start_color="FFFF0000", end_color="FFFF0000", fill_type="solid")
    light_gray_fill = PatternFill(start_color="FFD9D9D9", end_color="FFD9D9D9", fill_type="solid")

    transfers_work = CONFIG.get("transfers_work_days", [])
    transfers_rest = CONFIG.get("transfers_rest_days", [])
    fit_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

    for sheet_name in sheets:
        ws = wb[sheet_name]

        # Безопасный сброс старых правил шаблона через встроенный __init__
        ws.conditional_formatting.__init__()

        config = sheet_configs.get(sheet_name)
        if not config:
            continue

        day_row_num = config['day_row_num']
        day_col_map = config['day_col_map']

        def get_col(d, _map=day_col_map):
            if d in _map: return _map[d]
            if 1 in _map: return _map[1] + (d - 1)
            return None

        norm_col = _find_norm_col(ws, sheet_name)

        # Находим hours_total_col точно так же, как в рабочем файле сравнения
        hours_total_col = _find_hours_total_col(ws, day_row_num)

        _paint_day_header(ws, day_row_num, days_in_month, get_col, year_num, month_num, transfers_work, transfers_rest,
                          pink_fill, gray_fill, )

        for norm_name, roles in template_docs.items():
            has_records = doctor_found_map.get(norm_name, False)
            for role in roles:
                if role['sheet'] != sheet_name:
                    continue
                role['norm_name'] = norm_name
                _fill_doctor_role(ws, role, has_records, days_in_month, get_col, year_num, month_num, transfers_work,
                                  transfers_rest, pink_fill, gray_fill, clear_fill, mismatch_fill, light_gray_fill,
                                  fit_alignment, norm_col, hours_total_col, base_norm, uzd_norm, highlight_enabled,
                                  red_fill, green_fill)