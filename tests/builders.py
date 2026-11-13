"""Построители маленьких синтетических книг для тестов и tools/bench.py.

Реальные графики содержат ФИО и лежат вне репозитория (*.xlsx в .gitignore), поэтому
тесты собирают книги в tmp_path сами. Раскладка повторяет настоящие файлы:

* источник («График»): в столбце A подписи строк «Отделение / Кабинет / Специалист / Дата»,
  начиная со столбца C — блоки врачей из пар «Смена / Часы»; отделение, кабинет и ФИО
  обычно записаны в объединённых ячейках над парой;
* шаблон («Табель»): лист на отделение, строка с числами 1–31, под ней строки врачей —
  строка часов (ФИО + должность) и строка времени; на листе МИБС добавляется
  третья строка — ночные часы.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from openpyxl import Workbook
from openpyxl.utils import get_column_letter

# (время, часы) за один день; любой из элементов может быть None.
ShiftCell = Tuple[Optional[str], Optional[float]]

FIRST_DOCTOR_COL = 3        # столбец C
DAY_ROW = 4                 # строка с числами 1–31 в шаблоне
FIRST_DAY_COL = 3           # день 1 — столбец C
NORM_COL = 34               # «Расчетная норма»
HOURS_COL = 35              # «Часы»


# ─────────────────────────────── источник ────────────────────────────────────

@dataclass
class SrcDoc:
    """Один врач в источнике.

    name  — «Иванов Иван Иванович»; spec — хвост после ФИО («, врач-терапевт (1,0 ст)»).
    pairs — по одному словарю {день: (время, часы)} на каждую пару столбцов «Смена/Часы».
    merge_name=False — ФИО записано только над первым столбцом пары (над «Часы» пусто):
    разбор должен сам протянуть имя вправо.
    """
    name: str
    spec: str = ""
    direction: str = ""
    cabinet: str = ""
    pairs: List[Dict[int, ShiftCell]] = field(default_factory=list)
    merge_name: bool = True


def make_source_book(path: str, docs: Sequence[SrcDoc], sheet: str = "Апрель 2026",
                     days: int = 30, total_column: bool = True) -> str:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet

    r_dept, r_cab, r_name, r_hdr = 1, 2, 3, 4
    ws.cell(r_dept, 1, "Отделение")
    ws.cell(r_cab, 1, "Кабинет")
    ws.cell(r_name, 1, "Специалист")
    ws.cell(r_hdr, 1, "Дата")
    for d in range(1, days + 1):
        ws.cell(r_hdr + d, 1, d)

    col = FIRST_DOCTOR_COL
    for doc in docs:
        pairs = doc.pairs or [{}]
        c0, c1 = col, col + 2 * len(pairs) - 1

        ws.cell(r_dept, c0, doc.direction or None)
        ws.cell(r_cab, c0, doc.cabinet or None)
        ws.cell(r_name, c0, doc.name + doc.spec)
        if c1 > c0:
            for r in (r_dept, r_cab):
                ws.merge_cells(start_row=r, start_column=c0, end_row=r, end_column=c1)
            if doc.merge_name:
                ws.merge_cells(start_row=r_name, start_column=c0, end_row=r_name, end_column=c1)

        for p, shifts in enumerate(pairs):
            tc, hc = c0 + 2 * p, c0 + 2 * p + 1
            ws.cell(r_hdr, tc, "Смена")
            ws.cell(r_hdr, hc, "Часы")
            for day, (time, hours) in shifts.items():
                if time is not None:
                    ws.cell(r_hdr + day, tc, time)
                if hours is not None:
                    ws.cell(r_hdr + day, hc, hours)
        col = c1 + 1

    if total_column:
        # Столбец «Итого» разбор должен пропускать целиком.
        ws.cell(r_name, col, "Итого")
        ws.cell(r_hdr, col, "Часы")
        for d in range(1, days + 1):
            ws.cell(r_hdr + d, col, 99)

    wb.save(path)
    return path


# ─────────────────────────────── шаблон ──────────────────────────────────────

@dataclass
class TplDoc:
    name: str       # «Иванов И.И.»
    title: str      # «Врач-терапевт (1,0 ст.)»
    # Заранее вписанные смены (для книг сравнения): {день: (время, часы)}.
    shifts: Dict[int, ShiftCell] = field(default_factory=dict)


def make_template_book(path: str, sheets: Dict[str, Sequence[TplDoc]],
                       header: str = "ГРАФИК РАБОТЫ НА МАРТ 2026 г.",
                       ack_sheet: bool = True, hours_formula: bool = True,
                       doctor_offset: int = 5) -> str:
    """Шаблон табеля. Листа «Ознакомление» (если ack_sheet) fill_template не трогает,
    кроме строки «…на <месяц> года». На листе МИБС у врача три строки, на остальных две."""
    wb = Workbook()
    first = True
    for sheet_name, docs in sheets.items():
        ws = wb.active if first else wb.create_sheet()
        first = False
        ws.title = sheet_name
        ws["A1"] = header
        ws.cell(DAY_ROW, 1, "Врачи")
        ws.cell(DAY_ROW, 2, "Должность (ставка)")
        for d in range(1, 32):
            ws.cell(DAY_ROW, FIRST_DAY_COL + d - 1, d)
        ws.cell(DAY_ROW, NORM_COL, "Расчетная норма")
        ws.cell(DAY_ROW, HOURS_COL, "Часы")

        # Строка-шапка, по форме совпадающая с ФИО: разбор обязан её пропустить.
        # (При doctor_offset=3 врач стоит прямо в первой просматриваемой строке — шапки нет.)
        if doctor_offset > 3:
            ws.cell(DAY_ROW + 3, 1, "Фамилия И.О.")

        step = 3 if sheet_name.upper() == "МИБС" else 2
        row = DAY_ROW + doctor_offset
        for doc in docs:
            ws.cell(row, 1, doc.name)
            ws.cell(row, 2, doc.title)
            for day, (time, hours) in doc.shifts.items():
                if hours is not None:
                    ws.cell(row, FIRST_DAY_COL + day - 1, hours)
                if time is not None:
                    ws.cell(row + 1, FIRST_DAY_COL + day - 1, time)
            if hours_formula:
                last = get_column_letter(FIRST_DAY_COL + 30)
                ws.cell(row, HOURS_COL, f"=SUM(C{row}:{last}{row})")
            row += step

    if ack_sheet:
        ws = wb.create_sheet("Ознакомление")
        ws["A1"] = "ПРИЛОЖЕНИЕ. С графиком работы на март 2026 года ознакомлены:"

    wb.save(path)
    return path


# ─────────────────────── стандартные наборы для тестов ───────────────────────

def standard_source_docs() -> List[SrcDoc]:
    """Источник на апрель 2026: объединённые ячейки, две смены в день, опечатка в
    отделении, ФИО без объединения, столбец «Итого»."""
    return [
        SrcDoc("Иванов Иван Иванович", ", врач-терапевт (1,0 ст)", "Консультативное", "101",
               [{1: ("09:00-17:00", 8), 2: ("09:00-17:00", 8), 3: ("09:00-16:00", 7),
                 6: ("вых", None), 7: ("09:00-17:00", "7,5")}]),
        # две смены в день в двух парах столбцов → времена и часы складываются
        SrcDoc("Петров Пётр Петрович", ", врач-хирург (1,0 ст)", "хиругическое", "205",
               [{1: ("09:00-12:00", 3), 2: ("09:00-12:00", 3)},
                {1: ("14:00-18:00", 4), 2: ("14:00-18:00", 4)}]),
        # ФИО только над «Сменой», над «Часы» пусто
        SrcDoc("Сидорова Анна Сергеевна", ", врач ультразвуковой диагностики (0,5 ст)",
               "Диагностическое", "УЗИ-1",
               [{1: ("10:00-14:00", 4), 4: ("10:00-14:00", 4)}], merge_name=False),
        # МИБС: ночная смена через полночь
        SrcDoc("Козлов Игорь Олегович", ", врач-анестезиолог (1,0 ст)", "МИБС", "ОРИТ",
               [{1: ("22:00-06:00", 8), 3: ("22:00-06:00", 8)}]),
        # Расхождение «часы ≠ время»
        SrcDoc("Орлов Олег Олегович", ", врач-кардиолог (1,0 ст)", "Консультативное", "103",
               [{1: ("09:00-17:00", 7)}]),
        # Есть в источнике, но не нужен в шаблоне
        SrcDoc("Лишний Леонид Львович", ", врач-невролог (1,0 ст)", "Консультативное", "110",
               [{1: ("09:00-13:00", 4)}]),
    ]


def standard_template_sheets() -> Dict[str, List[TplDoc]]:
    return {
        "Терапия": [
            TplDoc("Иванов И.И.", "Врач-терапевт (1,0 ст.)"),
            TplDoc("Орлов О.О.", "Врач-кардиолог (1,0 ст.)"),
            TplDoc("Сидоров С.С.", "Врач-терапевт (1,0 ст.)"),   # нет в источнике
        ],
        "Хирургия": [
            TplDoc("Петров П.П.", "Врач-хирург (1,0 ст.)"),
        ],
        "УЗИ": [
            TplDoc("Сидорова А.С.", "Врач ультразвуковой диагностики (0,5 ст.)"),
        ],
        "МИБС": [
            TplDoc("Козлов И.О.", "Врач-анестезиолог (1,0 ст.)"),
        ],
    }


_SURNAMES = ["Иванов", "Петров", "Сидоров", "Козлов", "Орлов", "Волков", "Зайцев", "Лебедев"]
_LETTERS = "абвгдежзик"


def _suffix(n: int) -> str:
    """0 → "", 1 → "б", 12 → "бв": буквы вместо цифр, чтобы фамилия проходила проверку ФИО."""
    out = ""
    while n:
        out = _LETTERS[n % len(_LETTERS)] + out
        n //= len(_LETTERS)
    return out


def make_scale_scenario(n_doctors: int, year: int = 2026, month: int = 4
                        ) -> Tuple[List[SrcDoc], Dict[str, List[TplDoc]]]:
    """n_doctors врачей, расписание на каждый рабочий день месяца. Детерминировано.

    Врачи поровну делятся между листами «Терапия», «Хирургия», «УЗИ», «МИБС»; у каждого
    пятого две смены в день (две пары столбцов). Нужен tools/bench.py и тестам масштаба."""
    import calendar

    _, days = calendar.monthrange(year, month)
    workdays = [d for d in range(1, days + 1) if calendar.weekday(year, month, d) < 5]
    kinds = [  # (лист, отделение, должность в источнике, должность в шаблоне)
        ("Терапия", "Консультативное", "врач-терапевт (1,0 ст)", "Врач-терапевт (1,0 ст.)"),
        ("Хирургия", "Хирургическое", "врач-хирург (1,0 ст)", "Врач-хирург (1,0 ст.)"),
        ("УЗИ", "Диагностическое", "врач ультразвуковой диагностики (1,0 ст)",
         "Врач ультразвуковой диагностики (1,0 ст.)"),
        ("МИБС", "МИБС", "врач-анестезиолог (1,0 ст)", "Врач-анестезиолог (1,0 ст.)"),
    ]
    src: List[SrcDoc] = []
    sheets: Dict[str, List[TplDoc]] = {k[0]: [] for k in kinds}
    for i in range(n_doctors):
        sheet, direction, spec_src, title = kinds[i % len(kinds)]
        surname = _SURNAMES[(i // len(kinds)) % len(_SURNAMES)] + _suffix(i // (len(kinds) * len(_SURNAMES)))
        if sheet == "МИБС":
            pairs = [{d: ("22:00-06:00", 8) for d in workdays}]
        elif i % 5 == 0:
            pairs = [{d: ("08:00-12:00", 4) for d in workdays}, {d: ("13:00-17:00", 4) for d in workdays}]
        else:
            pairs = [{d: ("09:00-17:00", 8) for d in workdays}]
        src.append(SrcDoc(f"{surname} Иван Иванович", f", {spec_src}", direction, str(100 + i % 40), pairs))
        sheets[sheet].append(TplDoc(f"{surname} И.И.", title))
    return src, sheets


def make_compare_pair(auto_path: str, manual_path: str) -> Tuple[str, str]:
    """Две книги для compare(): одинаковые, кроме нескольких намеренных расхождений."""
    sheets_auto = {
        "Терапия": [TplDoc("Иванов И.И.", "Врач-терапевт (1,0 ст.)",
                           {1: ("09:00-17:00", 8), 2: ("09:00-17:00", 8), 3: ("09:00-16:00", 7)})],
        "МИБС": [TplDoc("Козлов И.О.", "Врач-анестезиолог (1,0 ст.)", {1: ("22:00-06:00", 8)})],
    }
    sheets_manual = {
        "Терапия": [TplDoc("Иванов И.И.", "Врач-терапевт (1,0 ст.)",
                           {1: ("09:00-17:00", 8), 2: ("09:00-16:00", 7),   # расхождение: время и часы
                            3: ("09:00-16:00", 7)})],
        "МИБС": [TplDoc("Козлов И.О.", "Врач-анестезиолог (1,0 ст.)", {1: ("22:00-06:00", 8)})],
    }
    make_template_book(auto_path, sheets_auto, header="ГРАФИК РАБОТЫ НА АПРЕЛЬ 2026 г.")
    make_template_book(manual_path, sheets_manual, header="ГРАФИК РАБОТЫ НА АПРЕЛЬ 2026 г.")
    return auto_path, manual_path
