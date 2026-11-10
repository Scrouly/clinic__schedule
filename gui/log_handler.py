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

        self.textbox.after(0, append)