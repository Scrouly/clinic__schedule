"""
pages/generate.py — страница «Генерация табеля».

Публичные атрибуты (читаются из CityClinicApp):
    src_entry      — поле пути к сводному графику
    tpl_entry      — поле пути к шаблону
    month_combo    — выпадающий список месяца
    year_entry     — поле года
    out_entry      — поле пути к результату
    run_btn        — кнопка запуска
    status_lbl     — метка статуса
    progress       — прогресс-бар
    log_box        — текстовое поле лога
"""
import customtkinter as ctk

from ..themes import T, MONTHS
from ..widgets import UIHelpersMixin


class GeneratePage(ctk.CTkFrame, UIHelpersMixin):
    """Страница генерации: выбор файлов, месяца и запуск."""

    def __init__(self, parent, app):
        ctk.CTkFrame.__init__(self, parent, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self._build()

    # ── Построение ────────────────────────────────────────────────────────────

    def _build(self):
        self._page_title(self, "Генерация табеля", "Выберите файлы, укажите месяц и запустите генерацию")

        # ── Карточка файлов
        fc = self._card(self)
        fc.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        fc.grid_columnconfigure(1, weight=1)

        self.src_entry = self._file_row(fc, 0, "Сводный график", "График 2026.xlsx", self.app._pick_source)
        self.tpl_entry = self._file_row(fc, 1, "Шаблон табеля", "ГРАФИК врачи шаблон.xlsx", self.app._pick_template)

        ctk.CTkFrame(fc, height=1, fg_color=T("BORDER")).grid(
            row=2, column=0, columnspan=3, sticky="ew", padx=10, pady=2
        )

        self._flabel(fc, "Месяц и год").grid(row=3, column=0, padx=12, pady=8, sticky="w")
        mf = ctk.CTkFrame(fc, fg_color="transparent")
        mf.grid(row=3, column=1, sticky="w", padx=(0, 10), pady=6)

        self.month_combo = self._combo(mf, MONTHS, width=150)
        self.month_combo.set("Март")
        self.month_combo.configure(command=lambda _: self.app._update_out_from_month())
        self.month_combo.pack(side="left")

        self.year_entry = self._entry(mf, placeholder_text="2026", width=80)
        self.year_entry.pack(side="left", padx=(8, 0))
        self.year_entry.bind("<KeyRelease>", lambda _: self.app._update_out_from_month())

        ctk.CTkFrame(fc, height=1, fg_color=T("BORDER")).grid(
            row=4, column=0, columnspan=3, sticky="ew", padx=10, pady=2
        )
        self.out_entry = self._file_row(fc, 5, "Сохранить как", "...ГРАФИК врачи.xlsx", self.app._pick_output, save=True)

        # ── Карточка запуска
        run_card = self._card(self)
        run_card.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        run_card.grid_columnconfigure(0, weight=1)

        ri = ctk.CTkFrame(run_card, fg_color="transparent")
        ri.pack(fill="x", padx=12, pady=10)
        ri.grid_columnconfigure(0, weight=1)

        self.run_btn = ctk.CTkButton(
            ri,
            text="⚡   СГЕНЕРИРОВАТЬ ТАБЕЛЬ",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=T("ACCENT"),
            hover_color=T("ACCENT_LIGHT"),
            text_color="#FFFFFF",
            height=42,
            corner_radius=9,
            command=self.app._start,
        )
        self.run_btn.grid(row=0, column=0, sticky="ew")

        sf = ctk.CTkFrame(ri, fg_color="transparent")
        sf.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        sf.grid_columnconfigure(1, weight=1)

        self.status_lbl = ctk.CTkLabel(
            sf, text="Ожидание", font=ctk.CTkFont(size=11), text_color=T("TEXT_DIM")
        )
        self.status_lbl.grid(row=0, column=0, sticky="w")

        self.progress = ctk.CTkProgressBar(
            sf, mode="indeterminate", height=2, progress_color=T("ACCENT"), fg_color=T("BORDER")
        )
        self.progress.grid(row=0, column=1, sticky="ew", padx=(12, 0))
        self.progress.set(0)

        # ── Карточка лога
        log_card = self._card(self)
        log_card.grid(row=4, column=0, sticky="nsew")
        self.grid_rowconfigure(4, weight=1)

        lh = ctk.CTkFrame(log_card, fg_color="transparent")
        lh.pack(fill="x", padx=12, pady=(8, 0))
        ctk.CTkLabel(
            lh, text="Лог выполнения", font=ctk.CTkFont(size=13, weight="bold"), text_color=T("TEXT_SEC")
        ).pack(side="left")
        self._ghost_btn(lh, "Очистить", self._clear_log, width=72).pack(side="right")

        self.log_box = ctk.CTkTextbox(
            log_card,
            fg_color=T("BG_DEEP"),
            text_color=T("TEXT_SEC"),
            font=ctk.CTkFont(family="Consolas", size=12),
            border_width=0,
            wrap="word",
        )
        self.log_box.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.log_box.insert("1.0", "Система готова к работе.\n")
        self.log_box.tag_config("body", foreground=T("TEXT_PRI"))
        self.log_box.tag_config("success", foreground=T("SUCCESS"))
        self.log_box.tag_config("error", foreground=T("DANGER"))
        self.log_box.tag_config("warning", foreground=T("WARNING"))
        self.log_box.tag_config("detail", foreground=T("TEXT_DIM"))
        self.log_box.tag_config("dbg", foreground=T("TEXT_DIM"))
        self.log_box.tag_config("stat", foreground=T("ACCENT"))
        self.log_box.tag_config("doc_name", foreground=T("ACCENT_LIGHT"))
        self.log_box.tag_config("days_label", foreground=T("TEXT_SEC"))
        self.log_box.tag_config("days_time", foreground=T("SUCCESS"))
        self.log_box.tag_config("separator", foreground=T("BORDER"))
        self.log_box.configure(state="disabled")

    # ── Действия ──────────────────────────────────────────────────────────────

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def set_status(self, text: str, color=None):
        self.status_lbl.configure(text=text, text_color=color or T("TEXT_DIM"))
