"""Unit tests for src.common.indexer.Indexer."""

from __future__ import annotations

import pytest

from src.common.indexer import Indexer


class _ConcreteIndexer(Indexer):
    def run(self) -> None:
        pass


class TestInit:
    def test_sets_name_and_description(self):
        indexer = _ConcreteIndexer(name="my_indexer", description="Fetches data from source")
        assert indexer.name == "my_indexer"
        assert indexer.description == "Fetches data from source"


class TestIndexerIsAbstract:
    def test_cannot_instantiate_indexer_directly(self):
        with pytest.raises(TypeError):
            Indexer(name="x", description="y")  # missing run() implementation


class TestLoad:
    def test_delegates_to_discover_subclasses(self, monkeypatch, tmp_path):
        captured = {}

        def fake_discover_subclasses(directory, base_class, module_prefix):
            captured["directory"] = directory
            captured["base_class"] = base_class
            captured["module_prefix"] = module_prefix
            return [_ConcreteIndexer]

        monkeypatch.setattr("src.common.indexer.discover_subclasses", fake_discover_subclasses)

        result = Indexer.load(tmp_path)

        assert result == [_ConcreteIndexer]
        assert captured["directory"] == tmp_path
        assert captured["base_class"] is Indexer
        assert captured["module_prefix"] == "src.indexers"

    def test_default_directory_is_src_indexers(self, monkeypatch):
        captured = {}

        def fake_discover_subclasses(directory, base_class, module_prefix):
            captured["directory"] = directory
            return []

        monkeypatch.setattr("src.common.indexer.discover_subclasses", fake_discover_subclasses)

        Indexer.load()

        assert captured["directory"] == "src/indexers"
