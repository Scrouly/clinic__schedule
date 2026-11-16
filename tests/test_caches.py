"""Кэши в core.utils не должны менять результат и не должны «залипать»."""
from core import utils


def test_get_tags_sees_keyword_changes_without_manual_cache_reset(monkeypatch):
    monkeypatch.setitem(utils.CONFIG["title_keywords"], "тестолог", ["абракадабра"])
    assert utils.get_tags("врач абракадабра") == {"тестолог"}
    monkeypatch.setitem(utils.CONFIG["title_keywords"], "тестолог", ["другое"])
    assert utils.get_tags("врач абракадабра") == set()
    assert utils.get_tags("врач другое") == {"тестолог"}


def test_get_tags_sees_in_place_list_mutation(monkeypatch):
    """GUI правит списки слов на месте (append/remove), а не подменяет словарь целиком."""
    words = ["альфа"]
    monkeypatch.setitem(utils.CONFIG["title_keywords"], "тестолог", words)
    assert utils.get_tags("врач альфа") == {"тестолог"}
    words.append("бета")
    assert utils.get_tags("врач бета") == {"тестолог"}
    words.clear()
    assert utils.get_tags("врач бета") == set()


def test_get_tags_returns_independent_sets():
    first = utils.get_tags("Врач-хирург (1,0 ст.)")
    first.add("мусор")
    assert "мусор" not in utils.get_tags("Врач-хирург (1,0 ст.)")


def test_get_tags_empty_input():
    assert utils.get_tags("") == set() and utils.get_tags(None) == set()


def test_interval_parsing_is_stable_across_repeated_calls():
    for _ in range(3):
        assert utils.parse_time_intervals("09:00-12:00/14:00-18:00") == [(540, 720), (840, 1080)]
        assert utils.parse_time_intervals("22:00-06:00") == [(1320, 1800)]
        assert utils.parse_time_intervals("нет") == []
