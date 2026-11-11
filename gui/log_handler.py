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

# Какие логгеры core.* пишут в какую страницу GUI. Имена — это __name__ модулей
# (core.auto_schedule, core.excel_io, core.compare_schedules). Хендлеры вешаются
# ТОЛЬКО на них, а не на корневой логгер: иначе записи приходят дважды, логи
# сравнения попадают на страницу генерации, а после пересборки интерфейса
# (смена темы) корневой хендлер остаётся привязанным к уничтоженному виджету.
GENERATE_LOGGERS = ("core.auto_schedule", "core.excel_io")
COMPARE_LOGGERS = ("core.compare_schedules",)


class TextboxHandler(logging.Handler):
    """Направляет записи логгера в виджет CTkTextbox с цветовым форматированием."""

    def __init__(self, textbox):
        super().__init__()
        self.textbox = textbox

    def emit(self, record: logging.LogRecord) -> None:
        msg = record.getMessage()
        level = record.levelno

        def append():
            try:
                tb = self.textbox
                tb.configure(state="normal")

                # --- ПЕРЕХВАТ ВСЕХ ВОЗМОЖНЫХ МАРКЕРОВ ---
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

                # --- ОБРАБОТКА СТАНДАРТНЫХ УРОВНЕЙ ЛОГИРОВАНИЯ ---
                elif level == logging.WARNING:
                    tb.insert("end", f"⚠  {msg}\n", "warning")

                elif level == logging.ERROR:
                    tb.insert("end", f"✕  {msg}\n", "error")

                else:
                    tb.insert("end", f"   {msg}\n", "body")

                tb.see("end")
                tb.configure(state="disabled")
            except Exception as e:
                print(f"[UI ERROR в TextboxHandler]: {e}")

        try:
            self.textbox.after(0, append)
        except Exception:
            # Виджет уже уничтожен (например, при смене темы) — не роняем
            # вызывающий код, который просто что-то залогировал.
            self.handleError(record)


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


def bind_textbox(logger_names, textbox, level: int = logging.DEBUG) -> TextboxHandler:
    """Привязывает textbox к перечисленным логгерам (один общий хендлер).
    Старые TextboxHandler на этих логгерах предварительно снимаются — повторный
    вызов не создаёт дублей."""
    handler = TextboxHandler(textbox)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(message)s"))
    for name in logger_names:
        lg = logging.getLogger(name)
        for h in lg.handlers[:]:
            if isinstance(h, TextboxHandler):
                lg.removeHandler(h)
        if lg.getEffectiveLevel() > level:
            lg.setLevel(level)
        lg.addHandler(handler)
    return handler
