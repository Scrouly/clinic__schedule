"""_score_match и _match_doctors_to_roles: баллы соответствия и распределение по статусам.

Баллы — сердце сопоставления врача с должностью в табеле; пакеты оптимизации
(кэш get_tags, один расчёт string_similarity) не должны менять ни одно значение."""
import pytest

from core.auto_schedule import _match_doctors_to_roles, _score_match
from core.models import DiagReport, DoctorRecord, Shift


# ── _score_match ────────────────────────────────────────────────────────────

CASES = [
    # (отделение, кабинет, должность, подсказка, лист) → балл, пояснение
    (("", "Невролог", "Врач-невролог (1,0 ст.)", "", ""), 4.0, "кабинет совпал по специальности: 3 + 1/1"),
    (("", "Уролог", "Врач-хирург-уролог (1,0 ст.)", "", ""), 3.5, "кабинет совпал, у должности две метки: 3 + 1/2"),
    (("Кардиология", "", "Врач-кардиолог (1,0 ст.)", "", ""), 3.0, "совпало отделение: 2 + 1/1"),
    (("Кардиология", "Хирург", "Врач-кардиолог (1,0 ст.)", "", ""), 2.0, "кабинет чужой, но совпало отделение: 1 + 1/1"),
    (("Кардиология", "", "Врач-терапевт (1,0 ст.)", ", врач-терапевт (1,0 ст)", ""), 0.5,
     "отделение чужое, но подсказка специальности совпала"),
    (("Кардиология", "", "Врач-терапевт (1,0 ст.)", "", ""), -1.0, "отделение чужое, подсказки нет"),
    (("", "", "Медсестра", "", ""), 0.5, "у должности нет специальности, у источника тоже"),
    (("Кардиология", "", "Медсестра", "", ""), -0.1, "у должности нет специальности, а у источника есть"),
    (("Хирургическое", "", "Врач-хирург (1,0 ст.)", "", "Хирургия"), 3.4, "+0.4: общая метка отделения и листа"),
    (("Приёмное", "", "Медсестра", "", "Приемное"), 0.7, "+0.2: названия отделения и листа похожи (ё → е)"),
    (("МИБС", "ОРИТ", "Врач-анестезиолог (1,0 ст.)", "", "МИБС"), 0.1, "меток нет нигде: -0.1 + 0.2 за похожий лист"),
]


@pytest.mark.parametrize("args,expected,why", CASES, ids=[c[2] for c in CASES])
def test_score_table(args, expected, why):
    assert _score_match(*args) == pytest.approx(expected)


def test_spec_hint_is_ignored_when_neither_direction_nor_cabinet_name_a_specialty():
    """Характеризация (возможная слабость, решать в пакете «fixes»): для отделения вроде
    «Консультативное» подсказка «врач-терапевт» не используется — балл остаётся -0.1,
    и такой врач всегда попадает в «сомнительные» (порог 1.5)."""
    with_hint = _score_match("Консультативное", "101", "Врач-терапевт (1,0 ст.)",
                             ", врач-терапевт (1,0 ст)", "Терапия")
    without = _score_match("Консультативное", "101", "Врач-терапевт (1,0 ст.)", "", "Терапия")
    assert with_hint == without == pytest.approx(-0.1)


# ── _match_doctors_to_roles ─────────────────────────────────────────────────

def _role(sheet, title, **extra):
    return {"sheet": sheet, "title": title, "data_r": 9, "time_r": 10, "night_r": None,
            "assigned_schedule": {}, **extra}


def _rec(name, direction="Хирургическое", cabinet="205", spec="", schedule=None):
    return DoctorRecord(name=name, direction=direction, cabinet=cabinet, spec_hint=spec,
                        schedule=schedule if schedule is not None else
                        {1: Shift(time="09:00-17:00", hours=8.0)})


def _run(template_docs, records):
    diag = DiagReport(month_str="апрель 2026")
    found = _match_doctors_to_roles(template_docs, records, diag)
    return found, diag


def test_good_match_goes_to_ok_and_schedule_is_assigned():
    roles = {"Петров П.П.": [_role("Хирургия", "Врач-хирург (1,0 ст.)")]}
    found, diag = _run(roles, [_rec("Петров П.П.")])
    assert found == {"Петров П.П.": True}
    assert [x["name"] for x in diag.ok] == ["Петров П.П."]
    assert diag.ok[0]["total_hours"] == 8.0 and diag.ok[0]["workdays"] == 1
    assert roles["Петров П.П."][0]["assigned_schedule"][1].hours == 8.0


def test_weak_match_is_assigned_but_marked_dubious():
    roles = {"Иванов И.И.": [_role("Терапия", "Врач-терапевт (1,0 ст.)")]}
    _, diag = _run(roles, [_rec("Иванов И.И.", "Консультативное", "101")])
    assert [x["name"] for x in diag.dubious] == ["Иванов И.И."]
    assert diag.ok == []
    assert roles["Иванов И.И."][0]["assigned_schedule"]            # расписание всё равно записано


def test_best_scoring_role_wins():
    therapy = _role("Терапия", "Врач-терапевт (1,0 ст.)")
    surgery = _role("Хирургия", "Врач-хирург (1,0 ст.)")
    _run({"Петров П.П.": [therapy, surgery]}, [_rec("Петров П.П.")])
    assert surgery["assigned_schedule"] and not therapy["assigned_schedule"]


def test_too_low_score_is_rejected_and_schedule_not_assigned():
    role = _role("Хирургия", "Врач-хирург (1,0 ст.)")
    _, diag = _run({"Петров П.П.": [role]}, [_rec("Петров П.П.", "Кардиология", "")])
    assert [x["name"] for x in diag.low_score] == ["Петров П.П."]
    assert role["assigned_schedule"] == {}


def test_doctor_missing_from_source_is_reported():
    found, diag = _run({"Сидоров С.С.": [_role("Терапия", "Врач-терапевт")]}, [])
    assert found == {"Сидоров С.С.": False}
    assert diag.not_in_source == ["Сидоров С.С."]


def test_source_doctor_missing_from_template_is_reported():
    _, diag = _run({}, [_rec("Лишний Л.Л.", "Консультативное", "110")])
    assert len(diag.source_not_in_template) == 1
    assert diag.source_not_in_template[0].startswith("Лишний Л.Л.")


@pytest.mark.parametrize("schedule,bucket", [
    ({}, "empty_schedule"),
    ({1: Shift(time="09:00-17:00", hours=0.0)}, "no_hours"),
    ({1: Shift(time=None, hours=8.0)}, "missing_time"),
])
def test_status_buckets_for_strong_matches(schedule, bucket):
    roles = {"Петров П.П.": [_role("Хирургия", "Врач-хирург (1,0 ст.)")]}
    _, diag = _run(roles, [_rec("Петров П.П.", schedule=schedule)])
    assert [x["name"] for x in getattr(diag, bucket)] == ["Петров П.П."]
    assert diag.ok == []


def test_two_source_records_of_one_doctor_are_merged_into_one_role():
    role = _role("Хирургия", "Врач-хирург (1,0 ст.)")
    morning = _rec("Петров П.П.", schedule={1: Shift(time="09:00-12:00", hours=3.0)})
    evening = _rec("Петров П.П.", cabinet="206", schedule={1: Shift(time="14:00-18:00", hours=4.0)})
    _run({"Петров П.П.": [role]}, [morning, evening])
    merged = role["assigned_schedule"][1]
    assert merged.time == "09:00-12:00/14:00-18:00" and merged.hours == 7.0


# ── Нечёткое сравнение имён (порог 0.95, строго «больше») ───────────────────

def test_name_with_missing_trailing_dot_is_matched_fuzzily():
    role = _role("Хирургия", "Врач-хирург (1,0 ст.)")
    found, _ = _run({"Петров П.П.": [role]}, [_rec("Петров П.П")])
    assert found == {"Петров П.П.": True}
    assert role["assigned_schedule"]


def test_different_initials_are_not_matched():
    found, diag = _run({"Иванов И.И.": [_role("Терапия", "Врач-терапевт")]}, [_rec("Иванов И.П.")])
    assert found == {"Иванов И.И.": False}
    assert diag.not_in_source == ["Иванов И.И."]


def test_male_and_female_surname_are_currently_treated_as_the_same_person():
    """ВОЗМОЖНАЯ ОШИБКА, зафиксирована как есть: «Иванов И.И.» и «Иванова И.И.» похожи на 0.9565 > 0.95,
    поэтому, если в графике есть только Иванова, её смены попадут в строку Иванова.
    Менять порог или правило сравнения — отдельное решение (пакет «fixes»)."""
    role = _role("Терапия", "Врач-терапевт (1,0 ст.)")
    found, _ = _run({"Иванов И.И.": [role]}, [_rec("Иванова И.И.", "Консультативное", "101")])
    assert found == {"Иванов И.И.": True}
