"""Unit tests for src.common.storage.ParquetStorage market chunking.

append_markets used to split an oversized batch only once (first CHUNK_SIZE
rows into the existing chunk file, the rest into a single new chunk file
regardless of size). A batch large enough to push the combined row count past
2x CHUNK_SIZE would silently produce a chunk file holding more rows than its
filename's nominal range implies. See src/indexers/polymarket/markets.py for
the equivalent while-loop chunking pattern this now matches.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from src.common.storage import ParquetStorage


@dataclass
class FakeMarket:
    ticker: str


@pytest.fixture
def storage(tmp_path):
    s = ParquetStorage(data_dir=tmp_path)
    s.CHUNK_SIZE = 100
    return s


def chunk_sizes(data_dir):
    return {p.name: len(pd.read_parquet(p)) for p in sorted(data_dir.glob("*.parquet"))}


class TestAppendMarkets:
    def test_first_batch_creates_single_chunk(self, storage, tmp_path):
        storage.append_markets([FakeMarket(f"t{i}") for i in range(80)])
        assert chunk_sizes(tmp_path) == {"markets_0_100.parquet": 80}

    def test_batch_filling_existing_chunk_stays_in_one_file(self, storage, tmp_path):
        storage.append_markets([FakeMarket(f"t{i}") for i in range(80)])
        storage.append_markets([FakeMarket(f"t{i}") for i in range(80, 100)])
        assert chunk_sizes(tmp_path) == {"markets_0_100.parquet": 100}

    def test_batch_overflowing_one_chunk_splits_into_two(self, storage, tmp_path):
        storage.append_markets([FakeMarket(f"t{i}") for i in range(80)])
        storage.append_markets([FakeMarket(f"t{i}") for i in range(80, 130)])
        assert chunk_sizes(tmp_path) == {
            "markets_0_100.parquet": 100,
            "markets_100_200.parquet": 30,
        }

    def test_batch_overflowing_multiple_chunks_splits_into_all_of_them(self, storage, tmp_path):
        # Combined size (80 + 150 = 230) is more than 2x CHUNK_SIZE (100), so a
        # single split is not enough: every resulting chunk must still be
        # capped at CHUNK_SIZE rows.
        storage.append_markets([FakeMarket(f"t{i}") for i in range(80)])
        storage.append_markets([FakeMarket(f"t{i}") for i in range(80, 230)])
        sizes = chunk_sizes(tmp_path)
        assert sizes == {
            "markets_0_100.parquet": 100,
            "markets_100_200.parquet": 100,
            "markets_200_300.parquet": 30,
        }
        assert all(size <= storage.CHUNK_SIZE for size in sizes.values())

    def test_deduplicates_across_chunks(self, storage, tmp_path):
        storage.append_markets([FakeMarket(f"t{i}") for i in range(80)])
        total = storage.append_markets([FakeMarket("t0"), FakeMarket("t500")])
        assert total == 81
        assert chunk_sizes(tmp_path) == {"markets_0_100.parquet": 81}
