"""
config.py — Модуль управления конфигурацией приложения.
Загружает, хранит и обновляет настройки из JSON-файла.
"""

import copy
import json
import os
import sys
import tempfile
from typing import Optional

from . import holidays


def _config_dir() -> str:
    """Папка с конфигом: в собранном .exe — рядом с программой (как в gui/app.py),
    иначе корень проекта. Раньше core искал файл внутри временной папки сборки,
    а GUI — рядом с .exe, то есть два разных файла."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _config_file() -> str:
    """Путь к файлу конфига. Переменная окружения CITYCLINIC_CONFIG нужна тестам и
    скрипту tools/bench.py, чтобы не трогать настоящий конфиг; в обычной работе не задаётся."""
    override = os.environ.get("CITYCLINIC_CONFIG")
    if override:
        return os.path.abspath(override)
    return os.path.join(_config_dir(), "auto_schedule_config.json")


CONFIG_FILE = _config_file()

DEFAULT_CONFIG = {
    "hours_control": {
        "highlight_diff": True,
        "base_norm": 38.5,
        "uzd_norm": 35.0
    },
    "excel_colors": {
        "holiday": "#FFB6C1",
        "weekend": "#CAFFCA",
        "overwork_red": "FFC7CE",
        "underwork_green": "C6EFCE"
    },
    "holidays_by": [
        [1, 1], [1, 2], [1, 7], [3, 8], [4, 21], [5, 1], [5, 9],
        [7, 3], [11, 7], [12, 25]
    ],
    "transfers_work_days": [
        [2026, 4, 25]
    ],
    "transfers_rest_days": [
        [2026, 4, 20]
    ],
    "scoring": {
        "min_accept_score": -0.8,
        "dubious_threshold": 1.5,
        "fuzzy_name_threshold": 0.95
    },
    "special_codes": {
        "вых": "В", "командировка": "К", "отпуск": "О",
        "больничный": "Б", "учеба": "У"
    },
    "month_ru": {
        "январь": 1, "февраль": 2, "март": 3, "апрель": 4,
        "май": 5, "июнь": 6, "июль": 7, "август": 8,
        "сентябрь": 9, "октябрь": 10, "ноябрь": 11, "декабрь": 12
    },
    "title_keywords": {
        "акушер-гинеколог": ["гинеколог", "гинекология"],
        "уролог": ["уролог", "урология"],
        "хирург": ["хирург", "хирургия", "флеболог", "флебология"],
        "пластический": ["пластическ", "пластика"],
        "ортопед": ["ортопед", "травматолог", "травматология"],
        "оториноларинголог": ["лор", "оториноларинголог"],
        "эндокринолог": ["эндокринолог", "эндокринология"],
        "невролог": ["невролог", "неврология"],
        "кардиолог": ["кардиолог", "кардиология"],
        "терапевт": ["терапевт", "терапия"],
        "педиатр": ["педиатр", "педиатрия"],
        "ультразвуковой": ["узи", "ультразвуков"],
        "функциональной": ["фд", "функциональн", "функц"],
        "рентгенолог": ["мрт", "рентген", "кт", "рентгенолог"],
        "косметолог": ["косметолог", "косметология"],
        "дерматовенеролог": ["дерматолог", "венеролог", "дерматовенеролог"],
        "ревматолог": ["ревматолог", "ревматология"],
        "физиотерапевт": ["физиотерапевт", "физиотерапия"],
        "рефлексотерапевт": ["рефлексотерапевт", "рефлексотерапи"],
        "психиатр": ["психиатр", "психотерапевт"],
        "онколог": ["онколог", "онкология"],
        "анестезиолог": ["анестезиолог", "реаниматолог"]
    }
}

class ConfigSaveError(Exception):
    """Настройки не удалось записать; текст можно показывать пользователю как есть."""


def load_config() -> dict:
    """Читает настройки из файла и дополняет значениями по умолчанию. Файл НЕ пишется:
    миграция и сортировка остаются в памяти, на диск попадают при ближайшем save_config()
    (так импорт модуля ничего не создаёт и не перезаписывает)."""
    # Всегда работаем с глубокой копией — DEFAULT_CONFIG никогда не мутирует
    config = copy.deepcopy(DEFAULT_CONFIG)

    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            user_config = json.load(f)
        # Ключи, которых нет в файле, берутся из DEFAULT_CONFIG: новые версии программы
        # подхватывают новые настройки без потери старых.
        config = {**config, **user_config}

    config["holidays_by"] = sorted(config.get("holidays_by", []), key=holidays.sort_key)
    for key in ("transfers_work_days", "transfers_rest_days"):
        config[key] = sorted(config.get(key, []), key=lambda x: (x[0], x[1], x[2]))
    return config


# Глобальный словарь настроек: общий для всех модулей, меняется только на месте.
CONFIG = load_config()


def get_config() -> dict:
    """Текущие настройки (тот же словарь, что и core.utils.CONFIG)."""
    return CONFIG


def update_config(new: dict) -> None:
    """Заменяет содержимое CONFIG на месте. Новый dict не создаётся: на CONFIG ссылаются
    другие модули (utils, auto_schedule, excel_io), и подмена объекта разорвала бы связь.
    Значения копируются, чтобы правки в окне не меняли рабочие настройки до применения."""
    fresh = copy.deepcopy(new)
    for key in [k for k in CONFIG if k not in fresh]:
        del CONFIG[key]
    CONFIG.update(fresh)


def reload_config() -> None:
    """Перечитывает файл и обновляет CONFIG на месте."""
    update_config(load_config())


def save_config(cfg: Optional[dict] = None) -> None:
    """Записывает настройки (по умолчанию — CONFIG) в CONFIG_FILE.

    Запись атомарная: данные сначала целиком сериализуются и пишутся во временный файл рядом,
    затем он заменяет старый. Сбой на любом шаге оставляет прежний файл нетронутым.
    Ошибка — ConfigSaveError с понятным текстом."""
    data = CONFIG if cfg is None else cfg
    target = CONFIG_FILE
    tmp_path = None
    try:
        text = json.dumps(data, ensure_ascii=False, indent=4)
        fd, tmp_path = tempfile.mkstemp(prefix=".cfg-", suffix=".tmp", dir=os.path.dirname(target) or ".")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_path, target)
    except (OSError, TypeError, ValueError) as e:
        raise ConfigSaveError(f"Не удалось сохранить настройки:\n{target}\n\n{e}") from e
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)
