"""Уровни логирования: отладка (бывшие print) не попадает ни в окно, ни в файл, пока её не включили."""
import logging

import pytest

from gui.log_handler import GENERATE_LOGGERS, bind_textbox, configure_logging, detach_all_textbox_handlers
from tests.test_logging_wiring import FakeTextbox
from tests.test_score_match import _rec, _role, _run


@pytest.fixture
def root_logging():
    """configure_logging перенастраивает корневой логгер — возвращаем как было."""
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    core_level = logging.getLogger("core").level
    yield root
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()
    for h in saved[0]:
        root.addHandler(h)
    root.setLevel(saved[1])
    logging.getLogger("core").setLevel(core_level)
    detach_all_textbox_handlers()


def _log_text(path):
    for h in logging.getLogger().handlers:
        h.flush()
    return path.read_text(encoding="utf-8")


def test_info_goes_to_the_file_and_debug_does_not(tmp_path, root_logging):
    log_file = tmp_path / "auto_schedule.log"
    configure_logging(str(log_file), debug=False)
    logging.getLogger("core.auto_schedule").info("обычная-запись")
    logging.getLogger("core.auto_schedule").debug("отладочная-запись")
    text = _log_text(log_file)
    assert "обычная-запись" in text and "отладочная-запись" not in text


def test_debug_mode_writes_debug_to_the_file_but_not_to_the_window(tmp_path, root_logging):
    log_file = tmp_path / "auto_schedule.log"
    configure_logging(str(log_file), debug=True)
    box = FakeTextbox()
    bind_textbox(GENERATE_LOGGERS, box)
    logging.getLogger("core.auto_schedule").debug("отладочная-запись")
    assert "отладочная-запись" in _log_text(log_file)
    assert box.count("отладочная-запись") == 0


def test_binding_a_window_does_not_lower_the_logger_level_for_the_file(tmp_path, root_logging):
    """Раньше bind_textbox ставил логгеру DEBUG, и отладка из логгера шла в файл через корневой хендлер."""
    log_file = tmp_path / "auto_schedule.log"
    configure_logging(str(log_file), debug=False)
    bind_textbox(GENERATE_LOGGERS, FakeTextbox())
    logging.getLogger("core.auto_schedule").debug("отладочная-запись")
    assert "отладочная-запись" not in _log_text(log_file)


def test_matching_trace_is_logged_at_debug_level_not_printed(capsys, caplog):
    role = _role("Терапия", "Врач-терапевт (1,0 ст.)")
    with caplog.at_level(logging.DEBUG, logger="core.auto_schedule"):
        _run({"Иванов И.И.": [role]}, [_rec("Иванов И.И.", "Терапия", "101")])
    assert capsys.readouterr().out == ""
    debug_text = "\n".join(r.getMessage() for r in caplog.records
                           if r.levelno == logging.DEBUG and r.name == "core.auto_schedule")
    assert "Иванов И.И." in debug_text and "Балл" in debug_text and "ИТОГ" in debug_text
    assert not any(r.levelno > logging.DEBUG for r in caplog.records if r.name == "core.auto_schedule")


def test_file_handler_level_is_explicit_so_a_debug_logger_cannot_leak_into_the_file(tmp_path, root_logging):
    """Прежняя ошибка: кто-то ставит логгеру DEBUG, а корневой хендлер без уровня пишет всё."""
    log_file = tmp_path / "auto_schedule.log"
    configure_logging(str(log_file), debug=False)
    noisy = logging.getLogger("core.auto_schedule")
    noisy.setLevel(logging.DEBUG)
    try:
        noisy.debug("утечка-отладки")
    finally:
        noisy.setLevel(logging.NOTSET)
    assert "утечка-отладки" not in _log_text(log_file)
