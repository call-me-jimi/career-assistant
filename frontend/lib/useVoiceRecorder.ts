"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "./ws";

export type RecorderState = "idle" | "requesting" | "recording" | "transcribing" | "error";

const MAX_DURATION_SEC = 60;

type Options = {
  sessionId?: string;
  onTranscript: (text: string) => void;
};

function describeError(err: unknown): string {
  if (err instanceof Error) {
    if (err.name === "NotAllowedError" || err.name === "SecurityError") {
      return "Microphone permission denied.";
    }
    if (err.name === "NotFoundError" || err.name === "OverconstrainedError") {
      return "No microphone found.";
    }
    if (err.name === "NotSupportedError") {
      return "This browser doesn't support voice input.";
    }
    return err.message || "Voice input failed.";
  }
  return String(err);
}

function pickMimeType(): string {
  if (typeof MediaRecorder === "undefined") return "";
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  for (const m of candidates) {
    if (MediaRecorder.isTypeSupported?.(m)) return m;
  }
  return "";
}

export function useVoiceRecorder({ sessionId, onTranscript }: Options) {
  const [state, setState] = useState<RecorderState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [elapsedSec, setElapsedSec] = useState(0);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cancelledRef = useRef(false);

  const supported =
    typeof window !== "undefined" &&
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== "undefined";

  const cleanup = useCallback(() => {
    if (tickRef.current) {
      clearInterval(tickRef.current);
      tickRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    recorderRef.current = null;
    chunksRef.current = [];
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const start = useCallback(async () => {
    if (!supported) {
      setError("This browser doesn't support voice input.");
      setState("error");
      return;
    }
    setError(null);
    cancelledRef.current = false;
    setState("requesting");
    try {
      const stream = await Promise.race([
        navigator.mediaDevices.getUserMedia({ audio: true }),
        new Promise<never>((_, reject) =>
          setTimeout(
            () => reject(new Error("No response — check your browser's address bar for a microphone permission prompt.")),
            20000,
          )
        ),
      ]);
      streamRef.current = stream;

      const mimeType = pickMimeType();
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      recorderRef.current = recorder;
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        if (cancelledRef.current) {
          cleanup();
          setState("idle");
          setElapsedSec(0);
          return;
        }
        const blob = new Blob(chunksRef.current, {
          type: recorder.mimeType || "audio/webm",
        });
        cleanup();
        setElapsedSec(0);

        if (blob.size === 0) {
          setState("idle");
          return;
        }

        setState("transcribing");
        try {
          if (!sessionId) throw new Error("Session id missing.");
          const fd = new FormData();
          fd.append("session_id", sessionId);
          const ext = (blob.type.split("/")[1] || "webm").split(";")[0];
          fd.append("file", blob, `voice.${ext}`);
          const res = await fetch(`${API_BASE}/api/transcribe/voice-prompt`, {
            method: "POST",
            body: fd,
          });
          if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
            throw new Error(err.detail || `HTTP ${res.status}`);
          }
          const data = await res.json();
          const text = (data.text || "").trim();
          if (text) onTranscript(text);
          setState("idle");
        } catch (err) {
          setError(describeError(err));
          setState("error");
        }
      };

      recorder.start();
      setState("recording");
      setElapsedSec(0);
      const startedAt = Date.now();
      tickRef.current = setInterval(() => {
        const sec = Math.floor((Date.now() - startedAt) / 1000);
        setElapsedSec(sec);
        if (sec >= MAX_DURATION_SEC && recorder.state === "recording") {
          recorder.stop();
        }
      }, 250);
    } catch (err) {
      cleanup();
      setError(describeError(err));
      setState("error");
    }
  }, [cleanup, onTranscript, sessionId, supported]);

  const stop = useCallback(() => {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.stop();
    }
  }, []);

  const cancel = useCallback(() => {
    cancelledRef.current = true;
    stop();
  }, [stop]);

  const reset = useCallback(() => {
    setError(null);
    setState("idle");
  }, []);

  return { state, error, elapsedSec, supported, start, stop, cancel, reset };
}
