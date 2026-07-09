"""Unit tests for src.common.util.datetime.parse_iso_datetime.

This is the shared implementation behind both src.indexers.kalshi.models.parse_datetime
and the inline parser in src.indexers.polymarket.models.Market.from_dict. Both call
sites used to carry their own copy of this logic, which is how the same fractional-
second and negative-UTC-offset bugs ended up needing to be fixed twice, in separate
commits, for each source.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.common.util.datetime import parse_iso_datetime


class TestParseIsoDatetime:
    def test_no_fractional_seconds(self):
        assert parse_iso_datetime("2024-01-15T12:30:45Z") == datetime(
            2024, 1, 15, 12, 30, 45, tzinfo=timezone.utc
        )

    def test_millisecond_precision(self):
        assert parse_iso_datetime("2024-01-15T12:30:45.123Z") == datetime(
            2024, 1, 15, 12, 30, 45, 123000, tzinfo=timezone.utc
        )

    def test_microsecond_precision(self):
        assert parse_iso_datetime("2024-01-15T12:30:45.123456Z") == datetime(
            2024, 1, 15, 12, 30, 45, 123456, tzinfo=timezone.utc
        )

    def test_single_digit_fraction_is_padded(self):
        assert parse_iso_datetime("2024-01-15T12:30:45.1Z") == datetime(
            2024, 1, 15, 12, 30, 45, 100000, tzinfo=timezone.utc
        )

    def test_sub_microsecond_fraction_is_truncated(self):
        assert parse_iso_datetime("2024-01-15T12:30:45.123456789Z") == datetime(
            2024, 1, 15, 12, 30, 45, 123456, tzinfo=timezone.utc
        )

    def test_negative_offset_with_fractional_seconds_is_padded(self):
        assert parse_iso_datetime("2024-01-15T12:30:45.1-05:00") == datetime(
            2024, 1, 15, 12, 30, 45, 100000, tzinfo=timezone(-timedelta(hours=5))
        )

    def test_negative_offset_without_fractional_seconds(self):
        assert parse_iso_datetime("2024-01-15T12:30:45-05:00") == datetime(
            2024, 1, 15, 12, 30, 45, tzinfo=timezone(-timedelta(hours=5))
        )

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError):
            parse_iso_datetime("not-a-date")
