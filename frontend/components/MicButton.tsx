"use client";

import { useEffect } from "react";
import { useVoiceRecorder } from "../lib/useVoiceRecorder";

type Props = {
  sessionId?: string;
  disabled?: boolean;
  onTranscript: (text: string) => void;
  onError?: (msg: string | null) => void;
};

function formatElapsed(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function MicIcon({ filled = false }: { filled?: boolean }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <rect x="9" y="3" width="6" height="12" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0" />
      <line x1="12" y1="18" x2="12" y2="22" />
    </svg>
  );
}

function Spinner() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      className="animate-spin"
      aria-hidden
    >
      <path d="M21 12a9 9 0 1 1-6.219-8.56" />
    </svg>
  );
}

export default function MicButton({ sessionId, disabled, onTranscript, onError }: Props) {
  const { state, error, elapsedSec, supported, start, stop } = useVoiceRecorder({
    sessionId,
    onTranscript: (text) => {
      onError?.(null);
      onTranscript(text);
    },
  });

  useEffect(() => {
    if (onError) onError(error);
  }, [error, onError]);

  if (!supported) return null;

  const onClick = () => {
    if (state === "recording") {
      stop();
    } else if (state === "idle" || state === "error") {
      void start();
    }
  };

  if (state === "recording") {
    return (
      <button
        type="button"
        onClick={onClick}
        aria-label="Stop and transcribe"
        className="relative px-4 py-3 rounded-xl bg-err text-bg font-medium flex items-center gap-2 min-w-[5rem]"
      >
        <span className="absolute inset-0 rounded-xl bg-err/40 animate-ping" aria-hidden />
        <span className="relative flex items-center gap-2">
          <MicIcon filled />
          <span className="tabular-nums text-sm">{formatElapsed(elapsedSec)}</span>
        </span>
      </button>
    );
  }

  if (state === "transcribing") {
    return (
      <button
        type="button"
        disabled
        aria-label="Transcribing"
        className="px-4 py-3 rounded-xl border border-border text-subtle flex items-center gap-2 disabled:opacity-70"
      >
        <Spinner />
        <span className="text-sm">Transcribing…</span>
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label="Start voice input"
      title="Speak your prompt"
      className="px-4 py-3 rounded-xl border border-border text-subtle hover:text-accent hover:border-accent transition-colors disabled:opacity-50"
    >
      <MicIcon />
    </button>
  );
}
