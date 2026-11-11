"""Speaker diarization: label bookkeeping, and graceful degradation without deps.

The embedding/clustering itself needs the optional `diarization` extra, so the
tests here cover the pure logic plus the contract that matters most — a failure
anywhere in diarization must cost speaker labels, never the transcript.
"""
from __future__ import annotations

from pathlib import Path

from backend.tools import diarize as mod
from backend.tools.transcribe import TranscriptSegment


def test_speaker_a_is_whoever_spoke_first():
    # Cluster ids are arbitrary integers from the clusterer; the first one seen
    # must always become SPEAKER_A so labels are stable across runs.
    assert mod._name_by_first_appearance([1, 1, 0, 0, 1]) == [
        "SPEAKER_A",
        "SPEAKER_A",
        "SPEAKER_B",
        "SPEAKER_B",
        "SPEAKER_A",
    ]


def test_short_segments_inherit_nearest_speaker_in_time():
    starts = [0.0, 5.0, 5.4, 20.0]
    clusters = {0: 0, 1: 1, 3: 0}  # index 2 was too short to embed
    assert mod._backfill_clusters(starts, clusters) == [0, 1, 1, 0]


def test_lone_outlier_does_not_become_the_second_speaker():
    # Item 40 is a trailing slice of silence. The first fit isolates it, which
    # would put the whole interview on one speaker; the refit must split 0..39.
    calls: list[list[int]] = []

    def fit(rows):
        calls.append(rows)
        if 40 in rows:
            return [1 if r == 40 else 0 for r in rows]
        return [0 if r % 2 else 1 for r in rows]

    clusters = mod._cluster_ignoring_outliers(41, fit, num_speakers=2)

    assert len(calls) == 2
    assert 40 not in clusters  # left for _backfill_clusters
    assert sorted(set(clusters.values())) == [0, 1]


def test_balanced_clusters_are_fitted_once():
    calls = []

    def fit(rows):
        calls.append(rows)
        return [r % 2 for r in rows]

    assert mod._cluster_ignoring_outliers(10, fit, num_speakers=2) == {
        r: r % 2 for r in range(10)
    }
    assert len(calls) == 1


def test_backfill_returns_none_when_nothing_was_embedded():
    assert mod._backfill_clusters([0.0, 1.0], {}) is None


def test_diarize_returns_none_when_optional_deps_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name in {"torch", "sklearn.cluster", "sklearn"}:
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    segments = [
        TranscriptSegment(start=0.0, end=4.0, text="a"),
        TranscriptSegment(start=4.0, end=8.0, text="b"),
    ]
    assert mod.diarize(Path("/nonexistent.m4a"), segments) is None


def test_diarize_returns_none_on_unreadable_audio():
    # Deps may or may not be installed; either way a missing file must not raise.
    segments = [
        TranscriptSegment(start=0.0, end=4.0, text="a"),
        TranscriptSegment(start=4.0, end=8.0, text="b"),
    ]
    assert mod.diarize(Path("/nonexistent.m4a"), segments) is None


def test_diarize_returns_none_for_trivial_transcript():
    assert mod.diarize(Path("/nonexistent.m4a"), []) is None
