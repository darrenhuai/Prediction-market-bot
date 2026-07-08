"""Unit tests for src.indexers.kalshi.models: datetime parsing and dataclass mapping.

parse_datetime pads/truncates fractional seconds to exactly 6 digits before
handing off to datetime.fromisoformat, which (on Python's minimum supported
version for this project) only accepts 0, 3, or 6 fractional digits. These
tests cover the range of fractional-second precisions Kalshi's API can send.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.indexers.kalshi.models import Market, Trade, parse_datetime


class TestParseDatetime:
    def test_no_fractional_seconds(self):
        assert parse_datetime("2024-01-15T12:30:45Z") == datetime(2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc)

    def test_millisecond_precision(self):
        assert parse_datetime("2024-01-15T12:30:45.123Z") == datetime(
            2024, 1, 15, 12, 30, 45, 123000, tzinfo=timezone.utc
        )

    def test_microsecond_precision(self):
        assert parse_datetime("2024-01-15T12:30:45.123456Z") == datetime(
            2024, 1, 15, 12, 30, 45, 123456, tzinfo=timezone.utc
        )

    def test_single_digit_fraction_is_padded(self):
        assert parse_datetime("2024-01-15T12:30:45.1Z") == datetime(
            2024, 1, 15, 12, 30, 45, 100000, tzinfo=timezone.utc
        )

    def test_sub_microsecond_fraction_is_truncated(self):
        # Nanosecond-precision timestamps get truncated to microseconds.
        assert parse_datetime("2024-01-15T12:30:45.123456789Z") == datetime(
            2024, 1, 15, 12, 30, 45, 123456, tzinfo=timezone.utc
        )

    def test_result_is_timezone_aware_utc(self):
        result = parse_datetime("2024-01-15T12:30:45Z")
        assert result.tzinfo is not None
        assert result.utcoffset().total_seconds() == 0


class TestTradeFromDict:
    def test_maps_all_fields(self):
        trade = Trade.from_dict(
            {
                "trade_id": "abc123",
                "ticker": "FOO-24",
                "count": 5,
                "yes_price": 60,
                "no_price": 40,
                "taker_side": "yes",
                "created_time": "2024-01-15T12:30:45.5Z",
            }
        )
        assert trade == Trade(
            trade_id="abc123",
            ticker="FOO-24",
            count=5,
            yes_price=60,
            no_price=40,
            taker_side="yes",
            created_time=datetime(2024, 1, 15, 12, 30, 45, 500000, tzinfo=timezone.utc),
        )

    def test_missing_required_field_raises(self):
        with pytest.raises(KeyError):
            Trade.from_dict({"ticker": "FOO-24"})


class TestMarketFromDict:
    def test_maps_required_and_optional_fields(self):
        market = Market.from_dict(
            {
                "ticker": "FOO-24",
                "event_ticker": "FOO",
                "status": "open",
                "yes_bid": 45,
                "yes_ask": 50,
                "no_bid": 50,
                "no_ask": 55,
                "last_price": 48,
                "volume": 1000,
                "volume_24h": 200,
                "open_interest": 500,
                "result": "",
                "created_time": "2024-01-01T00:00:00Z",
                "open_time": "2024-01-01T00:00:00Z",
                "close_time": "2024-06-01T00:00:00Z",
            }
        )
        assert market.ticker == "FOO-24"
        assert market.close_time == datetime(2024, 6, 1, tzinfo=timezone.utc)

    def test_defaults_for_missing_optional_fields(self):
        market = Market.from_dict({"ticker": "FOO-24", "event_ticker": "FOO", "status": "open"})
        assert market.market_type == "binary"
        assert market.title == ""
        assert market.volume == 0
        assert market.open_interest == 0
        assert market.result == ""
        assert market.close_time is None
        assert market.open_time is None
        assert market.created_time is None
