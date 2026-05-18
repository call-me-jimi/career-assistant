# LLM Models

Three files need updating. No code changes required for standard providers (Anthropic, OpenAI, Ollama).

## 1. `backend/config/settings.json` — pricing

Add an entry under `model_pricing`:

```json
"model_pricing": {
  "gpt-5.5": {
    "input_per_mtok": 5.0,
    "output_per_mtok": 30.0
  },
  ...
}
```

Pricing is in USD per million tokens. If unknown, omit the entry — cost tracking will show $0.

### Known prices (last verified 2026-05-04)

Sources: [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) · [OpenAI pricing](https://developers.openai.com/api/docs/pricing)

| Model | Input $/1M | Output $/1M |
|---|---|---|
| `gpt-5.5` | 5.00 | 30.00 |
| `gpt-5.5-pro` | 30.00 | 180.00 |
| `gpt-5.4` | 2.50 | 15.00 |
| `gpt-5.4-mini` | 0.75 | 4.50 |
| `claude-opus-4-7` | 5.00 | 25.00 |
| `claude-opus-4-6` | 5.00 | 25.00 |
| `claude-sonnet-4-6` | 3.00 | 15.00 |
| `claude-haiku-4-5` / `claude-haiku-4-5-20251001` | 1.00 | 5.00 |

## 2. `frontend/app/settings/page.tsx` — model dropdown

Add the model name to the `PROVIDER_MODELS` object under the correct provider key (`anthropic`, `openai`, or `ollama`). Insert at the top of the list (newest first):

```ts
const PROVIDER_MODELS = {
  openai: [
    "gpt-5.5",      // add here
    "gpt-5.5-pro",  // add here
    "gpt-5.4",
    ...
  ],
  ...
};
```

## 3. `backend/llm/service.py` — temperature handling (OpenAI only)

Check the `startswith` guard at the `build_chat_model` function. Reasoning/frontier models typically reject a `temperature` parameter. The current guard covers `gpt-5`, `o1`, and `o3` prefixes:

```python
if not cfg.model_name.lower().startswith(("gpt-5", "o1", "o3")):
    kwargs["temperature"] = 0.7
```

Extend this tuple if adding a new model family that doesn't accept temperature (e.g. a future `o4` series).

For Anthropic models, a separate guard covers `claude-opus-4` (which uses default temperature). Update similarly if a new Anthropic model rejects temperature.

## Using the model

After the changes above, the model is selectable in **Settings → LLM defaults** or any per-task override. No restart needed — `settings.json` is read on each request.

To set a model as default for a specific task, add it to `task_llm_configs` in `settings.json`:

```json
"task_llm_configs": {
  "cover_letter_generation": {
    "provider": "openai",
    "model_name": "gpt-5.5",
    "base_url": null,
    "api_key": null
  }
}
```

## New providers

To add a provider beyond Anthropic/OpenAI/Ollama, add a new `if provider == "..."` branch in `build_chat_model` (`backend/llm/service.py`) and add the provider name to `PROVIDERS` in the settings page.
