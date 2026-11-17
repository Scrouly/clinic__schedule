"""UIHelpersMixin._build_color_row на подменённых tkinter/customtkinter (настоящих в среде тестов нет)."""
import importlib
import sys
import types

import pytest


class Widget:
    """Запоминает аргументы; pack/pack_propagate возвращают себя, cget читает сохранённые."""
    created = []

    def __init__(self, *args, **kw):
        self.kw = dict(kw)
        Widget.created.append(self)

    def pack(self, **_): return self
    def pack_propagate(self, *_): return self
    def configure(self, **kw): self.kw.update(kw)
    def cget(self, name): return self.kw[name]


class Button(Widget):
    def invoke(self): self.kw["command"]()


@pytest.fixture
def mixin(monkeypatch):
    Widget.created = []
    ctk = types.SimpleNamespace(CTkFrame=Widget, CTkLabel=Widget, CTkButton=Button,
                                CTkFont=lambda **kw: kw)
    tk = types.ModuleType("tkinter")
    tk.colorchooser = types.SimpleNamespace(askcolor=lambda **kw: (None, None))
    monkeypatch.setitem(sys.modules, "customtkinter", ctk)
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.colorchooser", tk.colorchooser)
    sys.modules.pop("gui.widgets", None)
    module = importlib.import_module("gui.widgets")
    module.colorchooser = tk.colorchooser          # то, что вызывает метод
    yield module
    sys.modules.pop("gui.widgets", None)


def build(mixin, init_color, picked):
    holder = mixin.UIHelpersMixin()
    calls = []
    holder._build_color_row(object(), "Заголовок", "Подпись", init_color, calls.append)
    button = next(w for w in Widget.created if isinstance(w, Button))
    swatch = next(w for w in Widget.created if "fg_color" in w.kw and w.kw.get("width") == 32)
    label = next(w for w in Widget.created if w.kw.get("text", "").startswith("#"))
    mixin.colorchooser.askcolor = lambda **kw: (None, picked)
    return button, swatch, label, calls


def test_initial_color_is_normalized_and_shown(mixin):
    _, swatch, label, _ = build(mixin, "ffb6c1", None)
    assert swatch.kw["fg_color"] == "#ffb6c1"
    assert label.kw["text"] == "#FFB6C1"


def test_picked_color_updates_the_chip_and_is_reported_upcased(mixin):
    button, swatch, label, calls = build(mixin, "#FFFFFF", "#aabbcc")
    button.invoke()
    assert calls == ["#AABBCC"]
    assert swatch.kw["fg_color"] == "#AABBCC"
    assert label.kw["text"] == "#AABBCC"


def test_cancelled_dialog_changes_nothing(mixin):
    button, swatch, label, calls = build(mixin, "#FFFFFF", None)
    button.invoke()
    assert calls == []
    assert swatch.kw["fg_color"] == "#FFFFFF"
    assert label.kw["text"] == "#FFFFFF"


def test_dialog_starts_from_the_current_color(mixin):
    seen = {}
    button, _, _, _ = build(mixin, "#123456", "#654321")

    def fake_askcolor(**kw):
        seen.update(kw)
        return (None, "#654321")

    mixin.colorchooser.askcolor = fake_askcolor
    button.invoke()
    assert seen["initialcolor"] == "#123456"
