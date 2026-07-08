"""Step 8: the configured default model must always have a pricing entry.

Regression guard for the bug where the default model (claude-sonnet-4-5) had no
model_pricing entry, so _cost_for silently reported $0 for every default-model
call in /stats and traces. Written against the default model name so it keeps
guarding the invariant even if the default or its price changes.
"""
import pytest

from backend.api.routes import _cost_for
from backend.config import load_settings


def test_default_model_has_nonzero_pricing():
    settings = load_settings()
    default_model = settings.default_llm.model_name
    pricing = settings.model_pricing
    assert default_model in pricing, (
        f"default model {default_model!r} has no model_pricing entry -> "
        "cost tracking would report $0"
    )
    cost = _cost_for(default_model, 1_000_000, 1_000_000, pricing)
    assert cost > 0


def test_cost_for_unpriced_model_is_zero():
    # sanity: the helper returns 0.0 (not an error) for an unknown model
    assert _cost_for("no-such-model", 1_000_000, 1_000_000, {}) == 0.0
