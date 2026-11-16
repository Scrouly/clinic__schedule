"""Баги №3 и №4: логи после смены темы и дубли в логе."""
import logging
import threading

import pytest

from gui.log_handler import (
    COMPARE_LOGGERS,
    GENERATE_LOGGERS,
    TextboxHandler,
    bind_textbox,
    detach_all_textbox_handlers,
)


class FakeTextbox:
    """Минимальная замена CTkTextbox. after() только запоминает колбэк (как настоящий Tk —
    колбэк выполняет главный цикл), pump() выполняет накопленное. Любое обращение к виджету
    не из главного потока — ошибка: Tk не потокобезопасен."""

    def __init__(self):
        self.text = ""
        self.destroyed = False
        self.pending = {}
        self.configure_calls = []
        self._next = 0
        self._main = threading.get_ident()

    def _alive(self):
        if self.destroyed:
            raise RuntimeError("виджет уничтожен")
        assert threading.get_ident() == self._main, "виджет тронут не из главного потока"

    def after(self, ms, fn):
        self._alive()
        self._next += 1
        self.pending[self._next] = fn
        return str(self._next)

    def after_cancel(self, job):
        self.pending.pop(int(job), None)

    def pump(self):
        """Один оборот главного цикла: выполняет колбэки, стоявшие в очереди на этот момент."""
        batch, self.pending = self.pending, {}
        for fn in batch.values():
            fn()

    def configure(self, **kw):
        self._alive()
        self.configure_calls.append(kw)

    def insert(self, index, text, tag=None):
        self._alive()
        self.text += text

    def see(self, index):
        self._alive()

    def index(self, index):
        self._alive()
        lines = self.text.split("\n")
        return f"{len(lines)}.{len(lines[-1])}"

    def delete(self, start, end):
        self._alive()
        assert start == "1.0" and end.endswith(".0")
        self.text = "\n".join(self.text.split("\n")[int(end.split(".")[0]) - 1:])

    @property
    def lines(self):
        return self.text.splitlines()

    def count(self, needle):
        self.pump()
        return self.text.count(needle)


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



# ── очередь: запись в виджет только из главного потока, пачками ────────────────

def test_records_from_worker_threads_touch_the_widget_only_in_the_main_loop():
    box = FakeTextbox()
    bind_textbox(GENERATE_LOGGERS, box)
    log = logging.getLogger("core.auto_schedule")
    worker = threading.Thread(target=lambda: [log.info(f"из-потока-{i}") for i in range(200)])
    worker.start()
    worker.join()
    assert box.text == ""                       # до оборота цикла виджет не тронут
    box.pump()
    assert box.count("из-потока-") == 200
    assert box.lines[0].endswith("из-потока-0") and box.lines[-1].endswith("из-потока-199")   # порядок сохранён


def test_a_burst_of_records_is_inserted_in_one_batch():
    box = FakeTextbox()
    bind_textbox(GENERATE_LOGGERS, box)
    for i in range(500):
        logging.getLogger("core.auto_schedule").info(f"строка {i}")
    box.configure_calls.clear()
    box.pump()
    assert box.configure_calls == [{"state": "normal"}, {"state": "disabled"}]


def test_text_is_trimmed_to_the_last_lines():
    box = FakeTextbox()
    handler = bind_textbox(GENERATE_LOGGERS, box)
    handler.max_lines = 100
    for i in range(250):
        logging.getLogger("core.auto_schedule").info(f"запись-{i:03d}")
    box.pump()
    assert len(box.lines) == 100
    assert box.lines[0].endswith("запись-150") and box.lines[-1].endswith("запись-249")


def test_flush_loop_keeps_running_until_the_handler_is_detached():
    box = FakeTextbox()
    bind_textbox(GENERATE_LOGGERS, box)
    for round_no in range(3):
        logging.getLogger("core.auto_schedule").info(f"тик-{round_no}")
        box.pump()
        assert box.text.count(f"тик-{round_no}") == 1
    detach_all_textbox_handlers()
    assert box.pending == {}                    # цикл остановлен, ничего не висит в Tk


def test_destroyed_widget_stops_the_loop_without_errors():
    box = FakeTextbox()
    bind_textbox(GENERATE_LOGGERS, box)
    logging.getLogger("core.auto_schedule").info("ещё-жив")
    box.destroyed = True
    box.pump()                                  # колбэк видит мёртвый виджет — тихо останавливается
    assert box.pending == {}
    for _ in range(3):
        logging.getLogger("core.auto_schedule").info("в-пустоту")   # и не копит память бесконечно


def test_queue_is_bounded_when_nobody_drains_it():
    box = FakeTextbox()
    handler = bind_textbox(GENERATE_LOGGERS, box)
    for i in range(handler.MAX_QUEUE + 500):
        logging.getLogger("core.auto_schedule").info(f"x{i}")
    assert len(handler._queue) == handler.MAX_QUEUE


def test_standard_levels_and_markers_still_render():
    box = FakeTextbox()
    bind_textbox(GENERATE_LOGGERS, box)
    log = logging.getLogger("core.excel_io")
    log.warning("предупр")
    log.error("ошибка")
    log.info("§OK§ готово")
    log.info("§HDR§ Раздел")
    box.pump()
    assert "⚠  предупр" in box.text and "✕  ошибка" in box.text
    assert "✓  готово" in box.text and "  Раздел" in box.text


def test_debug_records_do_not_reach_the_window_by_default():
    box = FakeTextbox()
    bind_textbox(GENERATE_LOGGERS, box)
    logging.getLogger("core.auto_schedule").debug("отладка-не-для-окна")
    assert box.count("отладка-не-для-окна") == 0


def test_closed_handler_drops_records_and_its_queue():
    box = FakeTextbox()
    handler = bind_textbox(GENERATE_LOGGERS, box)
    logging.getLogger("core.auto_schedule").info("до-закрытия")
    handler.close()
    assert len(handler._queue) == 0
    handler.emit(logging.LogRecord("core.auto_schedule", logging.INFO, "", 0, "после-закрытия", None, None))
    assert len(handler._queue) == 0


def test_trimming_starts_exactly_one_line_over_the_limit():
    box = FakeTextbox()
    handler = bind_textbox(GENERATE_LOGGERS, box)
    handler.max_lines = 100
    for i in range(100):
        logging.getLogger("core.auto_schedule").info(f"s{i:03d}")
    box.pump()
    assert len(box.lines) == 100 and box.lines[0].endswith("s000")      # ровно по лимиту — не режем
    logging.getLogger("core.auto_schedule").info("s100")
    box.pump()
    assert len(box.lines) == 100 and box.lines[0].endswith("s001")
