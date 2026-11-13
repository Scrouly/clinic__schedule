"""Загрузка конфига: создание файла, миграция новых ключей, сортировка дат,
путь к файлу (в том числе переменная окружения CITYCLINIC_CONFIG для тестов)."""
import copy
import json
import os
import sys

import pytest

from core import config


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    """Подменяет путь к конфигу на временный файл (настоящий конфиг не затрагивается)."""
    path = tmp_path / "auto_schedule_config.json"
    monkeypatch.setattr(config, "CONFIG_FILE", str(path))
    return path


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ── Путь к файлу ─────────────────────────────────────────────────────────────

def test_env_variable_overrides_config_path(monkeypatch, tmp_path):
    target = tmp_path / "custom.json"
    monkeypatch.setenv("CITYCLINIC_CONFIG", str(target))
    assert config._config_file() == str(target)


def test_default_config_path_is_project_root(monkeypatch):
    monkeypatch.delenv("CITYCLINIC_CONFIG", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    root = os.path.dirname(os.path.dirname(os.path.abspath(config.__file__)))
    assert config._config_file() == os.path.join(root, "auto_schedule_config.json")


def test_frozen_build_looks_next_to_executable(monkeypatch, tmp_path):
    monkeypatch.delenv("CITYCLINIC_CONFIG", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "CityClinicSchedule.exe"))
    assert config._config_file() == os.path.join(str(tmp_path), "auto_schedule_config.json")


def test_test_session_does_not_use_the_real_config():
    """conftest.py подменяет путь до импорта core: настоящий файл тесты не читают и не пишут."""
    real = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(config.__file__))), "auto_schedule_config.json"
    )
    assert os.path.abspath(config.CONFIG_FILE) != os.path.abspath(real)


# ── Создание файла ───────────────────────────────────────────────────────────

def test_missing_file_is_created_with_defaults(cfg_path):
    loaded = config.load_config()
    assert cfg_path.exists()
    assert _read(cfg_path) == loaded
    assert loaded["hours_control"] == config.DEFAULT_CONFIG["hours_control"]


def test_returned_config_is_a_deep_copy_of_defaults(cfg_path):
    before = copy.deepcopy(config.DEFAULT_CONFIG)
    loaded = config.load_config()
    loaded["holidays_by"].append([12, 31])
    loaded["hours_control"]["base_norm"] = 1.0
    assert config.DEFAULT_CONFIG == before


# ── Миграция ─────────────────────────────────────────────────────────────────

def test_missing_keys_are_added_and_user_values_are_kept(cfg_path):
    cfg_path.write_text(
        json.dumps({"hours_control": {"highlight_diff": False, "base_norm": 40.0}}), encoding="utf-8"
    )
    loaded = config.load_config()
    assert loaded["hours_control"] == {"highlight_diff": False, "base_norm": 40.0}
    assert loaded["month_ru"] == config.DEFAULT_CONFIG["month_ru"]
    assert _read(cfg_path)["month_ru"] == config.DEFAULT_CONFIG["month_ru"]


def test_unsorted_dates_are_sorted_and_saved(cfg_path):
    data = copy.deepcopy(config.DEFAULT_CONFIG)
    data["holidays_by"] = [[5, 9], [1, 1], [3, 8]]
    data["transfers_work_days"] = [[2026, 5, 2], [2026, 4, 25]]
    data["transfers_rest_days"] = [[2026, 6, 1], [2026, 4, 20]]
    cfg_path.write_text(json.dumps(data), encoding="utf-8")

    loaded = config.load_config()

    assert loaded["holidays_by"] == [[1, 1], [3, 8], [5, 9]]
    assert loaded["transfers_work_days"] == [[2026, 4, 25], [2026, 5, 2]]
    assert loaded["transfers_rest_days"] == [[2026, 4, 20], [2026, 6, 1]]
    assert _read(cfg_path)["holidays_by"] == [[1, 1], [3, 8], [5, 9]]


def test_complete_sorted_file_is_not_rewritten(cfg_path):
    """Файл пользователя трогаем только когда есть что мигрировать."""
    raw = json.dumps(config.DEFAULT_CONFIG, ensure_ascii=False)  # компактный формат, не как у программы
    cfg_path.write_text(raw, encoding="utf-8")
    config.load_config()
    assert cfg_path.read_text(encoding="utf-8") == raw
