"""
pages/norms.py — страница «Нормы часов».

Базовая норма, нормы по специальностям и ставкам, цвета подсветки переработок.

Публичные атрибуты:
    highlight_var      — BooleanVar: включить подсветку
    base_norm_entry    — поле базовой нормы (часов в неделю на 1,0 ставки)
    spec_rows          — список dict{"frame", "k", "r", "w"} строк таблицы специальностей
    get_rule_rows()    — [(ключевые слова, ставка, часов в неделю), ...] для core.norms.parse_norm_rules
"""
import customtkinter as ctk

from core import norms
from ..themes import T
from ..widgets import UIHelpersMixin

RATE_CHOICES = ["Любая", "1.0", "0.75", "0.5", "0.25"]

_HINT = (
    "Ставка «Любая»: часов в неделю на 1,0 ставки, для неполной ставки умножается на её долю.\n"
    "Конкретная ставка: часов в неделю именно при этой ставке (без умножения).\n"
    "Специальности нет в таблице — действует базовая норма. "
    "Ключевые слова ищутся в названии должности с начала слова."
)


def _fmt_rate(rate) -> str:
    if rate is None:
        return "Любая"
    s = f"{float(rate):g}"
    return s if "." in s else s + ".0"


class NormsPage(ctk.CTkFrame, UIHelpersMixin):
    """Страница настройки норм часов и цветов переработок."""

    def __init__(self, parent, app):
        ctk.CTkFrame.__init__(self, parent, fg_color="transparent")
        self.app = app
        self.spec_rows: list[dict] = []
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build()

    # ── Построение ────────────────────────────────────────────────────────────

    def _build(self):
        self._page_title(self, "Нормы часов", "Нормы по специальностям и ставкам, подсветка переработок")

        # Страница длиннее окна — весь контент в прокручиваемой области
        body = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=T("BORDER"),
            scrollbar_button_hover_color=T("BG_CARD_HVR"),
        )
        body.grid(row=2, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)

        hours_ctrl = self.app.cfg.get(
            "hours_control", {"highlight_diff": True, "base_norm": 38.5}
        )

        # ── Блок 1: базовая норма ──────────────────────────────────────────

        card = self._card(body)
        card.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        card.grid_columnconfigure(1, weight=1)

        self.highlight_var = ctk.BooleanVar(value=hours_ctrl.get("highlight_diff", True))
        ctk.CTkSwitch(
            card,
            text="Включить цветовую подсветку табеля (красный/зелёный)",
            variable=self.highlight_var,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=T("TEXT_PRI"),
            progress_color=T("ACCENT"),
        ).grid(row=0, column=0, columnspan=2, padx=16, pady=16, sticky="w")

        ctk.CTkFrame(card, height=1, fg_color=T("BORDER")).grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=2
        )

        self._flabel(card, "Базовая норма (часов в неделю на 1,0 ставки):").grid(
            row=2, column=0, padx=16, pady=16, sticky="w"
        )
        self.base_norm_entry = self._entry(card, placeholder_text="38.5", width=120)
        self.base_norm_entry.insert(0, str(hours_ctrl.get("base_norm", 38.5)))
        self.base_norm_entry.grid(row=2, column=1, sticky="e", padx=16, pady=16)

        # ── Блок 2: нормы по специальностям ────────────────────────────────

        spec_card = self._card(body)
        spec_card.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        spec_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            spec_card, text="Нормы по специальностям и ставкам",
            font=ctk.CTkFont(size=14, weight="bold"), text_color=T("TEXT_PRI"),
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 2))
        ctk.CTkLabel(
            spec_card, text=_HINT, font=ctk.CTkFont(size=12), text_color=T("TEXT_DIM"),
            justify="left", anchor="w", wraplength=600,
        ).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 8))

        hdr = ctk.CTkFrame(spec_card, fg_color="transparent")
        hdr.grid(row=2, column=0, sticky="ew", padx=14)
        hdr.grid_columnconfigure(0, weight=1)
        for col, (text, width) in enumerate(
            [("Ключевые слова должности (через запятую)", 0), ("Ставка", 110), ("Часов в неделю", 100)]
        ):
            ctk.CTkLabel(
                hdr, text=text, font=ctk.CTkFont(size=11, weight="bold"),
                text_color=T("TEXT_DIM"), anchor="w", **({"width": width} if width else {}),
            ).grid(row=0, column=col, sticky="w", padx=(0, 6))

        self._spec_holder = ctk.CTkFrame(spec_card, fg_color="transparent")
        self._spec_holder.grid(row=3, column=0, sticky="ew", padx=14, pady=(2, 4))
        self._spec_holder.grid_columnconfigure(0, weight=1)

        for rule in norms.rules_for_display(self.app.cfg):
            self.add_row(
                ", ".join(rule.get("keywords", [])),
                _fmt_rate(rule.get("rate")),
                f"{float(rule.get('weekly', 0)):g}",
            )

        self._ghost_btn(spec_card, "＋  Добавить специальность", lambda: self.add_row("", "Любая", "")).grid(
            row=4, column=0, sticky="w", padx=14, pady=(4, 12)
        )

        # ── Блок 3: цвета переработок ──────────────────────────────────────

        color_card = self._card(body)
        color_card.grid(row=2, column=0, sticky="ew", pady=(0, 8))

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

    # ── Таблица специальностей ────────────────────────────────────────────────

    def add_row(self, keywords: str = "", rate: str = "Любая", weekly: str = ""):
        rf = ctk.CTkFrame(self._spec_holder, fg_color="transparent")
        rf.pack(fill="x", pady=2)
        rf.columnconfigure(0, weight=1)

        ke = self._entry(rf, placeholder_text="ультразвуков, узд")
        ke.insert(0, keywords)
        ke.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        rc = self._combo(rf, RATE_CHOICES, width=110)
        rc.set(rate or "Любая")
        rc.grid(row=0, column=1, padx=(0, 6))

        we = self._entry(rf, placeholder_text="35", width=100)
        we.insert(0, weekly)
        we.grid(row=0, column=2, padx=(0, 6))

        rec = {"frame": rf, "k": ke, "r": rc, "w": we}
        self._del_btn(rf, lambda r=rec: self._del_row(r)).grid(row=0, column=3)
        self.spec_rows.append(rec)

    def _del_row(self, rec: dict):
        rec["frame"].destroy()
        if rec in self.spec_rows:
            self.spec_rows.remove(rec)

    def get_rule_rows(self) -> list:
        """Сырые строки таблицы для core.norms.parse_norm_rules."""
        return [(r["k"].get(), r["r"].get(), r["w"].get()) for r in self.spec_rows]

    # ── Цвета ─────────────────────────────────────────────────────────────────

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
