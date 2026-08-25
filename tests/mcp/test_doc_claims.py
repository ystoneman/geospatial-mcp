"""The reader-facing surface must not rank this package against others.

A superlative about the ecosystem -- "the only MCP server that...", "no other
server implements..." -- has three problems. It cannot be verified at review
time, it goes stale silently as the field moves, and in a tool description it
becomes something the model repeats to a user as fact.

The fix is not a softer hedge. "As far as we can tell" reads as caution while
doing the opposite: it is what makes an unchecked claim feel safe to ship. State
what this package does, and link to a live index so the reader can compare.

Scope is the surface a reader or a model actually sees: the README and every
tool description sent over the wire. Internal architecture statements are fair
game and deliberately not matched -- "the only module that imports from `mcp`"
is a checkable fact about this repository, not a claim about anyone else.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.conftest import mcp_client

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Each pattern targets a comparison with software outside this repository.
#: Keep them narrow: a broad "only" or "best" would fire on legitimate prose.
BANNED = {
    # The filler refuses articles: "given only the tool catalogue" is ordinary
    # prose, while "the only open-source MCP server" is a ranking.
    "ecosystem superlative": re.compile(
        r"\b(?:the\s+)?(?:only|first|best|leading)\s+"
        r"(?:(?!the\b|a\b|an\b)\w+[- ]){0,3}"
        r"(?:open[- ]source\s+)?(?:mcp\s+server|server|package|library|"
        r"implementation|tool)\b",
        re.IGNORECASE,
    ),
    "no-one-else claim": re.compile(
        r"\bno\s+(?:other|one\s+else)\b[^.]{0,60}\b(?:server|package|library|"
        r"project|implement)",
        re.IGNORECASE,
    ),
    "unverifiable hedge": re.compile(
        r"\bas far as (?:we|i) (?:can tell|know)\b|"
        r"\bto (?:our|my) knowledge\b|"
        r"\bwe believe this is the\b",
        re.IGNORECASE,
    ),
    "unfavourable comparison": re.compile(
        r"\b(?:unlike|better than|superior to)\s+(?:other|most|every|all)\s+"
        r"\w*\s*(?:mcp\s+)?(?:servers?|packages?|libraries|tools?)\b",
        re.IGNORECASE,
    ),
}


def _offenders(text: str) -> list[str]:
    hits = []
    for label, pattern in BANNED.items():
        for match in pattern.finditer(text):
            line = text[: match.start()].count("\n") + 1
            hits.append(f"line {line}: {label}: {match.group(0)!r}")
    return hits


class TestReaderFacingDocs:
    @pytest.mark.parametrize(
        "relative_path",
        ["README.md", "CHANGELOG.md", "docs/REFERENCES.md", "evals/README.md"],
    )
    def test_no_claims_about_other_projects(self, relative_path):
        path = REPO_ROOT / relative_path
        if not path.exists():
            pytest.skip(f"{relative_path} does not exist")
        offenders = _offenders(path.read_text(encoding="utf-8"))
        assert not offenders, f"{relative_path} ranks itself against other projects:\n" + "\n".join(
            offenders
        )


class TestToolDescriptions:
    """The model-facing surface matters most: it gets repeated to users."""

    async def test_no_tool_description_ranks_this_server(self):
        async with mcp_client("all") as client:
            for tool in (await client.list_tools()).tools:
                offenders = _offenders(tool.description or "")
                assert not offenders, (
                    f"{tool.name} description makes a claim about other software:\n"
                    + "\n".join(offenders)
                )


class TestThePatternsActuallyFire:
    """A guard that never fires is worse than no guard: it reads as coverage."""

    @pytest.mark.parametrize(
        "text",
        [
            "As far as we can tell this is the only open-source MCP server that does X.",
            "This is the first MCP server to implement a link budget.",
            "No other server implements USNG conversion.",
            "Unlike other MCP servers, this one is correct.",
            "To our knowledge nothing else does this.",
        ],
    )
    def test_catches_the_claims_it_is_meant_to_catch(self, text):
        assert _offenders(text), f"pattern set missed: {text!r}"

    @pytest.mark.parametrize(
        "text",
        [
            "`_sdk.py` is the only module that imports from `mcp`.",
            "`cli.py` is the only place that prints to stdout.",
            "Pick the best route for the vehicle profile.",
            "The first line of a docstring must be a standalone sentence.",
            "This is one server among many; see the registry to compare.",
            "Whether a model, given only the tool catalogue, selects the right tools.",
            "Offline keeps only the tools that make no network call.",
        ],
    )
    def test_does_not_fire_on_legitimate_prose(self, text):
        assert not _offenders(text), f"false positive on: {text!r}"
