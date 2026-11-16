"""Праздники с необязательным годом: [м, д] — каждый год, [г, м, д] — только в этом году."""
import pytest

from core import holidays, utils
from core.excel_io import _day_type
from core.utils import calculate_monthly_norm, is_holiday


@pytest.fixture
def hol(monkeypatch):
    """Подменяет список праздников в живом CONFIG."""
    def _set(entries):
        monkeypatch.setitem(utils.CONFIG, "holidays_by", entries)
    return _set


# ── разбор записей ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("entry,expected", [
    ([5, 9], (None, 5, 9)), ((5, 9), (None, 5, 9)), ([2026, 5, 9], (2026, 5, 9)),
    (["5", "9"], (None, 5, 9)), ([2, 29], (None, 2, 29)), ([2028, 2, 29], (2028, 2, 29)),
])
def test_valid_entries(entry, expected):
    assert holidays.normalize_holiday(entry) == expected


@pytest.mark.parametrize("entry", [
    [13, 1], [0, 5], [4, 31], [2, 30], [2027, 2, 29], [2026, 13, 1], [1899, 1, 1],
    [1], [2026, 5, 9, 1], "5.9", None, [None, 1], ["а", "б"], [1.5, 2],
])
def test_invalid_entries_are_rejected(entry):
    with pytest.raises(ValueError):
        holidays.normalize_holiday(entry)


def test_entry_roundtrip_keeps_the_short_form_short():
    assert holidays.to_entry((None, 5, 9)) == [5, 9]
    assert holidays.to_entry((2026, 5, 9)) == [2026, 5, 9]


def test_sort_key_orders_by_date_then_recurring_before_dated():
    items = [[5, 9], [2026, 5, 9], [1, 1], [2025, 5, 9], [2026, 1, 1]]
    assert sorted(items, key=holidays.sort_key) == [[1, 1], [2026, 1, 1], [5, 9], [2025, 5, 9], [2026, 5, 9]]


def test_sort_key_puts_broken_entries_last_without_failing():
    assert sorted([["мусор"], [1, 1], [13, 40]], key=holidays.sort_key)[0] == [1, 1]


# ── календарь ────────────────────────────────────────────────────────────────

def test_two_item_entry_means_every_year():
    cal = holidays.HolidayCalendar([[5, 9]])
    assert all(cal.contains(y, 5, 9) for y in (2024, 2026, 2031)) and not cal.contains(2026, 5, 10)


def test_three_item_entry_means_that_year_only():
    cal = holidays.HolidayCalendar([[2026, 5, 11]])
    assert cal.contains(2026, 5, 11) and not cal.contains(2027, 5, 11) and not cal.contains(2025, 5, 11)


def test_calendar_without_year_knows_only_recurring_holidays():
    cal = holidays.HolidayCalendar([[5, 9], [2026, 5, 11]])
    assert cal.contains(None, 5, 9) and not cal.contains(None, 5, 11)


def test_broken_entries_are_ignored_and_reported():
    cal = holidays.HolidayCalendar([[1, 1], [13, 5], ["мусор"]])
    assert cal.contains(2026, 1, 1) and len(cal.invalid) == 2


# ── is_holiday читает живой CONFIG ───────────────────────────────────────────

def test_is_holiday_uses_the_year(hol):
    hol([[1, 1], [2026, 5, 11]])
    assert is_holiday(1, 1, 2031) and is_holiday(11, 5, 2026) and not is_holiday(11, 5, 2027)


def test_is_holiday_without_year_matches_recurring_only(hol):
    hol([[1, 1], [2026, 5, 11]])
    assert is_holiday(1, 1) and not is_holiday(11, 5)


def test_is_holiday_sees_changes_made_in_place(hol):
    entries = [[1, 1]]
    hol(entries)
    assert not is_holiday(2, 1, 2026)
    entries.append([1, 2])
    assert is_holiday(2, 1, 2026)
    entries.remove([1, 1])
    assert not is_holiday(1, 1, 2026)


def test_no_separate_holidays_global_to_keep_in_sync():
    """Раньше utils.HOLIDAYS и CONFIG["holidays_by"] приходилось синхронизировать вручную."""
    assert not hasattr(utils, "HOLIDAYS")


# ── норма месяца и тип дня ───────────────────────────────────────────────────

def _norm(year=2026, month=4):
    return calculate_monthly_norm("Терапевт (1,0 ст.)", 38.5, 35.0, year, month, norm_rules=[])


def test_monthly_norm_dated_holiday_equals_recurring_one_in_its_year(hol):
    hol([[4, 21]])
    every_year = _norm()
    hol([[2026, 4, 21]])
    assert _norm() == every_year
    assert _norm(2027, 4) != every_year                       # в другом году этого праздника нет


def test_monthly_norm_ignores_a_holiday_of_another_year(hol):
    hol([])
    without = _norm()
    hol([[2027, 4, 21]])
    assert _norm() == without


def test_pre_holiday_day_across_the_new_year_uses_the_next_year(hol):
    """31 декабря сокращается, если 1 января СЛЕДУЮЩЕГО года — праздник."""
    hol([])
    plain = _norm(2026, 12)
    hol([[2027, 1, 1]])
    assert _norm(2026, 12) < plain                            # сокращённый предпраздничный день
    hol([[2026, 1, 1]])
    assert _norm(2026, 12) == plain                           # праздник прошлого года ни при чём


def test_day_type_respects_the_year(hol):
    hol([[2026, 4, 21]])
    assert _day_type(2026, 4, 21, [], [])[0] is True
    assert _day_type(2027, 4, 21, [], [])[0] is False


# ── разбор строк формы (страница «Праздники») ────────────────────────────────

def test_form_rows_without_a_year_become_short_entries():
    assert holidays.from_form_rows([(5, 9, ""), (1, 1, "  ")]) == [[1, 1], [5, 9]]


def test_form_rows_with_a_year_become_dated_entries_sorted_by_date():
    assert holidays.from_form_rows([(5, 11, "2026"), (5, 9, ""), (5, 9, "2025")]) == [[5, 9], [2025, 5, 9], [2026, 5, 11]]


def test_form_year_that_is_not_a_number_is_explained():
    with pytest.raises(ValueError, match=r"05\.11.*«abc».*не число"):
        holidays.from_form_rows([(11, 5, "abc")])


def test_form_rejects_feb_29_in_a_common_year_but_allows_it_in_a_leap_one():
    assert holidays.from_form_rows([(2, 29, "2028")]) == [[2028, 2, 29]]
    with pytest.raises(ValueError):
        holidays.from_form_rows([(2, 29, "2027")])
    assert holidays.from_form_rows([(2, 29, "")]) == [[2, 29]]


def test_calendar_cache_does_not_grow_without_bound():
    for i in range(30):
        holidays.calendar_for([[1, 1], [2000 + i, 5, 9]])
    assert len(holidays._cache) <= 8
