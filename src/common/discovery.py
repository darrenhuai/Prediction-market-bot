"""Shared helper for discovering plugin subclasses under a directory.

Both src.common.analysis.Analysis and src.common.indexer.Indexer scan a
directory tree for concrete subclasses of themselves (analyses and
indexers, respectively). This module factors out that scanning logic so
it's implemented once instead of duplicated between the two classes.
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")


def discover_subclasses(directory: Path | str, base_class: type[T], module_prefix: str) -> list[type[T]]:
    """Import every .py file under `directory` and collect concrete subclasses of `base_class`.

    Args:
        directory: Root directory to scan recursively for .py files.
            Files whose name starts with "_" (e.g. __init__.py) are skipped.
        base_class: The class that discovered subclasses must inherit from.
            base_class itself and abstract subclasses are excluded.
        module_prefix: Dotted prefix used to build each module's import
            path, e.g. "src.indexers" for a file at
            "src/indexers/kalshi/foo.py" -> "src.indexers.kalshi.foo".

    Returns:
        List of matching subclass types, in the order files were found.
        Returns an empty list if `directory` doesn't exist. Modules that
        fail to import are silently skipped (e.g. missing optional deps).
    """
    directory = Path(directory)
    if not directory.exists():
        return []

    found: list[type[T]] = []

    for py_file in directory.glob("**/*.py"):
        if py_file.name.startswith("_"):
            continue

        relative_path = py_file.relative_to(directory)
        module_parts = relative_path.with_suffix("").parts
        module_name = f"{module_prefix}." + ".".join(module_parts)
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, base_class) and obj is not base_class and not inspect.isabstract(obj):
                found.append(obj)

    return found
