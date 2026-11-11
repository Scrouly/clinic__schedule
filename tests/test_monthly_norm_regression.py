"""Характеризационный тест: расчёт месячной нормы не должен измениться после
перехода на таблицу норм по специальностям (старый конфиг без таблицы)."""
import calendar
from decimal import Decimal, ROUND_HALF_UP
import re

import pytest

from core import utils
from core.utils import calculate_monthly_norm


def _legacy_monthly_norm(title_str, base_norm, uzd_norm, year, month):
    """Точная копия прежней реализации (эталон)."""
    title_lower = str(title_str).lower()
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
    if ("ультразвуков" in title_lower or "узд" in title_lower) and fraction == 1.0:
        W = float(uzd_norm)
    else:
        W = float(base_norm)
    holidays = set(tuple(h) for h in utils.CONFIG.get("holidays_by", []))
    _, num_days = calendar.monthrange(year, month)
    D_o, D_p = 0, 0
    for day in range(1, num_days + 1):
        if (month, day) in holidays:
            continue
        if calendar.weekday(year, month, day) < 5:
            tomorrow, tmr_month = day + 1, month
            if tomorrow > num_days:
                tomorrow, tmr_month = 1, (month + 1 if month < 12 else 1)
            if (tmr_month, tomorrow) in holidays:
                D_p += 1
            else:
                D_o += 1
    daily = Decimal(str(W)) / Decimal('5')
    calc = Decimal(str(D_o)) * daily + Decimal(str(D_p)) * (daily - Decimal('1'))
    val = calc * Decimal(str(fraction))
    return float(val.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


TITLES = [
    "Врач-терапевт (1,0 ст.)",
    "Врач-терапевт (0,5 ст.)",
    "Врач-хирург (0,75 ст.)",
    "Врач-гинеколог (0,25 ст)",
    "Врач ультразвуковой диагностики (1,0 ст.)",
    "Врач ультразвуковой диагностики (0,5 ст.)",
    "Врач УЗД (1,0 ст.)",
    "Врач УЗД (0,25 ст.)",
    "Врач-кардиолог",
    "",
]


@pytest.mark.parametrize("title", TITLES)
@pytest.mark.parametrize("month", range(1, 13))
def test_matches_legacy_without_specialty_table(clean_config, monkeypatch, title, month):
    monkeypatch.setitem(utils.CONFIG, "holidays_by", [[1, 1], [3, 8], [4, 21], [5, 1], [5, 9], [7, 3], [11, 7], [12, 25]])
    for base, uzd in [(38.5, 35.0), (40.0, 36.0)]:
        assert calculate_monthly_norm(title, base, uzd, 2026, month) == \
            _legacy_monthly_norm(title, base, uzd, 2026, month)
