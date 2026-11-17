"""Вспомогательные функции раскладки compare(): сопоставление врачей и строки блоков."""
import pytest

from core import compare_schedules as cs


def doc(name, title="врач"):
    return {'name': name, 'title': title}


def test_pair_by_name_and_title_first():
    a = [doc("Иванов И.", "терапевт")]
    m = [doc("Иванов И.", "хирург"), doc("Иванов И.", "терапевт")]
    pairs = cs._pair_doctors(a, m)
    assert pairs[0]['manual'] is m[1]            # совпала должность
    assert pairs[1] == {'name': "Иванов И.", 'auto': None, 'manual': m[0]}


def test_pair_falls_back_to_name_only():
    a, m = [doc("Петров П.", "лор")], [doc("Петров П.", "отоларинголог")]
    assert cs._pair_doctors(a, m)[0]['manual'] is m[0]


def test_each_manual_record_is_used_once():
    a = [doc("Сидоров С."), doc("Сидоров С.")]
    m = [doc("Сидоров С.")]
    pairs = cs._pair_doctors(a, m)
    assert [p['manual'] for p in pairs] == [m[0], None]
    assert len(pairs) == 2


def test_unmatched_manual_goes_to_the_end_and_missing_auto_is_none():
    a, m = [doc("А")], [doc("Б"), doc("А")]
    pairs = cs._pair_doctors(a, m)
    assert [p['name'] for p in pairs] == ["А", "Б"]
    assert pairs[1]['auto'] is None and pairs[1]['manual'] is m[0]


@pytest.mark.parametrize("is_mibs,auto,manual,last", [
    (False, (10, 11, None), (12, 13, None), 13),
    (True, (10, 11, 12), (13, 14, 15), 15),
])
def test_card_rows_layout(is_mibs, auto, manual, last):
    a, m = cs._card_rows(10, is_mibs)
    assert (a.hours, a.times, a.night) == auto
    assert (m.hours, m.times, m.night) == manual
    assert m.last == last


@pytest.mark.parametrize("data,expected", [
    (None, False),
    ({'times': {1: "9:00-12:00", 2: ""}}, False),
    ({'times': {1: "9:00-12:00/14:00-18:00"}}, True),
    ({'times': {1: "9:00-12:00\\14:00-18:00"}}, True),
])
def test_multiple_intervals_detection(data, expected):
    assert cs._has_multiple_intervals(data) is expected
