"""Errors must reach the model as errors, and must teach it how to recover.

This is the single most important behavioural contract in the package.
Returning ``{"status": "error", ...}`` from a failed tool is the tempting shape
and the wrong one: MCP marks such a response ``is_error=False``, so the model
reads the failure as a success and proceeds on fabricated data.
"""

from __future__ import annotations

import json

import pytest

from geospatial_mcp.errors import GeoInputError

from ..conftest import mcp_client

#: (tool, arguments, a fragment the message must contain).
BAD_CALLS = [
    ("coord_convert", {"location": "999,999"}, "Latitude must be between"),
    ("coord_convert", {"location": "10SGJ068"}, "even number of digits"),
    ("coord_convert", {"location": ""}, "empty"),
    ("coord_describe", {"value": "48.8584,2.2945"}, None),  # returns is_valid, never errors
    ("geom_transform", {"geojson": "nonsense", "operation": "buffer", "distance_m": 100}, "WKT"),
    (
        "geom_transform",
        {
            "geojson": '{"type":"Point","coordinates":[2,48]}',
            "operation": "buffer",
            "distance_m": 0,
        },
        "non-zero",
    ),
    ("geom_overlay", {"geojson_a": "{}", "geojson_b": "{}"}, None),
    (
        "coord_transform_crs",
        {"x": 0, "y": 0, "source_crs": "EPSG:4326", "target_crs": "EPSG:99999"},
        "coordinate reference system",
    ),
    ("rf_link_budget", {"environment": "atlantis"}, None),
    ("rf_towers", {"location": "", "radius_m": 500.0}, None),
    ("route_matrix", {"origins": " ; ; "}, None),
    (
        "place_search",
        {"location": "48.86,2.29", "category": "unicorn_stable"},
        "Unknown place category",
    ),
    ("data_convert", {"data": "!!!not-data!!!", "to_format": "geojson"}, None),
]


def _message_of(result) -> str:
    if result.structured_content:
        return json.dumps(result.structured_content)
    return "".join(getattr(block, "text", "") for block in (result.content or []))


class TestErrorSignalling:
    @pytest.mark.parametrize(("tool", "arguments", "fragment"), BAD_CALLS)
    async def test_bad_input_sets_is_error(self, tool, arguments, fragment):
        async with mcp_client() as client:
            result = await client.call_tool(tool, arguments)
            if tool == "coord_describe":
                # This tool reports validity in its payload rather than failing,
                # so that it is safe to use for validating user input.
                assert not result.is_error
                return
            assert result.is_error, f"{tool} returned success for invalid input"
            if fragment:
                assert fragment in _message_of(result)

    @pytest.mark.parametrize(("tool", "arguments", "_fragment"), BAD_CALLS)
    async def test_error_messages_teach_recovery(self, tool, arguments, _fragment):
        """A message the model cannot act on is only marginally better than a crash."""
        if tool == "coord_describe":
            pytest.skip("reports validity in its payload rather than erroring")
        async with mcp_client() as client:
            result = await client.call_tool(tool, arguments)
        message = _message_of(result)
        assert message.strip(), f"{tool} produced an empty error message"
        actionable = any(
            token in message
            for token in ("Example", "example", "Valid", "valid", "Available", "must be")
        )
        assert actionable, f"{tool} error gives the model nothing to act on: {message[:200]}"


class TestErrorConstruction:
    def test_with_example_names_input_problem_and_fix(self):
        error = GeoInputError.with_example(
            got="10SGJ068", problem="Odd digit count.", example="10S GJ 0683 4468"
        )
        message = str(error)
        assert "10SGJ068" in message  # what was received
        assert "Odd digit count" in message  # why it is wrong
        assert "10S GJ 0683 4468" in message  # what a good value looks like


class TestUnknownTool:
    async def test_calling_a_missing_tool_is_an_error(self):
        async with mcp_client() as client:
            result = await client.call_tool("no_such_tool", {})
        assert result.is_error
