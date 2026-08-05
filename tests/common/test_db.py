"""Unit tests for src.common.db.

upsert_positions splits a single signed `position` field into separate
yes_position/no_position columns (positive -> yes_position, negative ->
abs(position) -> no_position). That sign-based mapping has no other test
coverage, so a regression here would be silent.
"""

from __future__ import annotations

import pytest

from src.common.db import get_conn, upsert_markets, upsert_positions


@pytest.fixture
def conn(tmp_path):
    c = get_conn(path=tmp_path / "test.duckdb")
    yield c
    c.close()


class TestUpsertMarkets:
    def test_inserts_and_returns_count(self, conn):
        markets = [
            {"ticker": "A", "title": "Market A", "status": "open", "volume": 10},
            {"ticker": "B", "subtitle": "Market B", "status": "open", "volume": 20},
        ]
        assert upsert_markets(conn, markets) == 2
        rows = conn.execute("SELECT ticker, title, volume FROM markets ORDER BY ticker").fetchall()
        assert rows == [("A", "Market A", 10), ("B", "Market B", 20)]

    def test_falls_back_to_subtitle_when_title_missing(self, conn):
        upsert_markets(conn, [{"ticker": "A", "subtitle": "Fallback title"}])
        title = conn.execute("SELECT title FROM markets WHERE ticker='A'").fetchone()[0]
        assert title == "Fallback title"

    def test_replaces_existing_ticker(self, conn):
        upsert_markets(conn, [{"ticker": "A", "volume": 10}])
        upsert_markets(conn, [{"ticker": "A", "volume": 99}])
        rows = conn.execute("SELECT ticker, volume FROM markets").fetchall()
        assert rows == [("A", 99)]


class TestUpsertPositions:
    def test_positive_position_maps_to_yes_position(self, conn):
        upsert_positions(conn, [{"ticker": "A", "position": 5}])
        row = conn.execute("SELECT yes_position, no_position FROM positions WHERE ticker='A'").fetchone()
        assert row == (5, 0)

    def test_negative_position_maps_to_no_position(self, conn):
        upsert_positions(conn, [{"ticker": "A", "position": -5}])
        row = conn.execute("SELECT yes_position, no_position FROM positions WHERE ticker='A'").fetchone()
        assert row == (0, 5)

    def test_zero_position_maps_to_both_zero(self, conn):
        upsert_positions(conn, [{"ticker": "A", "position": 0}])
        row = conn.execute("SELECT yes_position, no_position FROM positions WHERE ticker='A'").fetchone()
        assert row == (0, 0)

    def test_missing_position_defaults_to_zero(self, conn):
        upsert_positions(conn, [{"ticker": "A"}])
        row = conn.execute("SELECT yes_position, no_position FROM positions WHERE ticker='A'").fetchone()
        assert row == (0, 0)

    def test_returns_count(self, conn):
        positions = [{"ticker": "A", "position": 1}, {"ticker": "B", "position": -1}]
        assert upsert_positions(conn, positions) == 2
