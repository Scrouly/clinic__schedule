"""
config.py — Модуль управления конфигурацией приложения.
Загружает, хранит и обновляет настройки из JSON-файла.
"""

import copy
import json
import logging
import os
import sys
import tempfile
from typing import List, Optional

from . import holidays

logger = logging.getLogger(__name__)


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
    # [месяц, день] — каждый год; [год, месяц, день] — только в этом году.
    # Радоница «плавающая» (9-й день после Пасхи), поэтому записана с годом.
    "holidays_by": [
        [1, 1], [1, 2], [1, 7], [3, 8], [2026, 4, 21], [5, 1], [5, 9], [2027, 5, 11],
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


# Что не так с файлом настроек при последней загрузке (человеческим языком). Программа с
# --noconsole не показывает traceback, поэтому GUI выводит эти строки в окне при запуске.
LOAD_WARNINGS: List[str] = []


def _read_user_config() -> dict:
    """Содержимое файла настроек. Нечитаемый или испорченный файл не роняет программу:
    он переименовывается в «…json.bak» (чтобы следующее сохранение его не затёрло),
    а работа идёт на значениях по умолчанию."""
    if not os.path.exists(CONFIG_FILE):
        return {}
    problem = None
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        problem = "в файле не словарь настроек"
    except (OSError, ValueError) as e:       # ValueError: и JSONDecodeError, и UnicodeDecodeError
        problem = str(e)

    backup = CONFIG_FILE + ".bak"
    try:
        os.replace(CONFIG_FILE, backup)
        where = f"Испорченный файл сохранён как «{os.path.basename(backup)}»."
    except OSError:
        where = "Переименовать испорченный файл не удалось, он будет перезаписан при сохранении."
    msg = f"Файл настроек не прочитан ({problem}). Используются значения по умолчанию. {where}"
    logger.warning(msg)
    LOAD_WARNINGS.append(msg)
    return {}


def _clean_transfers(entries) -> list:
    """Переносы дней: оставляем только записи [год, месяц, день] из целых чисел."""
    good = []
    for e in entries:
        try:
            if not isinstance(e, (list, tuple)) or len(e) != 3 or any(isinstance(x, (bool, float)) for x in e):
                raise ValueError
            good.append([int(x) for x in e])
        except (TypeError, ValueError):
            msg = f"Пропущена некорректная запись переноса дня: {e!r}"
            logger.warning(msg)
            LOAD_WARNINGS.append(msg)
    return good


def load_config() -> dict:
    """Читает настройки из файла и дополняет значениями по умолчанию. Исправный файл НЕ пишется:
    миграция и сортировка остаются в памяти, на диск попадают при ближайшем save_config()
    (так импорт модуля ничего не создаёт и не перезаписывает). Испорченный файл переименовывается
    в «.bak» — см. _read_user_config."""
    LOAD_WARNINGS.clear()
    # Всегда работаем с глубокой копией — DEFAULT_CONFIG никогда не мутирует
    config = copy.deepcopy(DEFAULT_CONFIG)

    user_config = _read_user_config()
    # Раздел неверного вида (например, "holidays_by": null) заменяется значением по умолчанию:
    # иначе дальше всё падало бы с непонятной ошибкой.
    for key, default in DEFAULT_CONFIG.items():
        if key in user_config and not isinstance(user_config[key], type(default)):
            msg = f"Раздел «{key}» в файле настроек имеет неверный вид, взято значение по умолчанию."
            logger.warning(msg)
            LOAD_WARNINGS.append(msg)
            del user_config[key]
    # Ключи, которых нет в файле, берутся из DEFAULT_CONFIG: новые версии программы
    # подхватывают новые настройки без потери старых.
    config = {**config, **user_config}

    config["holidays_by"] = sorted(config.get("holidays_by", []), key=holidays.sort_key)
    for key in ("transfers_work_days", "transfers_rest_days"):
        config[key] = sorted(_clean_transfers(config.get(key, [])))
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
