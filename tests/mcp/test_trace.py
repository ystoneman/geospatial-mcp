"""The opt-in tool-call trace: complete, harmless, and off by default.

Agent evals score what a model called from this file, whichever harness ran
the model. So it must record failed and malformed calls as faithfully as good
ones, must not change any result, and must never write to stdout.
"""

from __future__ import annotations

import json
from dataclasses import replace

from mcp import Client

from geospatial_mcp import config
from geospatial_mcp.server import build_server
from geospatial_mcp.trace import enable_tracing


def _lines(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


async def _call(server, tool: str, arguments: dict):
    async with Client(server, raise_exceptions=False) as client:
        return await client.call_tool(tool, arguments)


class TestTraceRecords:
    async def test_a_successful_call_is_recorded_with_its_arguments(self, tmp_path):
        trace = tmp_path / "trace.jsonl"
        server = build_server("default")
        enable_tracing(server, trace)

        await _call(server, "coord_convert", {"location": "30SUF6542755114"})

        (record,) = _lines(trace)
        assert record["tool"] == "coord_convert"
        assert record["arguments"] == {"location": "30SUF6542755114"}
        assert record["ok"] is True
        assert record["result_chars"] > 0
        assert record["duration_ms"] >= 0

    async def test_a_tool_error_is_recorded_as_a_failure_with_the_reason(self, tmp_path):
        trace = tmp_path / "trace.jsonl"
        server = build_server("default")
        enable_tracing(server, trace)

        result = await _call(
            server,
            "geom_transform",
            {
                "geojson": '{"type":"Point","coordinates":[2,48]}',
                "operation": "buffer",
                "distance_m": 0.0674,
            },
        )

        assert result.is_error  # tracing must not swallow the error
        (record,) = _lines(trace)
        assert record["ok"] is False
        assert "degrees" in record["error"]

    async def test_a_malformed_call_is_recorded_before_validation(self, tmp_path):
        """Argument validity is an eval metric, so rejected arguments must be kept raw."""
        trace = tmp_path / "trace.jsonl"
        server = build_server("default")
        enable_tracing(server, trace)

        await _call(server, "rf_link_budget", {"frequency_mhz": "not a number"})

        (record,) = _lines(trace)
        assert record["ok"] is False
        assert record["arguments"] == {"frequency_mhz": "not a number"}

    async def test_calls_append_in_order(self, tmp_path):
        trace = tmp_path / "trace.jsonl"
        server = build_server("default")
        enable_tracing(server, trace)

        async with Client(server, raise_exceptions=False) as client:
            await client.call_tool("coord_convert", {"location": "48.8584,2.2945"})
            await client.call_tool("rf_link_budget", {})

        assert [r["tool"] for r in _lines(trace)] == ["coord_convert", "rf_link_budget"]


class TestTraceIsHarmless:
    async def test_results_are_identical_with_and_without_tracing(self, tmp_path):
        plain = await _call(build_server("default"), "rf_link_budget", {"environment": "rural"})
        traced_server = build_server("default")
        enable_tracing(traced_server, tmp_path / "trace.jsonl")
        traced = await _call(traced_server, "rf_link_budget", {"environment": "rural"})
        assert traced.structured_content == plain.structured_content

    async def test_nothing_reaches_stdout(self, tmp_path, capsys):
        server = build_server("default")
        enable_tracing(server, tmp_path / "trace.jsonl")
        await _call(server, "coord_convert", {"location": "48.8584,2.2945"})
        assert capsys.readouterr().out == ""

    async def test_an_unwritable_trace_does_not_fail_the_call(self, tmp_path):
        trace = tmp_path / "trace.jsonl"
        server = build_server("default")
        enable_tracing(server, trace)
        trace.mkdir()  # the path is now a directory, so every append fails

        result = await _call(server, "rf_link_budget", {})
        assert not result.is_error


class TestTraceSwitch:
    def test_off_by_default(self):
        server = build_server("default")
        assert all("run" not in vars(t) for t in server._tool_manager.list_tools())

    async def test_geo_trace_file_turns_it_on(self, tmp_path):
        trace = tmp_path / "from-env.jsonl"
        original = config.settings
        config.set_settings(replace(original, trace_file=trace))
        try:
            server = build_server("default")
        finally:
            config.set_settings(original)

        await _call(server, "rf_link_budget", {})
        assert _lines(trace)[0]["tool"] == "rf_link_budget"

    def test_settings_read_the_variable(self, tmp_path):
        settings = config.Settings.from_env({"GEO_TRACE_FILE": str(tmp_path / "t.jsonl")})
        assert settings.trace_file == tmp_path / "t.jsonl"
        assert config.Settings.from_env({}).trace_file is None
