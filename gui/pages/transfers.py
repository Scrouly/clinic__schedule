"""
pages/transfers.py — страница «Переносы дней» (чип-стиль).

Два столбца:
  • Рабочие дни, перенесённые с выходных (transfers_work_days)
  • Выходные дни, перенесённые с рабочих  (transfers_rest_days)

Публичные атрибуты:
    tw_rows  — список кортежей (_FakeCombo, _FakeCombo, _FakeCombo) для рабочих переносов
    tr_rows  — аналогично для выходных переносов
"""
from datetime import date

import customtkinter as ctk

from ..themes import T
from ..widgets import UIHelpersMixin

MONTH_SHORT = ["Янв", "Фев", "Мар", "Апр", "Май", "Июн",
               "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]
MONTH_GEN   = ["января", "февраля", "марта", "апреля", "мая", "июня",
               "июля", "августа", "сентября", "октября", "ноября", "декабря"]


class _FakeCombo:
    """Заглушка ComboBox для совместимости с parse_transfers в app._save_config."""
    def __init__(self, val): self._v = str(val)
    def get(self): return self._v


class TransfersPage(ctk.CTkFrame, UIHelpersMixin):
    """Страница настройки переносов рабочих/выходных дней."""

    def __init__(self, parent, app):
        ctk.CTkFrame.__init__(self, parent, fg_color="transparent")
        self.app = app
        self.tw_rows: list[tuple] = []   # рабочие переносы
        self.tr_rows: list[tuple] = []   # выходные переносы
        self.grid_columnconfigure((0, 1), weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build()

    # ── Построение ────────────────────────────────────────────────────────────

    def _build(self):
        self._page_title(
            self,
            "Переносы дней",
            "Рабочие дни, перенесённые с выходных, и выходные, перенесённые с рабочих",
            columnspan=2,
        )
        self._make_card(0, "💼", "Рабочие (за выходные)", self.tw_rows, "transfers_work_days", (0, 8))
        self._make_card(1, "🌴", "Выходные (за рабочие)", self.tr_rows, "transfers_rest_days", (8, 0))

    def _make_card(self, col: int, icon: str, label: str, rows_list: list, cfg_key: str, padx):
        card = self._card(self)
        card.grid(row=2, column=col, sticky="nsew", padx=padx, pady=(0, 8))
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            card, text=f"{icon}  {label}",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=T("TEXT_PRI"),
        ).grid(row=0, column=0, pady=(12, 6), padx=14, sticky="w")

        scroll = ctk.CTkScrollableFrame(
            card, fg_color="transparent",
            scrollbar_button_color=T("BORDER"),
            scrollbar_button_hover_color=T("BG_CARD_HVR"),
        )
        scroll.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 4))
        scroll.grid_columnconfigure(0, weight=1)

        add_frame = ctk.CTkFrame(card, fg_color="transparent")
        add_frame.grid(row=2, column=0, sticky="w", padx=10, pady=(0, 10))
        self._build_add_row(add_frame, scroll, rows_list)

        for d in self.app.cfg.get(cfg_key, []):
            self._add_chip(scroll, rows_list, d)

    # ── Строка добавления ─────────────────────────────────────────────────────

    def _build_add_row(self, parent, scroll, rows_list: list):
        days  = [f"{i:02d}" for i in range(1, 32)]
        years = [str(i) for i in range(2024, 2035)]
        cur_y = str(date.today().year)

        def _mc(values, width):
            cb = ctk.CTkComboBox(
                parent, values=values, width=width, height=30,
                fg_color=T("BG_DEEP"), border_color=T("BORDER"),
                text_color=T("TEXT_PRI"), button_color=T("BORDER"),
                button_hover_color=T("BG_CARD_HVR"),
                dropdown_fg_color=T("BG_CARD"),
                dropdown_text_color=T("TEXT_PRI"),
                dropdown_hover_color=T("BG_CARD_HVR"),
                font=ctk.CTkFont(family="Segoe UI", size=12),
                corner_radius=6,
            )
            cb.pack(side="left", padx=(0, 4))
            return cb

        day_cb   = _mc(days,        width=70)
        month_cb = _mc(MONTH_SHORT, width=80)
        year_cb  = _mc(years,       width=90)
        day_cb.set("01")
        month_cb.set("Янв")
        year_cb.set(cur_y)

        def _add():
            try:
                d = int(day_cb.get())
                m = MONTH_SHORT.index(month_cb.get()) + 1
                y = int(year_cb.get())
            except (ValueError, IndexError):
                return
            self._add_chip(scroll, rows_list, [y, m, d])

        ctk.CTkButton(
            parent, text="＋", width=36, height=30,
            fg_color=T("ACCENT"), hover_color=T("ACCENT_LIGHT"),
            text_color="#FFFFFF", corner_radius=6,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=_add,
        ).pack(side="left", padx=(4, 0))

    # ── Чип одной даты ────────────────────────────────────────────────────────

    def _add_chip(self, parent, target_list: list, date_val=None):
        cur_y = str(date.today().year)
        d_val, m_val, y_val = 1, 1, int(cur_y)
        if date_val and len(date_val) == 3:
            y_val, m_val, d_val = int(date_val[0]), int(date_val[1]), int(date_val[2])

        chip = ctk.CTkFrame(
            parent, fg_color=T("BG_DEEP"),
            corner_radius=8, border_width=1, border_color=T("BORDER"),
        )
        chip.pack(fill="x", pady=3, padx=2)

        inner = ctk.CTkFrame(chip, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=6)
        inner.grid_columnconfigure(0, weight=1)

        date_text = f"📅  {d_val} {MONTH_GEN[m_val - 1]} {y_val}"
        ctk.CTkLabel(
            inner, text=date_text,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=T("TEXT_PRI"), anchor="w",
        ).grid(row=0, column=0, sticky="w")

        del_btn = ctk.CTkButton(
            inner, text="✕", width=24, height=24,
            fg_color="transparent", hover_color=T("DANGER"),
            text_color=T("TEXT_DIM"), corner_radius=4,
            font=ctk.CTkFont(size=11), border_width=0,
        )
        del_btn.grid(row=0, column=1, padx=(8, 0))

        widgets_tuple = (
            _FakeCombo(f"{d_val:02d}"),
            _FakeCombo(MONTH_SHORT[m_val - 1]),
            _FakeCombo(str(y_val)),
        )
        target_list.append(widgets_tuple)

        def _delete():
            if widgets_tuple in target_list:
                target_list.remove(widgets_tuple)
            chip.destroy()

        del_btn.configure(command=_delete)
