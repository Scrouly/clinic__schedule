"""
pages/keywords.py — страница «Направления».

Редактирование словаря title_keywords:
  ключевое слово из должности  →  список слов для поиска кабинета.

Публичные атрибуты:
    kw_rows  — список dict{"frame", "k", "v"} для чтения в _save_config
"""
import customtkinter as ctk

from ..themes import T
from ..widgets import UIHelpersMixin


class KeywordsPage(ctk.CTkFrame, UIHelpersMixin):
    """Страница настройки направлений (title_keywords)."""

    def __init__(self, parent, app):
        ctk.CTkFrame.__init__(self, parent, fg_color="transparent")
        self.app = app
        self.kw_rows: list[dict] = []
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self._build()

    # ── Построение ────────────────────────────────────────────────────────────

    def _build(self):
        self._page_title(
            self,
            "Направления",
            "Ключевое слово из должности  →  слова для поиска кабинета в источнике",
        )

        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        ctk.CTkLabel(
            hdr, text="  Должность (ключ. слово)",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=T("TEXT_DIM"), width=200, anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            hdr, text="Кабинеты / направления (через запятую)",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=T("TEXT_DIM"), anchor="w",
        ).pack(side="left", padx=(16, 0))

        card = self._card(self)
        card.grid(row=3, column=0, sticky="nsew")

        self._kw_scroll = ctk.CTkScrollableFrame(
            card, fg_color="transparent",
            scrollbar_button_color=T("BORDER"),
            scrollbar_button_hover_color=T("BG_CARD_HVR"),
        )
        self._kw_scroll.pack(fill="both", expand=True, padx=8, pady=8)
        self._kw_scroll.grid_columnconfigure(1, weight=1)

        for k, v in self.app.cfg.get("title_keywords", {}).items():
            self.add_row(k, ", ".join(v) if isinstance(v, list) else str(v))

        self._ghost_btn(self, "＋  Добавить направление", lambda: self.add_row("", "")).grid(
            row=4, column=0, sticky="w", pady=(8, 0)
        )

    # ── Управление строками ───────────────────────────────────────────────────

    def add_row(self, key: str = "", val: str = ""):
        rf = ctk.CTkFrame(self._kw_scroll, fg_color="transparent")
        rf.pack(fill="x", pady=2)
        rf.columnconfigure(1, weight=1)

        ke = self._entry(rf, placeholder_text="гинеколог", width=190)
        ke.insert(0, key)
        ke.grid(row=0, column=0, padx=(0, 6))

        ve = self._entry(rf, placeholder_text="201к, 202к, 203к")
        ve.insert(0, val)
        ve.grid(row=0, column=1, sticky="ew", padx=(0, 6))

        rec = {"frame": rf, "k": ke, "v": ve}
        self._del_btn(rf, lambda r=rec: self._del_row(r)).grid(row=0, column=2)
        self.kw_rows.append(rec)

    def _del_row(self, rec: dict):
        rec["frame"].destroy()
        if rec in self.kw_rows:
            self.kw_rows.remove(rec)
