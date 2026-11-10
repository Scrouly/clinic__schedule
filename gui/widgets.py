"""
widgets.py — UIHelpersMixin.

Mixin-класс с фабричными методами для создания стилизованных виджетов CustomTkinter.
Подключается к CityClinicApp и к каждой странице.

Все методы используют T() из themes.py для получения актуального цвета темы.
"""
import customtkinter as ctk
from .themes import T


class UIHelpersMixin:
    """Набор фабрик виджетов. Ожидает, что у self есть корень CTk/CTkFrame."""

    # ── no-op для обратной совместимости (CTK кэширует цвета внутри)
    def _tw(self, widget, **_):
        return widget

    # ── Контейнеры ────────────────────────────────────────────────────────────

    def _card(self, parent, **kw):
        kw.setdefault("fg_color", T("BG_CARD"))
        kw.setdefault("corner_radius", 10)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", T("BORDER"))
        return ctk.CTkFrame(parent, **kw)

    def _div(self, parent):
        ctk.CTkFrame(
            parent, height=1, fg_color=T("BORDER")
        ).pack(fill="x", padx=12, pady=6)

    # ── Текстовые метки ───────────────────────────────────────────────────────

    def _lbl(self, parent, text: str):
        ctk.CTkLabel(
            parent,
            text=f"  {text}",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=T("TEXT_DIM"),
        ).pack(anchor="w", padx=4, pady=(6, 1))

    def _flabel(self, parent, text: str):
        return ctk.CTkLabel(
            parent,
            text=text,
            font=ctk.CTkFont(family="Segoe UI", size=13),
            text_color=T("TEXT_SEC"),
        )

    def _page_title(self, parent, title: str, sub: str, columnspan: int = 1):
        ctk.CTkLabel(
            parent,
            text=title,
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color=T("TEXT_PRI"),
        ).grid(row=0, column=0, columnspan=columnspan, sticky="w", pady=(0, 2))
        ctk.CTkLabel(
            parent,
            text=sub,
            font=ctk.CTkFont(size=13),
            text_color=T("TEXT_DIM"),
            wraplength=580,
            justify="left",
        ).grid(row=1, column=0, columnspan=columnspan, sticky="w", pady=(0, 10))

    # ── Поля ввода и выбора ───────────────────────────────────────────────────

    def _entry(self, parent, **kw):
        kw.setdefault("fg_color", T("BG_DEEP"))
        kw.setdefault("border_color", T("BORDER"))
        kw.setdefault("text_color", T("TEXT_PRI"))
        kw.setdefault("placeholder_text_color", T("TEXT_DIM"))
        kw.setdefault("font", ctk.CTkFont(family="Segoe UI", size=13))
        kw.setdefault("height", 36)
        kw.setdefault("corner_radius", 7)
        return ctk.CTkEntry(parent, **kw)

    def _combo(self, parent, values, width=None, **kw):
        kw.setdefault("fg_color", T("BG_DEEP"))
        kw.setdefault("border_color", T("BORDER"))
        kw.setdefault("text_color", T("TEXT_PRI"))
        kw.setdefault("button_color", T("BORDER"))
        kw.setdefault("button_hover_color", T("BG_CARD_HVR"))
        kw.setdefault("dropdown_fg_color", T("BG_CARD"))
        kw.setdefault("dropdown_text_color", T("TEXT_PRI"))
        kw.setdefault("dropdown_hover_color", T("BG_CARD_HVR"))
        kw.setdefault("font", ctk.CTkFont(family="Segoe UI", size=13))
        kw.setdefault("height", 36)
        kw.setdefault("corner_radius", 7)
        if width:
            kw["width"] = width
        return ctk.CTkComboBox(parent, values=values, **kw)

    # ── Кнопки ────────────────────────────────────────────────────────────────

    def _sbtn(self, parent, icon: str, label: str, cmd):
        """Кнопка боковой навигации."""
        b = ctk.CTkButton(
            parent,
            text=f"  {icon}  {label}",
            anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=13),
            height=34,
            corner_radius=8,
            fg_color="transparent",
            hover_color=T("BG_CARD_HVR"),
            text_color=T("TEXT_SEC"),
            command=cmd,
        )
        b.pack(fill="x", pady=1)
        return b

    def _ghost_btn(self, parent, text: str, cmd, width=None, **kw):
        """Обводная кнопка (прозрачный фон, рамка)."""
        kw.setdefault("fg_color", T("BG_CARD"))
        kw.setdefault("hover_color", T("BG_CARD_HVR"))
        kw.setdefault("border_color", T("BORDER"))
        kw.setdefault("border_width", 1)
        kw.setdefault("text_color", T("TEXT_SEC"))
        kw.setdefault("font", ctk.CTkFont(family="Segoe UI", size=13))
        kw.setdefault("height", 36)
        kw.setdefault("corner_radius", 7)
        if width:
            kw["width"] = width
        return ctk.CTkButton(parent, text=text, command=cmd, **kw)

    def _del_btn(self, parent, cmd):
        """Маленькая кнопка удаления строки (✕)."""
        return ctk.CTkButton(
            parent,
            text="✕",
            width=36,
            height=36,
            fg_color=T("BG_DEEP"),
            hover_color=T("DANGER"),
            text_color=T("TEXT_SEC"),
            corner_radius=7,
            border_width=1,
            border_color=T("BORDER"),
            font=ctk.CTkFont(size=13),
            command=cmd,
        )

    # ── Строка выбора файла ───────────────────────────────────────────────────

    def _file_row(self, parent, row: int, label: str, placeholder: str, cmd, save: bool = False):
        """Строка: метка + поле ввода + кнопка «Обзор/Сохранить»."""
        self._flabel(parent, label).grid(row=row, column=0, padx=12, pady=7, sticky="w")
        e = self._entry(parent, placeholder_text=placeholder)
        e.grid(row=row, column=1, sticky="ew", padx=(0, 6), pady=6)
        btn_text = "Сохранить" if save else "Обзор"
        self._ghost_btn(parent, btn_text, cmd, width=80 if save else 66).grid(
            row=row, column=2, padx=(0, 10), pady=6
        )
        return e
