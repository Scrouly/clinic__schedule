"""Общие фикстуры: изолируем тесты от реального auto_schedule_config.json."""
import atexit
import os
import shutil
import tempfile

# ВАЖНО: путь к конфигу подменяется ДО первого импорта core — core.config читает и
# (при отсутствии файла) создаёт его прямо при импорте. Так тесты работают на
# значениях по умолчанию (DEFAULT_CONFIG), а не на настройках конкретного компьютера.
_CFG_DIR = tempfile.mkdtemp(prefix="cityclinic-tests-")
atexit.register(shutil.rmtree, _CFG_DIR, ignore_errors=True)
os.environ["CITYCLINIC_CONFIG"] = os.path.join(_CFG_DIR, "auto_schedule_config.json")

import pytest  # noqa: E402

from core import utils  # noqa: E402


@pytest.fixture
def clean_config(monkeypatch):
    """Фиксированный календарь без праздников и без таблицы норм по специальностям
    (старое поведение). Реальный конфиг пользователя не затрагивается."""
    monkeypatch.setitem(utils.CONFIG, "holidays_by", [])
    monkeypatch.delitem(utils.CONFIG, "norms_by_specialty", raising=False)
    return utils.CONFIG


@pytest.fixture
def april_2026(monkeypatch):
    """Полностью заданный календарь и настройки для сквозных тестов и «золотых» дампов.

    Не зависит от DEFAULT_CONFIG: правка значений по умолчанию не должна молча менять
    эталоны. Апрель 2026: праздник вторник 21.04 (Радоница), перенос 25.04 (сб) —
    рабочий, 20.04 (пн) — выходной. HOLIDAYS в core.utils подменяется отдельно: is_holiday()
    читает его, а не CONFIG (поэтому GUI тоже патчит оба объекта)."""
    cfg = utils.CONFIG
    monkeypatch.setitem(cfg, "holidays_by", [[1, 1], [3, 8], [4, 21], [5, 1], [5, 9]])
    monkeypatch.setitem(cfg, "transfers_work_days", [[2026, 4, 25]])
    monkeypatch.setitem(cfg, "transfers_rest_days", [[2026, 4, 20]])
    monkeypatch.setitem(cfg, "hours_control", {"highlight_diff": True, "base_norm": 38.5, "uzd_norm": 35.0})
    monkeypatch.setitem(cfg, "excel_colors", {"holiday": "#FFB6C1", "weekend": "#CAFFCA",
                                              "overwork_red": "FFC7CE", "underwork_green": "C6EFCE"})
    monkeypatch.delitem(cfg, "norms_by_specialty", raising=False)
    monkeypatch.setattr(utils, "HOLIDAYS", {(m, d) for m, d in cfg["holidays_by"]})
    return cfg
