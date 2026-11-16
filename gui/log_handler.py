"""
log_handler.py — TextboxHandler: пишет форматированные лог-сообщения в CTkTextbox.

Маркеры сообщений:
  §HDR§   — заголовок секции
  §STAT§  — строка статистики (ключ: значение)
  §SEP§   — пустая строка-разделитель
  §OK§    — успех
  §WARN§  — предупреждение
  §ERR§   — ошибка
  §INFO§  — информация
  §DETAIL§— детали
  §DOC§   — имя документа
  §DAYS§  — строка с расписанием дней (день: время, ...)
  §DBG§   — отладка
"""
import logging
import logging.handlers
import sys
from collections import deque

# Какие логгеры core.* пишут в какую страницу GUI. Имена — это __name__ модулей
# (core.auto_schedule, core.excel_io, core.compare_schedules). Хендлеры вешаются
# ТОЛЬКО на них, а не на корневой логгер: иначе записи приходят дважды, логи
# сравнения попадают на страницу генерации, а после пересборки интерфейса
# (смена темы) корневой хендлер остаётся привязанным к уничтоженному виджету.
GENERATE_LOGGERS = ("core.auto_schedule", "core.excel_io")
COMPARE_LOGGERS = ("core.compare_schedules",)


class TextboxHandler(logging.Handler):
    """Направляет записи логгера в виджет CTkTextbox с цветовым форматированием.

    emit() только кладёт запись в очередь — к виджету он не обращается, поэтому его можно
    вызывать из любого потока. Один цикл на главном потоке (раз в FLUSH_MS) вставляет накопленное
    пачкой и обрезает текст до последних max_lines строк."""

    FLUSH_MS = 50
    MAX_QUEUE = 20000       # защита от бесконечного роста, если цикл остановлен
    MAX_LINES = 5000

    def __init__(self, textbox):
        super().__init__()
        self.textbox = textbox
        self.max_lines = self.MAX_LINES
        self._queue: deque = deque(maxlen=self.MAX_QUEUE)
        self._job = None
        self._closed = False
        self._schedule()            # конструктор вызывается из главного потока

    # ── приём записей (любой поток) ───────────────────────────────────────────

    def emit(self, record: logging.LogRecord) -> None:
        if self._closed:
            return
        self._queue.append((record.getMessage(), record.levelno))

    # ── цикл на главном потоке ────────────────────────────────────────────────

    def _schedule(self) -> None:
        try:
            self._job = self.textbox.after(self.FLUSH_MS, self._tick)
        except Exception:           # виджет уничтожен (например, при смене темы)
            self._job = None
            self._closed = True

    def _tick(self) -> None:
        self._job = None
        if self._closed:
            return
        self.flush()
        if not self._closed:
            self._schedule()

    def flush(self) -> None:
        """Вставляет накопленные записи одной пачкой. Только из главного потока."""
        if not self._queue or self._closed:
            return
        batch = []
        while True:
            try:
                batch.append(self._queue.popleft())
            except IndexError:
                break
        tb = self.textbox
        try:
            tb.configure(state="normal")
            for msg, level in batch:
                self._render(tb, msg, level)
            self._trim(tb)
            tb.see("end")
            tb.configure(state="disabled")
        except Exception:           # виджет умер посреди вставки — цикл больше не нужен
            self._closed = True
            self._queue.clear()

    def _trim(self, tb) -> None:
        total = int(tb.index("end-1c").split(".")[0]) - 1
        if total > self.max_lines:
            tb.delete("1.0", f"{total - self.max_lines + 1}.0")

    def close(self) -> None:
        """Останавливает цикл. Вызывается перед уничтожением виджета и при повторной привязке."""
        self._closed = True
        job, self._job = self._job, None
        if job is not None:
            try:
                self.textbox.after_cancel(job)
            except Exception:
                pass
        self._queue.clear()
        super().close()

    # ── оформление одной записи ───────────────────────────────────────────────

    @staticmethod
    def _render(tb, msg: str, level: int) -> None:
        if msg.startswith("§DBG§"):
            tb.insert("end", f"   {msg[5:].strip()}\n", "dbg")

        elif msg.startswith("§HDR§"):
            text = msg[5:].strip()
            tb.insert("end", "\n", "body")
            tb.insert("end", f"  {text}\n", "header")
            tb.insert("end", "  " + "─" * 52 + "\n", "body")

        elif msg.startswith("§SEP§"):
            tb.insert("end", "\n", "body")

        elif msg.startswith("§OK§"):
            tb.insert("end", f"✓  {msg[4:].strip()}\n", "success")

        elif msg.startswith("§INFO§"):
            tb.insert("end", f"   {msg[6:].strip()}\n", "body")

        elif msg.startswith("§WARN§"):
            tb.insert("end", f"⚠  {msg[6:].strip()}\n", "warning")

        elif msg.startswith("§ERR§"):
            tb.insert("end", f"✕  {msg[5:].strip()}\n", "error")

        elif msg.startswith("§STAT§"):
            tb.insert("end", f"   {msg[6:].strip()}\n", "stat")

        elif msg.startswith("§DETAIL§"):
            tb.insert("end", f"      {msg[8:].strip()}\n", "detail")

        elif msg.startswith("§DOC§"):
            tb.insert("end", f"\n  📋 {msg[5:].strip()}\n", "doc_name")

        elif msg.startswith("§DAYS§"):
            parts = [p.strip() for p in msg[6:].strip().split(",") if p.strip()]
            tb.insert("end", "     ", "body")
            for i, part in enumerate(parts):
                if ":" in part:
                    label, _, time = part.partition(":")
                    tb.insert("end", label.strip() + ": ", "days_label")
                    tb.insert("end", time.strip(), "days_time")
                else:
                    tb.insert("end", part, "days_time")
                if i < len(parts) - 1:
                    tb.insert("end", "   ·   ", "separator")
            tb.insert("end", "\n", "body")

        # --- стандартные уровни логирования ---
        elif level == logging.WARNING:
            tb.insert("end", f"⚠  {msg}\n", "warning")

        elif level == logging.ERROR:
            tb.insert("end", f"✕  {msg}\n", "error")

        else:
            tb.insert("end", f"   {msg}\n", "body")


def detach_all_textbox_handlers() -> None:
    """Снимает все TextboxHandler со всех логгеров, включая корневой.
    Вызывается перед уничтожением виджетов (смена темы) и перед повторной привязкой."""
    loggers = [logging.getLogger()]
    loggers += [lg for lg in logging.Logger.manager.loggerDict.values()
                if isinstance(lg, logging.Logger)]
    for lg in loggers:
        for h in lg.handlers[:]:
            if isinstance(h, TextboxHandler):
                lg.removeHandler(h)
                h.close()


def bind_textbox(logger_names, textbox, level: int = logging.INFO) -> TextboxHandler:
    """Привязывает textbox к перечисленным логгерам (один общий хендлер).
    Старые TextboxHandler на этих логгерах предварительно снимаются и останавливаются —
    повторный вызов не создаёт дублей.

    Окно показывает только INFO и выше: отладка (бывшие print) в него не попадает.
    Уровень самих логгеров не трогаем — им управляет configure_logging."""
    handler = TextboxHandler(textbox)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(message)s"))
    for name in logger_names:
        lg = logging.getLogger(name)
        for h in lg.handlers[:]:
            if isinstance(h, TextboxHandler):
                lg.removeHandler(h)
                h.close()
        if lg.getEffectiveLevel() > level:
            lg.setLevel(level)
        lg.addHandler(handler)
    return handler


def configure_logging(log_file: str, debug: bool = False) -> None:
    """Файл (с ротацией) и консоль на корневом логгере.

    Уровень хендлеров задан явно: по умолчанию INFO, при debug=True — DEBUG. Окно страницы
    показывает INFO и выше при любом режиме (см. bind_textbox)."""
    level = logging.DEBUG if debug else logging.INFO
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    console = logging.StreamHandler(sys.stdout)
    for h in (file_handler, console):
        h.setLevel(level)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[file_handler, console],
        force=True,
    )
    logging.getLogger("core").setLevel(level)
