"""Unit tests for src.analysis.kalshi.util.categories.get_hierarchy.

SUBCATEGORY_PATTERNS is matched top-to-bottom with a substring check, and the
module docstring states patterns must be ordered most-specific-first. Several
generic patterns were previously listed *before* more specific siblings that
contain them as a substring (e.g. "PRES" before "PRESNOMD"), which made the
specific pattern permanently unreachable - every ticker for that specific
sub-category silently fell back to the generic bucket instead.
"""

from __future__ import annotations

from src.analysis.kalshi.util.categories import get_hierarchy


class TestPresidentialSubcategories:
    def test_specific_pattern_not_shadowed_by_generic_pres(self):
        # "PRES" is a substring of every pattern below; it must not win.
        assert get_hierarchy("PRESNOMD") == ("Politics", "Presidential", "Nominations D")
        assert get_hierarchy("PRESPARTYGA") == ("Politics", "Presidential", "Georgia")
        assert get_hierarchy("PRESLEAVESK") == ("Politics", "Presidential", "South Korea")

    def test_generic_pres_still_matches_as_fallback(self):
        assert get_hierarchy("PRES") == ("Politics", "Presidential", "General")
        assert get_hierarchy("PRES-24") == ("Politics", "Presidential", "General")


class TestElectoralCollegeNotShadowingCabinet:
    def test_cabinet_secretary_tickers_not_shadowed_by_ec(self):
        # "EC" used to be listed early in the Electoral College section, and
        # "EC" is a substring of "SECAG"/"SECDEF"/etc. (the "SEC" in
        # "Secretary"), so every Cabinet secretary ticker was silently
        # miscategorized as Electoral College instead of Cabinet.
        assert get_hierarchy("SECAG") == ("Politics", "Cabinet", "Sec Agriculture")
        assert get_hierarchy("SECDEF") == ("Politics", "Cabinet", "Sec Defense")
        assert get_hierarchy("SECHHS") == ("Politics", "Cabinet", "Sec HHS")
        assert get_hierarchy("SECTREASURY") == ("Politics", "Cabinet", "Sec Treasury")
        assert get_hierarchy("SECSTATE") == ("Politics", "Cabinet", "Sec State")

    def test_last_state_call_not_shadowed_by_ec(self):
        assert get_hierarchy("LASTSTATECALL24") == (
            "Politics",
            "Electoral College",
            "Last State Call",
        )

    def test_generic_ec_still_matches_as_fallback(self):
        assert get_hierarchy("EC") == ("Politics", "Electoral College", "Other")
        assert get_hierarchy("ECMOV") == ("Politics", "Electoral College", "Margin")
        assert get_hierarchy("ECDJTBLOWOUT") == (
            "Politics",
            "Electoral College",
            "DJT Blowout",
        )

    def test_unrelated_tickers_containing_ec_not_shadowed(self):
        # "EC" is buried inside these tickers by coincidence (e.g. the "EC"
        # in "FEDDECISION", "RATECUT", "ELECTION") and previously won
        # because it still sorted ahead of them in SUBCATEGORY_PATTERNS.
        assert get_hierarchy("FEDDECISION") == ("Finance", "Fed", "Decisions")
        assert get_hierarchy("RATECUT") == ("Finance", "Fed", "Rate Cut")
        assert get_hierarchy("ELECTION") == ("Politics", "Other Elections", "Other")
        assert get_hierarchy("RTMINECRAFT") == ("Entertainment", "Movies", "Minecraft")


class TestFinanceDailyUpSubcategories:
    def test_inxdu_not_shadowed_by_inxd(self):
        assert get_hierarchy("INXDU") == ("Finance", "S&P 500", "Daily Up")

    def test_inxd_still_matches(self):
        assert get_hierarchy("INXD") == ("Finance", "S&P 500", "Daily")

    def test_nasdaq100du_not_shadowed_by_nasdaq100d(self):
        assert get_hierarchy("NASDAQ100DU") == ("Finance", "NASDAQ", "Daily Up")

    def test_nasdaq100d_still_matches(self):
        assert get_hierarchy("NASDAQ100D") == ("Finance", "NASDAQ", "Daily")
