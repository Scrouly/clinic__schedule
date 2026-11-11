"""
utils.py — Инструменты, математика времени и очистка текста.
"""

import re
import calendar
from typing import List, Tuple, Optional
from decimal import Decimal, ROUND_HALF_UP

from rapidfuzz import fuzz

from .config import CONFIG, HOLIDAYS

# Регулярное выражение для поиска ФИО (например, "Иванов И.И." или "Иванов И.")
# ВАЖНО: якорь $ добавлен, но сам по себе он не решает главную проблему —
# см. is_doctor_name_row() и _HEADER_LABELS ниже.
DR_RE = re.compile(r'^[А-ЯЁA-Z][а-яёa-zА-ЯЁA-Z\-]+\s+[А-ЯЁA-Z]\.\s*([А-ЯЁA-Z]\.?)?$')

# Строки-заголовки таблицы, которые по чистой форме совпадают с шаблоном ФИО
# ("Слово + Иниц.Иниц."), например "Фамилия И.О." — визуально это ровно то же,
# что и настоящее имя "Иванов И.И.". DR_RE их не отличает, поэтому исключаем
# по содержанию явно. Сравнение регистронезависимое, без хвостовых знаков.
_HEADER_LABELS = {
    'фамилия и.о', 'фамилия', 'должность (ставка)', 'должность',
    'врачи', 'примечание', 'с графиком ознакомлен', 'с графиком ознакомлена',
}


def _normalize_label(s: str) -> str:
    """Нормализует строку для сравнения с известными заголовками: нижний
    регистр, без хвостовых пробелов/точек/двоеточий (одинаково для обеих
    сторон сравнения, иначе 'Фамилия И.О.' и 'фамилия и.о' не совпадут)."""
    return re.sub(r'[\s:.]+$', '', s.strip().lower())


def is_doctor_name_row(value) -> bool:
    """Проверяет, что значение ячейки — это реальное ФИО врача, а не строка
    заголовка таблицы, случайно совпавшая по форме с DR_RE (например,
    "Фамилия И.О."). Используйте эту функцию вместо прямого DR_RE.match()
    везде, где строка может прилететь из шапки таблицы."""
    if not value or not isinstance(value, str):
        return False
    v = value.strip()
    if not v:
        return False
    if _normalize_label(v) in _HEADER_LABELS:
        return False
    return bool(DR_RE.match(v))

# ─────────────────────────────────────────────
# Константы
# ─────────────────────────────────────────────
UNICODE_DASHES = r'[\-\u2012\u2013\u2014\u2015\u2212\uFE58\uFE63\uFF0D]'
FULL_DAY_ALIASES = {'круглосуточно', '24/7', 'весь день', 'all day'}

# 'H,MM-H,MM' → 'H:MM-H:MM'. Запятая внутри интервала — десятичный разделитель
# минут ('9,30-18,00'), а не разделитель интервалов. Заменяем её только если
# ОБЕ стороны интервала имеют форму H,MM: иначе '9-12,14-18' (два интервала:
# 9–12 и 14–18) был бы склеен неправильно.
_DECIMAL_COMMA_INTERVAL_RE = re.compile(
    r'(?<![\d:,])(\d{1,2}),(\d{2})(\s*' + UNICODE_DASHES + r'\s*)(\d{1,2}),(\d{2})(?![\d:])'
)


# ─────────────────────────────────────────────
# Нормализация одной части времени
# ─────────────────────────────────────────────
def _normalize_time_part(part: str) -> str:
    """
    Приводит одну сторону интервала к HH:MM.
    """
    part = part.strip()

    # Срезаем лишние знаки препинания по краям конкретной части времени
    # (превратит "08:30:" в чистые "08:30" до начала основных проверок)
    part = part.strip(':.,; ')

    # OCR-артефакт: буква O/o вместо цифры 0
    part = re.sub(r'[Oo]', '0', part)

    # Убираем лишние пробелы вокруг разделителей: '9 : 30' -> '9:30'
    part = re.sub(r'\s*[:\s]\s*', ':', part).strip()

    # Задвоенные разделители: '20::00', '9...30'
    part = re.sub(r'[:.]{2,}', ':', part)

    # Запятая как разделитель: '9,30' -> '9:30'
    part = re.sub(r',', ':', part)

    # Точка как разделитель: '9.30' -> '9:30'
    part = re.sub(r'\.', ':', part)

    # AM/PM
    am_pm_match = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?([AaPp][Mm])', part)
    if am_pm_match:
        h = int(am_pm_match.group(1))
        mn = int(am_pm_match.group(2) or 0)
        meridiem = am_pm_match.group(3).lower()
        if meridiem == 'am':
            h = 0 if h == 12 else h
        else:
            h = 12 if h == 12 else h + 12
        return f"{h:02d}:{mn:02d}"

    # Секунды — отбрасываем третью группу: '09:00:00' -> '09:00'
    sec_match = re.fullmatch(r'(\d{1,2}):(\d{2}):\d{2}', part)
    if sec_match:
        return f"{int(sec_match.group(1)):02d}:{int(sec_match.group(2)):02d}"

    # Только часы: '18' -> '18:00'
    if re.fullmatch(r'\d{1,2}', part):
        return f"{int(part):02d}:00"

    # Стандарт H:M
    m = re.fullmatch(r'(\d{1,2}):(\d{1,2})', part)
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"

    return part  # Не смогли нормализовать


# ─────────────────────────────────────────────
# Конвертация нормализованного времени в минуты
# ─────────────────────────────────────────────
def _to_minutes(t: str) -> Optional[int]:
    """
    '09:00' -> 540
    '24:00' -> 1440  (допустимый конец суток)
    Возвращает None если формат или значения невалидны.
    """
    m = re.fullmatch(r'(\d{1,2}):(\d{2})', t)
    if not m:
        return None
    h, mn = int(m.group(1)), int(m.group(2))

    # 24:00 — допустимый «конец суток», всё что выше — нет
    if h == 24 and mn == 0:
        return 24 * 60
    if not (0 <= h <= 23 and 0 <= mn <= 59):
        return None

    return h * 60 + mn


# ─────────────────────────────────────────────
# Парсинг одного интервала
# ─────────────────────────────────────────────
def _parse_single_interval(raw: str) -> Optional[Tuple[int, int]]:
    """
    Парсит строку 'A - B' в пару минут от полуночи.

    Дополнительно обрабатывает:
      - любые типографские дефисы (– — ‒ −)
      - несколько дефисов подряд ('09:00 -- 18:00')
      - «до»/«-»/«to» как альтернативные разделители ('с 9:00 до 18:00')
      - скобки с текстом вроде (127 каб) и мусорные знаки на концах строки
    """
    raw = raw.strip()
    if not raw:
        return None

    # 1. УДАЛЯЕМ ТЕКСТ В СКОБКАХ: вырезаем любые (...) или [...] вместе со скобками
    # '17:00-20:00 (127 каб)' превратится в '17:00-20:00 '
    raw = re.sub(r'[\(\[][^\]\)]*[\)\]]', '', raw)

    # Текстовые разделители: 'с 9:00 до 18:00', '9:00 to 18:00'
    raw = re.sub(r'\b(до|to|по)\b', '-', raw, flags=re.IGNORECASE)

    # Убираем текстовые префиксы: 'с ', 'from '
    raw = re.sub(r'^\s*(с|from)\s+', '', raw, flags=re.IGNORECASE)

    # Приводим все виды дефисов к обычному
    raw = re.sub(UNICODE_DASHES, '-', raw)

    # Схлопываем несколько дефисов в один: '09:00 -- 18:00'
    raw = re.sub(r'-{2,}', '-', raw)

    # 2. СРЕЗАЕМ МУСОР НА КОНЦАХ: убираем пробелы, двоеточия, точки, запятые и точки с запятой
    # '08:00-16:00:' превратится в '08:00-16:00'
    raw = raw.strip(':.,; ')

    # Теперь ищем ровно один дефис между двумя частями времени
    m = re.match(r'^([^-]+?)\s*-\s*([^-]+)$', raw)
    if not m:
        return None

    left  = _normalize_time_part(m.group(1))
    right = _normalize_time_part(m.group(2))

    start = _to_minutes(left)
    end   = _to_minutes(right)

    if start is None or end is None:
        return None

    # overnight: 22:00-02:00
    if end < start:
        end += 24 * 60

    # Нулевой интервал (начало == конец) — игнорируем
    if end == start:
        return None

    return (start, end)

def parse_time_intervals(time_str: str) -> List[Tuple[int, int]]:
    if not time_str:
        return []

    time_str = time_str.strip()

    if time_str.lower() in FULL_DAY_ALIASES:
        return [(0, 24 * 60)]

    # '9,30-18,00' → '9:30-18:00' (см. _DECIMAL_COMMA_INTERVAL_RE)
    time_str = _DECIMAL_COMMA_INTERVAL_RE.sub(r'\1:\2\3\4:\5', time_str)

    intervals = []
    # Добавили \\ как разделитель
    for part in re.split(r'[/,;|\\]', time_str):
        result = _parse_single_interval(part)
        if result:
            intervals.append(result)
    return intervals

def merge_intervals(intervals: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    if not intervals: return []
    intervals.sort(key=lambda x: x[0])
    merged = [intervals[0]]
    for current in intervals[1:]:
        last = merged[-1]
        if current[0] <= last[1]:
            merged[-1] = (last[0], max(last[1], current[1]))
        else:
            merged.append(current)
    return merged

def format_intervals(intervals: List[Tuple[int, int]]) -> str:
    res = []
    for start, end in intervals:
        h1, m1 = divmod(start, 60)
        h2, m2 = divmod(end, 60)
        if h2 >= 24: h2 -= 24
        res.append(f"{h1:02d}:{m1:02d}-{h2:02d}:{m2:02d}")
    return "/".join(res)

def combine_times(t1: str, t2: str) -> str:
    i1 = parse_time_intervals(str(t1)) if t1 else []
    i2 = parse_time_intervals(str(t2)) if t2 else []
    all_intervals = i1 + i2
    if not all_intervals: return t1 if t1 else (t2 if t2 else "")
    merged = merge_intervals(all_intervals)
    return format_intervals(merged)


def calculate_total_hours(time_str: str) -> float:
    """Считает суммарное количество часов во всех интервалах строки."""
    intervals = parse_time_intervals(time_str)
    if not intervals:
        return 0.0

    total_minutes = 0
    for start, end in intervals:
        total_minutes += (end - start)

    return round(total_minutes / 60.0, 2)

def month_info(s: str) -> Tuple[int, int, int]:
    parts = s.strip().split()
    month_name = parts[0].lower()
    m = CONFIG["month_ru"].get(month_name)
    if m is None:
        valid = ", ".join(CONFIG["month_ru"].keys())
        raise ValueError(
            f"Неизвестное название месяца: '{parts[0]}'. "
            f"Допустимые значения: {valid}"
        )
    try:
        y = int(parts[1]) if len(parts) > 1 else 2026
    except ValueError:
        raise ValueError("Неверный формат года. Ожидается строка вида 'апрель 2026'.")
    _, d = calendar.monthrange(y, m)
    return m, y, d

def is_holiday(day: int, month: int) -> bool:
    return (month, day) in HOLIDAYS

def yo_to_ye(s: str) -> str:
    return s.replace('ё', 'е').replace('Ё', 'Е')

def normalize_name(raw) -> Optional[str]:
    # Отклоняем None, пустые строки и float NaN (IEEE 754: NaN != NaN).
    # pandas не нужен — эти три случая покрывают всё, что приходит из Excel-ячеек.
    if raw is None:
        return None
    try:
        if raw != raw:   # float('nan') или numpy.nan
            return None
    except Exception:
        pass
    if not str(raw).strip():
        return None
    s = str(raw).replace('\n', ' ').strip()
    s = re.sub(r'\s*[\(\[].+?[\)\]]', '', s)
    s = re.sub(r',\s*.+$', '', s).strip()
    if re.match(r'^[А-ЯЁA-Z][а-яёa-zA-ZА-ЯЁ\-]+\s+[А-ЯЁA-Z]\.\s*[А-ЯЁA-Z]\.?$', s.strip()):
        return s.strip()
    parts = [p for p in s.split() if p]
    if not parts: return None
    def _initial(p: str) -> str:
        for ch in p:
            if ch.isalpha():
                return ch.upper()
        return ''
    if len(parts) >= 3:
        i1, i2 = _initial(parts[1]), _initial(parts[2])
        if i1 and i2: return f"{parts[0]} {i1}.{i2}."
        if i1: return f"{parts[0]} {i1}."
        return parts[0]
    if len(parts) == 2:
        i1 = _initial(parts[1])
        return f"{parts[0]} {i1}." if i1 else parts[0]
    return s or None

def normalize_time_legacy(shift_str: str) -> Optional[str]:
    if not shift_str or shift_str.lower() in ('nan', 'вых', ''): return None
    if not re.search(r'\d+:\d+', shift_str): return None
    if '/' in shift_str: return shift_str

    def pad(t: str) -> str:
        return ('0' + t.strip()) if len(t.strip().split(':')[0]) == 1 else t.strip()

    if '-' in shift_str:
        a, b = shift_str.split('-', 1)
        return f"{pad(a)}-{pad(b)}"
    return shift_str

def get_tags(text: str) -> set:
    if not text or not isinstance(text, str): return set()
    t = text.lower()
    tags = set()
    for role, keywords in CONFIG["title_keywords"].items():
        if re.search(r'(?<![а-яёa-z])' + re.escape(role), t):
            tags.add(role)
            continue
        for kw in keywords:
            if re.search(r'(?<![а-яёa-z])' + re.escape(kw), t):
                tags.add(role)
                break
    return tags

def string_similarity(a: str, b: str) -> float:
    return fuzz.token_sort_ratio(a.lower(), b.lower()) / 100.0


def calculate_monthly_norm(title_str: str, base_norm: float, uzd_norm: float, year: int, month: int) -> float:
    """
    Расчет нормы строго по закону: идеальная 5-дневка без учета переносов (transfers).
    """
    title_lower = str(title_str).lower()

    # 1. Извлекаем долю ставки
    match = re.search(r'\((\d+)[.,](\d+)\s*ст', title_lower)
    if not match:
        match = re.search(r'\((\d+)\s*ст', title_lower)

    if match:
        if len(match.groups()) == 2:
            fraction = float(f"{match.group(1)}.{match.group(2)}")
        else:
            fraction = float(match.group(1))
    else:
        fraction = 1.0

    # 2. Проверка на УЗИ и полную ставку
    if ("ультразвуков" in title_lower or "узд" in title_lower) and fraction == 1.0:
        W = float(uzd_norm)
    else:
        W = float(base_norm)

    # Берем ТОЛЬКО праздники, переносы для нормы не нужны!
    holidays = set(tuple(h) for h in CONFIG.get("holidays_by", []))

    _, num_days = calendar.monthrange(year, month)
    D_o, D_p = 0, 0

    # 3. Проходим по дням классической пятидневки
    for day in range(1, num_days + 1):
        current_date = (month, day)

        # Если сам день - праздник, он не рабочий
        if current_date in holidays:
            continue

        # ПН-ПТ считаются рабочими
        weekday = calendar.weekday(year, month, day)
        is_working_day = weekday < 5

        if is_working_day:
            is_pre_holiday = False

            # Завтра праздник?
            tomorrow = day + 1
            tmr_month = month
            if tomorrow > num_days:
                tomorrow = 1
                tmr_month = month + 1 if month < 12 else 1

            if (tmr_month, tomorrow) in holidays:
                is_pre_holiday = True

            if is_pre_holiday:
                D_p += 1
            else:
                D_o += 1

    # 4. СТРОГАЯ МАТЕМАТИКА через Decimal
    W_dec = Decimal(str(W))
    daily_hours = W_dec / Decimal('5')

    D_o_dec = Decimal(str(D_o))
    D_p_dec = Decimal(str(D_p))

    base_norm_calc = (D_o_dec * daily_hours) + (D_p_dec * (daily_hours - Decimal('1')))

    val = base_norm_calc * Decimal(str(fraction))
    return float(val.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

def get_openpyxl_color(hex_color: str) -> Optional[str]:
    if not hex_color or str(hex_color).upper() == "NONE": return None
    clean_hex = str(hex_color).replace('#', '').strip().upper()
    if not re.fullmatch(r'[0-9A-F]{6}|[0-9A-F]{8}', clean_hex): return None
    return 'FF' + clean_hex if len(clean_hex) == 6 else clean_hex
