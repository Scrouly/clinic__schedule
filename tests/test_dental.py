"""Стоматология: чтение обеих раскладок графика и сопоставление с листом шаблона.

Фамилии в тестах вымышленные: реальные ФИО в репозиторий не попадают."""
import pytest
from openpyxl import Workbook

from core import dental
from core.models import DiagReport, DoctorRecord, Shift

LATIN_C = "\N{LATIN CAPITAL LETTER C}"       # в графике встречается фамилия с латинской «C» в начале


def _legacy_book(path, sheet="Апрель 26  "):
    """Прежняя раскладка: Кабинет / Доктор / Смена-Часы, дни — строки."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws["A1"], ws["A2"] = "Кабинет", "Доктор"
    ws["C1"], ws["C2"] = "25 каб", "Тестов А.В."
    ws["E1"], ws["E2"] = "37 каб", "Тестов"
    ws["G2"] = LATIN_C + "околов Д"
    ws["I2"] = "Пробина ПАРОДОНТ"
    ws["K2"] = "Итого"
    for c in (3, 5, 7, 9):
        ws.cell(3, c, "Смена")
        ws.cell(3, c + 1, "Часы")
    for d in range(1, 4):
        ws.cell(3 + d, 1, float(d))
    ws["C4"], ws["D4"] = "09:00-15:00", 6
    ws["E4"], ws["F4"] = "10:00-14:00", 4
    ws["G4"], ws["H4"] = "Учеба", None
    ws["I4"], ws["J4"] = "09:00-12:00", 3
    ws["I5"] = "14:00-16:00"          # часы не проставлены
    wb.save(path)


def test_find_month_sheet_handles_short_year_and_spaces():
    names = ["Отчёт по часам", "Март 26 ", "Апрель 26  "]
    assert dental.find_month_sheet(names, "Апрель 2026") == "Апрель 26  "
    with pytest.raises(ValueError, match="нет листа"):
        dental.find_month_sheet(names, "Май 2026")


@pytest.mark.parametrize("raw,expected", [
    (LATIN_C + "околов Д", ("Соколов Д.", "")),
    ("Сергеев С.С.", ("Сергеев С.С.", "")),
    ("Васильева Т.Г", ("Васильева Т.Г.", "")),
    ("Пробина ПАРОДОНТ", ("Пробина", "ПАРОДОНТ")),
    ("Иванова ", ("Иванова", "")),
])
def test_split_legacy_name(raw, expected):
    assert dental.split_legacy_name(raw) == expected


def test_parse_legacy_sheet(tmp_path):
    path = str(tmp_path / "dent.xlsx")
    _legacy_book(path)
    recs = {(r.name, r.cabinet): r for r in dental.parse_dental_source(path, "Апрель 2026")}
    assert set(recs) == {("Тестов А.В.", "25 каб"), ("Тестов", "37 каб"),
                         ("Соколов Д.", "37 каб"), ("Пробина", "37 каб")}
    assert all(r.direction == dental.DENTAL_DIRECTION for r in recs.values())
    assert recs[("Тестов А.В.", "25 каб")].schedule[1] == Shift(time="09:00-15:00", hours=6)
    assert recs[("Соколов Д.", "37 каб")].schedule[1].time == "Учеба"
    # часы не проставлены — считаются по времени
    assert recs[("Пробина", "37 каб")].schedule[2].hours == 2.0


def test_parse_unknown_layout_is_reported(tmp_path):
    path = str(tmp_path / "dent.xlsx")
    wb = Workbook()
    wb.active.title = "Апрель 26"
    wb.active["A1"] = "что-то другое"
    wb.save(path)
    with pytest.raises(ValueError, match="раскладку"):
        dental.parse_dental_source(path, "Апрель 2026")


# ── Сопоставление ────────────────────────────────────────────────────────────

def _role(title, sheet="Стоматологическое"):
    return {"sheet": sheet, "title": title, "assigned_schedule": {}}


def _rec(name, cab="", hint="", sched=None):
    return DoctorRecord(name=name, direction=dental.DENTAL_DIRECTION, cabinet=cab, spec_hint=hint,
                        schedule=sched or {})


def test_is_dental_sheet():
    assert dental.is_dental_sheet("Стоматологическое")
    assert not dental.is_dental_sheet("Ознакомление СО (стоматология)")
    assert not dental.is_dental_sheet("Хирургическое")


def test_split_template_docs():
    docs = {"А": [_role("т", "Стоматологическое"), _role("т", "Хирургическое")]}
    regular, dent = dental.split_template_docs(docs)
    assert [r["sheet"] for r in regular["А"]] == ["Хирургическое"]
    assert [r["sheet"] for r in dent["А"]] == ["Стоматологическое"]


def test_match_by_surname_and_merge_cabinets():
    role = _role("врач-стоматолог-терапевт (0,25 ст.)")
    docs = {"Соколов Д.М.": [role]}
    s = Shift(time="09:00-12:00", hours=3)
    s2 = Shift(time="12:00-15:00", hours=3)
    recs = [_rec("Соколов Д.", "31 каб", sched={1: s}), _rec("Соколов", "37 каб", sched={1: s2})]
    diag = DiagReport()
    found = dental.match_dental(docs, recs, diag)
    assert found == {"Соколов Д.М.": True}
    assert role["assigned_schedule"][1] == Shift(time="09:00-15:00", hours=6)
    assert [d["name"] for d in diag.ok] == ["Соколов Д.М."]


def test_two_people_same_name_resolved_by_cabinet(monkeypatch):
    # правила «фамилия|кабинет» живут в локальном конфиге, а не в коде
    monkeypatch.setitem(dental.CONFIG, "dental_role_by_cabinet",
                        {"тестов|25": "ортопед", "тестов|37": "терапевт"})
    ortho = _role("врач-стоматолог-ортопед (1,0 ст.)")
    ther = _role("врач-стоматолог-терапевт (1,25 ст.)")
    docs = {"Тестов А.В.": [ortho, ther]}
    sh = Shift(time="09:00-15:00", hours=6)
    recs = [_rec("Тестов А.В.", "25 каб", sched={1: sh}), _rec("Тестов", "37 каб", sched={2: sh})]
    diag = DiagReport()
    dental.match_dental(docs, recs, diag)
    assert list(ortho["assigned_schedule"]) == [1]
    assert list(ther["assigned_schedule"]) == [2]
    assert not diag.dubious


def test_without_configured_rules_two_roles_by_cabinet_are_dubious(monkeypatch):
    monkeypatch.delitem(dental.CONFIG, "dental_role_by_cabinet", raising=False)
    assert dental.DEFAULT_ROLE_BY_CABINET == {}          # в коде правил с фамилиями нет
    docs = {"Тестов А.В.": [_role("врач-стоматолог-ортопед (1,0 ст.)"),
                            _role("врач-стоматолог-терапевт (1,25 ст.)")]}
    diag = DiagReport()
    dental.match_dental(docs, [_rec("Тестов", "25 каб", sched={1: Shift(time="09:00-15:00", hours=6)})], diag)
    assert [d["name"] for d in diag.dubious] == ["Тестов А.В."]


def test_two_roles_resolved_by_specialty_hint():
    ortho = _role("врач-стоматолог-ортопед (1,0 ст.)")
    ther = _role("врач-стоматолог-терапевт (1,25 ст.)")
    docs = {"Тестов А.В.": [ortho, ther]}
    sh = Shift(time="09:00-15:00", hours=6)
    recs = [_rec("Тестов А.В.", "37 каб", ", врач-стоматолог-терапевт (1,25 ст)", {3: sh})]
    dental.match_dental(docs, recs, DiagReport())
    assert list(ther["assigned_schedule"]) == [3] and not ortho["assigned_schedule"]


def test_ambiguous_role_goes_to_dubious():
    docs = {"Иванов И.И.": [_role("врач-стоматолог-ортопед (1,0 ст.)"), _role("врач-стоматолог-терапевт (0,5 ст.)")]}
    diag = DiagReport()
    dental.match_dental(docs, [_rec("Иванов И.И.", "5 каб", sched={1: Shift(time="09:00-10:00", hours=1)})], diag)
    assert [d["name"] for d in diag.dubious] == ["Иванов И.И."]


def test_missing_and_unknown_doctors_reported():
    docs = {"Образцов А.Ю.": [_role("врач-стоматолог-ортопед (0,25 ст.)")]}
    diag = DiagReport()
    found = dental.match_dental(docs, [_rec("Примеров", "22 каб")], diag)
    assert found == {"Образцов А.Ю.": False}
    assert diag.not_in_source == ["Образцов А.Ю."]
    assert diag.source_not_in_template and diag.source_not_in_template[0].startswith("Примеров")


def test_no_dental_sheet_in_template_is_reported():
    diag = DiagReport()
    assert dental.match_dental({}, [_rec("Примеров")], diag) == {}
    assert len(diag.source_not_in_template) == 1


def test_dental_titles_do_not_trigger_surgeon_and_orthopedist_day_norms():
    from core.excel_io import get_daily_hours_norm
    assert get_daily_hours_norm("врач-стоматолог-хирург (1,0 ст.)") is None
    assert get_daily_hours_norm("врач-стоматолог-ортопед (1,0 ст.)") is None
    assert get_daily_hours_norm("врач-хирург (1,0 ст.)") == 6.16
