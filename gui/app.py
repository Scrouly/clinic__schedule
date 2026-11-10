"""
app.py — CityClinicApp.

Главный класс приложения. Отвечает за:
  • загрузку/сохранение конфига и состояния GUI
  • построение боковой панели и навигацию
  • запуск генерации в отдельном потоке
  • синхронизацию конфига с модулями парсера
"""
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
import logging.handlers  # noqa: E402  (нужен для RotatingFileHandler выше)

from core import auto_schedule

from . import themes as _themes_mod
from .themes import T, THEMES
from .log_handler import TextboxHandler
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
CONFIG_FILE    = os.path.join(APP_DIR,      "auto_schedule_config.json")
LOGO_PATH      = os.path.join(RESOURCE_DIR, "resources", "logo.png")


# ── Логирование ───────────────────────────────────────────────────────────────

def setup_logger() -> None:
    log_file = os.path.join(APP_DIR, "auto_schedule.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.handlers.RotatingFileHandler(
                log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
            ),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
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

        # ── Загрузка конфига (с автосозданием при первом запуске)
        from core.config import DEFAULT_CONFIG
        if not os.path.exists(CONFIG_FILE):
            self.cfg: dict = json.loads(json.dumps(DEFAULT_CONFIG))  # глубокая копия
            try:
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.cfg, f, ensure_ascii=False, indent=4)
            except Exception as _e:
                logging.getLogger("auto_schedule").warning(
                    f"§WARN§ Не удалось создать конфиг: {_e}"
                )
        else:
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    self.cfg = json.load(f)
            except Exception:
                self.cfg = json.loads(json.dumps(DEFAULT_CONFIG))

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
        self._setup_logging()
        self._load_state()
        self._nav_to("generate")
        self.gui_logger = TextboxHandler(self.generate_page.log_box)
        self.gui_logger.setLevel(logging.INFO)

        # 2. Берем ГЛАВНЫЙ логгер программы и привязываем к нему наш обработчик
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        # Защита от двойного добавления, если __init__ вызовется дважды
        if not any(isinstance(h, TextboxHandler) for h in root_logger.handlers):
            root_logger.addHandler(self.gui_logger)

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

        self._save_state()
        self._rebuild_ui()

    def _rebuild_ui(self) -> None:
        """Уничтожает весь интерфейс и пересоздаёт с текущей темой."""
        active = self._active

        # Убираем TextboxHandler до уничтожения виджетов
        for logger_name in ("auto_schedule", "compare_schedules"):
            lg = logging.getLogger(logger_name)
            lg.handlers = [h for h in lg.handlers if not isinstance(h, TextboxHandler)]

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
        f"Разработано: t.me/Scrouly  ·  {date.today().year}"
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
        boxes = [
            ("auto_schedule",    self.generate_page.log_box),
            ("compare_schedules", self.compare_page.log_box),
        ]
        for name, box in boxes:
            logger = logging.getLogger(name)
            logger.setLevel(logging.DEBUG)
            for h in logger.handlers[:]:
                if isinstance(h, TextboxHandler):
                    logger.removeHandler(h)
            h = TextboxHandler(box)
            h.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(h)
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
            logging.getLogger("auto_schedule").error(f"Не удалось загрузить состояние GUI: {e}")

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
                        "month":      month,
                        "out":        gp.out_entry.get(),
                        "cmp_auto":   cp.auto_entry.get(),
                        "cmp_manual": cp.manual_entry.get(),
                        "theme":      self._theme_name,
                    },
                    f, ensure_ascii=False, indent=2,
                )
        except Exception as e:
            logging.getLogger("auto_schedule").error(f"Не удалось сохранить состояние GUI: {e}")

    # ── Сохранение конфига ────────────────────────────────────────────────────

    def _save_config(self) -> None:
        # 1. Валидация норм
        np = self.norms_page
        try:
            base_val = float(np.base_norm_entry.get().replace(",", "."))
            uzd_val  = float(np.uzd_norm_entry.get().replace(",", "."))
        except ValueError:
            messagebox.showerror("Ошибка", "Нормы часов должны быть числами (например, 38.5)!")
            return

        # 2. Фиксируем данные из страниц в self.cfg
        self.cfg["holidays_by"] = []
        for r in self.holidays_page.hol_rows:
            try:
                self.cfg["holidays_by"].append(
                    [int(r["m"].get().split()[0]), int(r["d"].get().strip())]
                )
            except Exception:
                pass

        self.cfg["title_keywords"] = {}
        for r in self.keywords_page.kw_rows:
            k, v = r["k"].get().strip(), r["v"].get().strip()
            if k and v:
                self.cfg["title_keywords"][k] = [w.strip() for w in v.split(",") if w.strip()]

        self.cfg["hours_control"] = {
            "highlight_diff": np.highlight_var.get(),
            "base_norm":      base_val,
            "uzd_norm":       uzd_val,
        }

        MONTH_SHORT_MAP = {
            "Янв": 1, "Фев": 2, "Мар": 3, "Апр": 4, "Май": 5, "Июн": 6,
            "Июл": 7, "Авг": 8, "Сен": 9, "Окт": 10, "Ноя": 11, "Дек": 12,
        }

        def parse_transfers(widgets_list: list) -> list:
            res = []
            for day_cb, month_cb, year_cb in widgets_list:
                try:
                    d    = int(day_cb.get())
                    m_raw = month_cb.get()
                    m = MONTH_SHORT_MAP[m_raw] if m_raw in MONTH_SHORT_MAP else int(m_raw.split()[0])
                    y = int(year_cb.get())
                    res.append([y, m, d])
                except (ValueError, IndexError):
                    pass
            return sorted(res, key=lambda x: (x[0], x[1], x[2]))

        self.cfg["transfers_work_days"] = parse_transfers(self.transfers_page.tw_rows)
        self.cfg["transfers_rest_days"] = parse_transfers(self.transfers_page.tr_rows)

        # 3. Запись на диск и синхронизация
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=4)
            self._force_sync_config()
            messagebox.showinfo("Сохранено", "✓  Настройки успешно сохранены.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить:\n{e}")

    # ── Синхронизация конфига с модулями парсера ──────────────────────────────

    def _persist_excel_colors(self) -> None:
        """Немедленно сохраняет excel_colors и синхронизирует парсер."""
        self._force_sync_config()

    def _force_sync_config(self) -> None:
        """
        Записывает self.cfg на диск и патчит объекты CONFIG/HOLIDAYS
        во всех уже импортированных модулях парсера in-place.

        Нельзя вызывать reload_config() — он создаёт новый dict,
        разрывая общую ссылку между auto_schedule, excel_io и utils.
        """
        # 1. Диск
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=4)
        except Exception:
            pass

        # 2. Патч CONFIG in-place
        try:
            if hasattr(auto_schedule, "CONFIG"):
                cfg_obj = auto_schedule.CONFIG
                for k, v in self.cfg.items():
                    cfg_obj[k] = v
                for k in list(cfg_obj.keys()):
                    if k not in self.cfg:
                        del cfg_obj[k]
        except Exception:
            pass

        # 3. Явная замена utils.HOLIDAYS
        try:
            from core import utils as _utils_mod
            _utils_mod.HOLIDAYS = set(tuple(x) for x in self.cfg.get("holidays_by", []))
        except Exception:
            pass

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
        gp   = self.generate_page
        src  = gp.src_entry.get().strip()
        tpl  = gp.tpl_entry.get().strip()
        year = gp.year_entry.get().strip() or str(date.today().year)
        month = f"{gp.month_combo.get()} {year}"
        out  = gp.out_entry.get().strip()

        if not all([src, tpl, out]):
            messagebox.showwarning("Внимание", "Заполните все поля перед запуском.")
            return
        if not os.path.exists(src):
            messagebox.showerror("Файл не найден", f"Сводный график не найден:\n{src}")
            return
        if not os.path.exists(tpl):
            messagebox.showerror("Файл не найден", f"Шаблон табеля не найден:\n{tpl}")
            return
        if not year.isdigit() or not (2000 <= int(year) <= 2100):
            messagebox.showwarning("Внимание", "Укажите корректный год (2000–2100).")
            return
        if os.path.exists(out):
            if not messagebox.askyesno("Файл уже существует", f"Файл уже существует:\n{out}\n\nЗаменить его?"):
                return

        self._save_state()
        self._force_sync_config()

        gp.run_btn.configure(state="disabled", text="⏳   Обработка…")
        gp.set_status("Читаю файлы…", T("ACCENT_LIGHT"))
        gp.progress.configure(mode="determinate")
        gp.progress.set(0)
        gp._clear_log()

        threading.Thread(target=self._process, args=(src, tpl, month, out), daemon=True).start()

    def _process(self, src: str, tpl: str, month: str, out: str) -> None:
        gp = self.generate_page

        def on_progress(v: float):
            self.after(0, lambda val=v: gp.progress.set(val))
            if v < 0.30:
                self.after(0, lambda: gp.set_status("Читаю источник…",     T("ACCENT_LIGHT")))
            elif v < 0.50:
                self.after(0, lambda: gp.set_status("Читаю шаблон…",       T("ACCENT_LIGHT")))
            elif v < 0.75:
                self.after(0, lambda: gp.set_status("Сопоставляю врачей…", T("ACCENT_LIGHT")))
            elif v < 0.92:
                self.after(0, lambda: gp.set_status("Записываю данные…",   T("ACCENT_LIGHT")))
            else:
                self.after(0, lambda: gp.set_status("Сохраняю файл…",      T("ACCENT_LIGHT")))

        try:
            records = auto_schedule.parse_source(src, month, progress_cb=on_progress)
            auto_schedule.fill_template(tpl, records, month, out, progress_cb=on_progress)
            self.after(0, self._on_success)
        except Exception as e:
            logging.getLogger("auto_schedule").error(f"Сбой: {e}")
            self.after(0, lambda err=e: self._on_error(err))
        finally:
            self.after(0, self._reset_ui)

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
        gp = self.generate_page
        gp.progress.set(0)
        gp.progress.configure(mode="indeterminate")
        gp.run_btn.configure(state="normal", text="⚡   СГЕНЕРИРОВАТЬ ТАБЕЛЬ")

    # ── Закрытие ──────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        saved: dict = {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f).get("excel_colors", {})
        except Exception:
            pass

        current = self.cfg.get("excel_colors", {})
        if current != saved:
            if not messagebox.askyesno(
                "Несохранённые изменения",
                "Есть несохранённые изменения цветов.\n\nВыйти без сохранения?",
            ):
                return

        self._save_state()
        self.destroy()