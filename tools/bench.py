#!/usr/bin/env python3
"""Замер скорости: чтение графика, заполнение табеля и сравнение на большой синтетике.

    python tools/bench.py                      # 150 врачей, 3 прогона, таблица времени
    python tools/bench.py --doctors 400        # крупнее
    python tools/bench.py --profile            # + cProfile: топ функций по накопленному времени
    python tools/bench.py --json before.json   # сохранить цифры, потом сравнить с after.json

Что мерим (по этапам, лучшее из --repeat прогонов):
  parse_source   — чтение сводного графика (pandas + openpyxl);
  fill_template  — разбор шаблона, сопоставление врачей, запись, условное форматирование;
  compare        — сравнение двух книг (parse_full_sheet_data ×2 + формулы xlcalculator).

Настоящий auto_schedule_config.json не трогается: путь к конфигу подменяется ДО импорта core.
Лог и print во время замеров отключены — меряем работу, а не вывод в консоль.
Результат зависит от компьютера: сравнивайте «до» и «после» только на одной машине.
"""
from __future__ import annotations

import argparse
import contextlib
import cProfile
import io
import json
import logging
import os
import pstats
import shutil
import statistics
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="cityclinic-bench-")
# ВАЖНО: до первого импорта core (он создаёт конфиг при импорте).
os.environ["CITYCLINIC_CONFIG"] = os.path.join(_TMP, "auto_schedule_config.json")
sys.path.insert(0, ROOT)

from core import auto_schedule, compare_schedules, excel_io  # noqa: E402
from tests.builders import make_scale_scenario, make_source_book, make_template_book  # noqa: E402

SHEET = "Апрель 2026"
MONTH = "апрель 2026"


@contextlib.contextmanager
def _quiet():
    """Глушим print и логи на время замера."""
    logging.disable(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            yield
    finally:
        logging.disable(logging.NOTSET)


def _timed(fn, repeat: int, profile: bool):
    times, last = [], None
    for _ in range(repeat):
        t0 = time.perf_counter()
        with _quiet():
            last = fn()
        times.append(time.perf_counter() - t0)
    prof_text = ""
    if profile:
        pr = cProfile.Profile()
        with _quiet():
            pr.enable()
            fn()
            pr.disable()
        buf = io.StringIO()
        pstats.Stats(pr, stream=buf).strip_dirs().sort_stats("cumulative").print_stats(18)
        prof_text = buf.getvalue()
    return min(times), statistics.median(times), last, prof_text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doctors", type=int, default=150, help="число врачей (по умолчанию 150)")
    ap.add_argument("--repeat", type=int, default=3, help="число прогонов этапа (по умолчанию 3)")
    ap.add_argument("--profile", action="store_true", help="напечатать cProfile по каждому этапу")
    ap.add_argument("--json", metavar="FILE", help="сохранить результаты в JSON")
    args = ap.parse_args()

    try:
        src_docs, tpl_sheets = make_scale_scenario(args.doctors)
        src = make_source_book(os.path.join(_TMP, "src.xlsx"), src_docs, sheet=SHEET)
        tpl = make_template_book(os.path.join(_TMP, "tpl.xlsx"), tpl_sheets,
                                 header="ГРАФИК РАБОТЫ НА МАРТ 2026 г.")
        out = os.path.join(_TMP, "out.xlsx")

        results, profiles = {}, {}

        best, med, records, prof = _timed(lambda: excel_io.parse_source(src, SHEET), args.repeat, args.profile)
        results["parse_source"] = (best, med)
        profiles["parse_source"] = prof

        best, med, _, prof = _timed(lambda: auto_schedule.fill_template(tpl, records, MONTH, out),
                                    args.repeat, args.profile)
        results["fill_template"] = (best, med)
        profiles["fill_template"] = prof

        manual = os.path.join(_TMP, "manual.xlsx")
        shutil.copyfile(out, manual)
        best, med, cmp_res, prof = _timed(lambda: compare_schedules.compare(out, manual), args.repeat, args.profile)
        results["compare"] = (best, med)
        profiles["compare"] = prof

        print(f"\nВрачей: {args.doctors}   записей в источнике: {len(records)}   прогонов: {args.repeat}")
        print(f"Расхождений в compare (ожидается 0, книги одинаковы): {cmp_res.diffs}\n")
        print(f"{'этап':<16}{'лучшее, с':>12}{'медиана, с':>14}")
        for name, (best, med) in results.items():
            print(f"{name:<16}{best:>12.3f}{med:>14.3f}")
        total = sum(b for b, _ in results.values())
        print(f"{'ИТОГО':<16}{total:>12.3f}")

        if args.profile:
            for name, text in profiles.items():
                print(f"\n══════ cProfile: {name} ══════\n{text}")

        if args.json:
            with open(args.json, "w", encoding="utf-8") as f:
                json.dump({"doctors": args.doctors, "repeat": args.repeat,
                           "best_seconds": {k: round(v[0], 4) for k, v in results.items()}},
                          f, ensure_ascii=False, indent=2)
            print(f"\nСохранено: {args.json}")
        return 0 if cmp_res.diffs == 0 else 1
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
