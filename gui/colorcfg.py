"""Работа с цветами Excel в настройках (без tkinter, чтобы проверять тестами)."""


def normalize_color(color):
    """Добавляет «#» к цвету, записанному без него («FFB6C1» → «#FFB6C1»).
    Пустое значение возвращается как есть."""
    if color and not color.startswith("#"):
        return "#" + color
    return color


def set_excel_color(cfg: dict, key: str, color: str) -> None:
    """Записывает выбранный цвет в cfg["excel_colors"][key] (заглавными буквами)."""
    cfg.setdefault("excel_colors", {})[key] = color.upper()
