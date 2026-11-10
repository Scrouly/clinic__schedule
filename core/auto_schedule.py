#!/usr/bin/env python3
"""
auto_schedule.py — Главный контроллер генерации табеля.
Содержит бизнес-логику сопоставления врачей и управляет процессом.
"""

import logging
from collections import defaultdict
from openpyxl import load_workbook
from openpyxl.styles import PatternFill, Font, Alignment, Border, Side


# Экспортируем функции и настройки, чтобы gui_app.py мог их использовать
from .config import CONFIG, reload_config
from .excel_io import parse_source, write_sheet_data
from .models import DiagReport, Shift, DoctorRecord
from .utils import (
    combine_times, get_openpyxl_color, get_tags, month_info,
    string_similarity, yo_to_ye, is_doctor_name_row
)

logger = logging.getLogger(__name__)


# ─── БИЗНЕС-ЛОГИКА СРАВНЕНИЯ И НАЗНАЧЕНИЯ ─────────────────────────────────────

def _score_match(dir_text: str, cab_text: str, title_text: str, spec_hint: str = "", sheet_name: str = "") -> float:
    """Вычисление балла соответствия между данными врача и должностью."""
    # Убрали все принты отсюда, чтобы не засорять консоль!
    dir_text = yo_to_ye(dir_text)
    sheet_name = yo_to_ye(sheet_name)
    dir_tags = get_tags(dir_text)
    cab_tags = get_tags(cab_text)
    title_tags = get_tags(title_text)
    sheet_tags = get_tags(sheet_name)

    sheet_bonus = 0.0
    if dir_text and sheet_name:
        if dir_tags and sheet_tags and len(dir_tags & sheet_tags) > 0:
            sheet_bonus = 0.4
        elif string_similarity(dir_text, sheet_name) >= 0.7:
            sheet_bonus = 0.2

    base_score = -0.1

    if not title_tags:
        if not dir_tags and not cab_tags:
            base_score = 0.5
        else:
            base_score = -0.1
    elif cab_tags:
        intersect_cab = len(cab_tags & title_tags)
        if intersect_cab > 0:
            union_cab = len(cab_tags | title_tags)
            base_score = 3.0 + (intersect_cab / union_cab)
        elif dir_tags:
            intersect_dir = len(dir_tags & title_tags)
            if intersect_dir > 0:
                union_dir = len(dir_tags | title_tags)
                base_score = 1.0 + (intersect_dir / union_dir)
            elif spec_hint:
                hint_tags = get_tags(spec_hint)
                if hint_tags and len(hint_tags & title_tags) > 0:
                    base_score = 0.5
                else:
                    base_score = -1.0
            else:
                base_score = -1.0
        elif spec_hint:
            hint_tags = get_tags(spec_hint)
            if hint_tags and len(hint_tags & title_tags) > 0:
                base_score = 0.5
            else:
                base_score = -1.0
        else:
            base_score = -1.0
    elif dir_tags:
        intersect_dir = len(dir_tags & title_tags)
        if intersect_dir > 0:
            union_dir = len(dir_tags | title_tags)
            base_score = 2.0 + (intersect_dir / union_dir)
        elif spec_hint:
            hint_tags = get_tags(spec_hint)
            if hint_tags and len(hint_tags & title_tags) > 0:
                base_score = 0.5
            else:
                base_score = -1.0
        else:
            base_score = -1.0

    if base_score >= -1.0:
        return base_score + sheet_bonus
    return base_score


def _match_doctors_to_roles(template_docs: dict, records: list[DoctorRecord], diag: DiagReport) -> dict:
    """Алгоритм маршрутизации: сопоставляет врачей из источника с табелем."""
    print("\n" + "═" * 80)
    print("СТАРТ МАРШРУТИЗАЦИИ (_match_doctors_to_roles)")
    print("═" * 80)

    scoring = CONFIG.get("scoring", {})
    min_accept = scoring.get("min_accept_score", -0.8)
    dubious_thr = scoring.get("dubious_threshold", 1.5)
    fuzzy_thr = scoring.get("fuzzy_name_threshold", 0.95)

    doctor_found_map = {}
    source_names_seen = set()

    for norm_name, roles in template_docs.items():
        exact = [r for r in records if r.name == norm_name]
        doc_records = exact

        if not doc_records:
            fuzzy_matches = [(string_similarity(norm_name, r.name), r.name) for r in records if
                             string_similarity(norm_name, r.name) > fuzzy_thr]
            if fuzzy_matches:
                best_match_score, best_name = max(fuzzy_matches, key=lambda x: x[0])
                doc_records = [r for r in records if r.name == best_name]

        doctor_found_map[norm_name] = bool(doc_records)

        if not doc_records:
            print(f"\n❌ Врач из табеля '{norm_name}' НЕ НАЙДЕН в исходных данных.")
            diag.not_in_source.append(norm_name)
            continue

        for r in doc_records:
            source_names_seen.add(r.name)

            print(f"\n👨‍⚕️ ВРАЧ: {r.name}")
            print(f"   Исходные данные -> Отделение: '{r.direction}' | Кабинет: '{r.cabinet}'")
            print(f"   Варианты в табеле ({len(roles)} шт.):")

            # Собираем все варианты и их баллы в список
            evaluated_roles = []
            for role in roles:
                score = _score_match(r.direction, r.cabinet, role['title'], r.spec_hint, role['sheet'])
                evaluated_roles.append({'role': role, 'score': score})

            # Сортируем варианты по убыванию балла, чтобы лучшие были сверху
            evaluated_roles.sort(key=lambda x: x['score'], reverse=True)

            best_role = evaluated_roles[0]['role'] if evaluated_roles else None
            best_score = evaluated_roles[0]['score'] if evaluated_roles else -999.0

            # Выводим список вариантов
            for item in evaluated_roles:
                role = item['role']
                score = item['score']

                # Ставим галочку напротив того варианта, который победит
                is_winner = (role == best_role) and (score >= min_accept)
                marker = "✅" if is_winner else "  "

                print(f"   {marker} Лист: {role['sheet']:<15} | Роль: {role['title']:<30} | Балл: {score:.2f}")

            print("   " + "-" * 60)

            # Итог по врачу
            if best_role is not None and best_score >= min_accept:
                print(f"   🏆 ИТОГ: Выбрана роль '{best_role['title']}' (Лист: {best_role['sheet']})")

                # Интеграция расписания
                for day, shift in r.schedule.items():
                    if shift.hours > 0 or shift.time:
                        existing = best_role['assigned_schedule'].get(day)
                        if existing:
                            new_time = combine_times(existing.time, shift.time)
                            new_hours = existing.hours + shift.hours
                            best_role['assigned_schedule'][day] = Shift(time=new_time, hours=new_hours)
                        else:
                            best_role['assigned_schedule'][day] = shift

                total_hours = sum(s.hours for s in best_role['assigned_schedule'].values())
                workdays = len(best_role['assigned_schedule'])
                days_no_time = [d for d, s in best_role['assigned_schedule'].items() if s.hours > 0 and not s.time]

                # Распределение по категориям
                if best_score < dubious_thr:
                    print(f"   ⚠️ СТАТУС: DUBIOUS (Сомнительное совпадение, балл < {dubious_thr})")
                    diag.dubious.append({
                        'name': r.name, 'sheet': best_role['sheet'],
                        'title': best_role['title'], 'score': best_score,
                        'direction': r.direction, 'cabinet': r.cabinet,
                    })
                elif workdays == 0:
                    print(f"   ⚠️ СТАТУС: EMPTY_SCHEDULE (Нет рабочих дней)")
                    diag.empty_schedule.append({'name': r.name, 'sheet': best_role['sheet']})
                elif total_hours == 0:
                    print(f"   ⚠️ СТАТУС: NO_HOURS (Рабочие дни есть, часы = 0)")
                    diag.no_hours.append({'name': r.name, 'sheet': best_role['sheet'], 'workdays': workdays})
                elif days_no_time:
                    print(f"   ⚠️ СТАТУС: MISSING_TIME (Нет времени для дней: {days_no_time})")
                    diag.missing_time.append(
                        {'name': r.name, 'sheet': best_role['sheet'], 'days': sorted(days_no_time)})
                else:
                    print(f"   🟢 СТАТУС: OK (Расписание добавлено, часов: {total_hours})")
                    diag.ok.append(
                        {'name': r.name, 'sheet': best_role['sheet'], 'score': best_score, 'workdays': workdays,
                         'total_hours': total_hours})
            else:
                print(f"   ❌ ИТОГ: ОТБРАКОВАН. Лучший балл ({best_score:.2f}) ниже проходного порога ({min_accept})")
                sheet_name = best_role['sheet'] if best_role else '—'
                diag.low_score.append({
                    'name': r.name, 'best_sheet': sheet_name,
                    'score': best_score, 'direction': r.direction, 'cabinet': r.cabinet,
                })

    # Проверка "потеряшек"
    print("\n" + "═" * 80)
    print("ПРОВЕРКА НЕРАСПРЕДЕЛЕННЫХ ВРАЧЕЙ ИЗ ИСХОДНИКА")
    print("═" * 80)
    unmatched_count = 0
    for r in records:
        if r.name not in source_names_seen:
            unmatched_count += 1
            print(
                f"❓ Врач '{r.name}' (Напр: '{r.direction}', Каб: '{r.cabinet}') есть в исходнике, но не нужен в табеле.")
            diag.source_not_in_template.append(f"{r.name}  (отделение: «{r.direction}», кабинет: «{r.cabinet}»)")

    if unmatched_count == 0:
        print("Все врачи из исходника распределены.")

    print("\nЗАВЕРШЕНИЕ МАРШРУТИЗАЦИИ\n")

    return doctor_found_map


def _print_diag_report(rep: DiagReport) -> None:
    """Форматирование и вывод диагностического отчета в лог."""
    n_template = (len(rep.not_in_source) + len(rep.low_score) + len(rep.dubious) +
                  len(rep.no_hours) + len(rep.missing_time) + len(rep.empty_schedule) + len(rep.ok))
    n_warn = len(rep.dubious) + len(rep.no_hours) + len(rep.missing_time) + len(rep.empty_schedule)
    n_err = len(rep.not_in_source) + len(rep.low_score)

    logger.info("§HDR§ ИТОГОВЫЙ ДИАГНОСТИЧЕСКИЙ ОТЧЁТ")
    logger.info(f"§STAT§ Месяц: {rep.month_str}")
    logger.info(f"§STAT§ Всего врачей в шаблоне: {n_template}")
    logger.info(f"§STAT§ Врачей из источника вне шаблона: {len(rep.source_not_in_template)}")
    logger.info(f"§STAT§ Заполнено без замечаний: {len(rep.ok)}")
    logger.info(f"§STAT§ С предупреждениями: {n_warn}")
    logger.info(f"§STAT§ Не заполнено / ошибки: {n_err}")

    if rep.not_in_source:
        logger.info("§SEP§")
        logger.info("§HDR§ НЕ НАЙДЕНЫ В ИСТОЧНИКЕ")
        for x in rep.not_in_source: logger.info(f"§ERR§ {x}")

    if rep.low_score:
        logger.info("§SEP§")
        logger.info("§HDR§ НАЙДЕНЫ В ИСТОЧНИКЕ, НО НЕ НАЗНАЧЕНЫ")
        for x in rep.low_score:
            logger.info(f"§ERR§ {x['name']}")
            logger.info(f"§DETAIL§ Лучший лист: «{x['best_sheet']}»")

    if rep.no_hours:
        logger.info("§SEP§")
        logger.info("§HDR§ НАЗНАЧЕНЫ, НО НУЛЕВЫЕ ЧАСЫ ЗА ВЕСЬ МЕСЯЦ")
        for x in rep.no_hours:
            logger.info(f"§WARN§ {x['name']}  →  лист «{x['sheet']}»")

    if rep.source_not_in_template:
        logger.info("§SEP§")
        logger.info("§HDR§ ВРАЧИ ИЗ ИСТОЧНИКА, КОТОРЫХ НЕТ В ШАБЛОНЕ")
        for x in rep.source_not_in_template: logger.info(f"§INFO§ {x}")

    if rep.missing_time:
        logger.info("§SEP§")
        logger.info("§HDR§ РАБОЧИЕ ДНИ БЕЗ ВРЕМЕНИ")
        for x in rep.missing_time:
            logger.info(f"§WARN§ {x['name']}  →  лист «{x['sheet']}»")
            logger.info(f"§DETAIL§ Дни без времени: {x['days']}")

    if rep.empty_schedule:
        logger.info("§SEP§")
        logger.info("§HDR§ ПУСТОЕ РАСПИСАНИЕ — только выходные/праздники")
        for x in rep.empty_schedule: logger.info(f"§WARN§ {x['name']}  →  лист «{x['sheet']}»")


    # if rep.dubious:
    #     logger.info("§SEP§")
    #     logger.info("§HDR§ СОМНИТЕЛЬНЫЕ НАЗНАЧЕНИЯ (возможен неверный лист)")
    #     for x in rep.dubious:
    #         logger.info(f"§WARN§ {x['name']}  →  лист «{x['sheet']}»  балл={x['score']:.2f}")
    #         logger.info(f"§DETAIL§ Должность: «{x['title']}»")


def _write_diag_to_excel(wb, rep: DiagReport) -> None:
    """Создает красиво оформленный лист со сгруппированным отчетом об ошибках."""
    sheet_name = "Отчет_по_ошибкам"

    if sheet_name in wb.sheetnames:
        del wb[sheet_name]

    ws = wb.create_sheet(title=sheet_name)

    # Отключаем сетку Excel для более "чистого" вида
    ws.sheet_view.showGridLines = False

    # Настраиваем стили
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )
    align_left = Alignment(horizontal="left", vertical="center", wrap_text=True)
    align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    # Ширина колонок
    ws.column_dimensions['A'].width = 45
    ws.column_dimensions['B'].width = 70

    current_row = 1

    def add_category(title, items, format_func, bg_color, font_color):
        """Создает отдельный визуальный блок для категории."""
        nonlocal current_row
        if not items:
            return  # Если ошибок в этой категории нет, блок не рисуем

        # 1. Заголовок категории (Объединяем ячейки)
        ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=2)
        title_cell = ws.cell(row=current_row, column=1, value=title)
        title_cell.font = Font(bold=True, color=font_color, size=12)
        title_cell.fill = PatternFill(start_color=bg_color, end_color=bg_color, fill_type="solid")
        title_cell.alignment = align_center

        # Красим рамки объединенной ячейки
        for col in range(1, 3):
            ws.cell(row=current_row, column=col).border = thin_border
        current_row += 1

        # 2. Подзаголовки колонок
        ws.append(["Врач / Лист", "Детали"])
        for col in range(1, 3):
            header_cell = ws.cell(row=current_row, column=col)
            header_cell.font = Font(bold=True, color="000000")
            header_cell.fill = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")  # Светло-серый
            header_cell.alignment = align_center
            header_cell.border = thin_border
        current_row += 1

        # 3. Сами данные
        for item in items:
            doctor, details = format_func(item)
            ws.append([doctor, details])
            for col in range(1, 3):
                data_cell = ws.cell(row=current_row, column=col)
                data_cell.alignment = align_left
                data_cell.border = thin_border
            current_row += 1

        # Добавляем пустую строку-отступ между категориями
        current_row += 1

    # Заполняем блоки, задавая цвета (HEX без решетки)
    # КРАСНЫЙ: Критичные проблемы
    add_category("НЕ НАЙДЕНЫ В ГРАФИКЕ", rep.not_in_source,
                 lambda x: (x, "Врач есть в табеле, но полностью отсутствует в графике."),
                 bg_color="FFC7CE", font_color="9C0006")

    # ЖЕЛТЫЙ: Предупреждения / Проблемы с расписанием
    add_category("НАЙДЕНЫ, НО НЕ НАЗНАЧЕНЫ", rep.low_score,
                 lambda x: (x['name'], f"Слишком мало совпадений. Лучший кандидат: «{x['best_sheet']}»."),
                 bg_color="FFEB9C", font_color="9C5700")

    add_category("НАЗНАЧЕНЫ, НО НЕТ ЧАСОВ", rep.no_hours,
                 lambda x: (f"{x['name']} (Лист: {x['sheet']})",
                            "В графике есть рабочие дни, но количество часов равно нулю."),
                 bg_color="FFEB9C", font_color="9C5700")

    add_category("РАБОЧИЕ ДНИ БЕЗ ВРЕМЕНИ", rep.missing_time,
                 lambda x: (f"{x['name']} (Лист: {x['sheet']})",
                            f"Часы указаны, но не проставлен интервал времени в дни: {x['days']}"),
                 bg_color="FFEB9C", font_color="9C5700")

    add_category("ПУСТОЕ РАСПИСАНИЕ", rep.empty_schedule,
                 lambda x: (f"{x['name']} (Лист: {x['sheet']})",
                            "У врача только выходные и праздники, нет ни одного рабочего дня."),
                 bg_color="FFEB9C", font_color="9C5700")

    # СИНИЙ: Информационные сообщения
    add_category("ВРАЧИ ИЗ ГРАФИКА ВНЕ ШАБЛОНА", rep.source_not_in_template,
                 lambda x: (x, "Присутствуют в графике, но для них нет подходящего места на листах табеля."),
                 bg_color="DCE6F1", font_color="1F497D")
    # Проходимся по всем листам книги и снимаем с них выделение
    for sheet in wb.worksheets:
        if sheet.views.sheetView:
            sheet.views.sheetView[0].tabSelected = False

    # Получаем самый первый лист в книге
    first_sheet = wb.worksheets[0]

    # Выделяем первый лист
    if first_sheet.views.sheetView:
        first_sheet.views.sheetView[0].tabSelected = True

    # Делаем первый лист активным (именно он откроется при запуске файла)
    wb.active = 0

# ─── ГЛАВНАЯ ФУНКЦИЯ КОНТРОЛЛЕРА ──────────────────────────────────────────────

def fill_template(template_file: str, records: list[DoctorRecord], month_str: str, output_file: str, progress_cb=None):
    """Открывает шаблон, передает данные на обработку и сохраняет итоговый файл."""

    def _prog(v):
        if progress_cb: progress_cb(v)

    month_num, year_num, days_in_month = month_info(month_str)
    diag = DiagReport(month_str=month_str)

    c_hol = get_openpyxl_color(CONFIG.get("excel_colors", {}).get("holiday", "#FFB6C1"))
    c_week = get_openpyxl_color(CONFIG.get("excel_colors", {}).get("weekend", "#F2F2F2"))

    pink_fill = PatternFill(start_color=c_hol, end_color=c_hol, fill_type="solid") if c_hol else PatternFill(
        fill_type=None)
    gray_fill = PatternFill(start_color=c_week, end_color=c_week, fill_type="solid") if c_week else PatternFill(
        fill_type=None)
    clear_fill = PatternFill(fill_type=None)

    try:
        wb = load_workbook(template_file)
        _prog(0.40)
    except Exception as e:
        logger.error(f"Ошибка шаблона '{template_file}': {e}")
        return

    try:
        sheets = [s for s in wb.sheetnames if 'ознакомление' not in s.lower()]
        template_docs = defaultdict(list)
        sheet_configs = {}

        for sheet_name in sheets:
            ws = wb[sheet_name]
            day_row_num, day_col_map = None, {}
            for row in ws.iter_rows():
                nums = [(c.column, int(c.value)) for c in row if
                        isinstance(c.value, (int, float)) and 1 <= c.value <= 31]
                if len(nums) >= 10:
                    day_row_num = row[0].row
                    for col, d in nums: day_col_map[d] = col
                    break

            if day_row_num is None: continue
            sheet_configs[sheet_name] = {'day_row_num': day_row_num, 'day_col_map': day_col_map}

            for row in ws.iter_rows(min_row=day_row_num + 3):
                v = row[0].value
                if is_doctor_name_row(v):
                    name_clean = v.strip()
                    title = str(row[1].value or '') if len(row) > 1 else ''

                    # Проверяем, является ли лист страницей МИБС
                    is_mibs = (sheet_name.upper() == 'МИБС')

                    template_docs[yo_to_ye(name_clean)].append({
                        'sheet': sheet_name,
                        'title': title,
                        'data_r': row[0].row,
                        'time_r': row[0].row + 1,
                        'night_r': row[0].row + 2 if is_mibs else None,  # Третья строка для ночных часов
                        'assigned_schedule': {}
                    })

        _prog(0.50)
        doctor_found_map = _match_doctors_to_roles(template_docs, records, diag)
        _prog(0.75)

        # ДОБАВИЛИ month_str В ВЫЗОВ ФУНКЦИИ
        write_sheet_data(
            wb, sheets, sheet_configs, template_docs, doctor_found_map,
            month_num, year_num, days_in_month,
            pink_fill, gray_fill, clear_fill,
            month_str=month_str
        )
        _prog(0.85)

        _print_diag_report(diag)
        _write_diag_to_excel(wb, diag)
        _prog(0.92)

        try:
            wb.save(output_file)

            # 1. ЧИСТЫЕ СТРОКИ ДЛЯ ДВИЖКА GUI (чтобы всплывало окно "Открыть сформированный график")
            logger.info("Табель успешно сгенерирован!")
            logger.info(f"Файл: {output_file}")

            # 2. СТРОКИ С ПРЕФИКСАМИ ДЛЯ ЦВЕТНОЙ РАЗМЕТКИ В КОНСОЛИ
            logger.info("§SEP§")
            logger.info(f"§OK§ Табель успешно сгенерирован!")
            logger.info(f"§DETAIL§ Файл: {output_file}")

            # 3. Сигнал 100% завершения для прогресс-бара
            _prog(1.0)

        except PermissionError:
            msg = f"Закройте файл '{output_file}' в Excel и попробуйте снова."
            logger.error(f"ОШИБКА: {msg}")
            raise PermissionError(msg)
        except Exception as e:
            logger.error(f"Сбой сохранения: {e}")
            raise
    finally:
        wb.close()