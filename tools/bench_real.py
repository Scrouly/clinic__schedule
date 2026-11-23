#!/usr/bin/env python3
"""Замер чтения РЕАЛЬНОГО сводного графика (tools/bench.py меряет только маленькую синтетику).

    python tools/bench_real.py "C:\\...\\График 2026.xlsx" "Апрель 2026"
    python tools/bench_real.py "C:\\...\\График 2026.xlsx" "Апрель 2026" --full   # + старый способ

Что печатается:
  чтение листа   — load_excel_with_merges (только нужный лист, см. core/xlsx_slim.py);
  parse_source   — чтение целиком: сетка + разбор врачей;
  --full         — для сравнения: открытие всей книги openpyxl, как делал прежний код
                   (на графике из 12+ листов это десятки секунд — не пугайтесь).

Файл не меняется, настоящий auto_schedule_config.json не трогается."""
from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="cityclinic-benchreal-")
# ВАЖНО: до первого импорта core (он читает конфиг при импорте).
os.environ["CITYCLINIC_CONFIG"] = os.path.join(_TMP, "auto_schedule_config.json")
sys.path.insert(0, ROOT)

from core import excel_io  # noqa: E402
from core.xlsx_slim import sheet_names  # noqa: E402


def _timed(fn):
    t0 = time.perf_counter()
    result = fn()
    return time.perf_counter() - t0, result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="путь к сводному графику (.xlsx)")
    ap.add_argument("sheet", help="лист месяца, например «Апрель 2026»")
    ap.add_argument("--repeat", type=int, default=3, help="число прогонов (по умолчанию 3)")
    ap.add_argument("--full", action="store_true", help="для сравнения: открыть книгу целиком, как раньше")
    args = ap.parse_args()

    logging.disable(logging.CRITICAL)
    names = sheet_names(args.file)
    print(f"Листов в книге: {len(names) if names else '?'}   файл: {os.path.getsize(args.file) / 1e6:.1f} МБ")

    grid_times = [_timed(lambda: excel_io.load_excel_with_merges(args.file, args.sheet))[0]
                  for _ in range(args.repeat)]
    parse_times = []
    records = []
    for _ in range(args.repeat):
        dt, records = _timed(lambda: excel_io.parse_source(args.file, args.sheet))
        parse_times.append(dt)
    print(f"{'чтение листа':<16}{min(grid_times):>8.2f} с  (лучшее из {args.repeat})")
    print(f"{'parse_source':<16}{min(parse_times):>8.2f} с  (записей врачей: {len(records)})")

    if args.full:
        from openpyxl import load_workbook
        dt, wb = _timed(lambda: load_workbook(args.file, data_only=True))
        wb.close()
        print(f"{'полная книга':<16}{dt:>8.2f} с  (так читал прежний код — на КАЖДОЕ чтение)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
