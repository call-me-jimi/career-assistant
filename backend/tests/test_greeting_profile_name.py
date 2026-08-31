"""Reusing a saved profile must set applicant_name from the candidate name, not the label.

A profile's `name` is a short user-chosen label (often a role, e.g. "Head of Data")
while `applicant_name` is the real person. The greeting node must pick the latter so
downstream naming (the exported CoverLetter.<name>.pdf) uses the applicant, not the role.
"""
from __future__ import annotations

import pytest

from backend.agent.nodes import greeting as mod
from backend.agent.state import ApplicationState


@pytest.mark.asyncio
async def test_reused_profile_uses_applicant_name_not_label(monkeypatch):
    profiles = [
        {
            "profile_id": "pid-1",
            "name": "Head of Data",              # role-based label
            "applicant_name": "Dr Hendrik Hache",  # actual candidate
            "updated_at": 0,
            "created_at": 0,
        }
    ]

    async def fake_list_profiles():
        return profiles

    monkeypatch.setattr(mod, "list_profiles", fake_list_profiles)
    monkeypatch.setattr(mod, "emit_message", lambda *a, **k: None)
    monkeypatch.setattr(mod, "interrupt", lambda payload: "1")  # pick profile #1

    state = ApplicationState(session_id="s", assistant_type="cover_letter")
    update = await mod.greeting_node(state)

    assert update["profile_id"] == "pid-1"
    assert update["applicant_name"] == "Dr Hendrik Hache"


@pytest.mark.asyncio
async def test_reused_profile_falls_back_to_label_when_no_applicant_name(monkeypatch):
    profiles = [
        {"profile_id": "pid-2", "name": "Backend focus", "applicant_name": None,
         "updated_at": 0, "created_at": 0}
    ]

    async def fake_list_profiles():
        return profiles

    monkeypatch.setattr(mod, "list_profiles", fake_list_profiles)
    monkeypatch.setattr(mod, "emit_message", lambda *a, **k: None)
    monkeypatch.setattr(mod, "interrupt", lambda payload: "1")

    state = ApplicationState(session_id="s", assistant_type="cover_letter")
    update = await mod.greeting_node(state)

    assert update["applicant_name"] == "Backend focus"
