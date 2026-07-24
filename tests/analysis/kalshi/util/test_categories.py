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


class TestFinanceDailyUpSubcategories:
    def test_inxdu_not_shadowed_by_inxd(self):
        assert get_hierarchy("INXDU") == ("Finance", "S&P 500", "Daily Up")

    def test_inxd_still_matches(self):
        assert get_hierarchy("INXD") == ("Finance", "S&P 500", "Daily")

    def test_nasdaq100du_not_shadowed_by_nasdaq100d(self):
        assert get_hierarchy("NASDAQ100DU") == ("Finance", "NASDAQ", "Daily Up")

    def test_nasdaq100d_still_matches(self):
        assert get_hierarchy("NASDAQ100D") == ("Finance", "NASDAQ", "Daily")
