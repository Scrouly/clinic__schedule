"""Диагностический отчёт и тексты сообщений: сомнительные назначения видны,
в логе нет дублей, ошибка источника написана по-человечески."""
import logging

import pytest
from openpyxl import Workbook

from core import auto_schedule, compare_schedules, excel_io
from core.models import DiagReport
from tests.test_compare_schedules import _make_book


def _dubious_report(n: int = 1) -> DiagReport:
    rep = DiagReport(month_str="апрель 2026")
    for i in range(n):
        rep.dubious.append({
            "name": f"Иванов И.{i}.", "sheet": "Консультативное",
            "title": "врач-невролог (1,0 ст.)", "score": 1.2,
            "direction": "Терапия", "cabinet": "201к",
        })
    return rep


def test_dubious_assignments_are_listed_in_excel_report():
    wb = Workbook()
    auto_schedule._write_diag_to_excel(wb, _dubious_report())
    ws = wb["Отчет_по_ошибкам"]
    text = " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value)
    assert "СОМНИТЕЛЬНЫЕ НАЗНАЧЕНИЯ" in text
    assert "Иванов И.0." in text


def test_dubious_count_in_log_points_to_excel_sheet(caplog):
    with caplog.at_level(logging.INFO, logger=auto_schedule.logger.name):
        auto_schedule._print_diag_report(_dubious_report(3))
    messages = [r.getMessage() for r in caplog.records]
    assert any("Сомнительных назначений: 3" in m and "Отчет_по_ошибкам" in m for m in messages)


def test_compare_success_message_is_logged_once(tmp_path, caplog):
    auto, manual = str(tmp_path / "auto.xlsx"), str(tmp_path / "manual.xlsx")
    _make_book(auto)
    _make_book(manual)
    with caplog.at_level(logging.INFO, logger=compare_schedules.logger.name):
        compare_schedules.compare(auto, manual)
    done = [r.getMessage() for r in caplog.records if "успешно сгенерирован" in r.getMessage()]
    assert len(done) == 1


def test_parse_source_error_uses_row_labels_not_internal_keys(tmp_path):
    path = str(tmp_path / "source.xlsx")
    wb = Workbook()
    ws = wb.active
    ws.title = "Апрель 2026"
    ws["A1"] = "Отделение"          # строк «Кабинет», «Специалист», «Дата» нет
    wb.save(path)
    with pytest.raises(ValueError) as exc:
        excel_io.parse_source(path, "Апрель 2026")
    text = str(exc.value)
    assert "«Кабинет»" in text and "«Специалист»" in text and "«Дата»" in text
    assert "cabinet" not in text
