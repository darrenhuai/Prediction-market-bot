"""Unit tests for src.common.util: EV/Kelly math and formatting helpers.

The ev_yes/ev_no tests double as a regression test for a bug where the
old formula (fair_prob - (1 - fair_prob) * cost) overestimated expected
value relative to the correct formula (fair_prob - cost). See git history
on src/common/util/__init__.py for details.
"""

from __future__ import annotations

import math

import pytest

from src.common.util import ev_no, ev_yes, fmt_cents, fmt_pct, kelly_fraction, remove_vig


class TestEvYes:
    def test_matches_first_principles_expected_profit(self):
        """EV should equal p*(1-cost) + (1-p)*(-cost) for a range of inputs."""
        for fair_prob in (0.1, 0.35, 0.5, 0.6, 0.9):
            for price_cents in (10, 25, 50, 75, 90):
                cost = price_cents / 100.0
                expected = fair_prob * (1 - cost) + (1 - fair_prob) * (-cost)
                assert ev_yes(fair_prob, price_cents) == pytest.approx(expected)

    def test_fair_price_has_zero_ev(self):
        """If the market price equals the fair probability, EV should be ~0."""
        assert ev_yes(0.6, 60) == pytest.approx(0.0, abs=1e-9)

    def test_underpriced_contract_is_positive_ev(self):
        # Fair prob 60%, but the market only charges 50c -> genuinely +EV.
        assert ev_yes(0.60, 50) == pytest.approx(0.10)

    def test_overpriced_contract_is_negative_ev(self):
        # Fair prob 40%, market charges 60c -> negative EV.
        assert ev_yes(0.40, 60) == pytest.approx(-0.20)

    def test_not_the_old_buggy_formula(self):
        """Guard against regressing to fair_prob - (1 - fair_prob) * cost."""
        fair_prob, price_cents = 0.60, 50
        cost = price_cents / 100.0
        buggy_value = fair_prob - (1 - fair_prob) * cost
        assert ev_yes(fair_prob, price_cents) != pytest.approx(buggy_value)


class TestEvNo:
    def test_matches_first_principles_expected_profit(self):
        for fair_prob_no in (0.1, 0.35, 0.5, 0.6, 0.9):
            for price_cents in (10, 25, 50, 75, 90):
                cost = price_cents / 100.0
                expected = fair_prob_no * (1 - cost) + (1 - fair_prob_no) * (-cost)
                assert ev_no(fair_prob_no, price_cents) == pytest.approx(expected)

    def test_symmetric_with_ev_yes(self):
        # ev_yes and ev_no share the same underlying formula (prob - cost).
        assert ev_no(0.6, 50) == pytest.approx(ev_yes(0.6, 50))


class TestRemoveVig:
    def test_normalizes_to_sum_one(self):
        fair_yes, fair_no = remove_vig(55, 55)
        assert fair_yes + fair_no == pytest.approx(1.0)
        assert fair_yes == pytest.approx(0.5)
        assert fair_no == pytest.approx(0.5)

    def test_preserves_relative_weighting(self):
        # yes_price double no_price -> fair_yes should be 2x fair_no.
        fair_yes, fair_no = remove_vig(60, 30)
        assert fair_yes == pytest.approx(2 * fair_no)

    def test_handles_asymmetric_prices(self):
        fair_yes, fair_no = remove_vig(70, 40)
        assert fair_yes == pytest.approx(70 / 110)
        assert fair_no == pytest.approx(40 / 110)

    def test_zero_prices_does_not_raise(self):
        # A market with no bids on either side (yes_price == no_price == 0)
        # would otherwise hit a ZeroDivisionError; fall back to a neutral split.
        assert remove_vig(0, 0) == (0.5, 0.5)


class TestKellyFraction:
    def test_zero_edge_gives_zero_stake(self):
        # prob == breakeven probability (1 / (1 + b)) -> kelly is ~0.
        b = 1.0
        breakeven_prob = 1 / (1 + b)
        assert kelly_fraction(breakeven_prob, b) == pytest.approx(0.0, abs=1e-9)

    def test_negative_edge_clamped_to_zero(self):
        # Way below breakeven probability -> raw kelly would be negative.
        assert kelly_fraction(0.1, payout_multiple=1.0) == 0.0

    def test_positive_edge_scaled_by_fraction(self):
        prob, b, fraction = 0.6, 1.0, 0.25
        raw_kelly = (b * prob - (1 - prob)) / b
        assert kelly_fraction(prob, b, fraction) == pytest.approx(raw_kelly * fraction)

    def test_default_fraction_is_quarter_kelly(self):
        prob, b = 0.7, 1.0
        full = kelly_fraction(prob, b, fraction=1.0)
        quarter = kelly_fraction(prob, b)
        assert quarter == pytest.approx(full * 0.25)

    def test_never_returns_nan_or_negative(self):
        for prob in (0.01, 0.25, 0.5, 0.75, 0.99):
            for b in (0.5, 1.0, 2.0, 5.0):
                result = kelly_fraction(prob, b)
                assert not math.isnan(result)
                assert result >= 0.0

    def test_zero_payout_multiple_does_not_raise(self):
        # payout_multiple is 0 when a contract's ask price is 100 cents
        # (bot.py: payout_mult = (100 - price) / price); would otherwise
        # hit a ZeroDivisionError since kelly = (b*prob - q) / b.
        assert kelly_fraction(0.5, payout_multiple=0) == 0.0


class TestFmtHelpers:
    def test_fmt_pct_default_decimals(self):
        assert fmt_pct(0.1234) == "12.3%"

    def test_fmt_pct_custom_decimals(self):
        assert fmt_pct(0.1234, decimals=2) == "12.34%"

    def test_fmt_pct_zero(self):
        assert fmt_pct(0.0) == "0.0%"

    def test_fmt_cents_whole_dollar(self):
        assert fmt_cents(100) == "$1.00"

    def test_fmt_cents_fractional(self):
        assert fmt_cents(150) == "$1.50"

    def test_fmt_cents_zero(self):
        assert fmt_cents(0) == "$0.00"
