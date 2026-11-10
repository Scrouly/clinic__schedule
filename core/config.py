"""
config.py — Модуль управления конфигурацией приложения.
Загружает, хранит и обновляет настройки из JSON-файла.
"""

import copy
import json
import os

CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "auto_schedule_config.json"
)

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

def load_config() -> dict:
    # Всегда работаем с глубокой копией — DEFAULT_CONFIG никогда не мутирует
    defaults = copy.deepcopy(DEFAULT_CONFIG)

    if not os.path.exists(CONFIG_FILE):
        defaults["holidays_by"] = sorted(
            defaults.get("holidays_by", []), key=lambda x: (x[0], x[1])
        )
        defaults["transfers_work_days"] = sorted(
            defaults.get("transfers_work_days", []), key=lambda x: (x[0], x[1], x[2])
        )
        defaults["transfers_rest_days"] = sorted(
            defaults.get("transfers_rest_days", []), key=lambda x: (x[0], x[1], x[2])
        )
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(defaults, f, ensure_ascii=False, indent=4)
        return defaults

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    changed = False

    # Миграция: добавляем ключи из DEFAULT_CONFIG, которых ещё нет в файле пользователя.
    # Это позволяет новым версиям программы подхватывать новые настройки без потери старых.
    for key, default_value in defaults.items():
        if key not in config:
            config[key] = copy.deepcopy(default_value)
            changed = True

    # Сортировка обычных праздников
    if "holidays_by" in config:
        sorted_holidays = sorted(config["holidays_by"], key=lambda x: (x[0], x[1]))
        if config["holidays_by"] != sorted_holidays:
            config["holidays_by"] = sorted_holidays
            changed = True

    # Сортировка рабочих переносов
    if "transfers_work_days" in config:
        sorted_tw = sorted(config["transfers_work_days"], key=lambda x: (x[0], x[1], x[2]))
        if config["transfers_work_days"] != sorted_tw:
            config["transfers_work_days"] = sorted_tw
            changed = True

    # Сортировка выходных переносов
    if "transfers_rest_days" in config:
        sorted_tr = sorted(config["transfers_rest_days"], key=lambda x: (x[0], x[1], x[2]))
        if config["transfers_rest_days"] != sorted_tr:
            config["transfers_rest_days"] = sorted_tr
            changed = True

    if changed:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)

    return config

# Глобальные переменные настроек
CONFIG = load_config()
HOLIDAYS = set(tuple(x) for x in CONFIG.get("holidays_by", []))

def reload_config() -> None:
    global CONFIG, HOLIDAYS
    CONFIG = load_config()
    HOLIDAYS = set(tuple(x) for x in CONFIG.get("holidays_by", []))