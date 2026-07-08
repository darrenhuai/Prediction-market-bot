"""Unit tests for src.indexers.polymarket.models: Market/Trade dataclass mapping.

Market.from_dict's inner parse_time mirrors the same fractional-second
normalization as src.indexers.kalshi.models.parse_datetime, fixing the same
class of bug: datetime.fromisoformat on Python <3.11 only accepts 0, 3, or 6
fractional digits, so any other precision used to be silently swallowed by
the except clause and turned into None instead of a parsed datetime.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.indexers.polymarket.models import Market, Trade


class TestMarketFromDict:
    def test_maps_all_fields(self):
        market = Market.from_dict(
            {
                "id": "123",
                "conditionId": "0xabc",
                "question": "Will it happen?",
                "slug": "will-it-happen",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.6", "0.4"]',
                "clobTokenIds": '["1", "2"]',
                "volume": "1000.5",
                "liquidity": "500.25",
                "active": True,
                "closed": False,
                "endDate": "2024-06-01T00:00:00Z",
                "createdAt": "2024-01-01T00:00:00Z",
                "marketMakerAddress": "0xdef",
            }
        )
        assert market.id == "123"
        assert market.condition_id == "0xabc"
        assert market.volume == 1000.5
        assert market.liquidity == 500.25
        assert market.end_date == datetime(2024, 6, 1, tzinfo=timezone.utc)
        assert market.created_at == datetime(2024, 1, 1, tzinfo=timezone.utc)
        assert market.market_maker_address == "0xdef"

    def test_defaults_for_missing_optional_fields(self):
        market = Market.from_dict({"id": "123"})
        assert market.condition_id == ""
        assert market.volume == 0.0
        assert market.active is False
        assert market.end_date is None
        assert market.created_at is None
        assert market.market_maker_address is None

    def test_none_date_returns_none(self):
        market = Market.from_dict({"id": "123", "endDate": None})
        assert market.end_date is None

    def test_malformed_date_returns_none(self):
        market = Market.from_dict({"id": "123", "endDate": "not-a-date"})
        assert market.end_date is None

    def test_single_digit_fraction_is_padded(self):
        market = Market.from_dict({"id": "123", "endDate": "2024-01-15T12:30:45.1Z"})
        assert market.end_date == datetime(2024, 1, 15, 12, 30, 45, 100000, tzinfo=timezone.utc)

    def test_sub_microsecond_fraction_is_truncated(self):
        # Regression: previously any fractional precision other than 3 or 6 digits
        # raised inside fromisoformat on Python <3.11 and was swallowed, yielding
        # None instead of a parsed datetime.
        market = Market.from_dict({"id": "123", "endDate": "2024-01-15T12:30:45.123456789Z"})
        assert market.end_date == datetime(2024, 1, 15, 12, 30, 45, 123456, tzinfo=timezone.utc)


class TestTradeFromDict:
    def test_maps_all_fields(self):
        trade = Trade.from_dict(
            {
                "conditionId": "0xabc",
                "asset": "1234",
                "side": "BUY",
                "size": "10.5",
                "price": "0.55",
                "timestamp": "1700000000",
                "outcome": "Yes",
                "outcomeIndex": "0",
                "transactionHash": "0xdeadbeef",
            }
        )
        assert trade == Trade(
            condition_id="0xabc",
            asset="1234",
            side="BUY",
            size=10.5,
            price=0.55,
            timestamp=1700000000,
            outcome="Yes",
            outcome_index=0,
            transaction_hash="0xdeadbeef",
        )

    def test_falls_back_to_market_field_for_condition_id(self):
        trade = Trade.from_dict({"market": "0xfallback"})
        assert trade.condition_id == "0xfallback"

    def test_defaults_for_missing_fields(self):
        trade = Trade.from_dict({})
        assert trade.condition_id == ""
        assert trade.size == 0.0
        assert trade.price == 0.0
        assert trade.timestamp == 0
        assert trade.outcome_index == 0
