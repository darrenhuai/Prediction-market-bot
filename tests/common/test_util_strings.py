"""Unit tests for src.common.util.strings."""

from __future__ import annotations

from src.common.util.strings import snake_to_title


class TestSnakeToTitle:
    def test_converts_snake_case(self):
        assert snake_to_title("hello_world") == "Hello World"

    def test_single_word(self):
        assert snake_to_title("market") == "Market"

    def test_already_title_case(self):
        assert snake_to_title("Already Title") == "Already Title"

    def test_empty_string(self):
        assert snake_to_title("") == ""
