"""An opt-in record of every tool call, for evaluating agents in any harness.

Each agent harness logs tool use in its own format, and some barely at all. Set
``GEO_TRACE_FILE`` and the server appends one JSON line per call instead: the
tool, the arguments exactly as the client sent them (before validation, so
malformed calls are recorded too), whether the call failed and why, how long it
took, and how large the result was. Scoring an agent then needs nothing from
the harness except its final answer.

The file holds coordinates and search terms, so tracing is never on by default.
It is written to a file, never to stdout, which the stdio transport reserves
for JSON-RPC.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

__all__ = ["enable_tracing"]

log = logging.getLogger(__name__)

_lock = threading.Lock()


def enable_tracing(server: Any, path: str | Path) -> None:
    """Wrap every registered tool so each call is appended to ``path``."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    for tool in server._tool_manager.list_tools():
        _wrap(tool, target)


def _wrap(tool: Any, target: Path) -> None:
    original = tool.run
    name = tool.name

    async def traced_run(arguments: dict[str, Any], context: Any, **kwargs: Any) -> Any:
        record: dict[str, Any] = {"ts": round(time.time(), 3), "tool": name, "arguments": arguments}
        started = time.monotonic()
        try:
            result = await original(arguments, context, **kwargs)
        except BaseException as exc:
            record.update(ok=False, error=f"{type(exc).__name__}: {exc}"[:1000])
            raise
        else:
            record.update(ok=True, result_chars=_size(result))
            return result
        finally:
            record["duration_ms"] = round((time.monotonic() - started) * 1000, 1)
            _append(target, record)

    # The SDK's Tool is a pydantic model; bypass its __setattr__ so the instance
    # attribute shadows the class method the tool manager calls.
    object.__setattr__(tool, "run", traced_run)


def _size(result: Any) -> int | None:
    try:
        dump = getattr(result, "model_dump_json", None)
        return len(dump() if dump else json.dumps(result, default=str))
    except Exception:  # sizing is diagnostic only; never fail a call over it
        return None


def _append(target: Path, record: dict[str, Any]) -> None:
    line = json.dumps(record, default=str) + "\n"
    try:
        with _lock, target.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError as exc:  # a full disk must not turn a good answer into an error
        log.warning("could not write tool trace to %s: %s", target, exc)
