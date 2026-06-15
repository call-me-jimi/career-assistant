"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

type AssistantType =
  | "cover_letter"
  | "interview_prep"
  | "career_advisor"
  | "interview_evaluator";

const LANGUAGES = [
  "English",
  "German",
  "French",
  "Spanish",
  "Italian",
  "Dutch",
  "Portuguese",
];

const ASSISTANTS: {
  type: AssistantType;
  title: string;
  blurb: string;
}[] = [
  {
    type: "cover_letter",
    title: "Cover Letter",
    blurb:
      "Draft a tailored cover letter for a specific role, refined by a simulated hiring-manager feedback loop, with optional Q&A.",
  },
  {
    type: "interview_prep",
    title: "Interview Prep",
    blurb:
      "Turn a job description + anything the company shared about the interview into a focused briefing: likely questions, stories to rehearse, and how to reduce hiring-manager doubt.",
  },
  {
    type: "career_advisor",
    title: "Career Advisor",
    blurb:
      "Open conversation about your experience to clarify strengths and weaknesses. Ask for a SWOT summary at any time.",
  },
  {
    type: "interview_evaluator",
    title: "Interview Evaluator",
    blurb:
      "Upload an audio recording of a real interview you've already given. Transcribed locally, then turned into a structured performance report — strengths, weaknesses, and a per-question breakdown.",
  },
];

export default function LandingPage() {
  const router = useRouter();
  const [loading, setLoading] = useState<AssistantType | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [language, setLanguage] = useState("English");
  const [hasPendingUpdates, setHasPendingUpdates] = useState(false);

  useEffect(() => {
    fetch("/api/profiles")
      .then((r) => r.json())
      .then((d) =>
        setHasPendingUpdates(
          (d.profiles ?? []).some(
            (p: { pending_suggestion_count?: number }) =>
              (p.pending_suggestion_count ?? 0) > 0,
          ),
        ),
      )
      .catch(() => {});
  }, []);

  async function startSession(assistantType: AssistantType) {
    setLoading(assistantType);
    setError(null);
    try {
      const res = await fetch(`/api/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ assistant_type: assistantType, language }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      router.push(`/session?id=${data.session_id}`);
    } catch (e: any) {
      setError(
        `Could not reach the backend. Make sure it's running: ` +
          `\`uv run uvicorn backend.main:app --reload --port 8001\` (${e?.message || e}).`,
      );
      setLoading(null);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center px-6 py-12">
      <div className="max-w-5xl w-full text-center space-y-10">
        <div className="space-y-4">
          <h1 className="text-5xl font-semibold tracking-tight">
            Personal Career Assistant
          </h1>
          <p className="text-lg text-subtle">
            Specialised assistants for the hard parts of switching jobs.
            Pick one to get started.
          </p>
        </div>

        <div className="flex flex-col items-center gap-1">
          <div className="flex items-center justify-center gap-3">
            <label htmlFor="language" className="text-sm text-subtle">
              Language
            </label>
            <select
              id="language"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              disabled={loading !== null}
              className="rounded-lg border border-subtle/30 bg-panel/40 px-3 py-2 text-sm disabled:opacity-50"
            >
              {LANGUAGES.map((l) => (
                <option key={l} value={l}>
                  {l}
                </option>
              ))}
            </select>
          </div>
          <p className="text-xs text-subtle">
            Deliverables and the assistant&apos;s replies will be in this language.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 text-left">
          {ASSISTANTS.map((a) => (
            <button
              key={a.type}
              onClick={() => startSession(a.type)}
              disabled={loading !== null}
              className="rounded-2xl border border-subtle/30 bg-panel/40 hover:border-accent hover:bg-panel/70 transition p-6 flex flex-col gap-3 disabled:opacity-50 disabled:cursor-not-allowed text-left"
            >
              <div className="text-xl font-semibold">{a.title}</div>
              <div className="text-sm text-subtle leading-relaxed">
                {a.blurb}
              </div>
              <div className="mt-auto pt-2 text-sm text-accent">
                {loading === a.type ? "Starting…" : "Start →"}
              </div>
            </button>
          ))}
        </div>

        {error && (
          <p className="text-sm text-err whitespace-pre-wrap">{error}</p>
        )}
        <div className="flex gap-6 justify-center">
          <a
            href="/profiles"
            className="text-sm text-accent hover:underline inline-flex items-center gap-1.5"
          >
            Profiles →
            {hasPendingUpdates && (
              <span
                className="h-2 w-2 rounded-full bg-accent"
                title="You have profile updates to review."
                aria-label="Profile updates to review"
              />
            )}
          </a>
          <a href="/dashboard" className="text-sm text-accent hover:underline">
            Dashboard →
          </a>
          <a href="/settings" className="text-sm text-accent hover:underline">
            Settings →
          </a>
        </div>
      </div>
    </main>
  );
}
