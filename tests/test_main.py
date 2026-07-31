"""Unit tests for main._pick: interactive option-picker input handling."""

from __future__ import annotations

from unittest.mock import patch

from main import _pick


class TestPick:
    def test_valid_choice_returns_zero_based_index(self):
        with patch("builtins.input", return_value="2"):
            assert _pick(["a", "b", "c"], "title") == 1

    def test_out_of_range_choice_returns_none(self):
        with patch("builtins.input", return_value="99"):
            assert _pick(["a", "b"], "title") is None

    def test_non_numeric_input_returns_none(self):
        with patch("builtins.input", return_value="not-a-number"):
            assert _pick(["a", "b"], "title") is None

    def test_keyboard_interrupt_returns_none(self):
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            assert _pick(["a", "b"], "title") is None

    def test_eof_returns_none(self):
        # input() raises EOFError when stdin has no more data (e.g. the
        # process is run non-interactively with stdin closed/redirected);
        # this used to propagate as an unhandled crash instead of the same
        # "user declined" behavior as Ctrl+C.
        with patch("builtins.input", side_effect=EOFError):
            assert _pick(["a", "b"], "title") is None
