"""Исправления пакета 2 (меняют поведение): у каждого есть тест, который падает на прежнем коде."""
import os

import pytest

from core import cfgdiff, norms, outfile, utils
from core.excel_io import get_daily_hours_norm, get_rate_from_title
from core.utils import calculate_monthly_norm, same_surname_other_gender


# ── «лор» только как отдельное слово ─────────────────────────────────────────

@pytest.mark.parametrize("title", ["Врач-ЛОР (1,0 ст.)", "Врач-оториноларинголог (1,0 ст.)", "ЛОР-врач (0,5 ст.)"])
def test_ent_doctor_has_the_ent_daily_norm(title):
    assert get_daily_hours_norm(title) == 6.16


def test_lor_inside_another_word_is_not_an_ent_doctor():
    """«колоректальный» содержит «лор» внутри слова."""
    assert get_daily_hours_norm("Врач-колоректальный онколог (1,0 ст.)") is None


# ── одна функция разбора ставки ──────────────────────────────────────────────

@pytest.mark.parametrize("title,expected", [
    ("Врач-терапевт (1,0 ст.)", 1.0), ("Врач (0,75 ст.)", 0.75), ("Врач (1 ст.)", 1.0),
    ("Врач (1,25 ст.)", 1.25), ("Врач 0,5 ст", 0.5), ("Хирург 0,5", 0.5), ("Врач", None), ("", None),
])
def test_rate_fraction(title, expected):
    assert norms.rate_from_title(title) == expected


def test_monthly_norm_and_highlight_agree_on_a_rate_without_brackets(clean_config):
    """Раньше подсветка читала «0,5» где угодно в тексте, а норма — только «(0,5 ст.)»."""
    bare = calculate_monthly_norm("Хирург 0,5", 38.5, 35.0, 2026, 4, norm_rules=[])
    full = calculate_monthly_norm("Хирург (0,5 ст.)", 38.5, 35.0, 2026, 4, norm_rules=[])
    assert bare == full and get_rate_from_title("Хирург 0,5") == "0.5"


def test_rate_digits_inside_a_bigger_number_are_not_a_rate():
    assert get_rate_from_title("Врач (10,5 ст.)") is None


def test_rate_above_one_is_supported_in_the_monthly_norm(clean_config):
    one = calculate_monthly_norm("Терапевт (1,0 ст.)", 38.5, 35.0, 2026, 4, norm_rules=[])
    assert calculate_monthly_norm("Терапевт (1,25 ст.)", 38.5, 35.0, 2026, 4, norm_rules=[]) == pytest.approx(one * 1.25, abs=0.06)


# ── год по умолчанию — текущий ───────────────────────────────────────────────

def test_month_without_year_uses_the_current_year(monkeypatch):
    monkeypatch.setattr(utils, "_current_year", lambda: 2031)
    assert utils.month_info("апрель") == (4, 2031, 30)
    assert utils.month_info("апрель 2026") == (4, 2026, 30)


# ── разные фамилии одного корня ──────────────────────────────────────────────

@pytest.mark.parametrize("a,b,expected", [
    ("Иванов И.И.", "Иванова И.И.", True), ("Иванова И.И.", "Иванов И.И.", True),
    ("Ковальский А.А.", "Ковальская А.А.", True), ("Заяцкий А.А.", "Заяцкая А.А.", True),
    ("Толстой А.А.", "Толстая А.А.", True), ("Страшный А.А.", "Страшная А.А.", True),
    ("Кравец Н.Н.", "Кравец Н.Н.", False),
    ("Петров П.П.", "Петров П.П", False), ("Петров П.П.", "Петроф П.П.", False),
    ("Иванов И.И.", "Иванов И.П.", False),
])
def test_same_surname_other_gender(a, b, expected):
    assert same_surname_other_gender(a, b) is expected


# ── проверка выходного файла до генерации ────────────────────────────────────

def test_writable_output_passes_and_leaves_no_trace(tmp_path):
    target = tmp_path / "новый.xlsx"
    outfile.check_output_writable(str(target))
    assert not target.exists()


def test_existing_output_is_kept_untouched(tmp_path):
    target = tmp_path / "табель.xlsx"
    target.write_bytes(b"old")
    outfile.check_output_writable(str(target))
    assert target.read_bytes() == b"old"


def test_missing_output_folder_is_reported(tmp_path):
    with pytest.raises(outfile.OutputNotWritable, match="Папка"):
        outfile.check_output_writable(str(tmp_path / "нет" / "табель.xlsx"))


def test_output_locked_by_excel_is_reported_before_generation(tmp_path, monkeypatch):
    target = tmp_path / "табель.xlsx"
    target.write_bytes(b"old")
    real_open = open

    def locked(path, *a, **k):
        if os.fspath(path) == str(target):
            raise PermissionError(13, "Permission denied")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", locked)
    with pytest.raises(outfile.OutputNotWritable, match="Закройте"):
        outfile.check_output_writable(str(target))


# ── несохранённые изменения настроек ─────────────────────────────────────────

def _saved():
    return {"excel_colors": {"holiday": "#FFB6C1"}, "holidays_by": [[1, 1], [3, 8]],
            "hours_control": {"highlight_diff": True, "base_norm": 38.5, "uzd_norm": 35.0},
            "scoring": {"min_accept_score": -0.8}}


def test_identical_settings_have_no_unsaved_changes():
    assert cfgdiff.unsaved_sections(_saved(), _saved()) == []


def test_tuples_and_lists_are_the_same_value():
    cfg = _saved()
    cfg["holidays_by"] = [(1, 1), (3, 8)]
    assert cfgdiff.unsaved_sections(cfg, _saved()) == []


def test_every_section_is_checked_not_only_colors():
    cfg = _saved()
    cfg["scoring"] = {"min_accept_score": -0.5}
    cfg["hours_control"]["base_norm"] = 40.0
    assert cfgdiff.unsaved_sections(cfg, _saved()) == ["hours_control", "scoring"]


def test_legacy_norms_not_yet_in_the_file_are_not_a_change():
    cfg = _saved()
    cfg["norms_by_specialty"] = norms.rules_for_display(cfg)
    assert cfgdiff.unsaved_sections(cfg, _saved()) == []


def test_legacy_uzd_norm_field_missing_in_the_window_is_not_a_change():
    cfg = _saved()
    cfg["hours_control"] = {"highlight_diff": True, "base_norm": 38.5}
    assert cfgdiff.unsaved_sections(cfg, _saved()) == []


def test_edited_norms_are_a_change():
    cfg = _saved()
    cfg["norms_by_specialty"] = [{"keywords": ["хирург"], "rate": None, "weekly": 30.0}]
    assert cfgdiff.unsaved_sections(cfg, _saved()) == ["norms_by_specialty"]


# ── стоматология читает ставку тем же разбором ──────────────────────────────

def test_dental_role_choice_uses_the_rate_from_the_hint():
    from core import dental
    quarter, full = "Врач-стоматолог-ортопед (0,25 ст.)", "Врач-стоматолог-ортопед (1,0 ст.)"
    hint = ", врач-стоматолог-ортопед (0,25 ст)"
    assert dental._spec_score(quarter, hint) == 3 and dental._spec_score(full, hint) == 2
