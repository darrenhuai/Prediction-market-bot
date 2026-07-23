"""Unit tests for PolymarketLegacyTradesIndexer._fetch_logs_with_retry.

Mirrors the recursion-guard fix in test_blockchain.py: a "too large" RPC
error for a single-block range used to bisect into two calls with the same
from_block == to_block, recursing forever instead of raising.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.indexers.polymarket.fpmm_trades import PolymarketLegacyTradesIndexer


def make_client_stub(get_logs):
    return SimpleNamespace(w3=SimpleNamespace(eth=SimpleNamespace(get_logs=get_logs)))


class TestFetchLogsWithRetry:
    def test_single_block_too_large_raises_instead_of_recursing_forever(self):
        indexer = PolymarketLegacyTradesIndexer()
        calls = []

        def fake_get_logs(params):
            calls.append((params["fromBlock"], params["toBlock"]))
            raise Exception("response size too large")

        client = make_client_stub(fake_get_logs)

        with pytest.raises(Exception, match="too large"):
            indexer._fetch_logs_with_retry(client, "0xtopic", 100, 100)

        assert calls == [(100, 100)]

    def test_multi_block_too_large_still_bisects(self):
        indexer = PolymarketLegacyTradesIndexer()

        def fake_get_logs(params):
            from_block, to_block = params["fromBlock"], params["toBlock"]
            if to_block - from_block > 0:
                raise Exception("response size too large")
            return [f"log-{from_block}"]

        client = make_client_stub(fake_get_logs)

        logs = indexer._fetch_logs_with_retry(client, "0xtopic", 100, 103)

        assert sorted(logs) == ["log-100", "log-101", "log-102", "log-103"]

    def test_non_too_large_error_propagates_immediately(self):
        indexer = PolymarketLegacyTradesIndexer()
        calls = []

        def fake_get_logs(params):
            calls.append((params["fromBlock"], params["toBlock"]))
            raise Exception("connection reset")

        client = make_client_stub(fake_get_logs)

        with pytest.raises(Exception, match="connection reset"):
            indexer._fetch_logs_with_retry(client, "0xtopic", 100, 200)

        assert calls == [(100, 200)]
