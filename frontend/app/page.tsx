"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function LandingPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function startSession() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/sessions`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      router.push(`/session?id=${data.session_id}`);
    } catch (e: any) {
      setError(
        `Could not reach the backend. Make sure it's running: ` +
          `\`uv run uvicorn backend.main:app --reload --port 8001\` (${e?.message || e}).`,
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen flex items-center justify-center px-6">
      <div className="max-w-2xl text-center space-y-8">
        <h1 className="text-5xl font-semibold tracking-tight">
          Personal Application Assistant
        </h1>
        <p className="text-lg text-subtle">
          An agentic, conversational helper that drafts a tailored cover letter
          and answers application questions. Guided by a hiring-manager
          feedback loop — with full visibility into every LLM call.
        </p>
        <button
          onClick={startSession}
          disabled={loading}
          className="px-8 py-4 text-lg rounded-2xl bg-accent text-bg font-medium hover:opacity-90 transition disabled:opacity-50"
        >
          {loading ? "Starting…" : "Start a new application"}
        </button>
        {error && (
          <p className="text-sm text-err whitespace-pre-wrap">{error}</p>
        )}
        <div>
          <a href="/settings" className="text-sm text-accent hover:underline">
            Settings →
          </a>
        </div>
      </div>
    </main>
  );
}
