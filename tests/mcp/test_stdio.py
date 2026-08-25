"""stdio transport: stdout must carry JSON-RPC and nothing else.

The MCP specification is explicit that a stdio server "MUST NOT write anything
to its stdout that is not a valid MCP message". A single stray log line or
print corrupts the stream and the client disconnects.

The failure is easy to introduce and hard to notice:
``logging.basicConfig(stream=sys.stdout)`` is a one-word change that leaves the
HTTP transport working perfectly while making stdio unusable, so only a test
that actually drives the stdio subprocess will catch it.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _drive_stdio_server(requests: list[dict], *, timeout_s: float = 40.0):
    """Run the server over stdio and return (stdout_lines, stderr_text)."""
    env = {**os.environ, "GEO_LOG_LEVEL": "DEBUG", "GEO_CACHE": "0"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "geospatial_mcp", "--transport", "stdio", "--log-level", "DEBUG"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        bufsize=1,
        cwd=REPO_ROOT,
    )
    try:
        for request in requests:
            proc.stdin.write(json.dumps(request) + "\n")
            proc.stdin.flush()

        expected = sum(1 for r in requests if "id" in r)
        lines: list[str] = []
        deadline = time.time() + timeout_s
        while time.time() < deadline and len(lines) < expected:
            ready, _, _ = select.select([proc.stdout], [], [], 1.0)
            if not ready:
                continue
            line = proc.stdout.readline()
            if not line:
                break
            lines.append(line)
    finally:
        proc.terminate()
        try:
            _, stderr = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            _, stderr = proc.communicate()
    return lines, stderr


@pytest.fixture(scope="module")
def stdio_session():
    return _drive_stdio_server(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "stdout-purity-test", "version": "1"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "coord_convert", "arguments": {"location": "48.8584,2.2945"}},
            },
        ]
    )


@pytest.mark.slow
class TestStdoutPurity:
    def test_server_responds_over_stdio(self, stdio_session):
        lines, _ = stdio_session
        assert len(lines) == 3, f"expected 3 responses, got {len(lines)}"

    def test_every_stdout_line_is_valid_json_rpc(self, stdio_session):
        lines, _ = stdio_session
        for index, raw in enumerate(lines):
            text = raw.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                pytest.fail(f"stdout line {index} is not JSON ({exc}): {text[:120]!r}")
            assert payload.get("jsonrpc") == "2.0", f"line {index} is not a JSON-RPC frame"

    def test_logs_go_to_stderr(self, stdio_session):
        _, stderr = stdio_session
        assert "geospatial-mcp" in stderr, "startup log should appear on stderr"

    def test_the_tool_call_actually_worked(self, stdio_session):
        lines, _ = stdio_session
        response = next(json.loads(line) for line in lines if json.loads(line).get("id") == 3)
        assert "result" in response
        structured = response["result"].get("structuredContent") or {}
        assert structured.get("formats", {}).get("grid_reference", "").startswith("31UDQ")
