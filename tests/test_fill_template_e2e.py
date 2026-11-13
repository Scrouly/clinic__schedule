"""Сквозной тест: источник → parse_source → fill_template → готовый табель; и compare().

Проверяется на маленькой синтетической книге (tests/builders.py):
  • явные утверждения о значениях, заливках, нормах, ночных часах и правилах подсветки;
  • «золотые» дампы всей книги (tests/golden/*.json): ячейки отдельно от условного
    форматирования — см. tests/golden.py."""
import pytest
from openpyxl import load_workbook

from core import auto_schedule, compare_schedules, excel_io
from tests.builders import (make_compare_pair, make_source_book, make_template_book,
                            standard_source_docs, standard_template_sheets)
from tests.golden import assert_matches_golden, dump_cells, dump_conditional_formatting

MONTH = "апрель 2026"        # строка месяца для fill_template
SHEET = "Апрель 2026"        # имя листа в книге-источнике для parse_source

# Строки врачей в шаблоне из builders: данные с DAY_ROW + 5 = 9, шаг 2 (на МИБС — 3).
ROW = {"Иванов И.И.": 9, "Орлов О.О.": 11, "Сидоров С.С.": 13}   # лист «Терапия»


def col(day: int) -> int:
    return 2 + day            # день 1 — столбец C


@pytest.fixture
def out_path(tmp_path, april_2026):
    src = make_source_book(str(tmp_path / "src.xlsx"), standard_source_docs())
    tpl = make_template_book(str(tmp_path / "tpl.xlsx"), standard_template_sheets())
    records = excel_io.parse_source(src, SHEET)
    out = str(tmp_path / "out.xlsx")
    auto_schedule.fill_template(tpl, records, MONTH, out)
    return out


@pytest.fixture
def wb(out_path):
    book = load_workbook(out_path)
    yield book
    book.close()


def _v(ws, row, day):
    return ws.cell(row=row, column=col(day)).value


def _fill(ws, row, day):
    f = ws.cell(row=row, column=col(day)).fill
    return None if f.fill_type in (None, "none") else f.start_color.rgb


def _rules(ws):
    return [(str(cf.sqref), r) for cf in ws.conditional_formatting for r in cf.rules]


# ── Значения ────────────────────────────────────────────────────────────────

def test_shifts_are_written_as_hours_over_time(wb):
    ws = wb["Терапия"]
    r = ROW["Иванов И.И."]
    assert (_v(ws, r, 1), _v(ws, r + 1, 1)) == (8, "09:00-17:00")
    assert (_v(ws, r, 3), _v(ws, r + 1, 3)) == (7, "09:00-16:00")


def test_days_without_shift_get_V_and_holiday_gets_P(wb):
    ws = wb["Терапия"]
    r = ROW["Иванов И.И."]
    assert _v(ws, r, 4) == "В"          # суббота, смены нет
    assert _v(ws, r, 6) == "В"          # в источнике «вых» с нулём часов
    assert _v(ws, r, 21) == "П"         # 21.04 — праздник
    assert _v(ws, r + 1, 21) is None


def test_day_fills_follow_holidays_weekends_and_transfers(wb):
    ws = wb["Терапия"]
    r = ROW["Иванов И.И."]
    assert _fill(ws, r, 21) == "FFFFB6C1"      # праздник → розовый
    assert _fill(ws, r, 4) == "FFCAFFCA"       # суббота → цвет выходного
    assert _fill(ws, r, 20) == "FFCAFFCA"      # понедельник, но перенесённый выходной
    assert _fill(ws, r, 25) is None            # суббота, но перенесённый РАБОЧИЙ день
    assert _fill(ws, r, 8) is None             # обычный вторник… среда


def test_days_beyond_month_end_are_blanked_and_greyed(wb):
    ws = wb["Терапия"]
    r = ROW["Иванов И.И."]
    assert _v(ws, r, 31) is None and _fill(ws, r, 31) == "FFD9D9D9"
    assert _v(ws, 4, 31) is None                       # и в шапке: апрель — 30 дней


def test_header_row_with_numbers_is_filled_for_the_month(wb):
    ws = wb["Терапия"]
    assert [_v(ws, 4, d) for d in (1, 15, 30)] == [1, 15, 30]


def test_doctor_absent_from_source_stays_empty(wb):
    ws = wb["Терапия"]
    r = ROW["Сидоров С.С."]
    assert all(_v(ws, r, d) is None and _v(ws, r + 1, d) is None for d in range(1, 31))


def test_hours_that_disagree_with_time_are_marked_red_with_comment(wb):
    ws = wb["Терапия"]
    r = ROW["Орлов О.О."]                  # 09:00-17:00 = 8 ч, а в графике 7
    cell = ws.cell(row=r, column=col(1))
    assert cell.fill.start_color.rgb == "FFFF0000"
    # разница = «по времени» − «в графике» = 8 − 7
    assert "Расхождение" in cell.comment.text and "+1.00" in cell.comment.text
    ivanov = ws.cell(row=ROW["Иванов И.И."], column=col(7))     # 7,5 ч при 8 ч по времени
    assert ivanov.fill.start_color.rgb == "FFFF0000"


# ── Норма и ночные часы ─────────────────────────────────────────────────────

def test_monthly_norm_for_full_rate(wb):
    # апрель 2026: 22 будних дня − праздник 21.04 = 21; предпраздничные 20.04 и 30.04 (завтра 1 мая),
    # значит 19 обычных × 7.7 + 2 предпраздничных × 6.7 = 159.7. Переносы на норму не влияют.
    assert wb["Терапия"].cell(row=ROW["Иванов И.И."], column=34).value == pytest.approx(159.7)


def test_monthly_norm_for_half_rate_is_half(wb):
    # 0,5 ставки: 19 × 3.85 + 2 × (3.85 − 0.5) = 79.85
    assert wb["УЗИ"].cell(row=9, column=34).value == pytest.approx(79.85)


def test_night_hours_of_overnight_shift_on_mibs(wb):
    ws = wb["МИБС"]
    assert (_v(ws, 9, 1), _v(ws, 10, 1)) == (8, "22:00-06:00")
    assert _v(ws, 11, 1) == 8                      # 22:00–06:00 целиком ночные
    assert _v(ws, 11, 2) is None                   # смены нет → пусто
    assert _v(ws, 9, 2) == "В"


def test_mibs_has_three_rows_per_doctor_other_sheets_two(wb):
    assert wb["МИБС"].cell(row=11, column=1).value is None      # ночная строка без ФИО
    assert wb["Терапия"].cell(row=ROW["Орлов О.О."], column=1).value == "Орлов О.О."


# ── Подсветка (условное форматирование) ─────────────────────────────────────

def test_norm_vs_hours_rules_exist_for_every_doctor(wb):
    ws = wb["Терапия"]
    rules = _rules(ws)
    cell_is = [(rng, r) for rng, r in rules if r.type == "cellIs"]
    assert len(cell_is) == 6                               # 3 врача × («меньше», «больше»)
    assert {rng for rng, _ in cell_is} == {"AH9", "AH11", "AH13"}
    assert {r.formula[0] for _, r in cell_is} == {"$AI$9", "$AI$11", "$AI$13"}


def test_daily_norm_rule_depends_on_specialty_and_rate(wb):
    uzi = [(rng, r.formula[0]) for rng, r in _rules(wb["УЗИ"]) if r.type == "expression"]
    # 0,5 ставки у УЗД: подсвечиваем ПЕРЕРАБОТКУ — часы > 5.6 - 0.1
    assert uzi == [("C10:AF10", "AND(ISNUMBER(C$9), C$9>5.5)")]
    surg = [(rng, r.formula[0]) for rng, r in _rules(wb["Хирургия"]) if r.type == "expression"]
    # полная ставка хирурга: подсвечиваем НЕДОРАБОТКУ — часы < 6.16
    assert surg == [("C10:AF10", "AND(ISNUMBER(C$9), C$9<6.16)")]
    # у терапевта дневной нормы нет → правила нет
    assert [r for _, r in _rules(wb["Терапия"]) if r.type == "expression"] == []


# ── Заголовки и отчёт ───────────────────────────────────────────────────────

def test_month_in_sheet_headers_and_ack_sheet_is_updated(wb):
    assert wb["Терапия"]["A1"].value == "ГРАФИК РАБОТЫ НА АПРЕЛЬ 2026 г."
    assert wb["Ознакомление"]["A1"].value == "ПРИЛОЖЕНИЕ. С графиком работы на апрель 2026 года ознакомлены:"


def test_diagnostic_sheet_lists_missing_and_extra_doctors(wb):
    ws = wb["Отчет_по_ошибкам"]
    column_a = [c.value for c in ws["A"] if c.value]
    assert "НЕ НАЙДЕНЫ В ГРАФИКЕ" in column_a and "Сидоров С.С." in column_a
    assert "ВРАЧИ ИЗ ГРАФИКА ВНЕ ШАБЛОНА" in column_a
    assert any(str(x).startswith("Лишний Л.Л.") for x in column_a)


def test_existing_report_sheet_is_replaced_not_duplicated(tmp_path, april_2026):
    src = make_source_book(str(tmp_path / "src.xlsx"), standard_source_docs())
    tpl = make_template_book(str(tmp_path / "tpl.xlsx"), standard_template_sheets())
    records = excel_io.parse_source(src, SHEET)
    first, second = str(tmp_path / "a.xlsx"), str(tmp_path / "b.xlsx")
    auto_schedule.fill_template(tpl, records, MONTH, first)
    auto_schedule.fill_template(first, records, MONTH, second)     # результат как шаблон
    names = load_workbook(second).sheetnames
    assert names.count("Отчет_по_ошибкам") == 1


def test_doctor_in_the_first_scanned_row_is_found(tmp_path, april_2026):
    """Поиск врачей начинается с DAY_ROW + 3: врач, стоящий ровно там, не должен потеряться."""
    src = make_source_book(str(tmp_path / "src.xlsx"), standard_source_docs())
    tpl = make_template_book(str(tmp_path / "tpl.xlsx"),
                             {"Хирургия": standard_template_sheets()["Хирургия"]},
                             doctor_offset=3, ack_sheet=False)
    out = str(tmp_path / "o.xlsx")
    auto_schedule.fill_template(tpl, excel_io.parse_source(src, SHEET), MONTH, out)
    ws = load_workbook(out)["Хирургия"]
    assert ws.cell(row=7, column=1).value == "Петров П.П."
    assert (_v(ws, 7, 1), _v(ws, 8, 1)) == (7.0, "09:00-12:00/14:00-18:00")


def test_progress_reaches_one(tmp_path, april_2026):
    src = make_source_book(str(tmp_path / "src.xlsx"), standard_source_docs())
    tpl = make_template_book(str(tmp_path / "tpl.xlsx"), standard_template_sheets())
    seen = []
    auto_schedule.fill_template(tpl, excel_io.parse_source(src, SHEET), MONTH,
                                str(tmp_path / "o.xlsx"), progress_cb=seen.append)
    assert seen == sorted(seen) and seen[-1] == 1.0


# ── «Золотые» дампы ─────────────────────────────────────────────────────────

def test_fill_template_cells_golden(wb):
    assert_matches_golden("fill_template_april_2026_cells", dump_cells(wb))


def test_fill_template_conditional_formatting_golden(wb):
    assert_matches_golden("fill_template_april_2026_cf", dump_conditional_formatting(wb))


# ── compare() ───────────────────────────────────────────────────────────────

@pytest.fixture
def compare_result(tmp_path):
    auto, manual = make_compare_pair(str(tmp_path / "auto.xlsx"), str(tmp_path / "manual.xlsx"))
    result = compare_schedules.compare(auto, manual)
    book = load_workbook(result.path)
    yield result, book
    book.close()


def test_compare_counts_the_planted_differences(compare_result):
    result, _ = compare_result
    # день 2 у Иванова: и время, и часы отличаются → 2 расхождения
    assert result.diffs == 2


def test_compare_report_keeps_only_data_sheets(compare_result):
    _, book = compare_result
    assert book.sheetnames == ["Терапия", "МИБС"]


def test_compare_golden_cells(compare_result):
    _, book = compare_result
    assert_matches_golden("compare_april_2026_cells", dump_cells(book))
