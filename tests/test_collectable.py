"""The test suite must COLLECT inside the ProcMon test container, where the repo sits at a shallow path (``/app``): a module-level ``Path(__file__).parents[n]``
raised IndexError there in phases 78 and 79. Two guards: a source scan for ``parents[...]`` outside functions, and an import of every test module from a
copy placed in a shallow temp directory."""
from __future__ import annotations

import ast
import importlib.util
import shutil
import sys
from pathlib import Path

import pytest


def module_level_parents_subscripts(source: str) -> list[int]:
    """Line numbers of ``<x>.parents[...]`` that are evaluated at import time (not inside a function body)."""
    found: list[int] = []

    def visit(node: ast.AST, inside_function: bool) -> None:
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "parents" and not inside_function:
            found.append(node.lineno)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            # decorators and default values are evaluated at import time, the body only when the function runs
            defaults = [*node.args.defaults, *(d for d in node.args.kw_defaults if d is not None)]
            for early in (*node.decorator_list, *defaults):
                visit(early, inside_function)
            for statement in node.body:
                visit(statement, inside_function=True)
            return
        entering = inside_function or isinstance(node, ast.Lambda)
        for child in ast.iter_child_nodes(node):
            visit(child, entering)

    visit(ast.parse(source), inside_function=False)
    return found


def _test_sources(tests_dir: Path) -> list[Path]:
    return sorted(path for path in tests_dir.rglob("*.py") if "__pycache__" not in path.parts)


@pytest.mark.unit
def test_the_scanner_flags_module_level_parents_and_ignores_function_level() -> None:
    assert module_level_parents_subscripts("ROOT = Path(__file__).resolve().parents[4]\n") == [1]
    assert module_level_parents_subscripts("def f():\n    return Path(__file__).parents[2]\n") == []
    assert module_level_parents_subscripts("class A:\n    root = Path(__file__).parents[1]\n") == [2]
    assert module_level_parents_subscripts("def f(root=Path(__file__).parents[1]):\n    return root\n") == [1]
    assert module_level_parents_subscripts("FIX = Path(__file__).resolve().parent.parent / 'fixtures'\n") == []


@pytest.mark.unit
def test_no_test_source_uses_module_level_parents_arithmetic() -> None:
    tests_dir = Path(__file__).resolve().parent

    offenders = {
        str(path.relative_to(tests_dir)): lines
        for path in _test_sources(tests_dir)
        if (lines := module_level_parents_subscripts(path.read_text(encoding="utf-8")))
    }

    assert offenders == {}


@pytest.mark.unit
def test_every_test_module_imports_from_a_copy_in_a_shallow_directory(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    shallow = tmp_path / "t"
    shutil.copytree(tests_dir, shallow, ignore=shutil.ignore_patterns("__pycache__", "fixtures"))
    loaded: list[str] = []
    try:
        for path in _test_sources(shallow):
            if path.name == "conftest.py":
                continue
            name = f"collect_probe_{len(loaded)}_{path.stem}"
            spec = importlib.util.spec_from_file_location(name, path)
            assert spec is not None
            assert spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            loaded.append(name)
            spec.loader.exec_module(module)
    finally:
        for name in loaded:
            sys.modules.pop(name, None)

    assert len(loaded) >= 8
