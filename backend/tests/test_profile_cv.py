"""The original CV file: staged on upload, claimed by the profile cv_intake saves,
attachable afterwards, served back, and gone with its profile."""

import os
import time

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import backend.storage.cv_files as cv_files
from backend.agent.nodes import cv_intake as intake
from backend.agent.state import ApplicationState
from backend.api.routes import router
from backend.llm.service import LLMCallResult
from backend.storage.profiles import delete_profile, get_profile, save_profile

PDF = b"%PDF-1.4 fake"


@pytest.fixture(autouse=True)
def dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(cv_files, "STAGING_DIR", tmp_path / "staging")
    monkeypatch.setattr(cv_files, "CV_DIR", tmp_path / "cvs")


@pytest.fixture
async def client(test_db):
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _profile() -> str:
    return await save_profile(name="Backend", cv_text="CV", candidate_profile="P")


async def test_claimed_upload_lands_on_the_profile(test_db):
    pid = await _profile()
    upload_id = cv_files.stage_upload(PDF, "../../Jane Doe CV.pdf")

    assert await cv_files.claim_upload(pid, upload_id)

    profile = await get_profile(pid)
    assert profile["cv_filename"] == "Jane Doe CV.pdf"  # path parts stripped
    assert cv_files.cv_path(pid, "Jane Doe CV.pdf").read_bytes() == PDF
    assert not (cv_files.STAGING_DIR / upload_id).exists()


async def test_unknown_upload_is_not_claimed(test_db):
    pid = await _profile()
    assert not await cv_files.claim_upload(pid, "nope")
    assert (await get_profile(pid))["cv_filename"] is None


async def test_stale_staged_uploads_are_swept_on_next_upload(test_db):
    old = cv_files.stage_upload(PDF, "old.pdf")
    past = time.time() - cv_files.STALE_AFTER_S - 60
    os.utime(cv_files.STAGING_DIR / old, (past, past))

    fresh = cv_files.stage_upload(PDF, "new.pdf")

    assert not (cv_files.STAGING_DIR / old).exists()
    assert (cv_files.STAGING_DIR / fresh).exists()


async def test_deleting_the_profile_deletes_its_file(test_db):
    pid = await _profile()
    await cv_files.attach_cv(pid, PDF, "cv.pdf")
    await delete_profile(pid)
    assert not cv_files.cv_path(pid, "cv.pdf").exists()


async def test_attach_then_replace_then_download(client):
    pid = await _profile()
    assert (await client.get(f"/api/profiles/{pid}/cv")).status_code == 404

    r = await client.post(f"/api/profiles/{pid}/cv", files={"file": ("a.pdf", PDF)})
    assert r.json() == {"cv_filename": "a.pdf"}

    r = await client.post(f"/api/profiles/{pid}/cv", files={"file": ("b.PDF", b"%PDF-2")})
    assert r.json() == {"cv_filename": "b.PDF"}
    assert list(cv_files.CV_DIR.iterdir()) == [cv_files.cv_path(pid, "b.PDF")]

    r = await client.get(f"/api/profiles/{pid}/cv")
    assert r.status_code == 200
    assert r.content == b"%PDF-2"
    assert r.headers["content-disposition"].startswith("inline")
    assert (await get_profile(pid))["cv_text"] == "CV"  # replacing never re-parses


async def test_attach_to_unknown_profile_is_404(client):
    r = await client.post("/api/profiles/missing/cv", files={"file": ("a.pdf", PDF)})
    assert r.status_code == 404
    assert not cv_files.CV_DIR.exists() or not any(cv_files.CV_DIR.iterdir())


def _run_intake(monkeypatch, label: str, upload_id: str):
    replies = iter([{"cv_text": "MY CV", "upload_id": upload_id}, label])
    monkeypatch.setattr(intake, "interrupt", lambda payload: next(replies))

    async def fake_call_llm(**kw):
        return LLMCallResult(text="PROFILE", model="m", provider="p")

    monkeypatch.setattr(intake, "call_llm", fake_call_llm)
    monkeypatch.setattr(intake, "load_system_prompt", lambda stem: "sys")
    monkeypatch.setattr(intake, "render_user_prompt", lambda stem, **kw: "usr")
    return intake.cv_intake_node(ApplicationState(session_id="s", applicant_name="Jane"))


async def test_cv_intake_keeps_the_file_on_the_saved_profile(test_db, monkeypatch):
    upload_id = cv_files.stage_upload(PDF, "cv.pdf")
    update = await _run_intake(monkeypatch, "Backend", upload_id)
    assert (await get_profile(update["profile_id"]))["cv_filename"] == "cv.pdf"


async def test_cv_intake_leaves_the_file_staged_when_not_saving(test_db, monkeypatch):
    upload_id = cv_files.stage_upload(PDF, "cv.pdf")
    update = await _run_intake(monkeypatch, "no", upload_id)
    assert "profile_id" not in update
    assert (cv_files.STAGING_DIR / upload_id).exists()  # swept later
