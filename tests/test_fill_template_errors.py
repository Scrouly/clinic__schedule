"""Баг №2: fill_template не должен молча возвращаться при ошибке шаблона."""
import pytest

from core import auto_schedule


def test_fill_template_raises_when_template_cannot_be_loaded(tmp_path):
    with pytest.raises(FileNotFoundError):
        auto_schedule.fill_template(
            str(tmp_path / "нет_такого.xlsx"), [], "апрель 2026", str(tmp_path / "out.xlsx")
        )
