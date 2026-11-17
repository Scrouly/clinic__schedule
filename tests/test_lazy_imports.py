"""Тяжёлые библиотеки не должны подгружаться при запуске программы."""
import subprocess
import sys

import pytest

from core import compare_schedules


def _modules_after_import(statement: str) -> set:
    code = f"import sys; {statement}; print(' '.join(sorted(sys.modules)))"
    out = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, check=True)
    return set(out.stdout.split())


@pytest.mark.parametrize("statement", [
    "import core.excel_io",
    "import core.auto_schedule",
    "import core.compare_schedules",
])
def test_startup_does_not_load_pandas_or_formula_engine(statement):
    loaded = _modules_after_import(statement)
    assert "pandas" not in loaded
    assert "xlcalculator" not in loaded


def test_formula_engine_is_loaded_on_first_use(tmp_path):
    from tests.builders import make_compare_pair
    auto, _ = make_compare_pair(str(tmp_path / "a.xlsx"), str(tmp_path / "m.xlsx"))
    assert compare_schedules.build_formula_evaluator(auto) is not None


def test_missing_formula_engine_gives_no_evaluator(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "xlcalculator", None)       # import xlcalculator → ImportError
    assert compare_schedules.build_formula_evaluator(str(tmp_path / "any.xlsx")) is None
