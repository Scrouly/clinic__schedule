"""
norms.py — нормы часов по специальностям и ставкам.

Таблица хранится в конфиге в ключе "norms_by_specialty":

    [
        {"keywords": ["ультразвуков", "узд"], "rate": 1.0,  "weekly": 35.0},
        {"keywords": ["хирург"],              "rate": null, "weekly": 30.8}
    ]

keywords — слова из названия должности (с начала слова, регистр и «ё» не важны).
rate     — ставка, для которой задана норма; null = «Любая».
weekly   — часов В НЕДЕЛЮ:
             • для конкретной ставки — именно при этой ставке (без умножения);
             • для «Любая» — на 1,0 ставки, для неполной ставки умножается на её долю.

Выбор строки для должности: среди строк, чьи слова нашлись в названии,
1) строка с точно совпавшей ставкой; 2) строка «Любая» (× доля ставки);
3) если ничего нет — базовая норма (на 1,0 ставки) × доля ставки.
При равенстве побеждает строка, стоящая выше в таблице.
"""
import re
from decimal import Decimal
from typing import List, Optional, Sequence, Tuple

MAX_WEEKLY_HOURS = 60.0
MAX_RATE = 2.0

# Прежнее поведение, пока таблица в конфиге не сохранена: отдельная норма УЗД
# только на полной ставке.
LEGACY_UZD_KEYWORDS = ["ультразвуков", "узд"]


class NormsError(ValueError):
    """Ошибка ввода норм — текст предназначен для показа пользователю."""


# ── Разбор ввода из GUI ──────────────────────────────────────────────────────

def _to_float(raw) -> float:
    return float(str(raw).strip().replace(",", "."))


def parse_weekly(raw, label: str = "Норма") -> float:
    """Часы в неделю: число в диапазоне (0, MAX_WEEKLY_HOURS]."""
    try:
        value = _to_float(raw)
    except ValueError:
        raise NormsError(f"{label}: «{str(raw).strip()}» — не число (например, 38.5).") from None
    if not (0 < value <= MAX_WEEKLY_HOURS):
        raise NormsError(
            f"{label}: {value:g} вне диапазона 0–{MAX_WEEKLY_HOURS:g}. "
            f"Указывайте часы в неделю (например, 38.5), а не за месяц."
        )
    return value


def parse_rate(raw) -> Optional[float]:
    """Ставка: пусто/«Любая» → None, иначе число в диапазоне (0, MAX_RATE]."""
    text = str(raw).strip().lower()
    if text in ("", "любая", "any", "*"):
        return None
    try:
        value = _to_float(text)
    except ValueError:
        raise NormsError(f"ставка «{str(raw).strip()}» — не число (например, 0,5) и не «Любая».") from None
    if not (0 < value <= MAX_RATE):
        raise NormsError(f"ставка {value:g} вне диапазона 0–{MAX_RATE:g}.")
    return value


def _norm_text(s: str) -> str:
    return str(s).lower().replace("ё", "е")


def parse_keywords(raw) -> List[str]:
    return [w.strip() for w in _norm_text(raw).split(",") if w.strip()]


def parse_norm_rules(rows: Sequence[Tuple[str, str, str]]) -> List[dict]:
    """rows — (ключевые слова, ставка, часов в неделю) как строки из полей GUI.
    Полностью пустые строки пропускаются. При ошибке бросает NormsError с номером строки."""
    rules: List[dict] = []
    seen = set()
    for i, (kw_raw, rate_raw, weekly_raw) in enumerate(rows, 1):
        keywords = parse_keywords(kw_raw)
        if not keywords and not str(weekly_raw).strip():
            continue
        try:
            if not keywords:
                raise NormsError("не заполнены ключевые слова специальности.")
            rate = parse_rate(rate_raw)
            weekly = parse_weekly(weekly_raw, "часов в неделю")
        except NormsError as e:
            raise NormsError(f"Строка {i}: {e}") from None
        key = (frozenset(keywords), rate)
        if key in seen:
            raise NormsError(f"Строка {i}: повтор — такая специальность с этой ставкой уже есть выше.")
        seen.add(key)
        rules.append({"keywords": keywords, "rate": rate, "weekly": weekly})
    return rules


# ── Конфиг ───────────────────────────────────────────────────────────────────

def legacy_rules(uzd_norm: float) -> List[dict]:
    return [{"keywords": list(LEGACY_UZD_KEYWORDS), "rate": 1.0, "weekly": float(uzd_norm)}]


def rules_for_display(cfg: dict) -> List[dict]:
    """Строки таблицы для страницы «Нормы часов». Если таблица ещё не сохранялась,
    показываем прежнее поведение (строка УЗД из hours_control.uzd_norm)."""
    rules = cfg.get("norms_by_specialty")
    if rules is None:
        return legacy_rules(cfg.get("hours_control", {}).get("uzd_norm", 35.0))
    return rules


# ── Выбор нормы ──────────────────────────────────────────────────────────────

def _title_matches(title_norm: str, keywords: Sequence[str]) -> bool:
    # граница слева — как в get_tags(): «лор» не должно находиться внутри «колоректальный»
    return any(re.search(r'(?<![а-яa-z])' + re.escape(_norm_text(kw)), title_norm) for kw in keywords)


def weekly_norm_for(title: str, fraction: float, base_norm: float, rules: Sequence[dict]) -> Decimal:
    """Недельная норма часов именно для этой должности и ставки
    (доля ставки уже учтена, повторно умножать не нужно)."""
    t = _norm_text(title)
    matching = [r for r in rules if _title_matches(t, r.get("keywords", []))]
    for r in matching:
        if r.get("rate") is not None and abs(float(r["rate"]) - fraction) < 1e-9:
            return Decimal(str(r["weekly"]))
    for r in matching:
        if r.get("rate") is None:
            return Decimal(str(r["weekly"])) * Decimal(str(fraction))
    return Decimal(str(base_norm)) * Decimal(str(fraction))
