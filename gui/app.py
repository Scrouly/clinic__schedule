"""
app.py — CityClinicApp.

Главный класс приложения. Отвечает за:
  • загрузку/сохранение конфига и состояния GUI
  • построение боковой панели и навигацию
  • запуск генерации в отдельном потоке
  • синхронизацию конфига с модулями парсера
"""
import copy
import json
import logging
import os
import subprocess
import sys
import threading
from datetime import date
from tkinter import filedialog, messagebox
import webbrowser

import customtkinter as ctk
from PIL import Image

from core import auto_schedule, cfgdiff, dental, norms, outfile
from core import config as core_config
from core import holidays as holiday_utils

from . import themes as _themes_mod
from .themes import T, THEMES
from .log_handler import (
    COMPARE_LOGGERS,
    GENERATE_LOGGERS,
    bind_textbox,
    configure_logging,
    detach_all_textbox_handlers,
)
from .progress import MainThreadQueue, stage_for
from .widgets import UIHelpersMixin
from .pages.generate import GeneratePage
from .pages.colors import ColorsPage
from .pages.keywords import KeywordsPage
from .pages.holidays import HolidaysPage
from .pages.norms import NormsPage
from .pages.transfers import TransfersPage
from .pages.compare import ComparePage


# ── Пути ──────────────────────────────────────────────────────────────────────

def _get_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # не frozen: __file__ = gui/app.py → поднимаемся к корню проекта
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_resource_dir() -> str:
    if getattr(sys, "frozen", False):
        return sys._MEIPASS  # type: ignore[attr-defined]
    # не frozen: __file__ = gui/app.py → поднимаемся к корню проекта
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


APP_DIR      = _get_app_dir()
RESOURCE_DIR = _get_resource_dir()

GUI_STATE_FILE = os.path.join(APP_DIR,      "gui_state.json")
LOGO_PATH      = os.path.join(RESOURCE_DIR, "resources", "logo.png")

# Названия разделов настроек для сообщений пользователю (ключи — разделы файла настроек).
_SECTION_TITLES = {
    "title_keywords":      "Направления",
    "holidays_by":         "Праздники",
    "hours_control":       "Нормы часов",
    "norms_by_specialty":  "Нормы часов",
    "transfers_work_days": "Переносы",
    "transfers_rest_days": "Переносы",
    "excel_colors":        "Цвета Excel",
}


def _section_names(keys) -> str:
    """«Праздники, Нормы часов» — без повторов, в порядке появления."""
    names = []
    for key in keys:
        name = _SECTION_TITLES.get(key, key)
        if name not in names:
            names.append(name)
    return ", ".join(names)


# ── Логирование ───────────────────────────────────────────────────────────────

# Логгер генерации: тот же, что у core/auto_schedule.py (его __name__).
# Сообщения GUI об ошибках идут в него, чтобы попадать в лог страницы «Генерация».
gen_log = logging.getLogger(GENERATE_LOGGERS[0])


def setup_logger() -> None:
    """Файл и консоль: INFO. Отладочный вывод (разбор сопоставления врачей) включается
    переменной окружения CITYCLINIC_DEBUG=1 и пишется только в файл и консоль, не в окно."""
    configure_logging(
        os.path.join(APP_DIR, "auto_schedule.log"),
        debug=os.environ.get("CITYCLINIC_DEBUG", "") not in ("", "0"),
    )

setup_logger()

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ── Главное окно ──────────────────────────────────────────────────────────────

class CityClinicApp(ctk.CTk, UIHelpersMixin):

    def __init__(self):
        super().__init__()
        self.title("CityClinic  ·  Auto Schedule")
        self.geometry("960x650")
        self.minsize(920, 560)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Идёт ли генерация. Нужен, чтобы после смены темы (страница пересоздаётся, кнопка
        # снова активна) нельзя было запустить вторую генерацию поверх первой.
        self._busy = False

        # ── Настройки: окно правит свою копию, в рабочие (core_config.CONFIG) и в файл они
        # попадают при сохранении. Файл создаётся при первом сохранении, не при запуске.
        self.cfg: dict = copy.deepcopy(core_config.get_config())
        # Проблемы файла настроек (испорчен, неверный раздел) — показываем в окне, а не в
        # консоли: в собранной программе консоли нет. Копируем сразу: load_config очищает список.
        self._startup_warnings: list = list(core_config.LOAD_WARNINGS)

        # ── Тема из сохранённого состояния (gui_state.json создаётся при первом сохранении)
        self._active      = "generate"
        self._theme_name  = "Тёмная"
        if not os.path.exists(GUI_STATE_FILE):
            # Первый запуск — сразу записываем пустой стейт с темой по умолчанию
            try:
                with open(GUI_STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump({"theme": self._theme_name}, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        else:
            try:
                with open(GUI_STATE_FILE, "r", encoding="utf-8") as f:
                    _s = json.load(f)
                if _s.get("theme") in THEMES:
                    self._theme_name = _s["theme"]
            except Exception:
                pass

        self._apply_theme(self._theme_name, rebuild=False)
        self._build_layout()
        # Логи привязываются здесь и заново — в _rebuild_ui (смена темы).
        # Раньше в __init__ ещё вешался хендлер на корневой логгер, и он не
        # переживал пересборку интерфейса.
        self._setup_logging()
        self._load_state()
        self._nav_to("generate")

        # Рабочие потоки не трогают Tk: они кладут задания сюда, а выполняет их главный поток.
        self.ui_queue = MainThreadQueue(self)
        self.ui_queue.start()

        if self._startup_warnings:
            self.after(300, self._show_startup_warnings)

    def _show_startup_warnings(self) -> None:
        messagebox.showwarning("Файл настроек", "\n\n".join(self._startup_warnings))
        self._startup_warnings = []

    # ── Тема ──────────────────────────────────────────────────────────────────

    def _apply_theme(self, name: str, rebuild: bool = True) -> None:
        if rebuild and name == self._theme_name:
            return
        self._theme_name = name
        _themes_mod.CURRENT_THEME = THEMES[name]
        ctk.set_appearance_mode(THEMES[name]["mode"])

        if not rebuild:
            self.configure(fg_color=T("BG_DEEP"))
            return

        # Страницы настроек пересоздаются из self.cfg. Без этого шага всё, что
        # пользователь поменял, но ещё не сохранил кнопкой «Сохранить настройки»
        # (праздники, направления, нормы, переносы), пропадало при смене темы.
        try:
            self._snapshot_pages_into_cfg()
        except Exception as e:
            gen_log.warning(f"§WARN§ Не удалось сохранить несохранённые правки при смене темы: {e}")

        self._save_state()
        self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        """Уничтожает весь интерфейс и пересоздаёт с текущей темой."""
        active = self._active

        # Снимаем ВСЕ TextboxHandler до уничтожения виджетов — иначе они
        # останутся привязанными к мёртвым текстовым полям.
        detach_all_textbox_handlers()

        for w in self.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        self.configure(fg_color=T("BG_DEEP"))
        self._build_layout()
        self._setup_logging()
        self._load_state()
        self._nav_to(active)

        if self._busy:
            # Генерация идёт в фоне: на новой странице кнопка должна быть заблокирована
            self.generate_page.run_btn.configure(state="disabled", text="⏳   Обработка…")

    # ── Разметка ──────────────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._sidebar = ctk.CTkFrame(self, width=200, fg_color=T("BG_PANEL"), corner_radius=0)
        self._sidebar.grid(row=0, column=0, sticky="nsew")
        self._sidebar.grid_propagate(False)
        self._build_sidebar()

        self._content = ctk.CTkFrame(self, fg_color=T("BG_DEEP"), corner_radius=0)
        self._content.grid(row=0, column=1, sticky="nsew")
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_rowconfigure(0, weight=1)

        # Создаём страницы
        self.generate_page  = GeneratePage (self._content, self)
        self.colors_page    = ColorsPage   (self._content, self)
        self.keywords_page  = KeywordsPage (self._content, self)
        self.holidays_page  = HolidaysPage (self._content, self)
        self.norms_page     = NormsPage    (self._content, self)
        self.transfers_page = TransfersPage(self._content, self)
        self.compare_page   = ComparePage  (self._content, self)

        self._pages = {
            "generate":  self.generate_page,
            "colors":    self.colors_page,
            "keywords":  self.keywords_page,
            "holidays":  self.holidays_page,
            "norms":     self.norms_page,
            "transfers": self.transfers_page,
            "compare":   self.compare_page,
        }

    def _build_sidebar(self) -> None:
        sb = self._sidebar

        # Лого
        logo = ctk.CTkFrame(sb, fg_color="transparent", height=44)
        logo.pack(fill="x", padx=12, pady=(16, 8))
        logo.pack_propagate(False)

        if os.path.exists(LOGO_PATH):
            _pil = Image.open(LOGO_PATH)
            _w = 156
            _h = int(_pil.height * _w / _pil.width)
            self._logo_img = ctk.CTkImage(light_image=_pil, dark_image=_pil, size=(_w, _h))
            ctk.CTkLabel(logo, image=self._logo_img, text="").pack(anchor="w")
        else:
            ctk.CTkLabel(
                logo, text="◈  CityClinic",
                font=ctk.CTkFont(family="Segoe UI", size=17, weight="bold"),
                text_color=T("TEXT_PRI"),
            ).pack(anchor="w")
            ctk.CTkLabel(
                logo, text="Auto Schedule",
                font=ctk.CTkFont(size=12), text_color=T("TEXT_DIM"),
            ).pack(anchor="w")

        self._div(sb)

        # Навигация
        nav = ctk.CTkFrame(sb, fg_color="transparent")
        nav.pack(fill="x", padx=8)

        self._lbl(nav, "ГЛАВНАЯ")
        self._nb   = self._sbtn(nav, "⚡", "Генерация",    lambda: self._nav_to("generate"))
        self._ncmp = self._sbtn(nav, "🔍", "Сравнение",    lambda: self._nav_to("compare"))

        self._lbl(nav, "НАСТРОЙКИ")
        self._nc   = self._sbtn(nav, "🎨", "Цвета Excel",  lambda: self._nav_to("colors"))
        self._nk   = self._sbtn(nav, "🗂", "Направления",  lambda: self._nav_to("keywords"))
        self._nh   = self._sbtn(nav, "📅", "Праздники",    lambda: self._nav_to("holidays"))
        self._nn   = self._sbtn(nav, "⏱", "Нормы часов",  lambda: self._nav_to("norms"))
        self._nt   = self._sbtn(nav, "🔄", "Переносы",     lambda: self._nav_to("transfers"))

        self._nav_map = {
            "generate":  self._nb,
            "colors":    self._nc,
            "keywords":  self._nk,
            "holidays":  self._nh,
            "norms":     self._nn,
            "transfers": self._nt,
            "compare":   self._ncmp,
        }

        self._div(sb)

        # Выбор темы
        theme_f = ctk.CTkFrame(sb, fg_color="transparent")
        theme_f.pack(fill="x", padx=10, pady=(4, 2))
        ctk.CTkLabel(
            theme_f, text="  ТЕМА",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=T("TEXT_DIM"),
        ).pack(anchor="w", pady=(0, 4))

        self._theme_btns: dict = {}
        for tname in THEMES:
            active = tname == self._theme_name
            btn = ctk.CTkButton(
                theme_f, text=tname, height=32,
                font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold" if active else "normal"),
                fg_color=T("ACCENT_DIM") if active else "transparent",
                text_color=T("ACCENT_LIGHT") if active else T("TEXT_SEC"),
                hover_color=T("BG_CARD_HVR"), corner_radius=8, anchor="w",
                command=lambda n=tname: self._apply_theme(n),
            )
            btn.pack(fill="x", pady=1)
            self._theme_btns[tname] = btn

        self._div(sb)

        # Кнопка «Сохранить настройки»
        ctk.CTkButton(
            sb, text="💾  Сохранить настройки",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=T("ACCENT"), hover_color=T("ACCENT_LIGHT"),
            text_color="#FFFFFF", height=36, corner_radius=8,
            command=self._save_config,
        ).pack(fill="x", padx=10, pady=(2, 6))

        # 1. СОЗДАЕМ виджет и сохраняем его в переменную
        author_label = ctk.CTkLabel(
            sb,
            text=f"Разработано: t.me/Scrouly  ·  {date.today().year}",
            font=ctk.CTkFont(size=11, underline=False),
            text_color=T("TEXT_DIM"),
            cursor="hand2"
        )

        # 2. РАЗМЕЩАЕМ виджет (строго на отдельной строке!)
        author_label.pack(side="bottom", pady=8)

        # 3. ПРИВЯЗЫВАЕМ клик
        author_label.bind(
            "<Button-1>",
            lambda event: webbrowser.open("https://t.me/Scrouly")
        )

    # ── Навигация ─────────────────────────────────────────────────────────────

    def _nav_to(self, key: str) -> None:
        self._active = key
        for k, b in self._nav_map.items():
            if k == key:
                b.configure(
                    fg_color=T("ACCENT_DIM"), text_color=T("ACCENT_LIGHT"),
                    font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
                )
            else:
                b.configure(
                    fg_color="transparent", text_color=T("TEXT_SEC"),
                    font=ctk.CTkFont(family="Segoe UI", size=13),
                )
        for k, p in self._pages.items():
            if k == key:
                p.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
            else:
                p.grid_remove()

    # ── Логирование в виджет ──────────────────────────────────────────────────

    def _setup_logging(self) -> None:
        """Привязывает лог-боксы страниц к логгерам core.* (см. gui/log_handler.py).
        Корневой логгер не трогаем: на нём остаётся только запись в файл/консоль."""
        detach_all_textbox_handlers()
        bind_textbox(GENERATE_LOGGERS, self.generate_page.log_box)
        bind_textbox(COMPARE_LOGGERS,  self.compare_page.log_box)
        self._refresh_log_tags()

    def _refresh_log_tags(self) -> None:
        boxes = []
        if hasattr(self, "generate_page"):
            boxes.append(self.generate_page.log_box)
        if hasattr(self, "compare_page"):
            boxes.append(self.compare_page.log_box)
        for box in boxes:
            try:
                box.tag_config("header",     foreground=T("ACCENT_LIGHT"), font=("Segoe UI", 13, "bold"))
                box.tag_config("separator",  foreground=T("TEXT_DIM"))
                box.tag_config("body",       foreground=T("TEXT_SEC"))
                box.tag_config("stat_val",   foreground=T("TEXT_PRI"),     font=("Segoe UI", 12, "bold"))
                box.tag_config("doc_name",   foreground=T("TEXT_PRI"),     font=("Segoe UI", 12, "bold"))
                box.tag_config("detail",     foreground=T("TEXT_DIM"))
                box.tag_config("days_label", foreground=T("TEXT_SEC"))
                box.tag_config("days_time",  foreground=T("ACCENT_LIGHT"), font=("Consolas", 12, "bold"))
                box.tag_config("success",    foreground=T("SUCCESS"),      font=("Segoe UI", 12, "bold"))
                box.tag_config("warning",    foreground=T("WARNING"))
                box.tag_config("error",      foreground=T("DANGER"))
                box.tag_config("info",       foreground=T("ACCENT_LIGHT"))
                box.tag_config("dbg",        foreground=T("TEXT_DIM"))
            except Exception:
                pass

    # ── Состояние GUI ─────────────────────────────────────────────────────────

    def _load_state(self) -> None:
        if not os.path.exists(GUI_STATE_FILE):
            return
        try:
            with open(GUI_STATE_FILE, "r", encoding="utf-8") as f:
                s = json.load(f)
            gp = self.generate_page
            cp = self.compare_page
            for key, entry in [
                ("src",        gp.src_entry),
                ("tpl",        gp.tpl_entry),
                ("dental",     gp.dental_entry),
                ("out",        gp.out_entry),
                ("cmp_auto",   cp.auto_entry),
                ("cmp_manual", cp.manual_entry),
            ]:
                if s.get(key):
                    entry.insert(0, s[key])
            if s.get("month"):
                parts = s["month"].split()
                gp.month_combo.set(parts[0])
                if len(parts) > 1:
                    gp.year_entry.insert(0, parts[1])
        except Exception as e:
            gen_log.error(f"Не удалось загрузить состояние GUI: {e}")

    def _save_state(self) -> None:
        try:
            gp = self.generate_page
            cp = self.compare_page
            month = f"{gp.month_combo.get()} {gp.year_entry.get() or str(date.today().year)}"
            with open(GUI_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "src":        gp.src_entry.get(),
                        "tpl":        gp.tpl_entry.get(),
                        "dental":     gp.dental_entry.get(),
                        "month":      month,
                        "out":        gp.out_entry.get(),
                        "cmp_auto":   cp.auto_entry.get(),
                        "cmp_manual": cp.manual_entry.get(),
                        "theme":      self._theme_name,
                    },
                    f, ensure_ascii=False, indent=2,
                )
        except Exception as e:
            gen_log.error(f"Не удалось сохранить состояние GUI: {e}")

    # ── Сохранение конфига ────────────────────────────────────────────────────

    def _collect_page_settings(self, base_val: float, rules: list) -> None:
        """Переносит значения со страниц настроек в self.cfg (на диск не пишет)."""
        np = self.norms_page

        self.cfg["title_keywords"] = {}
        for r in self.keywords_page.kw_rows:
            k, v = r["k"].get().strip(), r["v"].get().strip()
            if k and v:
                self.cfg["title_keywords"][k] = [w.strip() for w in v.split(",") if w.strip()]

        # Норма УЗД теперь строка таблицы norms_by_specialty, а не отдельное поле
        self.cfg["hours_control"] = {
            "highlight_diff": np.highlight_var.get(),
            "base_norm":      base_val,
        }
        self.cfg["norms_by_specialty"] = rules

        self.cfg["transfers_work_days"] = holiday_utils.transfers_from_rows(self.transfers_page.tw_rows)
        self.cfg["transfers_rest_days"] = holiday_utils.transfers_from_rows(self.transfers_page.tr_rows)

        # Последними: некорректный год праздника прерывает сбор исключением ValueError,
        # а всё остальное к этому моменту уже перенесено.
        self.cfg["holidays_by"] = holiday_utils.from_form_rows(
            (int(r["m"].get().split()[0]), int(r["d"].get().strip()), r["y"].get())
            for r in self.holidays_page.hol_rows
        )

    def _snapshot_pages_into_cfg(self) -> None:
        """Запоминает несохранённые правки страниц в self.cfg перед пересборкой
        интерфейса (смена темы). Некорректный ввод в нормах не запоминается —
        для норм остаются прежние значения, остальное переносится как есть."""
        np = self.norms_page
        try:
            base_val = norms.parse_weekly(np.base_norm_entry.get(), "Базовая норма")
            rules    = norms.parse_norm_rules(np.get_rule_rows())
        except norms.NormsError:
            base_val = self.cfg.get("hours_control", {}).get("base_norm", 38.5)
            rules    = norms.rules_for_display(self.cfg)
        self._collect_page_settings(base_val, rules)

    def _save_config_quiet(self) -> bool:
        """Проверяет значения на страницах, применяет их и записывает файл.
        Ошибки показывает сама (окном). True — настройки сохранены."""
        # 1. Валидация норм
        np = self.norms_page
        try:
            base_val = norms.parse_weekly(np.base_norm_entry.get(), "Базовая норма")
            rules    = norms.parse_norm_rules(np.get_rule_rows())
        except norms.NormsError as e:
            messagebox.showerror("Ошибка в нормах часов", str(e))
            return False

        # 2. Фиксируем данные из страниц в self.cfg
        try:
            self._collect_page_settings(base_val, rules)
        except ValueError as e:
            messagebox.showerror("Ошибка в праздничных днях", str(e))
            return False

        # 3. Запись на диск и применение
        return self._force_sync_config()

    def _save_config(self) -> None:
        if self._save_config_quiet():
            messagebox.showinfo("Сохранено", "✓  Настройки успешно сохранены.")

    # ── Синхронизация конфига с модулями парсера ──────────────────────────────

    def _persist_excel_colors(self) -> None:
        """Немедленно сохраняет excel_colors и синхронизирует парсер."""
        self._force_sync_config()

    def _force_sync_config(self) -> bool:
        """Применяет self.cfg к рабочим настройкам на месте (core_config.update_config:
        новый dict создавать нельзя — на CONFIG ссылаются auto_schedule, excel_io и utils)
        и записывает файл. False — файл записать не удалось (ошибка показана пользователю;
        в текущем сеансе настройки при этом действуют)."""
        core_config.update_config(self.cfg)
        try:
            core_config.save_config()
        except core_config.ConfigSaveError as e:
            messagebox.showerror("Настройки не сохранены", str(e))
            return False
        return True

    # ── Выбор файлов (колбэки для GeneratePage) ───────────────────────────────

    def _pick_source(self) -> None:
        fp = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx *.xls")])
        if fp:
            self.generate_page.src_entry.delete(0, "end")
            self.generate_page.src_entry.insert(0, fp)

    def _pick_template(self) -> None:
        fp = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx *.xls")])
        if fp:
            self.generate_page.tpl_entry.delete(0, "end")
            self.generate_page.tpl_entry.insert(0, fp)
            self._update_out_from_month()

    def _pick_dental(self) -> None:
        fp = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx *.xls")])
        if fp:
            self.generate_page.dental_entry.delete(0, "end")
            self.generate_page.dental_entry.insert(0, fp)

    def _pick_output(self) -> None:
        fp = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if fp:
            self.generate_page.out_entry.delete(0, "end")
            self.generate_page.out_entry.insert(0, fp)

    def _update_out_from_month(self) -> None:
        gp  = self.generate_page
        tpl = gp.tpl_entry.get().strip()
        if not tpl:
            return
        folder = os.path.dirname(tpl)
        month  = gp.month_combo.get().upper()
        year   = gp.year_entry.get().strip() or str(date.today().year)
        gp.out_entry.delete(0, "end")
        gp.out_entry.insert(0, os.path.join(folder, f"ГРАФИК врачи {month} {year}.xlsx"))

    # ── Генерация ─────────────────────────────────────────────────────────────

    def _start(self) -> None:
        if self._busy:
            messagebox.showinfo("Генерация идёт", "Табель уже формируется — дождитесь окончания.")
            return

        gp   = self.generate_page
        src  = gp.src_entry.get().strip()
        tpl  = gp.tpl_entry.get().strip()
        dental_src = gp.dental_entry.get().strip()  # необязательный
        year = gp.year_entry.get().strip() or str(date.today().year)
        month = f"{gp.month_combo.get()} {year}"
        out  = gp.out_entry.get().strip()

        empty = [name for name, value in (
            ("«Сводный график»", src), ("«Шаблон табеля»", tpl), ("«Сохранить как»", out),
        ) if not value]
        if empty:
            messagebox.showwarning("Внимание", "Не заполнено: " + ", ".join(empty) + ".")
            return
        if not os.path.exists(src):
            messagebox.showerror("Файл не найден", f"Сводный график не найден:\n{src}")
            return
        if not os.path.exists(tpl):
            messagebox.showerror("Файл не найден", f"Шаблон табеля не найден:\n{tpl}")
            return
        if dental_src and not os.path.exists(dental_src):
            messagebox.showerror("Файл не найден", f"График стоматологии не найден:\n{dental_src}")
            return
        if not year.isdigit() or not (2000 <= int(year) <= 2100):
            messagebox.showwarning("Внимание", "Укажите корректный год (2000–2100).")
            return
        # Результат не должен затирать исходные файлы: иначе пропадёт шаблон или график.
        out_key = os.path.normcase(os.path.abspath(out))
        protected = [src, tpl] + ([dental_src] if dental_src else [])
        if out_key in (os.path.normcase(os.path.abspath(p)) for p in protected):
            messagebox.showerror(
                "Нельзя перезаписать исходный файл",
                "Путь в поле «Сохранить как» совпадает со сводным графиком, графиком стоматологии "
                "или шаблоном.\nВыберите другое имя файла для результата.",
            )
            return
        if os.path.exists(out):
            if not messagebox.askyesno("Файл уже существует", f"Файл уже существует:\n{out}\n\nЗаменить его?"):
                return
        try:
            outfile.check_output_writable(out)
        except outfile.OutputNotWritable as e:
            messagebox.showerror("Нельзя сохранить результат", str(e))
            return

        # Правки на страницах настроек, которые не сохранены кнопкой «Сохранить настройки»,
        # в генерации не участвуют. Не даём этому случиться молча.
        changed = self._unsaved_settings()
        if changed:
            if not messagebox.askyesno(
                "Несохранённые настройки",
                f"Изменены, но не сохранены настройки: {_section_names(changed)}.\n\n"
                "Сохранить их и продолжить генерацию?\n"
                "(«Нет» — вернуться, чтобы проверить настройки.)",
            ):
                return
            if not self._save_config_quiet():
                return

        self._save_state()
        self._force_sync_config()

        self._busy = True
        gp.run_btn.configure(state="disabled", text="⏳   Обработка…")
        gp.set_status("Читаю файлы…", T("ACCENT_LIGHT"))
        gp.progress.configure(mode="determinate")
        gp.progress.set(0)
        gp._clear_log()

        threading.Thread(target=self._process, args=(src, tpl, month, out, dental_src), daemon=True).start()

    def _process(self, src: str, tpl: str, month: str, out: str, dental_src: str = "") -> None:
        post = self.ui_queue.post
        shown = {"stage": None}

        def apply_progress(v: float) -> None:
            gp = self.generate_page        # страница могла быть пересобрана сменой темы
            gp.progress.set(v)
            stage = stage_for(v)
            if stage != shown["stage"]:
                shown["stage"] = stage
                gp.set_status(stage, T("ACCENT_LIGHT"))

        def on_progress(v: float) -> None:
            # Только последнее значение: промежуточные никому не нужны
            self.ui_queue.post_latest("progress", lambda: apply_progress(v))

        try:
            records = auto_schedule.parse_source(src, month, progress_cb=on_progress)
            if dental_src:
                records += dental.parse_dental_source(dental_src, month)
            auto_schedule.fill_template(tpl, records, month, out, progress_cb=on_progress)
            post(self._on_success)
        except Exception as e:
            gen_log.error(f"Сбой: {e}")
            post(lambda err=e: self._on_error(err))
        finally:
            post(self._reset_ui)

    def _on_success(self) -> None:
        self.generate_page.set_status("✓  Табель готов!", T("SUCCESS"))
        if messagebox.askyesno("Готово", "Табель успешно сформирован!\n\nОткрыть папку с файлом?"):
            self._open_output_folder()

    def _open_output_folder(self) -> None:
        path = self.generate_page.out_entry.get().strip()
        if path and os.path.exists(path):
            subprocess.Popen(f'explorer /select,"{os.path.abspath(path)}"')
        elif path:
            folder = os.path.dirname(os.path.abspath(path))
            if os.path.isdir(folder):
                subprocess.Popen(f'explorer "{folder}"')

    def _on_error(self, err: Exception) -> None:
        self.generate_page.set_status("✕  Ошибка", T("DANGER"))
        messagebox.showerror("Ошибка", str(err))

    def _reset_ui(self) -> None:
        self._busy = False
        gp = self.generate_page
        gp.progress.set(0)
        gp.progress.configure(mode="indeterminate")
        gp.run_btn.configure(state="normal", text="⚡   СГЕНЕРИРОВАТЬ ТАБЕЛЬ")

    # ── Закрытие ──────────────────────────────────────────────────────────────

    def _unsaved_settings(self) -> list:
        """Разделы настроек, изменённые в окне, но не записанные в файл (все, а не только цвета).

        Проверка только читает: self.cfg после неё остаётся таким, каким был. Иначе правки,
        от которых пользователь отказался, оказались бы в self.cfg и ушли в файл со следующим
        выбором цвета."""
        saved_cfg = copy.deepcopy(self.cfg)
        try:
            self._snapshot_pages_into_cfg()
            return cfgdiff.unsaved_sections(self.cfg, core_config.load_config())
        except ValueError:
            # Правка есть, но она некорректна (например, год праздника — не число): собрать её
            # в настройки нельзя, значит она точно не сохранена.
            return ["holidays_by"]
        except Exception as e:      # не удалось сравнить — не мешаем закрыть окно
            gen_log.warning(f"Не удалось проверить несохранённые настройки: {e}")
            return []
        finally:
            self.cfg.clear()
            self.cfg.update(saved_cfg)

    def _on_close(self) -> None:
        changed = self._unsaved_settings()
        if changed:
            if not messagebox.askyesno(
                "Несохранённые изменения",
                f"Есть несохранённые изменения настроек: {_section_names(changed)}.\n\nВыйти без сохранения?",
            ):
                return

        self._save_state()
        self.ui_queue.stop()
        detach_all_textbox_handlers()
        self.destroy()
