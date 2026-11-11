"""Optional speaker diarization for interview recordings.

Whisper returns unlabelled segments, which leaves the evaluator LLM guessing who
said what from phrasing alone. This module assigns each segment a speaker by
embedding its slice of audio (ECAPA-TDNN) and clustering the embeddings.

Labels are deliberately neutral — SPEAKER_A is simply whoever talks first.
Mapping them onto interviewer/candidate is left to the evaluator prompt, which
can read the self-introductions and decide once, globally, rather than guessing
line by line.

The dependencies (torch, speechbrain, scikit-learn) are an optional extra:
`uv sync --extra diarization`. Without them `diarize()` returns None and the
caller keeps today's unlabelled transcript.
"""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
MIN_SEGMENT_SEC = 0.8  # ECAPA embeddings get unreliable below this
# A "speaker" holding fewer segments than this share is a stray sound, not a person.
MIN_CLUSTER_SHARE = 0.05
MAX_OUTLIER_PASSES = 3
ECAPA_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"

_SPEAKER_NAMES = ["SPEAKER_A", "SPEAKER_B", "SPEAKER_C", "SPEAKER_D"]

_encoder: Any | None = None


def _load_encoder(device: str, savedir: Path) -> Any:
    """Load (once) the ECAPA speaker-embedding model."""
    global _encoder
    if _encoder is None:
        try:
            from speechbrain.inference.speaker import EncoderClassifier
        except ImportError:  # speechbrain < 1.0
            from speechbrain.pretrained import EncoderClassifier

        _encoder = EncoderClassifier.from_hparams(
            source=ECAPA_SOURCE,
            savedir=str(savedir),
            run_opts={"device": device},
        )
    return _encoder


def _resolve_device(device: str) -> str:
    if device != "auto":
        return device
    import torch

    # speechbrain wants an explicit index — a bare "cuda" logs a parse warning.
    return "cuda:0" if torch.cuda.is_available() else "cpu"


def _cluster_ignoring_outliers(
    n: int, fit: Callable[[list[int]], list[int]], num_speakers: int
) -> dict[int, int]:
    """Cluster items 0..n-1, re-clustering without any implausibly small cluster.

    Average linkage gives a lone outlier — a trailing slice of silence, a cough —
    a cluster of its own whenever it is further from everything than the two
    voices are from each other, leaving one "speaker" with the whole interview.
    Dropped items get no cluster here; `_backfill_clusters` labels them from
    their neighbours in time.
    """
    keep = list(range(n))
    ids = fit(keep)
    for _ in range(MAX_OUTLIER_PASSES):
        counts = Counter(ids)
        tiny = {c for c in counts if counts[c] < MIN_CLUSTER_SHARE * len(keep)}
        survivors = [k for k, c in zip(keep, ids) if c not in tiny]
        if not tiny or len(survivors) < num_speakers:
            break
        keep = survivors
        ids = fit(keep)
    return {k: int(c) for k, c in zip(keep, ids)}


def _backfill_clusters(
    starts: list[float], clusters: dict[int, int]
) -> list[int] | None:
    """Give every segment a cluster, copying the nearest labelled one in time.

    Segments too short to embed reliably inherit from whoever was speaking
    closest to them, which beats dropping them from the transcript.
    """
    if not clusters:
        return None
    labelled = sorted(clusters)
    out = []
    for i, start in enumerate(starts):
        if i in clusters:
            out.append(clusters[i])
        else:
            nearest = min(labelled, key=lambda j: abs(starts[j] - start))
            out.append(clusters[nearest])
    return out


def _name_by_first_appearance(clusters: list[int]) -> list[str]:
    """SPEAKER_A is whoever speaks first, so labels are stable across runs."""
    order: dict[int, int] = {}
    for c in clusters:
        if c not in order:
            order[c] = len(order)
    return [
        _SPEAKER_NAMES[order[c]] if order[c] < len(_SPEAKER_NAMES) else f"SPEAKER_{order[c]}"
        for c in clusters
    ]


def diarize(
    audio_path: Path,
    segments: list[Any],
    *,
    num_speakers: int = 2,
    device: str = "auto",
    model_dir: Path | None = None,
) -> list[str] | None:
    """Return one speaker label per segment, or None if diarization is unavailable.

    `segments` need `.start` / `.end` in seconds. Never raises: diarization is a
    nice-to-have, and a failure here must not cost the user their transcript.
    """
    if len(segments) < 2:
        return None
    try:
        import numpy as np
        import torch
        from faster_whisper.audio import decode_audio
        from sklearn.cluster import AgglomerativeClustering
    except ImportError as exc:
        log.info("diarization unavailable (%s) — keeping unlabelled transcript", exc)
        return None

    try:
        from backend.config import DATA_DIR

        resolved = _resolve_device(device)
        encoder = _load_encoder(resolved, model_dir or DATA_DIR / "models" / "ecapa")

        audio = decode_audio(str(audio_path), sampling_rate=SAMPLE_RATE)

        vectors: list[Any] = []
        embedded: list[int] = []
        for i, seg in enumerate(segments):
            chunk = audio[int(seg.start * SAMPLE_RATE) : int(seg.end * SAMPLE_RATE)]
            if len(chunk) < MIN_SEGMENT_SEC * SAMPLE_RATE:
                continue
            with torch.no_grad():
                emb = encoder.encode_batch(
                    torch.from_numpy(chunk).unsqueeze(0).to(resolved)
                )
            v = emb.squeeze().cpu().numpy()
            norm = float(np.linalg.norm(v))
            if norm == 0.0:
                continue
            vectors.append(v / norm)
            embedded.append(i)

        if len(vectors) < num_speakers:
            log.warning(
                "diarization skipped: only %d embeddable segments", len(vectors)
            )
            return None

        matrix = np.vstack(vectors)

        def fit(rows: list[int]) -> list[int]:
            return AgglomerativeClustering(
                n_clusters=num_speakers, metric="cosine", linkage="average"
            ).fit_predict(matrix[rows]).tolist()

        kept = _cluster_ignoring_outliers(len(vectors), fit, num_speakers)
        clusters = {embedded[k]: c for k, c in kept.items()}
        filled = _backfill_clusters([float(s.start) for s in segments], clusters)
        if filled is None:
            return None
        return _name_by_first_appearance(filled)
    except Exception as exc:  # noqa: BLE001 — never lose a transcript over this
        log.warning("diarization failed (%s) — keeping unlabelled transcript", exc)
        return None
