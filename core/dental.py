"""
dental.py — график стоматологического отделения.

Стоматология ведётся в отдельной книге (лист на месяц: «Апрель 26», «Декабрь 26»…),
а в шаблон табеля попадает на отдельный лист, в названии которого есть «Стомат»
(например, «Стоматологическое»).

Листы месяцев бывают двух раскладок:

• новая (как в основном графике) — в первом столбце «Отделение / Кабинет / Специалист / Дата»,
  врач записан полностью: «Иванов Иван Иванович, врач-стоматолог-терапевт (1,0 ст)».
  Читается тем же разбором, что и основной график (excel_io.parse_source).

• прежняя — «Кабинет / Доктор / Смена-Часы», дни идут строками, а врач указан только
  фамилией («Шаричков», «Кузнецова пародонт», «Семуков С»). Один врач может стоять
  в нескольких кабинетах — его смены сливаются в одну строку табеля.

Сопоставление с листом шаблона идёт по фамилии (и инициалам, если они есть),
а не по баллам направлений, как у остальных отделений.
"""

import logging
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from openpyxl import load_workbook
from pydantic import ValidationError

from . import excel_io
from .config import CONFIG
from .models import DiagReport, DoctorRecord, Shift
from .utils import calculate_total_hours, combine_times, yo_to_ye

# Тот же логгер, что у генерации: GUI привязывает лог страницы «Генерация»
# к core.auto_schedule (см. gui/log_handler.py: GENERATE_LOGGERS).
logger = logging.getLogger("core.auto_schedule")

DENTAL_DIRECTION = "Стоматологическое"
DENTAL_SHEET_MARK = "стомат"

# Врач, у которого в табеле несколько строк, а в графике специальность не указана:
# «фамилия|номер кабинета» → слово из должности нужной строки табеля.
# Свои правила можно добавить в auto_schedule_config.json: "dental_role_by_cabinet".
DEFAULT_ROLE_BY_CABINET = {
    "становенко|25": "ортопед",   # Становенко А.В. (Александр), кабинеты 25 и 32 (в июле)
    "становенко|32": "ортопед",
    "становенко|37": "терапевт",  # Становенко А.В. (Андрей), кабинет 37
}

# Латинские буквы, похожие на русские (в графике встречается «Cавчук» с латинской C).
_LATIN_TO_CYR = str.maketrans("ABCEHKMOPTXYaceopxy", "АВСЕНКМОРТХУасеорху")
_INITIALS_RE = re.compile(r'^[А-ЯЁ](?:\.?[А-ЯЁ])?\.?$')
_RATE_RE = re.compile(r'\((\d+(?:[.,]\d+)?)\s*ст')


# ── Признаки стоматологии ────────────────────────────────────────────────────

def is_dental_sheet(sheet_name: str) -> bool:
    """Лист табеля стоматологии (листы «Ознакомление …» не считаются)."""
    low = str(sheet_name).lower()
    return DENTAL_SHEET_MARK in low and 'ознакомление' not in low


def is_dental_record(record: DoctorRecord) -> bool:
    return record.direction == DENTAL_DIRECTION


# ── Чтение источника ─────────────────────────────────────────────────────────

def find_month_sheet(sheet_names: List[str], month_str: str) -> str:
    """Лист месяца по строке «Апрель 2026». Названия листов бывают «Апрель 26  »
    (с пробелами и двузначным годом), поэтому сравниваем по словам."""
    parts = month_str.strip().split()
    month = parts[0].lower()
    year = parts[1] if len(parts) > 1 else ""
    for name in sheet_names:
        tokens = name.strip().lower().split()
        if not tokens or tokens[0] != month:
            continue
        if not year or len(tokens) == 1 or tokens[1] in (year, year[-2:]):
            return name
    shown = ", ".join(f"«{n.strip()}»" for n in sheet_names)
    raise ValueError(
        f"В графике стоматологии нет листа за «{month_str}». Листы в файле: {shown}."
    )


def _col_a_labels(ws, limit: int = 12) -> Dict[str, int]:
    labels: Dict[str, int] = {}
    for r in range(1, limit + 1):
        v = ws.cell(r, 1).value
        if isinstance(v, str):
            labels.setdefault(v.strip().lower(), r)
    return labels


def _to_float(value) -> float:
    try:
        return float(str(value).replace(",", ".").strip())
    except ValueError:
        return 0.0


def split_legacy_name(text: str) -> Tuple[str, str]:
    """«Cавчук Д» → («Савчук Д.», ""); «Кузнецова ПАРОДОНТ» → («Кузнецова», «ПАРОДОНТ»).
    Первое слово — фамилия, дальше инициалы; остальные слова — пометка."""
    tokens = text.replace(",", " ").split()
    surname = tokens[0].translate(_LATIN_TO_CYR)
    initials: List[str] = []
    extra: List[str] = []
    for tok in tokens[1:]:
        cyr = tok.translate(_LATIN_TO_CYR)
        if _INITIALS_RE.match(cyr):
            initials += re.findall(r'[А-ЯЁ]', cyr)
        else:
            extra.append(tok)
    name = surname + (" " + "".join(f"{i}." for i in initials[:2]) if initials else "")
    return yo_to_ye(name), " ".join(extra)


def _parse_legacy_sheet(ws) -> List[DoctorRecord]:
    labels = _col_a_labels(ws)
    name_r = labels["доктор"]
    cab_r = labels.get("кабинет")
    hdr_r = name_r + 1

    # Дни — строки, где в первом столбце номер дня (1, 2, … 31).
    day_rows: Dict[int, int] = {}
    for r in range(hdr_r + 1, hdr_r + 45):
        v = ws.cell(r, 1).value
        if isinstance(v, (int, float)) and float(v).is_integer() and 1 <= int(v) <= 31:
            day_rows.setdefault(int(v), r)
        elif day_rows:
            break
    if not day_rows:
        raise ValueError(f"Лист «{ws.title.strip()}»: не найдены строки с номерами дней в первом столбце.")

    # Кабинет действует до следующей непустой ячейки (блоки объединены по столбцам).
    # Пустая строка из пробелов тоже сбрасывает кабинет — название блока просто не заполнено.
    cab_at: Dict[int, str] = {}
    current = ""
    for c in range(3, ws.max_column + 2):
        if cab_r:
            v = ws.cell(cab_r, c).value
            if v is not None:
                current = str(v).strip()
        cab_at[c] = current

    records: List[DoctorRecord] = []
    for c in range(3, ws.max_column + 1):
        raw = ws.cell(name_r, c).value
        if raw is None:
            continue
        text = str(raw).replace("\n", " ").strip()
        if not text or "итого" in text.lower():
            continue
        # Имя стоит над первым столбцом пары «Смена / Часы». Подпись «Смена» в шапке местами
        # потеряна, поэтому смотрим только на подпись второго столбца.
        next_hdr = str(ws.cell(hdr_r, c + 1).value or "").strip().lower()
        hours_col = c + 1 if (not next_hdr or next_hdr.startswith("час")) else None

        name, hint = split_legacy_name(text)
        schedule: Dict[int, Shift] = {}
        for day, r in day_rows.items():
            t_val = ws.cell(r, c).value
            time_s = str(t_val).strip() if t_val is not None else ""
            if time_s.lower() in ("nan", "0", "-"):
                time_s = ""
            hours = _to_float(ws.cell(r, hours_col).value) if hours_col else 0.0
            if not time_s and hours == 0.0:
                continue
            if hours == 0.0 and time_s:
                hours = calculate_total_hours(time_s)  # часы не проставлены — считаем по времени
            try:
                schedule[day] = Shift(time=time_s, hours=hours)
            except ValidationError:
                schedule[day] = Shift(time=time_s, hours=0.0)

        records.append(DoctorRecord(name=name, direction=DENTAL_DIRECTION, cabinet=cab_at.get(c, ""),
                                    spec_hint=hint, schedule=schedule))
    return records


def parse_dental_source(source_file: str, month_str: str, progress_cb=None) -> List[DoctorRecord]:
    """Читает лист месяца из графика стоматологии. Все записи получают
    direction = DENTAL_DIRECTION — по нему auto_schedule отделяет их от остальных."""
    wb = load_workbook(source_file, data_only=True)
    legacy_records: Optional[List[DoctorRecord]] = None
    try:
        title = find_month_sheet(wb.sheetnames, month_str)
        labels = _col_a_labels(wb[title])
        if "специалист" in labels and "дата" in labels:
            pass  # новая раскладка — читаем ниже общим разбором
        elif "доктор" in labels:
            legacy_records = _parse_legacy_sheet(wb[title])
        else:
            raise ValueError(
                f"Лист «{title.strip()}»: в первом столбце нет ни строки «Доктор», ни «Специалист» — "
                f"не понимаю раскладку. Возможно, лист ещё не заполнен."
            )
    finally:
        wb.close()

    records = legacy_records if legacy_records is not None else excel_io.parse_source(
        source_file, title, progress_cb)
    for rec in records:
        rec.direction = DENTAL_DIRECTION
    logger.info(f"§INFO§ Стоматология: лист «{title.strip()}», записей врачей: {len(records)}")
    return records


# ── Сопоставление с листом шаблона ───────────────────────────────────────────

def split_template_docs(template_docs: dict) -> Tuple[dict, dict]:
    """Делит строки табеля на обычные отделения и лист стоматологии."""
    regular: Dict[str, list] = defaultdict(list)
    dental: Dict[str, list] = defaultdict(list)
    for name, roles in template_docs.items():
        for role in roles:
            (dental if is_dental_sheet(role["sheet"]) else regular)[name].append(role)
    return dict(regular), dict(dental)


def _name_parts(name: str) -> Tuple[str, str]:
    """«Становенко А.В.» → («становенко», «АВ»)."""
    tokens = yo_to_ye(str(name)).replace(",", " ").split()
    if not tokens:
        return "", ""
    surname = tokens[0].translate(_LATIN_TO_CYR).lower()
    tail = " ".join(tokens[1:]).translate(_LATIN_TO_CYR).upper()
    return surname, "".join(re.findall(r'[А-ЯЁ]', tail))


def _resolve_name(rec_name: str, template_names: List[str]) -> Optional[str]:
    """Имя из графика → имя из табеля: точное совпадение, иначе фамилия + совместимые инициалы."""
    if rec_name in template_names:
        return rec_name
    surname, initials = _name_parts(rec_name)
    hits = []
    for tname in template_names:
        t_surname, t_initials = _name_parts(tname)
        if t_surname == surname and all(a == b for a, b in zip(initials, t_initials)):
            hits.append(tname)
    return hits[0] if len(hits) == 1 else None


def _spec(text: str) -> Tuple[set, Optional[float]]:
    """Специальность и ставка из «, врач-стоматолог-ортопед (0,25 ст)» или «… (1,0 ст.)»."""
    low = yo_to_ye(str(text or "")).lower()
    m = _RATE_RE.search(low)
    rate = float(m.group(1).replace(",", ".")) if m else None
    words = {w for w in re.split(r'[^а-яa-z]+', low.split("(")[0]) if w and w != "врач"}
    return words, rate


def _spec_score(role_title: str, hint: str) -> int:
    h_words, h_rate = _spec(hint)
    t_words, t_rate = _spec(role_title)
    score = 0
    if h_words and t_words and (h_words <= t_words or t_words <= h_words):
        score += 2
    if h_rate is not None and t_rate is not None and abs(h_rate - t_rate) < 1e-9:
        score += 1
    return score


def _pick_role(roles: List[dict], rec: DoctorRecord) -> Tuple[dict, bool]:
    """Строка табеля для записи врача. Второе значение — уверенность выбора."""
    if len(roles) == 1:
        return roles[0], True

    # 1) по специальности и ставке, указанным в графике (новая раскладка)
    scored = sorted(((_spec_score(r["title"], rec.spec_hint), i) for i, r in enumerate(roles)),
                    key=lambda x: (-x[0], x[1]))
    if scored[0][0] >= 2 and scored[0][0] > scored[1][0]:
        return roles[scored[0][1]], True

    # 2) по правилу «фамилия|кабинет» (прежняя раскладка, специальность не указана)
    surname, _ = _name_parts(rec.name)
    num = re.search(r'\d+', rec.cabinet or "")
    if num:
        keyword = CONFIG.get("dental_role_by_cabinet", DEFAULT_ROLE_BY_CABINET).get(f"{surname}|{num.group()}")
        if keyword:
            hits = [r for r in roles if keyword.lower() in yo_to_ye(r["title"]).lower()]
            if len(hits) == 1:
                return hits[0], True

    return roles[0], False


def _merge_into(role: dict, schedule: Dict[int, Shift]) -> None:
    """Смены одного врача из нескольких кабинетов сливаются: время объединяется, часы суммируются."""
    target = role["assigned_schedule"]
    for day, shift in schedule.items():
        if shift.hours > 0 or shift.time:
            existing = target.get(day)
            if existing:
                target[day] = Shift(time=combine_times(existing.time, shift.time),
                                    hours=existing.hours + shift.hours)
            else:
                target[day] = shift


def match_dental(dental_docs: dict, records: List[DoctorRecord], diag: DiagReport) -> Dict[str, bool]:
    """Раскладывает записи стоматологии по строкам листа шаблона и наполняет диагностический отчёт.
    Возвращает {имя в табеле: найден ли в графике}."""
    found: Dict[str, bool] = {}

    def not_in_template(rec: DoctorRecord) -> None:
        line = f"{rec.name}  (отделение: «стоматология», кабинет: «{rec.cabinet}»)"
        if line not in diag.source_not_in_template:
            diag.source_not_in_template.append(line)

    if not dental_docs:
        if records:
            logger.warning("§WARN§ В шаблоне нет листа стоматологии (в названии листа должно быть «Стомат», "
                           "например «Стоматологическое») — данные стоматологии не записаны.")
            for rec in records:
                not_in_template(rec)
        return found

    names = list(dental_docs)
    assigned: Dict[str, List[Tuple[DoctorRecord, dict, bool]]] = defaultdict(list)
    for rec in records:
        tname = _resolve_name(rec.name, names)
        if tname is None:
            not_in_template(rec)
            continue
        role, certain = _pick_role(dental_docs[tname], rec)
        _merge_into(role, rec.schedule)
        assigned[tname].append((rec, role, certain))

    for tname in names:
        found[tname] = bool(assigned.get(tname))
        if not found[tname]:
            diag.not_in_source.append(tname)

    # Диагностика — по строкам табеля, а не по записям: врач из трёх кабинетов даёт одну строку.
    per_role: Dict[int, dict] = {}
    for tname, items in assigned.items():
        for rec, role, certain in items:
            entry = per_role.setdefault(id(role), {"name": tname, "role": role, "certain": True, "cabs": []})
            entry["certain"] = entry["certain"] and certain
            if rec.cabinet:
                entry["cabs"].append(rec.cabinet)

    for entry in per_role.values():
        role, name = entry["role"], entry["name"]
        sched = role["assigned_schedule"]
        total_hours = sum(s.hours for s in sched.values())
        days_no_time = sorted(d for d, s in sched.items() if s.hours > 0 and not s.time)
        if not entry["certain"]:
            diag.dubious.append({
                "name": name, "sheet": role["sheet"], "title": role["title"], "score": 0.0,
                "direction": "у врача несколько строк в табеле, а специальность в графике не указана",
                "cabinet": ", ".join(sorted(set(entry["cabs"]))),
            })
        elif not sched:
            diag.empty_schedule.append({"name": name, "sheet": role["sheet"]})
        elif total_hours == 0:
            diag.no_hours.append({"name": name, "sheet": role["sheet"], "workdays": len(sched)})
        elif days_no_time:
            diag.missing_time.append({"name": name, "sheet": role["sheet"], "days": days_no_time})
        else:
            diag.ok.append({"name": name, "sheet": role["sheet"], "score": 3.0,
                            "workdays": len(sched), "total_hours": total_hours})

    logger.info(f"§INFO§ Стоматология: в табеле найдено врачей {sum(found.values())} из {len(found)}")
    return found
