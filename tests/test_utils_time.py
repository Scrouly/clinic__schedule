"""Регрессионные тесты разбора времени (баг №5: запятая как разделитель)."""
from core.utils import parse_time_intervals, calculate_total_hours, combine_times


def test_comma_as_decimal_separator_in_single_interval():
    # '9,30-18,00' — это ОДИН интервал 09:30–18:00, а не три куска
    assert parse_time_intervals("9,30-18,00") == [(9 * 60 + 30, 18 * 60)]


def test_comma_as_decimal_separator_total_hours():
    assert calculate_total_hours("9,30-18,00") == 8.5


def test_comma_between_two_intervals_still_splits():
    # '09:00-12:00, 14:00-18:00' — запятая с пробелом между интервалами
    assert parse_time_intervals("09:00-12:00, 14:00-18:00") == [(540, 720), (840, 1080)]


def test_comma_between_intervals_without_space():
    assert parse_time_intervals("09:00-12:00,14:00-18:00") == [(540, 720), (840, 1080)]


def test_slash_separator_unchanged():
    assert parse_time_intervals("09:00-12:00/14:00-18:00") == [(540, 720), (840, 1080)]


def test_combine_times_merges_adjacent():
    assert combine_times("09:00-12:00", "12:00-15:00") == "09:00-15:00"


def test_bare_hours_split_by_comma_are_not_decimal():
    # '9-12,14-18' — два интервала (9–12 и 14–18), запятая НЕ десятичная
    assert parse_time_intervals("9-12,14-18") == [(540, 720), (840, 1080)]
