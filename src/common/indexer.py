"""
Base class for data indexers that fetch and store market data.

Usage:
    from src.common.indexer import Indexer

    class MyIndexer(Indexer):
        def run(self) -> None:
            # Fetch and store data
            pass

    indexer = MyIndexer("my_indexer", "Fetches data from source")
    indexer.run()
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from src.common.discovery import discover_subclasses


class Indexer(ABC):
    """Base class for data indexers.

    Subclasses implement `run()` to fetch and store data.
    """

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    @abstractmethod
    def run(self) -> None:
        """Execute the indexer to fetch and store data."""
        pass

    @classmethod
    def load(cls, indexer_dir: Path | str = "src/indexers") -> list[type[Indexer]]:
        """Scan directory for Indexer subclass implementations.

        Args:
            indexer_dir: Directory to scan for indexer modules.

        Returns:
            List of Indexer subclass types found.
        """
        return discover_subclasses(indexer_dir, cls, module_prefix="src.indexers")
