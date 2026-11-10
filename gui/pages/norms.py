"""
pages/norms.py — страница «Нормы часов».

Настройка базовых ставок и цветовой подсветки переработок/недоработок.

Публичные атрибуты:
    highlight_var      — BooleanVar: включить подсветку
    base_norm_entry    — поле базовой нормы часов
    uzd_norm_entry     — поле нормы часов УЗД
"""
import customtkinter as ctk

from ..themes import T, MONTHS
from ..widgets import UIHelpersMixin


class NormsPage(ctk.CTkFrame, UIHelpersMixin):
    """Страница настройки норм часов и цветов переработок."""

    def __init__(self, parent, app):
        ctk.CTkFrame.__init__(self, parent, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self._build()

    # ── Построение ────────────────────────────────────────────────────────────

    def _build(self):
        self._page_title(self, "Нормы часов", "Настройка базовых ставок и цветовой подсветки переработок")

        hours_ctrl = self.app.cfg.get(
            "hours_control", {"highlight_diff": True, "base_norm": 159.7, "uzd_norm": 145.0}
        )

        # ── Блок 1: числовые нормы ─────────────────────────────────────────

        card = self._card(self)
        card.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        card.grid_columnconfigure(1, weight=1)

        self.highlight_var = ctk.BooleanVar(value=hours_ctrl.get("highlight_diff", True))
        ctk.CTkSwitch(
            card,
            text="Включить цветовую подсветку табеля (красный/зелёный)",
            variable=self.highlight_var,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=T("TEXT_PRI"),
            progress_color=T("ACCENT"),
        ).grid(row=0, column=0, columnspan=2, padx=16, pady=20, sticky="w")

        ctk.CTkFrame(card, height=1, fg_color=T("BORDER")).grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=2
        )

        self._flabel(card, "Базовая норма часов (на 1 ставку):").grid(row=2, column=0, padx=16, pady=16, sticky="w")
        self.base_norm_entry = self._entry(card, placeholder_text="159.7", width=120)
        self.base_norm_entry.insert(0, str(hours_ctrl.get("base_norm", 159.7)))
        self.base_norm_entry.grid(row=2, column=1, sticky="e", padx=16, pady=16)

        ctk.CTkFrame(card, height=1, fg_color=T("BORDER")).grid(
            row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=2
        )

        self._flabel(card, "Норма часов УЗД (на 1 ставку):").grid(row=4, column=0, padx=16, pady=16, sticky="w")
        self.uzd_norm_entry = self._entry(card, placeholder_text="145.0", width=120)
        self.uzd_norm_entry.insert(0, str(hours_ctrl.get("uzd_norm", 145.0)))
        self.uzd_norm_entry.grid(row=4, column=1, sticky="e", padx=16, pady=16)

        # ── Блок 2: цвета переработок ──────────────────────────────────────

        color_card = self._card(self)
        color_card.grid(row=3, column=0, sticky="ew", pady=(0, 8))

        colors = self.app.cfg.get("excel_colors", {})
        self._build_color_row(
            color_card,
            "🔴  Переработка", "Цвет ячейки, если отработано больше нормы",
            colors.get("overwork_red", "#FFC7CE"), "overwork_red",
        )
        ctk.CTkFrame(color_card, height=1, fg_color=T("BORDER")).pack(fill="x", padx=12, pady=0)
        self._build_color_row(
            color_card,
            "🟢  Недоработка", "Цвет ячейки, если отработано меньше нормы",
            colors.get("underwork_green", "#C6EFCE"), "underwork_green",
        )

    def _build_color_row(self, parent, title: str, subtitle: str, init_color: str, key: str):
        from tkinter import colorchooser

        if init_color and not init_color.startswith("#"):
            init_color = "#" + init_color

        row_f = ctk.CTkFrame(parent, fg_color="transparent")
        row_f.pack(fill="x", padx=12, pady=8)

        info = ctk.CTkFrame(row_f, fg_color="transparent")
        info.pack(side="left")
        ctk.CTkLabel(info, text=title,    font=ctk.CTkFont(size=14, weight="bold"), text_color=T("TEXT_PRI")).pack(anchor="w")
        ctk.CTkLabel(info, text=subtitle, font=ctk.CTkFont(size=12),               text_color=T("TEXT_DIM")).pack(anchor="w")

        chip_holder = ctk.CTkFrame(row_f, fg_color="transparent")
        chip_holder.pack(side="right")

        color_display = ctk.CTkFrame(
            chip_holder, width=32, height=32,
            fg_color=init_color, corner_radius=7,
            border_width=1, border_color=T("BORDER"),
        )
        color_display.pack(side="left")
        color_display.pack_propagate(False)

        color_label = ctk.CTkLabel(
            chip_holder,
            text=init_color.upper(),
            font=ctk.CTkFont(family="Consolas", size=13),
            text_color=T("TEXT_SEC"),
        )
        color_label.pack(side="left", padx=(8, 0))

        def _pick(k=key, d=color_display, lb=color_label):
            current = lb.cget("text")
            result = colorchooser.askcolor(title="Выберите цвет", initialcolor=current)[1]
            if result:
                c = result.upper()
                d.configure(fg_color=c)
                lb.configure(text=c)
                if "excel_colors" not in self.app.cfg:
                    self.app.cfg["excel_colors"] = {}
                self.app.cfg["excel_colors"][k] = c
                self.app._persist_excel_colors()

        self._ghost_btn(chip_holder, "Изменить", _pick, width=80).pack(side="left", padx=(8, 0))
