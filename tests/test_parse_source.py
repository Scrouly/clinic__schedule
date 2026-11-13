"""parse_source: чтение сводного графика (объединённые ячейки, блоки врачей, пары «Смена/Часы»).

Эти тесты — страховка для пакетов «perf-core» (замена df.iloc на numpy) и «drop-pandas»
(чтение без pandas): поведение должно остаться ровно таким же. Часть проверок описывает
то, что код делает СЕЙЧАС (характеризация), а не то, что «правильно» — такие места помечены."""
import pytest

from core import excel_io
from tests.builders import SrcDoc, make_source_book, standard_source_docs
from tests.golden import assert_matches_golden, dump_records

SHEET = "Апрель 2026"


def _parse(tmp_path, docs, **kw):
    path = make_source_book(str(tmp_path / "src.xlsx"), docs, **kw)
    return excel_io.parse_source(path, SHEET)


def _by_name(records):
    out = {}
    for r in records:
        out.setdefault(r.name, []).append(r)
    return out


# ── Эталон на «типичном» графике ────────────────────────────────────────────

def test_standard_source_golden(tmp_path):
    records = _parse(tmp_path, standard_source_docs())
    assert_matches_golden("parse_source_standard", dump_records(records))


# ── Явные проверки того же графика (читаются без эталона) ───────────────────

def test_names_are_normalized_to_initials_and_order_is_kept(tmp_path):
    records = _parse(tmp_path, standard_source_docs())
    assert [r.name for r in records] == [
        "Иванов И.И.", "Петров П.П.", "Сидорова А.С.", "Козлов И.О.", "Орлов О.О.", "Лишний Л.Л."]


def test_direction_typo_is_corrected(tmp_path):
    records = _by_name(_parse(tmp_path, standard_source_docs()))
    assert records["Петров П.П."][0].direction == "Хирургическое"   # в книге: «хиругическое»


def test_spec_hint_is_the_tail_after_the_full_name(tmp_path):
    records = _by_name(_parse(tmp_path, standard_source_docs()))
    assert records["Иванов И.И."][0].spec_hint == ", врач-терапевт (1,0 ст)"


def test_two_pairs_of_columns_are_combined_into_one_day(tmp_path):
    petrov = _by_name(_parse(tmp_path, standard_source_docs()))["Петров П.П."][0]
    assert petrov.schedule[1].time == "09:00-12:00/14:00-18:00"
    assert petrov.schedule[1].hours == 7.0


def test_name_written_only_over_the_first_column_is_extended_to_hours_column(tmp_path):
    records = _by_name(_parse(tmp_path, standard_source_docs()))
    assert len(records["Сидорова А.С."]) == 1
    assert records["Сидорова А.С."][0].schedule[1].hours == 4.0


def test_total_column_is_not_a_doctor(tmp_path):
    names = [r.name for r in _parse(tmp_path, standard_source_docs())]
    assert not any("итого" in n.lower() for n in names)


def test_decimal_comma_in_hours_and_text_in_shift_cell(tmp_path):
    ivanov = _by_name(_parse(tmp_path, standard_source_docs()))["Иванов И.И."][0]
    assert ivanov.schedule[7].hours == 7.5            # «7,5» → 7.5
    # «вых» остаётся временем смены с нулём часов (кто и как её потом читает — дело write_sheet_data)
    assert (ivanov.schedule[6].time, ivanov.schedule[6].hours) == ("вых", 0.0)


def test_days_without_data_are_absent(tmp_path):
    ivanov = _by_name(_parse(tmp_path, standard_source_docs()))["Иванов И.И."][0]
    assert set(ivanov.schedule) == {1, 2, 3, 6, 7}


def test_negative_hours_fall_back_to_zero(tmp_path):
    docs = [SrcDoc("Тестов Тест Тестович", "", "Консультативное", "1", [{5: ("09:00-10:00", -1)}])]
    rec = _parse(tmp_path, docs)[0]
    assert (rec.schedule[5].time, rec.schedule[5].hours) == ("09:00-10:00", 0.0)


# ── Разбиение на блоки врачей (val != prev_raw_val) ─────────────────────────

def _same(cabinet, day=1):
    return SrcDoc("Иванов Иван Иванович", ", врач-терапевт (1,0 ст)", "Консультативное", cabinet,
                  [{day: ("09:00-12:00", 3)}])


def test_same_person_in_two_cabinets_gives_two_records(tmp_path):
    records = _parse(tmp_path, [_same("101"), _same("102", day=2)])
    assert [(r.name, r.cabinet) for r in records] == [("Иванов И.И.", "101"), ("Иванов И.И.", "102")]


def test_identical_neighbours_in_the_same_cabinet_are_one_block(tmp_path):
    # Характеризация: два соседних блока с одинаковой строкой «Специалист» считаются одним врачом.
    records = _parse(tmp_path, [_same("101", day=1), _same("101", day=2)])
    assert len(records) == 1
    assert set(records[0].schedule) == {1, 2}


def test_same_person_in_the_same_cabinet_separated_by_another_doctor_gives_two_records(tmp_path):
    other = SrcDoc("Петров Пётр Петрович", ", врач-хирург (1,0 ст)", "Хирургическое", "205",
                   [{1: ("09:00-12:00", 3)}])
    records = _parse(tmp_path, [_same("101", day=1), other, _same("101", day=2)])
    assert [r.name for r in records] == ["Иванов И.И.", "Петров П.П.", "Иванов И.И."]


# ── Ошибки и служебное ──────────────────────────────────────────────────────

def test_missing_label_rows_raise_a_readable_error(tmp_path):
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.title = SHEET
    wb.active["A1"] = "Что-то другое"
    path = str(tmp_path / "empty.xlsx")
    wb.save(path)
    with pytest.raises(ValueError, match="не найдены строки"):
        excel_io.parse_source(path, SHEET)


def test_unknown_sheet_is_reported_and_reraised(tmp_path):
    path = make_source_book(str(tmp_path / "src.xlsx"), standard_source_docs())
    with pytest.raises(Exception):
        excel_io.parse_source(path, "Май 2026")


def test_progress_callback_is_called_in_order(tmp_path):
    calls = []
    path = make_source_book(str(tmp_path / "src.xlsx"), standard_source_docs())
    excel_io.parse_source(path, SHEET, progress_cb=calls.append)
    assert calls == [0.05, 0.20, 0.30]
