"""Нормы часов по специальностям и ставкам."""
from decimal import Decimal

import pytest

from core import norms
from core.norms import NormsError
from core.utils import calculate_monthly_norm


# ── Разбор ввода ─────────────────────────────────────────────────────────────

def test_parse_weekly_accepts_comma():
    assert norms.parse_weekly("38,5") == 38.5


@pytest.mark.parametrize("raw", ["abc", "", "0", "-5", "nan"])
def test_parse_weekly_rejects_garbage(raw):
    with pytest.raises(NormsError):
        norms.parse_weekly(raw)


def test_parse_weekly_rejects_monthly_looking_value_with_hint():
    with pytest.raises(NormsError, match="в неделю"):
        norms.parse_weekly("159.7")


@pytest.mark.parametrize("raw", ["", "Любая", "любая", " any "])
def test_parse_rate_any(raw):
    assert norms.parse_rate(raw) is None


def test_parse_rate_number_with_comma():
    assert norms.parse_rate("0,5") == 0.5


@pytest.mark.parametrize("raw", ["abc", "0", "3"])
def test_parse_rate_rejects_garbage(raw):
    with pytest.raises(NormsError):
        norms.parse_rate(raw)


def test_parse_norm_rules_builds_rules_and_skips_empty_rows():
    rows = [
        ("Ультразвуков, УЗД", "1,0", "35"),
        ("", "", ""),
        ("хирург", "Любая", "30,8"),
    ]
    assert norms.parse_norm_rules(rows) == [
        {"keywords": ["ультразвуков", "узд"], "rate": 1.0, "weekly": 35.0},
        {"keywords": ["хирург"], "rate": None, "weekly": 30.8},
    ]


def test_parse_norm_rules_reports_row_number():
    with pytest.raises(NormsError, match="Строка 2"):
        norms.parse_norm_rules([("хирург", "", "30"), ("", "0,5", "20")])


def test_parse_norm_rules_rejects_duplicates():
    with pytest.raises(NormsError, match="повтор"):
        norms.parse_norm_rules([("хирург", "0,5", "20"), ("Хирург", "0.5", "21")])


# ── Выбор нормы ──────────────────────────────────────────────────────────────

RULES = [
    {"keywords": ["ультразвуков", "узд", "узи"], "rate": 1.0, "weekly": 35.0},
    {"keywords": ["ультразвуков", "узд", "узи"], "rate": 0.5, "weekly": 20.0},
    {"keywords": ["хирург"], "rate": None, "weekly": 30.8},
]


def W(title, fraction, base=38.5, rules=RULES):
    return norms.weekly_norm_for(title, fraction, base, rules)


def test_exact_rate_row_is_absolute():
    assert W("Врач УЗД (0,5 ст.)", 0.5) == Decimal("20.0")


def test_exact_rate_full():
    assert W("Врач УЗИ (1,0 ст.)", 1.0) == Decimal("35.0")


def test_any_rate_row_is_scaled_by_fraction():
    assert W("Врач-хирург (0,5 ст.)", 0.5) == Decimal("15.4")


def test_specialty_without_row_for_this_rate_falls_back_to_base_scaled():
    # у УЗД нет строки для 0,75 и нет «Любая» → базовая норма × ставка
    assert W("Врач УЗД (0,75 ст.)", 0.75) == Decimal("38.5") * Decimal("0.75")


def test_unknown_specialty_uses_base():
    assert W("Врач-терапевт", 1.0) == Decimal("38.5")


def test_keyword_must_start_a_word():
    rules = [{"keywords": ["лор"], "rate": None, "weekly": 30.0}]
    assert W("Врач-колоректальный хирург", 1.0, rules=rules) == Decimal("38.5")
    assert W("Врач-ЛОР", 1.0, rules=rules) == Decimal("30.0")


def test_yo_is_ignored():
    rules = [{"keywords": ["берёз"], "rate": None, "weekly": 30.0}]
    assert W("Врач Береза", 1.0, rules=rules) == Decimal("30.0")


def test_first_matching_row_wins():
    rules = [
        {"keywords": ["хирург"], "rate": None, "weekly": 30.0},
        {"keywords": ["хирург"], "rate": None, "weekly": 25.0},
    ]
    assert W("Хирург", 1.0, rules=rules) == Decimal("30.0")


# ── Конфиг ───────────────────────────────────────────────────────────────────

def test_rules_for_display_uses_saved_table():
    cfg = {"norms_by_specialty": [{"keywords": ["x"], "rate": None, "weekly": 1.0}]}
    assert norms.rules_for_display(cfg) == cfg["norms_by_specialty"]


def test_rules_for_display_falls_back_to_legacy_uzd_row():
    cfg = {"hours_control": {"uzd_norm": 33.0}}
    assert norms.rules_for_display(cfg) == [
        {"keywords": ["ультразвуков", "узд"], "rate": 1.0, "weekly": 33.0}
    ]


def test_empty_saved_table_is_kept_empty():
    assert norms.rules_for_display({"norms_by_specialty": []}) == []


# ── Интеграция с месячной нормой (апрель 2026: 22 рабочих дня) ───────────────

def test_monthly_norm_exact_rate_row_is_absolute(clean_config):
    rules = [{"keywords": ["узд"], "rate": 0.5, "weekly": 20.0}]
    # 20 ч/нед ÷ 5 = 4 ч/день × 22 дня
    assert calculate_monthly_norm("Врач УЗД (0,5 ст.)", 38.5, 35.0, 2026, 4, norm_rules=rules) == 88.0


def test_monthly_norm_any_rate_scaled(clean_config):
    rules = [{"keywords": ["хирург"], "rate": None, "weekly": 30.0}]
    # 30 × 0,5 = 15 ч/нед → 3 ч/день × 22
    assert calculate_monthly_norm("Хирург (0,5 ст.)", 38.5, 35.0, 2026, 4, norm_rules=rules) == 66.0


def test_monthly_norm_pre_holiday_reduction_scales_with_rate(clean_config, monkeypatch):
    monkeypatch.setitem(clean_config, "holidays_by", [[4, 22]])  # 22.04.2026 — среда
    # 21.04 — предпраздничный (−1 ч на полную ставку); рабочих дней 21: 20 обычных + 1 сокращённый
    assert calculate_monthly_norm("Терапевт (1,0 ст.)", 38.5, 35.0, 2026, 4, norm_rules=[]) == 160.7
    assert calculate_monthly_norm("Терапевт (0,5 ст.)", 38.5, 35.0, 2026, 4, norm_rules=[]) == 80.35


def test_monthly_norm_reads_table_from_config(clean_config, monkeypatch):
    monkeypatch.setitem(clean_config, "norms_by_specialty",
                        [{"keywords": ["хирург"], "rate": None, "weekly": 30.0}])
    assert calculate_monthly_norm("Хирург (1,0 ст.)", 38.5, 35.0, 2026, 4) == 132.0


def test_empty_table_in_config_disables_uzd_special_case(clean_config, monkeypatch):
    monkeypatch.setitem(clean_config, "norms_by_specialty", [])
    assert calculate_monthly_norm("Врач УЗД (1,0 ст.)", 38.5, 35.0, 2026, 4) == 169.4
