"""Единый API настроек: get_config / save_config / update_config; файл не пишется при импорте."""
import copy
import json
import os
import subprocess
import sys

import pytest

from core import config


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    path = tmp_path / "auto_schedule_config.json"
    monkeypatch.setattr(config, "CONFIG_FILE", str(path))
    return path


def test_importing_core_does_not_create_the_config_file(tmp_path):
    target = tmp_path / "must_not_appear.json"
    env = {**os.environ, "CITYCLINIC_CONFIG": str(target)}
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    subprocess.run([sys.executable, "-c", "import core.config, core.utils"], cwd=root, env=env, check=True)
    assert not target.exists()


def test_load_config_has_no_side_effects_on_a_missing_file(cfg_path):
    loaded = config.load_config()
    assert not cfg_path.exists()
    assert loaded["hours_control"] == config.DEFAULT_CONFIG["hours_control"]


def test_load_config_migrates_in_memory_without_rewriting_the_file(cfg_path):
    cfg_path.write_text(json.dumps({"hours_control": {"base_norm": 40.0}}), encoding="utf-8")
    before = cfg_path.read_text(encoding="utf-8")
    loaded = config.load_config()
    assert loaded["month_ru"] == config.DEFAULT_CONFIG["month_ru"]
    assert cfg_path.read_text(encoding="utf-8") == before


def test_get_config_returns_the_shared_dict():
    assert config.get_config() is config.CONFIG


# ── save_config ──────────────────────────────────────────────────────────────

def test_first_save_creates_the_file(cfg_path, monkeypatch):
    monkeypatch.setitem(config.CONFIG, "marker", "первое-сохранение")
    config.save_config()
    assert json.loads(cfg_path.read_text(encoding="utf-8"))["marker"] == "первое-сохранение"


def test_save_config_writes_the_given_dict(cfg_path):
    config.save_config({"a": 1, "б": "кириллица"})
    assert json.loads(cfg_path.read_text(encoding="utf-8")) == {"a": 1, "б": "кириллица"}
    assert "кириллица" in cfg_path.read_text(encoding="utf-8")          # не \uXXXX


def test_save_leaves_no_temporary_files(cfg_path):
    config.save_config({"a": 1})
    assert [p.name for p in cfg_path.parent.iterdir()] == [cfg_path.name]


def test_failed_save_keeps_the_old_file_and_reports(cfg_path):
    cfg_path.write_text('{"old": true}', encoding="utf-8")
    with pytest.raises(config.ConfigSaveError):
        config.save_config({"bad": object()})                           # не сериализуется
    assert cfg_path.read_text(encoding="utf-8") == '{"old": true}'
    assert [p.name for p in cfg_path.parent.iterdir()] == [cfg_path.name]


def test_save_to_a_missing_folder_reports_a_readable_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", str(tmp_path / "нет-папки" / "c.json"))
    with pytest.raises(config.ConfigSaveError, match="нет-папки"):
        config.save_config({"a": 1})


# ── update_config / reload_config меняют словарь на месте ─────────────────────

def test_update_config_keeps_the_same_object_and_replaces_content(monkeypatch):
    shared = config.CONFIG
    snapshot = copy.deepcopy(shared)
    try:
        config.update_config({"hours_control": {"base_norm": 1.0}, "новый": 5})
        assert config.CONFIG is shared and shared == {"hours_control": {"base_norm": 1.0}, "новый": 5}
    finally:
        shared.clear()
        shared.update(snapshot)


def test_update_config_copies_values_so_the_window_does_not_edit_live_settings():
    shared, snapshot = config.CONFIG, copy.deepcopy(config.CONFIG)
    window = {"scoring": {"min_accept_score": -0.5}}
    try:
        config.update_config(window)
        window["scoring"]["min_accept_score"] = 9
        assert shared["scoring"]["min_accept_score"] == -0.5
    finally:
        shared.clear()
        shared.update(snapshot)


def test_utils_and_config_share_one_dict_after_update():
    from core import utils
    assert utils.CONFIG is config.CONFIG


def test_reload_config_does_not_replace_the_shared_dict(cfg_path):
    from core import utils
    shared = config.CONFIG
    snapshot = copy.deepcopy(shared)
    cfg_path.write_text(json.dumps({"hours_control": {"base_norm": 41.0}}), encoding="utf-8")
    try:
        config.reload_config()
        assert config.CONFIG is shared and utils.CONFIG is shared
        assert shared["hours_control"]["base_norm"] == 41.0
    finally:
        shared.clear()
        shared.update(snapshot)
