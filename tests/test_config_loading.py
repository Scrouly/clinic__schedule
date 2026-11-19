"""Загрузка конфига: создание файла, миграция новых ключей, сортировка дат,
путь к файлу (в том числе переменная окружения CITYCLINIC_CONFIG для тестов),
устойчивость к испорченному файлу."""
import copy
import json
import os
import sys

import pytest

from core import config, holidays


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

def test_missing_file_gives_defaults_and_is_not_created_until_saved(cfg_path):
    loaded = config.load_config()
    assert not cfg_path.exists()
    assert loaded["hours_control"] == config.DEFAULT_CONFIG["hours_control"]
    config.save_config(loaded)
    assert _read(cfg_path) == loaded


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


def test_unsorted_dates_are_sorted(cfg_path):
    data = copy.deepcopy(config.DEFAULT_CONFIG)
    data["holidays_by"] = [[5, 9], [1, 1], [3, 8]]
    data["transfers_work_days"] = [[2026, 5, 2], [2026, 4, 25]]
    data["transfers_rest_days"] = [[2026, 6, 1], [2026, 4, 20]]
    cfg_path.write_text(json.dumps(data), encoding="utf-8")

    loaded = config.load_config()

    assert loaded["holidays_by"] == [[1, 1], [3, 8], [5, 9]]
    assert loaded["transfers_work_days"] == [[2026, 4, 25], [2026, 5, 2]]
    assert loaded["transfers_rest_days"] == [[2026, 4, 20], [2026, 6, 1]]


def test_mixed_holiday_forms_are_sorted_by_date(cfg_path):
    data = copy.deepcopy(config.DEFAULT_CONFIG)
    data["holidays_by"] = [[2026, 5, 9], [5, 9], [1, 1]]
    cfg_path.write_text(json.dumps(data), encoding="utf-8")
    assert config.load_config()["holidays_by"] == [[1, 1], [5, 9], [2026, 5, 9]]


def test_complete_sorted_file_is_not_rewritten(cfg_path):
    """Файл пользователя трогаем только когда есть что мигрировать."""
    raw = json.dumps(config.DEFAULT_CONFIG, ensure_ascii=False)  # компактный формат, не как у программы
    cfg_path.write_text(raw, encoding="utf-8")
    config.load_config()
    assert cfg_path.read_text(encoding="utf-8") == raw
    assert not os.path.exists(str(cfg_path) + ".bak")


# ── Значения по умолчанию ────────────────────────────────────────────────────

def test_default_config_has_the_official_april_2026_transfer():
    """Рабочий день с понедельника 20.04.2026 переносится на субботу 25.04.2026."""
    assert config.DEFAULT_CONFIG["transfers_work_days"] == [[2026, 4, 25]]
    assert config.DEFAULT_CONFIG["transfers_rest_days"] == [[2026, 4, 20]]


def test_radunitsa_is_dated_not_recurring():
    """Радоница плавающая: как «каждый год» 21.04 она давала бы ложный выходной в 2027 и позже."""
    holidays_by = config.DEFAULT_CONFIG["holidays_by"]
    assert [4, 21] not in holidays_by
    assert [2026, 4, 21] in holidays_by and [2027, 5, 11] in holidays_by


def test_every_default_holiday_is_a_valid_entry():
    for entry in config.DEFAULT_CONFIG["holidays_by"]:
        holidays.normalize_holiday(entry)


# ── Испорченный файл не роняет программу ─────────────────────────────────────

def test_broken_json_gives_defaults_keeps_a_backup_and_reports(cfg_path):
    cfg_path.write_text('{"hours_control": {', encoding="utf-8")        # оборванный файл
    loaded = config.load_config()
    assert loaded["hours_control"] == config.DEFAULT_CONFIG["hours_control"]
    assert (cfg_path.parent / (cfg_path.name + ".bak")).read_text(encoding="utf-8") == '{"hours_control": {'
    assert not cfg_path.exists()
    assert any("не прочитан" in w and ".bak" in w for w in config.LOAD_WARNINGS)


def test_binary_garbage_is_handled_like_broken_json(cfg_path):
    cfg_path.write_bytes(b"\xff\xfe\x00garbage\x80")
    assert config.load_config()["month_ru"] == config.DEFAULT_CONFIG["month_ru"]
    assert config.LOAD_WARNINGS


def test_json_that_is_not_a_dictionary_is_rejected(cfg_path):
    cfg_path.write_text("[1, 2, 3]", encoding="utf-8")
    assert config.load_config()["holidays_by"] == sorted(config.DEFAULT_CONFIG["holidays_by"], key=holidays.sort_key)
    assert config.LOAD_WARNINGS


def test_section_of_the_wrong_type_falls_back_to_default(cfg_path):
    cfg_path.write_text(json.dumps({"holidays_by": None, "hours_control": "x", "scoring": {"min_accept_score": -0.5}}),
                        encoding="utf-8")
    loaded = config.load_config()
    assert loaded["hours_control"] == config.DEFAULT_CONFIG["hours_control"]
    assert loaded["scoring"] == {"min_accept_score": -0.5}              # исправный раздел сохранён
    assert [4, 21] not in loaded["holidays_by"] and len(loaded["holidays_by"]) == len(config.DEFAULT_CONFIG["holidays_by"])
    assert len(config.LOAD_WARNINGS) == 2


def test_malformed_transfer_entries_are_dropped_not_fatal(cfg_path):
    data = copy.deepcopy(config.DEFAULT_CONFIG)
    data["transfers_work_days"] = [[2026, 4, 25], [4, 25], "мусор", [2026, 4, 1.5], [2026, 5, 2]]
    cfg_path.write_text(json.dumps(data), encoding="utf-8")
    loaded = config.load_config()
    assert loaded["transfers_work_days"] == [[2026, 4, 25], [2026, 5, 2]]
    assert len(config.LOAD_WARNINGS) == 3


def test_warnings_do_not_pile_up_between_loads(cfg_path):
    cfg_path.write_text("{oops", encoding="utf-8")
    config.load_config()
    assert len(config.LOAD_WARNINGS) == 1
    config.load_config()                       # файла уже нет (ушёл в .bak) — предупреждений нет
    assert config.LOAD_WARNINGS == []


def test_save_after_a_broken_file_does_not_destroy_the_backup(cfg_path):
    cfg_path.write_text("{oops", encoding="utf-8")
    loaded = config.load_config()
    config.save_config(loaded)
    assert (cfg_path.parent / (cfg_path.name + ".bak")).read_text(encoding="utf-8") == "{oops"
    assert _read(cfg_path) == loaded
