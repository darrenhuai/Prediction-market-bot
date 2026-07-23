"""Unit tests for src.indexers.polymarket.blockchain.PolygonClient._fetch_chunk.

_fetch_chunk retries a "too large" RPC error by bisecting the block range
and recursing on each half. Without a base case, a single-block range that
still errors as "too large" produced mid == start == end, so the recursive
calls repeated the exact same range forever (RecursionError) instead of
being treated as an unfetchable block.
"""

from __future__ import annotations

from src.indexers.polymarket.blockchain import CTF_EXCHANGE, PolygonClient


def make_client() -> PolygonClient:
    return PolygonClient(rpc_url="http://localhost:8545")


class TestFetchChunkTooLarge:
    def test_single_block_too_large_does_not_recurse_forever(self):
        client = make_client()
        calls = []

        def fake_get_trades(from_block, to_block, contract_address=CTF_EXCHANGE):
            calls.append((from_block, to_block))
            raise Exception("response size too large")

        client.get_trades = fake_get_trades

        trades, start, end = client._fetch_chunk(100, 100, CTF_EXCHANGE)

        assert trades == []
        assert (start, end) == (100, 100)
        assert calls == [(100, 100)]

    def test_multi_block_too_large_still_bisects(self):
        client = make_client()

        def fake_get_trades(from_block, to_block, contract_address=CTF_EXCHANGE):
            if to_block - from_block > 0:
                raise Exception("response size too large")
            return [f"trade-{from_block}"]

        client.get_trades = fake_get_trades

        trades, start, end = client._fetch_chunk(100, 103, CTF_EXCHANGE)

        assert sorted(trades) == ["trade-100", "trade-101", "trade-102", "trade-103"]
        assert (start, end) == (100, 103)

    def test_non_too_large_error_does_not_recurse(self):
        client = make_client()
        calls = []

        def fake_get_trades(from_block, to_block, contract_address=CTF_EXCHANGE):
            calls.append((from_block, to_block))
            raise Exception("connection reset")

        client.get_trades = fake_get_trades

        trades, start, end = client._fetch_chunk(100, 200, CTF_EXCHANGE)

        assert trades == []
        assert (start, end) == (100, 200)
        assert calls == [(100, 200)]
