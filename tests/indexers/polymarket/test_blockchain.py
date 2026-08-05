"""Unit tests for src.indexers.polymarket.blockchain.PolygonClient._fetch_chunk.

_fetch_chunk retries a "too large" RPC error by bisecting the block range
and recursing on each half. Without a base case, a single-block range that
still errors as "too large" produced mid == start == end, so the recursive
calls repeated the exact same range forever (RecursionError) instead of
being treated as an unfetchable block.
"""

from __future__ import annotations

from src.indexers.polymarket.blockchain import CTF_EXCHANGE, BlockchainTrade, PolygonClient


def make_client() -> PolygonClient:
    return PolygonClient(rpc_url="http://localhost:8545")


def make_trade(maker_asset_id: int, taker_asset_id: int, maker_amount: int, taker_amount: int) -> BlockchainTrade:
    return BlockchainTrade(
        block_number=1,
        transaction_hash="0xabc",
        log_index=0,
        order_hash="0xdef",
        maker="0xmaker",
        taker="0xtaker",
        maker_asset_id=maker_asset_id,
        taker_asset_id=taker_asset_id,
        maker_amount=maker_amount,
        taker_amount=taker_amount,
        fee=0,
    )


class TestBlockchainTradeIsBuy:
    def test_maker_asset_zero_is_buy(self):
        # asset_id 0 is USDC; the maker giving USDC is buying outcome tokens.
        assert make_trade(0, 123, 1_000_000, 2_000_000).is_buy is True

    def test_nonzero_maker_asset_is_sell(self):
        assert make_trade(123, 0, 1_000_000, 2_000_000).is_buy is False


class TestBlockchainTradePrice:
    def test_buy_price_is_usdc_per_token(self):
        # Maker gives 1 USDC (1e6 units), receives 2 tokens (2e6 units) -> $0.50/token.
        trade = make_trade(0, 123, 1_000_000, 2_000_000)
        assert trade.price == 0.5

    def test_sell_price_is_usdc_per_token(self):
        # Maker gives 2 tokens, receives 1 USDC -> $0.50/token.
        trade = make_trade(123, 0, 2_000_000, 1_000_000)
        assert trade.price == 0.5

    def test_buy_with_zero_taker_amount_returns_zero(self):
        assert make_trade(0, 123, 1_000_000, 0).price == 0.0

    def test_sell_with_zero_maker_amount_returns_zero(self):
        assert make_trade(123, 0, 0, 1_000_000).price == 0.0


class TestBlockchainTradeSize:
    def test_buy_size_is_taker_amount_in_tokens(self):
        assert make_trade(0, 123, 1_000_000, 2_000_000).size == 2.0

    def test_sell_size_is_maker_amount_in_tokens(self):
        assert make_trade(123, 0, 2_000_000, 1_000_000).size == 2.0


class TestBlockchainTradeSide:
    def test_buy_side_label(self):
        assert make_trade(0, 123, 1_000_000, 2_000_000).side == "BUY"

    def test_sell_side_label(self):
        assert make_trade(123, 0, 2_000_000, 1_000_000).side == "SELL"


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
