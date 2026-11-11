"""Общие фикстуры: изолируем тесты от реального auto_schedule_config.json."""
import pytest

from core import utils


@pytest.fixture
def clean_config(monkeypatch):
    """Фиксированный календарь без праздников и без таблицы норм по специальностям
    (старое поведение). Реальный конфиг пользователя не затрагивается."""
    monkeypatch.setitem(utils.CONFIG, "holidays_by", [])
    monkeypatch.delitem(utils.CONFIG, "norms_by_specialty", raising=False)
    return utils.CONFIG
