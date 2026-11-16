"""Праздничные дни. Запись в настройках: [месяц, день] — каждый год, [год, месяц, день] —
только в этом году (например, праздник, объявленный на один год)."""
import calendar
import logging
from typing import Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

Holiday = Tuple[Optional[int], int, int]        # (год или None, месяц, день)

MIN_YEAR, MAX_YEAR = 1900, 2200
_LEAP_YEAR = 2024                               # «каждый год»: 29 февраля допустимо


def normalize_holiday(entry) -> Holiday:
    """Приводит запись к (год | None, месяц, день). ValueError — запись некорректна."""
    if not isinstance(entry, (list, tuple)) or len(entry) not in (2, 3):
        raise ValueError(f"Праздник задаётся как [месяц, день] или [год, месяц, день]: {entry!r}")
    try:
        if any(isinstance(x, (bool, float)) for x in entry):
            raise ValueError
        nums = [int(x) for x in entry]
    except (TypeError, ValueError):
        raise ValueError(f"В записи праздника должны быть целые числа: {entry!r}") from None
    year: Optional[int] = None
    if len(nums) == 3:
        year, month, day = nums
        if not MIN_YEAR <= year <= MAX_YEAR:
            raise ValueError(f"Год праздника должен быть от {MIN_YEAR} до {MAX_YEAR}: {entry!r}")
    else:
        month, day = nums
    if not 1 <= month <= 12:
        raise ValueError(f"Месяц праздника должен быть от 1 до 12: {entry!r}")
    if not 1 <= day <= calendar.monthrange(year or _LEAP_YEAR, month)[1]:
        raise ValueError(f"В этом месяце нет такого дня: {entry!r}")
    return year, month, day


def to_entry(holiday: Holiday) -> list:
    """Запись для файла настроек: короткая форма остаётся короткой."""
    year, month, day = holiday
    return [month, day] if year is None else [year, month, day]


def sort_key(entry):
    """По дате в году; при равенстве «каждый год» идёт раньше записей с годом.
    Некорректные записи — в конец (их не теряем и не падаем на них)."""
    try:
        year, month, day = normalize_holiday(entry)
    except ValueError:
        return 13, 0, 0
    return month, day, year or 0


def from_form_rows(rows: Iterable[Tuple[int, int, str]]) -> List[list]:
    """Строки формы (месяц, день, текст года) → записи для настроек, по порядку дат.
    Пустой год — «каждый год». ValueError с понятным текстом, если год указан неверно."""
    result = []
    for month, day, year_text in rows:
        year_text = year_text.strip()
        if not year_text:
            result.append(to_entry(normalize_holiday([month, day])))
            continue
        try:
            year = int(year_text)
        except ValueError:
            raise ValueError(
                f"Праздник {day:02d}.{month:02d}: год «{year_text}» — не число. "
                "Укажите год, например 2026, или оставьте поле пустым (каждый год)."
            ) from None
        result.append(to_entry(normalize_holiday([year, month, day])))
    return sorted(result, key=sort_key)


class HolidayCalendar:
    def __init__(self, entries: Iterable):
        self._every_year = set()
        self._dated = set()
        self.invalid: List = []
        for entry in entries:
            try:
                year, month, day = normalize_holiday(entry)
            except ValueError:
                self.invalid.append(entry)
                continue
            if year is None:
                self._every_year.add((month, day))
            else:
                self._dated.add((year, month, day))

    def contains(self, year: Optional[int], month: int, day: int) -> bool:
        """year=None — учитываются только праздники «каждый год»."""
        return (month, day) in self._every_year or (year is not None and (year, month, day) in self._dated)


_cache: dict = {}


def calendar_for(entries) -> HolidayCalendar:
    """Календарь по списку из настроек. Кэшируется по содержимому: правка списка на месте
    (GUI, тесты) учитывается сразу, а повторные вызовы — тысячи за генерацию — дёшевы."""
    entries = list(entries)
    key = repr(entries)
    cal = _cache.get(key)
    if cal is None:
        cal = HolidayCalendar(entries)
        if cal.invalid:
            logger.warning(f"Некорректные праздники в настройках (пропущены): {cal.invalid}")
        if len(_cache) >= 8:
            _cache.clear()
        _cache[key] = cal
    return cal
