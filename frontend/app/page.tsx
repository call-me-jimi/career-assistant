"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

type AssistantType = "cover_letter" | "interview_prep" | "career_advisor";

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
];

export default function LandingPage() {
  const router = useRouter();
  const [loading, setLoading] = useState<AssistantType | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function startSession(assistantType: AssistantType) {
    setLoading(assistantType);
    setError(null);
    try {
      const res = await fetch(`/api/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ assistant_type: assistantType }),
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
            Three specialised assistants for the hard parts of switching jobs.
            Pick one to get started.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-left">
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
          <a href="/profiles" className="text-sm text-accent hover:underline">
            Profiles →
          </a>
          <a href="/settings" className="text-sm text-accent hover:underline">
            Settings →
          </a>
        </div>
      </div>
    </main>
  );
}
