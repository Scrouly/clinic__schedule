"""Очередь для главного потока и стадии прогресса (без tkinter)."""
import threading

import pytest

from gui.progress import MainThreadQueue, stage_for


class FakeApp:
    def __init__(self):
        self.pending = {}
        self._next = 0
        self.destroyed = False
        self._main = threading.get_ident()

    def after(self, ms, fn):
        if self.destroyed:
            raise RuntimeError("окно закрыто")
        assert threading.get_ident() == self._main, "after вызван не из главного потока"
        self._next += 1
        self.pending[self._next] = fn
        return str(self._next)

    def after_cancel(self, job):
        self.pending.pop(int(job), None)

    def pump(self):
        batch, self.pending = self.pending, {}
        for fn in batch.values():
            fn()


@pytest.fixture
def app():
    return FakeApp()


@pytest.mark.parametrize("v,stage", [
    (0.0, "Читаю источник…"), (0.29, "Читаю источник…"), (0.30, "Читаю шаблон…"),
    (0.49, "Читаю шаблон…"), (0.50, "Сопоставляю врачей…"), (0.74, "Сопоставляю врачей…"),
    (0.75, "Записываю данные…"), (0.91, "Записываю данные…"), (0.92, "Сохраняю файл…"), (1.0, "Сохраняю файл…"),
])
def test_stage_for_keeps_the_original_thresholds(v, stage):
    assert stage_for(v) == stage


def test_posts_run_in_order_in_the_main_loop(app):
    q = MainThreadQueue(app)
    q.start()
    done = []
    worker = threading.Thread(target=lambda: [q.post(lambda i=i: done.append(i)) for i in range(5)])
    worker.start()
    worker.join()
    assert done == []                           # из потока ничего не выполняется
    app.pump()
    assert done == [0, 1, 2, 3, 4]


def test_latest_wins_for_the_same_key(app):
    q = MainThreadQueue(app)
    q.start()
    seen = []
    for v in (0.1, 0.2, 0.3):
        q.post_latest("progress", lambda v=v: seen.append(v))
    app.pump()
    assert seen == [0.3]


def test_latest_updates_run_before_ordered_ones(app):
    """Иначе запоздавший прогресс затёр бы сброс интерфейса после завершения."""
    q = MainThreadQueue(app)
    q.start()
    order = []
    q.post(lambda: order.append("reset"))
    q.post_latest("progress", lambda: order.append("progress"))
    app.pump()
    assert order == ["progress", "reset"]


def test_loop_rearms_itself_and_survives_a_failing_callback(app):
    q = MainThreadQueue(app)
    q.start()
    done = []
    q.post(lambda: 1 / 0)
    q.post(lambda: done.append("after-error"))
    app.pump()
    assert done == ["after-error"] and len(app.pending) == 1      # цикл жив
    q.post(lambda: done.append("next-round"))
    app.pump()
    assert done[-1] == "next-round"


def test_stop_cancels_the_loop(app):
    q = MainThreadQueue(app)
    q.start()
    q.stop()
    assert app.pending == {}


def test_closed_window_ends_the_loop_quietly(app):
    q = MainThreadQueue(app)
    q.start()
    app.destroyed = True
    app.pump()
    assert app.pending == {}
