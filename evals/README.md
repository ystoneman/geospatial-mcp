# Tool-selection evals

Unit tests prove the tools compute correct answers. They say nothing about
whether an agent handed a real question will *pick the right tool*. That is a
property of the tool names, descriptions and parameter design, and it is the
thing most likely to silently regress when a description is reworded.

This directory holds a prompt library and two runners.

## Two modes

| Mode | Needs an API key | What it proves |
|---|---|---|
| `--mode validate` | no | Every case references tools that exist, and the expected tool chain actually produces an answer satisfying the case's assertions. Catches drift between the library and the server. |
| `--mode agent` | yes (`ANTHROPIC_API_KEY`) | Whether a model, given only the tool catalogue and the prompt, selects the expected tools, with sane arguments, and reaches a correct answer. |

`validate` is the cheap gate that runs in CI. `agent` is the real measure and
runs before a release or after any tool-description change.

## Running

```bash
uv run python evals/run.py --mode validate            # offline cases only
uv run python evals/run.py --mode validate --network  # include live-API cases
uv run python evals/run.py --mode agent --model claude-sonnet-5
uv run python evals/run.py --mode agent --filter telecom   # one persona
```

## Coverage axes

The library is organised so that each case tests one thing that could break:

1. **Persona breadth** — the anti-narrowing check. Every case is drawn from a
   different industry: logistics, telecom, agriculture, insurance, real estate,
   utilities, emergency response, surveying, maritime, consumer. If the tool
   surface only makes sense to one audience, these fail.
2. **Disambiguation pairs** — near-neighbour tools that are easy to confuse.
   *"How far apart"* must reach `geom_measure`; *"how long to drive"* must reach
   `route_directions`. Each pair appears twice, once for each side.
3. **Multi-tool chains** — questions needing three or more calls with real data
   dependencies, where an early wrong turn compounds.
4. **Input polymorphism** — the same question asked with decimal degrees, DMS,
   a grid reference, a Plus Code and a place name must reach the same tool.
5. **Error recovery** — a deliberately malformed input. Does the error message
   let the model correct itself within the turn budget?
6. **Gap awareness** — a capability that is switched off. The model should call
   `geo_capabilities` and report what to enable, not invent a tool or claim the
   task is impossible.

## Scoring

| Metric | Definition | Gate |
|---|---|---|
| Tool-selection F1 | called set vs `expect_tools` | ≥ 0.90 |
| First-call accuracy | first call is in `expect_tools` | ≥ 0.85 |
| Distractor rate | any `forbid_tools` was called | ≤ 0.05 |
| Argument validity | calls passing schema validation first try | ≥ 0.95 |
| Recovery rate | error cases resolved within `max_turns` | ≥ 0.80 |
| Answer correctness | rubric judged, or numeric within tolerance | ≥ 0.85 |

When a case fails, the fix is usually a tool *description*, not code. Feed the
failing transcripts back and rewrite the description that misled the model.
