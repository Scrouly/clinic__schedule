"""Вспомогательные функции записи расписания врача."""
import dataclasses

import pytest

from core import excel_io


@pytest.mark.parametrize("time_str,expected", [
    ("09:00-17:00", None),                 # дневная смена
    ("22:00-06:00", 8),                    # целиком ночная, через полночь
    ("20:00-24:00", 2),                    # 22:00–24:00
    ("08:00-23:30", 1.5),                  # дробные часы
    ("00:00-06:00", 6),                    # ранее утро
    ("06:00-22:00", None),                 # ровно между ночами
    ("08:00-12:00/22:00-02:00", 4),        # две смены в сутках
])
def test_night_hours(time_str, expected):
    assert excel_io._night_hours(time_str) == expected


def test_night_hours_returns_an_int_for_whole_hours_and_float_otherwise():
    assert isinstance(excel_io._night_hours("22:00-06:00"), int)
    assert isinstance(excel_io._night_hours("08:00-23:30"), float)


def test_fill_context_is_immutable_and_layout_is_separate():
    ctx_fields = {f.name for f in dataclasses.fields(excel_io.FillContext)}
    layout_fields = {f.name for f in dataclasses.fields(excel_io.SheetLayout)}
    assert {"year", "month", "days_in_month", "base_norm", "uzd_norm"} <= ctx_fields
    assert layout_fields == {"get_col", "norm_col", "hours_total_col"}
    assert not ctx_fields & layout_fields
    with pytest.raises(dataclasses.FrozenInstanceError):
        excel_io.SheetLayout(lambda d: d, 1, 2).norm_col = 5
