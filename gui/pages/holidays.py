"""
pages/holidays.py — страница «Праздничные дни».

Редактирование списка holidays_by: [месяц, день] — каждый год,
[год, месяц, день] — только в этом году (поле «Год» не заполнено — праздник каждый год).

Публичные атрибуты:
    hol_rows  — список dict{"frame", "m", "d", "y"} для чтения в _save_config
"""
import calendar

import customtkinter as ctk

from core import holidays

from ..themes import T, MONTHS
from ..widgets import UIHelpersMixin


class HolidaysPage(ctk.CTkFrame, UIHelpersMixin):
    """Страница настройки праздничных дней."""

    def __init__(self, parent, app):
        ctk.CTkFrame.__init__(self, parent, fg_color="transparent")
        self.app = app
        self.hol_rows: list[dict] = []
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build()

    # ── Построение ────────────────────────────────────────────────────────────

    def _build(self):
        self._page_title(self, "Праздничные дни",
                         "Дни, которые будут помечены «П» и подсвечены в табеле. "
                         "Год можно не указывать — тогда праздник повторяется каждый год")

        card = self._card(self)
        card.grid(row=2, column=0, sticky="nsew")

        self._hol_scroll = ctk.CTkScrollableFrame(
            card, fg_color="transparent",
            scrollbar_button_color=T("BORDER"),
            scrollbar_button_hover_color=T("BG_CARD_HVR"),
        )
        self._hol_scroll.pack(fill="both", expand=True, padx=8, pady=8)

        for item in self.app.cfg.get("holidays_by", []):
            try:
                year, month, day = holidays.normalize_holiday(item)
            except ValueError:
                continue
            self.add_row(month, day, year)

        self._ghost_btn(self, "＋  Добавить праздник", lambda: self.add_row(1, 1)).grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )

    # ── Управление строками ───────────────────────────────────────────────────

    def add_row(self, m: int = 1, d: int = 1, year=None):
        rf = ctk.CTkFrame(self._hol_scroll, fg_color="transparent")
        rf.pack(fill="x", pady=2)

        mc = self._combo(rf, [f"{i:02d}  —  {MONTHS[i - 1]}" for i in range(1, 13)], width=190)
        mc.set(f"{m:02d}  —  {MONTHS[m - 1]}")
        mc.pack(side="left", padx=(0, 6))

        def _get_max_days(month_str: str) -> int:
            try:
                mo = int(month_str.split()[0])
                # Без года — високосный: 29 февраля бывает не каждый год, но праздником быть может
                y = int(yc.get()) if yc.get().strip() else 2024
                return calendar.monthrange(y, mo)[1]
            except Exception:
                return 31

        def _update_days(*_):
            max_d = _get_max_days(mc.get())
            dc.configure(values=[f"{i:02d}" for i in range(1, max_d + 1)])
            if int(dc.get()) > max_d:
                dc.set(f"{max_d:02d}")

        yc = self._entry(rf, width=130, placeholder_text="каждый год")
        if year is not None:
            yc.insert(0, str(year))

        init_max = _get_max_days(mc.get())
        dc = self._combo(rf, [f"{i:02d}" for i in range(1, init_max + 1)], width=80)
        dc.set(f"{min(d, init_max):02d}")
        dc.pack(side="left", padx=(0, 6))
        yc.pack(side="left", padx=(0, 6))
        mc.configure(command=_update_days)
        yc.bind("<FocusOut>", _update_days)

        rec = {"frame": rf, "m": mc, "d": dc, "y": yc}
        self._del_btn(rf, lambda r=rec: self._del_row(r)).pack(side="left")
        self.hol_rows.append(rec)

    def _del_row(self, rec: dict):
        rec["frame"].destroy()
        if rec in self.hol_rows:
            self.hol_rows.remove(rec)
