"""Only `_sdk.py` may import from the MCP SDK.

Non-negotiable #4 in AGENTS.md. The SDK changed shape between 1.x
(`mcp.server.fastmcp.FastMCP`) and 2.x (`mcp.server.MCPServer`); the whole point
of the rule is that the next such change costs one file, not thirty.

`_sdk.py` claimed this test enforced it long before the test existed, which is
the same defect class as an unverifiable claim in the README -- so the last test
here checks that every test file a source docstring names is actually present.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "geospatial_mcp"
TESTS = Path(__file__).resolve().parents[1]
GATEWAY = SRC / "_sdk.py"


def _python_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def _imports_mcp(path: Path) -> list[str]:
    """Return the offending import statements in `path`, by AST not by grep.

    A regex would match `from ..models import` and the word `mcp` in prose; the
    AST matches only a real import of the `mcp` package or a submodule of it.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "mcp" or alias.name.startswith("mcp."):
                    offenders.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import: `from ..models import` is not `mcp`.
            is_absolute_mcp = (
                node.level == 0
                and node.module is not None
                and (node.module == "mcp" or node.module.startswith("mcp."))
            )
            if is_absolute_mcp:
                names = ", ".join(a.name for a in node.names)
                offenders.append(f"line {node.lineno}: from {node.module} import {names}")
    return offenders


class TestSdkIsolation:
    def test_the_gateway_module_exists_and_does_import_the_sdk(self):
        """Guard the guard: if `_sdk.py` moved, the sweep below would pass vacuously."""
        assert GATEWAY.exists(), "_sdk.py is missing; the isolation rule has no gateway"
        assert _imports_mcp(GATEWAY), "_sdk.py no longer imports the SDK -- has it moved?"

    def test_no_other_module_imports_the_sdk(self):
        offenders = {}
        for path in _python_files():
            if path == GATEWAY:
                continue
            found = _imports_mcp(path)
            if found:
                offenders[str(path.relative_to(SRC))] = found
        assert not offenders, (
            "only _sdk.py may import from `mcp`; import from `.._sdk` instead:\n"
            + "\n".join(f"  {f}: {'; '.join(v)}" for f, v in offenders.items())
        )

    def test_the_sweep_actually_covers_the_package(self):
        """A sweep over an empty file list passes and proves nothing."""
        files = _python_files()
        assert len(files) > 20, f"only found {len(files)} source files; is SRC wrong?"


class TestDocstringTestReferences:
    """A docstring that names an enforcing test must name one that exists.

    This is what let `_sdk.py` advertise `test_sdk_isolation.py` for the whole of
    the project's life before this file was written.
    """

    REFERENCE = re.compile(r"tests/[\w/]+/test_\w+\.py")

    def test_every_test_file_named_in_source_exists(self):
        missing = []
        for path in _python_files():
            text = path.read_text(encoding="utf-8")
            for match in self.REFERENCE.finditer(text):
                referenced = Path(__file__).resolve().parents[2] / match.group(0)
                if not referenced.exists():
                    line = text[: match.start()].count("\n") + 1
                    missing.append(f"{path.relative_to(SRC)}:{line} names {match.group(0)}")
        assert not missing, "source docstrings name tests that do not exist:\n" + "\n".join(missing)

    def test_it_would_notice_a_missing_file(self):
        """The pattern must actually match the shape used in real docstrings."""
        assert self.REFERENCE.search("guarded by ``tests/mcp/test_nonexistent.py``")
        assert not (TESTS / "mcp" / "test_nonexistent.py").exists()
