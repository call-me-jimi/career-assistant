# CLAUDE.md

Project-specific conventions. General coding guidelines live in `~/.claude/CLAUDE.md`.

## Project conventions

- **Package manager: `uv`.** Use `uv run <cmd>` for anything Python (`uv run pytest`, `uv run uvicorn …`), `uv add <pkg>` to add dependencies, `uv sync` to install. Do not call `pip`, `python -m venv`, or a bare `python` — they bypass the locked environment.

- **Prompts are versioned; never edit in place.** Templates under `backend/templates/prompts/` and `backend/templates/system/` follow `{stem}.vN.txt`. `backend/llm/prompts.py` resolves the highest `vN` on disk. To change a prompt, add a new file (`generate_cover_letter.v4.txt` alongside `.v3.txt`), do not mutate the existing one. This preserves history and lets you A/B compare.

- **LangGraph nodes return partial state dicts, not `ApplicationState` instances.** A node is an `async def foo(state: ApplicationState) -> dict` that returns `{"field_a": ..., "phase": "..."}`. LangGraph merges that dict into the checkpointed state. Returning a full `ApplicationState` or omitting the return are both silent bugs.

- **`emit_message` needs a `key=` when it precedes an `interrupt()`.** On resume, LangGraph re-runs the entire node body from the top, so any `emit_message` before the interrupt point will fire again. Pass a stable `key="unique:slug"` so the per-session event bus deduplicates. Messages emitted *after* the interrupt (once, on the post-resume pass) don't need a key.
