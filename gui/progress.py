"""Связь рабочего потока с главным (без tkinter, поэтому проверяется тестами).

Tk не потокобезопасен, а `widget.after(0, ...)` из рабочего потока иногда падает. Поток только
кладёт задания в очередь, а один цикл на главном потоке раз в INTERVAL_MS их выполняет."""
import logging
from collections import deque
from typing import Callable, Dict

logger = logging.getLogger(__name__)

INTERVAL_MS = 50

_STAGES = ((0.30, "Читаю источник…"), (0.50, "Читаю шаблон…"),
           (0.75, "Сопоставляю врачей…"), (0.92, "Записываю данные…"))


def stage_for(progress: float) -> str:
    """Подпись этапа по доле выполнения (0…1)."""
    for upper, text in _STAGES:
        if progress < upper:
            return text
    return "Сохраняю файл…"


class MainThreadQueue:
    """Очередь заданий для главного потока.

    post(fn) — выполнить по порядку; post_latest(key, fn) — оставить только последнее
    задание с этим ключом (прогресс: важно последнее значение, а не каждое)."""

    def __init__(self, widget, interval_ms: int = INTERVAL_MS):
        self._widget = widget
        self._interval = interval_ms
        self._ordered: deque = deque()
        self._latest: Dict[str, Callable] = {}
        self._job = None
        self._stopped = False

    def start(self) -> None:
        """Запускает цикл. Вызывается из главного потока."""
        self._stopped = False
        self._job = self._widget.after(self._interval, self._tick)

    def stop(self) -> None:
        self._stopped = True
        job, self._job = self._job, None
        if job is not None:
            try:
                self._widget.after_cancel(job)
            except Exception:
                pass

    def post(self, fn: Callable) -> None:
        self._ordered.append(fn)

    def post_latest(self, key: str, fn: Callable) -> None:
        self._latest[key] = fn

    def _run(self, fn: Callable) -> None:
        try:
            fn()
        except Exception:
            logger.exception("Ошибка в задании главного потока")

    def _tick(self) -> None:
        self._job = None
        if self._stopped:
            return
        # Сначала последние значения (прогресс), потом упорядоченные события (завершение, сброс):
        # иначе запоздавший прогресс затёр бы сброс интерфейса.
        for key in list(self._latest):
            fn = self._latest.pop(key, None)
            if fn is not None:
                self._run(fn)
        while True:
            try:
                fn = self._ordered.popleft()
            except IndexError:
                break
            self._run(fn)
        try:
            self._job = self._widget.after(self._interval, self._tick)
        except Exception:       # окно уничтожено — цикл заканчивается тихо
            self._job = None
