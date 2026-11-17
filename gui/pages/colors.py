"""
pages/colors.py — страница «Цвета Excel».

Позволяет настроить цвет ячеек для праздников и выходных дней.
Все изменения немедленно сохраняются через app._persist_excel_colors().
"""
import customtkinter as ctk

from ..colorcfg import set_excel_color
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
            colors.get("holiday", "#FFB6C1"), lambda c: self._on_color_picked("holiday", c),
        )
        ctk.CTkFrame(card, height=1, fg_color=T("BORDER")).pack(fill="x", padx=12, pady=0)
        self._build_color_row(
            card, "🌙  Выходные", "Цвет ячеек в субботу и воскресенье",
            colors.get("weekend", "#F2F2F2"), lambda c: self._on_color_picked("weekend", c),
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

    # ── Действия ──────────────────────────────────────────────────────────────

    def _on_color_picked(self, key: str, color: str):
        set_excel_color(self.app.cfg, key, color)
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
