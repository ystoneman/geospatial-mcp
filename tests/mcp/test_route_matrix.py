"""route_matrix: shape, nearest-destination summary, and limits.

The routing service is faked so these run offline; the live contract with the
public Valhalla instance is covered by the eval library.
"""

from __future__ import annotations

from typing import Any

import pytest

from geospatial_mcp.net.providers import valhalla
from tests.conftest import mcp_client

DEPOTS = "48.8584,2.2945; 48.8606,2.3376"
CUSTOMERS = "48.8530,2.3499; 48.8738,2.2950; 48.8867,2.3431"


class _FakeValhalla:
    """Travel time grows with index distance; (1, 2) is unreachable."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def __call__(self, sources, targets, *, profile="car") -> tuple[dict[str, Any], bool]:
        self.calls.append((len(sources), len(targets)))
        rows = []
        for i in range(len(sources)):
            row = []
            for j in range(len(targets)):
                unreachable = (i, j) == (1, 2)
                row.append(
                    {
                        "from_index": i,
                        "to_index": j,
                        "time": None if unreachable else 300.0 + 120.0 * abs(i - j) + j,
                        "distance": None if unreachable else 2.0 + abs(i - j),
                    }
                )
            rows.append(row)
        return {"sources_to_targets": rows, "units": "kilometers"}, False


@pytest.fixture
def fake_matrix(monkeypatch) -> _FakeValhalla:
    fake = _FakeValhalla()
    monkeypatch.setattr(valhalla, "matrix", fake)
    return fake


async def _call(args: dict[str, Any]):
    async with mcp_client() as client:
        return await client.call_tool("route_matrix", args)


class TestShape:
    async def test_every_pair_is_reported_origin_first(self, fake_matrix):
        body = (await _call({"origins": DEPOTS, "destinations": CUSTOMERS})).structured_content
        assert len(body["duration_s"]) == 2 and len(body["duration_s"][0]) == 3
        assert body["duration_s"][0][1] == pytest.approx(300.0 + 120.0 + 1)
        assert body["distance_km"][0][0] == pytest.approx(2.0)
        assert fake_matrix.calls == [(2, 3)]

    async def test_unreachable_pairs_are_null_and_counted(self, fake_matrix):
        body = (await _call({"origins": DEPOTS, "destinations": CUSTOMERS})).structured_content
        assert body["duration_s"][1][2] is None
        assert any("1 origin-destination pair" in n for n in body["meta"]["notes"])

    async def test_nearest_destination_per_origin(self, fake_matrix):
        body = (await _call({"origins": DEPOTS, "destinations": CUSTOMERS})).structured_content
        assert [n["destination"] for n in body["nearest"]] == [0, 1]

    async def test_without_destinations_a_place_is_not_its_own_nearest(self, fake_matrix):
        body = (await _call({"origins": CUSTOMERS})).structured_content
        assert fake_matrix.calls == [(3, 3)]
        for n in body["nearest"]:
            assert n["origin"] != n["destination"]

    async def test_credits_the_routing_data(self, fake_matrix):
        body = (await _call({"origins": DEPOTS, "destinations": CUSTOMERS})).structured_content
        assert body["meta"]["sources"] == ["valhalla"]
        assert body["meta"]["attribution"]


class TestLimits:
    async def test_the_public_instance_cap_is_enforced_before_any_request(self, monkeypatch):
        """100 pairs on FOSSGIS, measured; the request must never be sent."""
        sent = []
        monkeypatch.setattr(valhalla, "_post", lambda *a, **k: sent.append(a))
        many = "; ".join(f"48.{80 + i:02d},2.30" for i in range(11))
        ten = "; ".join(f"48.{80 + i:02d},2.35" for i in range(10))
        result = await _call({"origins": many, "destinations": ten})
        assert result.is_error
        text = "".join(getattr(b, "text", "") for b in result.content or [])
        assert "at most 100" in text and "11 origins x 10 destinations" in text
        assert sent == []

    async def test_too_many_place_names_is_refused_before_geocoding(self, fake_matrix):
        names = "; ".join(f"Town {i}" for i in range(11))
        result = await _call({"origins": names, "destinations": "48.85,2.35"})
        assert result.is_error
        text = "".join(getattr(b, "text", "") for b in result.content or [])
        assert "place_geocode" in text
        assert fake_matrix.calls == []

    def test_a_self_hosted_instance_gets_valhallas_own_limit(self, monkeypatch):
        from geospatial_mcp.config import Settings

        monkeypatch.setattr(
            valhalla, "settings", Settings.from_env({"VALHALLA_URL": "https://routing.example.com"})
        )
        assert valhalla.matrix_pair_cap() == 2500
