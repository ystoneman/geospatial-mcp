# CLAUDE.md

@AGENTS.md

Claude Code specifics:

- `.mcp.json` in this repo registers the server from the local checkout, so you
  can call its own tools while developing. Restart the session after changing
  the tool surface.
- Prefer `make check` over running ruff, mypy and pytest separately — it is
  exactly what CI runs.
