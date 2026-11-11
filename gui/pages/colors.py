"""
pages/colors.py — страница «Цвета Excel».

Позволяет настроить цвет ячеек для праздников и выходных дней.
Все изменения немедленно сохраняются через app._persist_excel_colors().
"""
from tkinter import colorchooser

import customtkinter as ctk

from ..themes import T
from ..widgets import UIHelpersMixin


class ColorsPage(ctk.CTkFrame, UIHelpersMixin):
    """Страница настройки цветов в итоговом Excel-файле."""

    def __init__(self, parent, app):
        ctk.CTkFrame.__init__(self, parent, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self._build()

    # ── Построение ────────────────────────────────────────────────────────────

    def _build(self):
        self._page_title(self, "Цвета Excel", "Настройте подсветку ячеек в табеле")

        card = self._card(self)
        card.grid(row=2, column=0, sticky="ew", pady=(0, 8))

        colors = self.app.cfg.get("excel_colors", {})
        self._build_color_row(
            card, "🎉  Праздники", "Цвет ячеек в праздничные дни",
            colors.get("holiday", "#FFB6C1"), "holiday",
        )
        ctk.CTkFrame(card, height=1, fg_color=T("BORDER")).pack(fill="x", padx=12, pady=0)
        self._build_color_row(
            card, "🌙  Выходные", "Цвет ячеек в субботу и воскресенье",
            colors.get("weekend", "#F2F2F2"), "weekend",
        )

        # Предпросмотр
        pc = self._card(self)
        pc.grid(row=3, column=0, sticky="ew")
        pi = ctk.CTkFrame(pc, fg_color="transparent")
        pi.pack(fill="x", padx=12, pady=10)
        ctk.CTkLabel(
            pi, text="Предпросмотр",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=T("TEXT_SEC"),
        ).pack(anchor="w", pady=(0, 8))
        self._preview_frame = ctk.CTkFrame(pi, fg_color="transparent")
        self._preview_frame.pack(anchor="w")
        self._rebuild_preview()

    def _build_color_row(self, parent, title: str, subtitle: str, init_color: str, key: str):
        # Нормализуем цвет
        if init_color and not init_color.startswith("#"):
            init_color = "#" + init_color

        row_f = ctk.CTkFrame(parent, fg_color="transparent")
        row_f.pack(fill="x", padx=12, pady=8)

        info = ctk.CTkFrame(row_f, fg_color="transparent")
        info.pack(side="left")
        ctk.CTkLabel(info, text=title, font=ctk.CTkFont(size=14, weight="bold"), text_color=T("TEXT_PRI")).pack(anchor="w")
        ctk.CTkLabel(info, text=subtitle, font=ctk.CTkFont(size=12), text_color=T("TEXT_DIM")).pack(anchor="w")

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

        self._ghost_btn(
            chip_holder, "Изменить",
            lambda k=key, d=color_display, lb=color_label: self._pick_color(k, d, lb),
            width=80,
        ).pack(side="left", padx=(8, 0))

        # Сохраняем ссылки для возможной синхронизации
        if key == "holiday":
            self._chip_hol_frame = color_display
            self._chip_hol_label = color_label
        else:
            self._chip_week_frame = color_display
            self._chip_week_label = color_label

    # ── Действия ──────────────────────────────────────────────────────────────

    def _pick_color(self, key: str, display_frame, label_widget):
        current = label_widget.cget("text")
        result = colorchooser.askcolor(title="Выберите цвет", initialcolor=current)[1]
        if result:
            c = result.upper()
            display_frame.configure(fg_color=c)
            label_widget.configure(text=c)
            if "excel_colors" not in self.app.cfg:
                self.app.cfg["excel_colors"] = {}
            self.app.cfg["excel_colors"][key] = c
            self._rebuild_preview()
            self.app._persist_excel_colors()

    def _rebuild_preview(self):
        for w in self._preview_frame.winfo_children():
            w.destroy()

        hol_c = self.app.cfg.get("excel_colors", {}).get("holiday", "#FFB6C1")
        week_c = self.app.cfg.get("excel_colors", {}).get("weekend", "#F2F2F2")

        days = [
            ("Пн", "8",    "09:00-17:00", T("BG_CARD")),
            ("Вт", "8",    "09:00-17:00", T("BG_CARD")),
            ("Ср", "6.67", "09:00-15:40", T("BG_CARD")),
            ("Чт", "8",    "09:00-17:00", T("BG_CARD")),
            ("Пт", "8",    "09:00-17:00", T("BG_CARD")),
            ("Сб", "В",    "",            week_c),
            ("Вс", "В",    "",            week_c),
            ("Пн", "П",    "",            hol_c),
        ]

        for i, (day, hrs, time, bg) in enumerate(days):
            is_light = bg in (week_c, hol_c)
            txt_c = "#1A1A1A" if is_light else T("TEXT_PRI")
            sub_c = "#444444" if is_light else T("TEXT_DIM")

            col = ctk.CTkFrame(
                self._preview_frame, fg_color=T("BORDER"), corner_radius=6, width=66, height=64
            )
            col.grid(row=0, column=i, padx=2)
            col.grid_propagate(False)

            inner = ctk.CTkFrame(col, fg_color=bg, corner_radius=5, width=64, height=62)
            inner.place(x=1, y=1)
            inner.grid_propagate(False)

            ctk.CTkLabel(inner, text=day,  font=ctk.CTkFont(size=8),                  text_color=sub_c).place(x=5, y=3)
            ctk.CTkLabel(inner, text=hrs,  font=ctk.CTkFont(size=13, weight="bold"),  text_color=txt_c).place(x=5, y=18)
            ctk.CTkLabel(inner, text=time, font=ctk.CTkFont(size=8),                  text_color=sub_c).place(x=5, y=40)
