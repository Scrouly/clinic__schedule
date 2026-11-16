"""Сравнение настроек в окне с сохранёнными в файле (для предупреждения при закрытии)."""
import json
from typing import List

from . import norms


def _canon(value):
    """JSON-круг приводит кортежи к спискам и ключи к строкам: так сравнивается то,
    что реально окажется в файле."""
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def unsaved_sections(current: dict, saved: dict) -> List[str]:
    """Разделы настроек, которые в окне отличаются от файла (отсортированы по имени).

    Таблица норм, которой ещё нет в файле, считается равной прежнему поведению
    (norms.rules_for_display) — иначе первое же закрытие окна давало бы ложное предупреждение."""
    current, saved = dict(current), dict(saved)
    for cfg in (current, saved):
        cfg.setdefault("norms_by_specialty", norms.rules_for_display(cfg))
        # uzd_norm — прежнее поле: страницы его уже не пишут (норма УЗД теперь строка таблицы),
        # поэтому его отсутствие в окне не считается правкой.
        cfg["hours_control"] = {k: v for k, v in cfg.get("hours_control", {}).items() if k != "uzd_norm"}
    cur, old = _canon(current), _canon(saved)
    return sorted(k for k in set(cur) | set(old) if cur.get(k) != old.get(k))
