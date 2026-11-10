"""
pages/compare.py — страница «Сравнение шаблонов».

Публичные атрибуты:
    auto_entry    — поле пути к авто-шаблону
    manual_entry  — поле пути к ручному шаблону
    run_btn       — кнопка запуска сравнения
    status_lbl    — метка статуса
    progress      — прогресс-бар
    log_box       — текстовое поле лога результата
"""
import os
import subprocess
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core import compare_schedules
from ..themes import T, MONTHS
from ..widgets import UIHelpersMixin


class ComparePage(ctk.CTkFrame, UIHelpersMixin):
    """Страница сравнения двух Excel-шаблонов."""

    def __init__(self, parent, app):
        ctk.CTkFrame.__init__(self, parent, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self._build()

    # ── Построение ────────────────────────────────────────────────────────────

    def _build(self):
        self._page_title(
            self,
            "Сравнение шаблонов",
            "Найти дни, где в ручном шаблоне есть время, а в автоматическом — нет",
        )

        # ── Карточка файлов
        fc = self._card(self)
        fc.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        fc.grid_columnconfigure(1, weight=1)

        self.auto_entry   = self._file_row(fc, 0, "Авто-шаблон",   "Автоматически заполненный .xlsx", self._pick_auto)
        ctk.CTkFrame(fc, height=1, fg_color=T("BORDER")).grid(
            row=1, column=0, columnspan=3, sticky="ew", padx=10, pady=2
        )
        self.manual_entry = self._file_row(fc, 2, "Ручной шаблон", "Заполненный вручную .xlsx",        self._pick_manual)

        # ── Карточка запуска
        run_card = self._card(self)
        run_card.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        run_card.grid_columnconfigure(0, weight=1)

        ri = ctk.CTkFrame(run_card, fg_color="transparent")
        ri.pack(fill="x", padx=12, pady=10)
        ri.grid_columnconfigure(0, weight=1)

        self.run_btn = ctk.CTkButton(
            ri,
            text="🔍   СРАВНИТЬ ШАБЛОНЫ",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            fg_color=T("ACCENT"),
            hover_color=T("ACCENT_LIGHT"),
            text_color="#FFFFFF",
            height=42,
            corner_radius=9,
            command=self._start,
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
            lh, text="Результат сравнения",
            font=ctk.CTkFont(size=13, weight="bold"), text_color=T("TEXT_SEC")
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
        self.log_box.insert("1.0", "Выберите два файла и нажмите «Сравнить».\n")
        self.log_box.configure(state="disabled")

    # ── Выбор файлов ──────────────────────────────────────────────────────────

    def _pick_auto(self):
        fp = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx *.xls")])
        if fp:
            self.auto_entry.delete(0, "end")
            self.auto_entry.insert(0, fp)

    def _pick_manual(self):
        fp = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx *.xls")])
        if fp:
            self.manual_entry.delete(0, "end")
            self.manual_entry.insert(0, fp)

    # ── Действия ──────────────────────────────────────────────────────────────

    def _clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def set_status(self, text: str, color=None):
        self.status_lbl.configure(text=text, text_color=color or T("TEXT_DIM"))

    def _start(self):
        auto_path   = self.auto_entry.get().strip()
        manual_path = self.manual_entry.get().strip()

        if not auto_path or not manual_path:
            messagebox.showwarning("Внимание", "Пожалуйста, выберите оба файла для сравнения.")
            return
        if not os.path.exists(auto_path) or not os.path.exists(manual_path):
            messagebox.showerror("Ошибка", "Один или оба файла не найдены по указанному пути.")
            return

        self.app._save_state()

        base_dir     = os.path.dirname(auto_path)
        base_name    = os.path.basename(auto_path).replace(".xlsx", "")
        expected_out = os.path.join(base_dir, f"{base_name}_РАЗЛИЧИЯ.xlsx")

        if os.path.exists(expected_out):
            try:
                with open(expected_out, "a"):
                    pass
            except PermissionError:
                messagebox.showerror(
                    "Файл занят",
                    f"Файл '{os.path.basename(expected_out)}' открыт в другой программе.\n"
                    "Закройте его и повторите попытку.",
                )
                return
            if not messagebox.askyesno(
                "Подтверждение перезаписи",
                f"Отчёт '{os.path.basename(expected_out)}' уже существует.\n\nПерезаписать?",
            ):
                return

        self.run_btn.configure(state="disabled", text="⏳  Сравнение…")
        self.progress.configure(mode="indeterminate")
        self.progress.start()
        self.set_status("Сравниваю файлы…", T("ACCENT_LIGHT"))

        threading.Thread(
            target=self._run_thread, args=(auto_path, manual_path), daemon=True
        ).start()

    def _run_thread(self, auto_path: str, manual_path: str):
        import logging
        try:
            out_path = compare_schedules.compare(auto_path, manual_path)
            self.after(0, lambda: self._on_success(out_path))
        except Exception as e:
            logging.getLogger("compare_schedules").error(f"Сбой: {e}")
            self.after(0, lambda err=e: self._on_error(err))
        finally:
            self.after(0, self._reset_ui)

    def _on_success(self, out_path):
        if out_path:
            if messagebox.askyesno(
                "Готово",
                "Сравнение успешно завершено! Найдены расхождения.\n\nОткрыть файл с отчётом?",
            ):
                if os.path.exists(out_path):
                    subprocess.Popen(f'explorer /select,"{os.path.abspath(out_path)}"')
        else:
            messagebox.showinfo("Идеально", "Расхождений не найдено!\nШаблоны полностью совпадают по времени.")

    def _on_error(self, err: Exception):
        messagebox.showerror("Ошибка при сравнении", str(err))

    def _reset_ui(self):
        self.progress.stop()
        self.progress.set(0)
        self.progress.configure(mode="indeterminate")
        self.run_btn.configure(state="normal", text="🔍   СРАВНИТЬ ШАБЛОНЫ")
