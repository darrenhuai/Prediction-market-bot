"""Unit tests for src.common.discovery.discover_subclasses."""

from __future__ import annotations

import sys
import textwrap
from abc import ABC, abstractmethod

from src.common.discovery import discover_subclasses


class _Base(ABC):
    @abstractmethod
    def run(self):
        pass


class _ConcreteChild(_Base):
    def run(self):
        return "child"


def _write_module(tmp_path, relative_path, content):
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content))
    return path


class TestDiscoverSubclasses:
    def test_returns_empty_list_for_missing_directory(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        assert discover_subclasses(missing, _Base, module_prefix="whatever") == []

    def test_finds_concrete_subclass_in_flat_directory(self, tmp_path, monkeypatch):
        pkg = "discovery_fixture_flat"
        monkeypatch.syspath_prepend(str(tmp_path))
        _write_module(tmp_path, f"{pkg}/__init__.py", "")
        _write_module(
            tmp_path,
            f"{pkg}/plugin_a.py",
            """
            from tests.common.test_discovery import _Base

            class PluginA(_Base):
                def run(self):
                    return "a"
            """,
        )
        try:
            found = discover_subclasses(tmp_path / pkg, _Base, module_prefix=pkg)
            assert [c.__name__ for c in found] == ["PluginA"]
        finally:
            sys.modules.pop(f"{pkg}.plugin_a", None)

    def test_skips_underscore_prefixed_files(self, tmp_path, monkeypatch):
        pkg = "discovery_fixture_underscore"
        monkeypatch.syspath_prepend(str(tmp_path))
        _write_module(tmp_path, f"{pkg}/__init__.py", "")
        _write_module(
            tmp_path,
            f"{pkg}/_helpers.py",
            """
            from tests.common.test_discovery import _Base

            class ShouldNotBeFound(_Base):
                def run(self):
                    return "hidden"
            """,
        )
        try:
            found = discover_subclasses(tmp_path / pkg, _Base, module_prefix=pkg)
            assert found == []
        finally:
            sys.modules.pop(f"{pkg}._helpers", None)

    def test_excludes_abstract_subclasses(self, tmp_path, monkeypatch):
        pkg = "discovery_fixture_abstract"
        monkeypatch.syspath_prepend(str(tmp_path))
        _write_module(tmp_path, f"{pkg}/__init__.py", "")
        _write_module(
            tmp_path,
            f"{pkg}/plugin_b.py",
            """
            from abc import abstractmethod
            from tests.common.test_discovery import _Base

            class StillAbstract(_Base):
                @abstractmethod
                def another_method(self):
                    pass

            class ConcreteOne(_Base):
                def run(self):
                    return "concrete"
            """,
        )
        try:
            found = discover_subclasses(tmp_path / pkg, _Base, module_prefix=pkg)
            assert [c.__name__ for c in found] == ["ConcreteOne"]
        finally:
            sys.modules.pop(f"{pkg}.plugin_b", None)

    def test_excludes_base_class_itself(self):
        # _ConcreteChild lives in this test module; scanning this directory
        # should never return _Base itself even though it's importable.
        found = discover_subclasses(
            "tests/common",
            _Base,
            module_prefix="tests.common",
        )
        assert _Base not in found

    def test_does_not_duplicate_class_reimported_by_another_module(self, tmp_path, monkeypatch):
        # A module that merely imports a subclass defined elsewhere (e.g. a
        # convenience re-export) should not cause that subclass to be
        # reported twice.
        pkg = "discovery_fixture_reexport"
        monkeypatch.syspath_prepend(str(tmp_path))
        _write_module(tmp_path, f"{pkg}/__init__.py", "")
        _write_module(
            tmp_path,
            f"{pkg}/plugin_d.py",
            """
            from tests.common.test_discovery import _Base

            class PluginD(_Base):
                def run(self):
                    return "d"
            """,
        )
        _write_module(
            tmp_path,
            f"{pkg}/reexport.py",
            f"""
            from {pkg}.plugin_d import PluginD  # noqa: F401
            """,
        )
        try:
            found = discover_subclasses(tmp_path / pkg, _Base, module_prefix=pkg)
            assert [c.__name__ for c in found] == ["PluginD"]
        finally:
            sys.modules.pop(f"{pkg}.plugin_d", None)
            sys.modules.pop(f"{pkg}.reexport", None)

    def test_recurses_into_subdirectories(self, tmp_path, monkeypatch):
        pkg = "discovery_fixture_nested"
        monkeypatch.syspath_prepend(str(tmp_path))
        _write_module(tmp_path, f"{pkg}/__init__.py", "")
        _write_module(tmp_path, f"{pkg}/nested/__init__.py", "")
        _write_module(
            tmp_path,
            f"{pkg}/nested/plugin_c.py",
            """
            from tests.common.test_discovery import _Base

            class NestedPlugin(_Base):
                def run(self):
                    return "nested"
            """,
        )
        try:
            found = discover_subclasses(tmp_path / pkg, _Base, module_prefix=pkg)
            assert [c.__name__ for c in found] == ["NestedPlugin"]
        finally:
            sys.modules.pop(f"{pkg}.nested.plugin_c", None)
