"""Баги №3 и №4: логи после смены темы и дубли в логе."""
import logging

import pytest

from gui.log_handler import (
    COMPARE_LOGGERS,
    GENERATE_LOGGERS,
    TextboxHandler,
    bind_textbox,
    detach_all_textbox_handlers,
)


class FakeTextbox:
    """Минимальная замена CTkTextbox: after() выполняет колбэк сразу."""

    def __init__(self):
        self.lines = []
        self.destroyed = False

    def after(self, ms, fn):
        if self.destroyed:
            raise RuntimeError("виджет уничтожен")
        fn()

    def configure(self, **kw):
        pass

    def insert(self, index, text, tag=None):
        self.lines.append(text)

    def see(self, index):
        pass

    def count(self, needle):
        return sum(needle in line for line in self.lines)


@pytest.fixture(autouse=True)
def _clean_handlers():
    detach_all_textbox_handlers()
    yield
    detach_all_textbox_handlers()


def test_core_logger_names_match_gui_bindings():
    from core import auto_schedule, compare_schedules
    assert auto_schedule.logger.name in GENERATE_LOGGERS
    assert compare_schedules.logger.name in COMPARE_LOGGERS


def test_generation_log_reaches_generate_box_exactly_once():
    gen = FakeTextbox()
    bind_textbox(GENERATE_LOGGERS, gen)
    logging.getLogger("core.auto_schedule").info("привет-генерация")
    assert gen.count("привет-генерация") == 1


def test_compare_log_does_not_leak_into_generate_box():
    gen, cmp_ = FakeTextbox(), FakeTextbox()
    bind_textbox(GENERATE_LOGGERS, gen)
    bind_textbox(COMPARE_LOGGERS, cmp_)
    logging.getLogger("core.compare_schedules").info("привет-сравнение")
    assert cmp_.count("привет-сравнение") == 1
    assert gen.count("привет-сравнение") == 0


def test_no_textbox_handler_on_root_logger():
    bind_textbox(GENERATE_LOGGERS, FakeTextbox())
    bind_textbox(COMPARE_LOGGERS, FakeTextbox())
    assert not any(isinstance(h, TextboxHandler) for h in logging.getLogger().handlers)


def test_rebind_after_theme_change_goes_only_to_new_box():
    old, new = FakeTextbox(), FakeTextbox()
    bind_textbox(GENERATE_LOGGERS, old)
    old.destroyed = True            # _rebuild_ui уничтожил виджеты
    detach_all_textbox_handlers()
    bind_textbox(GENERATE_LOGGERS, new)
    logging.getLogger("core.excel_io").warning("после-пересборки")  # не должно падать
    assert new.count("после-пересборки") == 1


def test_bind_twice_does_not_duplicate_lines():
    box = FakeTextbox()
    bind_textbox(GENERATE_LOGGERS, box)
    bind_textbox(GENERATE_LOGGERS, box)
    logging.getLogger("core.auto_schedule").info("один-раз")
    assert box.count("один-раз") == 1


def test_detach_all_removes_handlers_from_every_logger():
    bind_textbox(GENERATE_LOGGERS, FakeTextbox())
    bind_textbox(COMPARE_LOGGERS, FakeTextbox())
    detach_all_textbox_handlers()
    for name in (*GENERATE_LOGGERS, *COMPARE_LOGGERS, ""):
        assert not any(isinstance(h, TextboxHandler) for h in logging.getLogger(name).handlers)


def test_destroyed_widget_does_not_break_logging_call():
    box = FakeTextbox()
    bind_textbox(GENERATE_LOGGERS, box)
    box.destroyed = True            # виджет умер, а хендлер ещё привязан
    logging.getLogger("core.auto_schedule").info("не-должно-падать")  # исключения быть не должно
