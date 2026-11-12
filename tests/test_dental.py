"""Стоматология: чтение обеих раскладок графика и сопоставление с листом шаблона."""
import pytest
from openpyxl import Workbook

from core import dental
from core.models import DiagReport, DoctorRecord, Shift


def _legacy_book(path, sheet="Апрель 26  "):
    """Прежняя раскладка: Кабинет / Доктор / Смена-Часы, дни — строки."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws["A1"], ws["A2"] = "Кабинет", "Доктор"
    ws["C1"], ws["C2"] = "25 каб", "Становенко А.В."
    ws["E1"], ws["E2"] = "37 каб", "Становенко"
    ws["G2"] = "Cавчук Д"            # латинская C
    ws["I2"] = "Кузнецова ПАРОДОНТ"
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
    ("Cавчук Д", ("Савчук Д.", "")),
    ("Семуков С.С.", ("Семуков С.С.", "")),
    ("Виноградова Т.Г", ("Виноградова Т.Г.", "")),
    ("Кузнецова ПАРОДОНТ", ("Кузнецова", "ПАРОДОНТ")),
    ("Иванова ", ("Иванова", "")),
])
def test_split_legacy_name(raw, expected):
    assert dental.split_legacy_name(raw) == expected


def test_parse_legacy_sheet(tmp_path):
    path = str(tmp_path / "dent.xlsx")
    _legacy_book(path)
    recs = {(r.name, r.cabinet): r for r in dental.parse_dental_source(path, "Апрель 2026")}
    assert set(recs) == {("Становенко А.В.", "25 каб"), ("Становенко", "37 каб"),
                         ("Савчук Д.", "37 каб"), ("Кузнецова", "37 каб")}
    assert all(r.direction == dental.DENTAL_DIRECTION for r in recs.values())
    assert recs[("Становенко А.В.", "25 каб")].schedule[1] == Shift(time="09:00-15:00", hours=6)
    assert recs[("Савчук Д.", "37 каб")].schedule[1].time == "Учеба"
    # часы не проставлены — считаются по времени
    assert recs[("Кузнецова", "37 каб")].schedule[2].hours == 2.0


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
    docs = {"Савчук Д.М.": [role]}
    s = Shift(time="09:00-12:00", hours=3)
    s2 = Shift(time="12:00-15:00", hours=3)
    recs = [_rec("Савчук Д.", "31 каб", sched={1: s}), _rec("Савчук", "37 каб", sched={1: s2})]
    diag = DiagReport()
    found = dental.match_dental(docs, recs, diag)
    assert found == {"Савчук Д.М.": True}
    assert role["assigned_schedule"][1] == Shift(time="09:00-15:00", hours=6)
    assert [d["name"] for d in diag.ok] == ["Савчук Д.М."]


def test_two_people_same_name_resolved_by_cabinet():
    ortho = _role("врач-стоматолог-ортопед (1,0 ст.)")
    ther = _role("врач-стоматолог-терапевт (1,25 ст.)")
    docs = {"Становенко А.В.": [ortho, ther]}
    sh = Shift(time="09:00-15:00", hours=6)
    recs = [_rec("Становенко А.В.", "25 каб", sched={1: sh}), _rec("Становенко", "37 каб", sched={2: sh})]
    diag = DiagReport()
    dental.match_dental(docs, recs, diag)
    assert list(ortho["assigned_schedule"]) == [1]
    assert list(ther["assigned_schedule"]) == [2]
    assert not diag.dubious


def test_two_roles_resolved_by_specialty_hint():
    ortho = _role("врач-стоматолог-ортопед (1,0 ст.)")
    ther = _role("врач-стоматолог-терапевт (1,25 ст.)")
    docs = {"Становенко А.В.": [ortho, ther]}
    sh = Shift(time="09:00-15:00", hours=6)
    recs = [_rec("Становенко А.В.", "37 каб", ", врач-стоматолог-терапевт (1,25 ст)", {3: sh})]
    dental.match_dental(docs, recs, DiagReport())
    assert list(ther["assigned_schedule"]) == [3] and not ortho["assigned_schedule"]


def test_ambiguous_role_goes_to_dubious():
    docs = {"Иванов И.И.": [_role("врач-стоматолог-ортопед (1,0 ст.)"), _role("врач-стоматолог-терапевт (0,5 ст.)")]}
    diag = DiagReport()
    dental.match_dental(docs, [_rec("Иванов И.И.", "5 каб", sched={1: Shift(time="09:00-10:00", hours=1)})], diag)
    assert [d["name"] for d in diag.dubious] == ["Иванов И.И."]


def test_missing_and_unknown_doctors_reported():
    docs = {"Верас А.Ю.": [_role("врач-стоматолог-ортопед (0,25 ст.)")]}
    diag = DiagReport()
    found = dental.match_dental(docs, [_rec("Вощула", "22 каб")], diag)
    assert found == {"Верас А.Ю.": False}
    assert diag.not_in_source == ["Верас А.Ю."]
    assert diag.source_not_in_template and diag.source_not_in_template[0].startswith("Вощула")


def test_no_dental_sheet_in_template_is_reported():
    diag = DiagReport()
    assert dental.match_dental({}, [_rec("Вощула")], diag) == {}
    assert len(diag.source_not_in_template) == 1


def test_dental_titles_do_not_trigger_surgeon_and_orthopedist_day_norms():
    from core.excel_io import get_daily_hours_norm
    assert get_daily_hours_norm("врач-стоматолог-хирург (1,0 ст.)") is None
    assert get_daily_hours_norm("врач-стоматолог-ортопед (1,0 ст.)") is None
    assert get_daily_hours_norm("врач-хирург (1,0 ст.)") == 6.16
