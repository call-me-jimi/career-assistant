# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## Project conventions

- **Package manager: `uv`.** Use `uv run <cmd>` for anything Python (`uv run pytest`, `uv run uvicorn …`), `uv add <pkg>` to add dependencies, `uv sync` to install. Do not call `pip`, `python -m venv`, or a bare `python` — they bypass the locked environment.

- **Prompts are versioned; never edit in place.** Templates under `backend/templates/prompts/` and `backend/templates/system/` follow `{stem}.vN.txt`. `backend/llm/prompts.py` resolves the highest `vN` on disk. To change a prompt, add a new file (`generate_cover_letter.v4.txt` alongside `.v3.txt`), do not mutate the existing one. This preserves history and lets you A/B compare.

- **LangGraph nodes return partial state dicts, not `ApplicationState` instances.** A node is an `async def foo(state: ApplicationState) -> dict` that returns `{"field_a": ..., "phase": "..."}`. LangGraph merges that dict into the checkpointed state. Returning a full `ApplicationState` or omitting the return are both silent bugs.

- **`emit_message` needs a `key=` when it precedes an `interrupt()`.** On resume, LangGraph re-runs the entire node body from the top, so any `emit_message` before the interrupt point will fire again. Pass a stable `key="unique:slug"` so the per-session event bus deduplicates. Messages emitted *after* the interrupt (once, on the post-resume pass) don't need a key.
