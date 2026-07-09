"use client";

import { useEffect, useState } from "react";

type Journey = {
  journey_id: string;
  profile_id: string | null;
  job_url: string;
  job_title: string;
  company_name: string;
  location: string;
  job_description: string;
  company_description: string;
  job_ad_language: string;
  job_source_type: string;
  alignment_strategy: string;
  inferred_role_context: string;
  positioning_strategy: string;
  cover_letter: string;
  interview_briefing: string;
  evaluation_summary: string;
  created_at: number;
  updated_at: number;
};

function formatDate(ts: number) {
  return new Date(ts * 1000).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function badges(j: Journey): string[] {
  const out: string[] = [];
  if (j.cover_letter) out.push("cover letter ✓");
  if (j.interview_briefing) out.push("briefing ✓");
  if (j.evaluation_summary) out.push("evaluated ✓");
  return out;
}

export default function JobsPage() {
  const [journeys, setJourneys] = useState<Journey[]>([]);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/journeys")
      .then((r) => r.json())
      .then((d) => setJourneys(d.journeys))
      .catch(() => setError("Could not load job journeys."));
  }, []);

  async function deleteJourney(journey_id: string) {
    if (!confirm("Remove this job journey? Past sessions are not affected.")) return;
    setDeleting(journey_id);
    try {
      const r = await fetch(`/api/journeys/${journey_id}`, { method: "DELETE" });
      if (!r.ok) throw new Error();
      setJourneys((prev) => prev.filter((j) => j.journey_id !== journey_id));
    } catch {
      setError("Could not delete job journey.");
    } finally {
      setDeleting(null);
    }
  }

  return (
    <main className="min-h-screen">
      <header className="h-14 px-6 flex items-center justify-between border-b border-border">
        <div className="font-semibold">Jobs</div>
        <a href="/" className="text-xs text-accent hover:underline">← Home</a>
      </header>

      <div className="max-w-3xl mx-auto p-6 space-y-6">
        <p className="text-sm text-subtle">
          Every job you have worked on across the assistants. Cover letters, interview briefings,
          and evaluations attach to the same job, so a new session can pick up where the last one
          left off.
        </p>

        {error && <p className="text-sm text-err">{error}</p>}

        {journeys.length === 0 && !error && (
          <p className="text-subtle text-sm">No job journeys yet.</p>
        )}

        <ul className="space-y-3">
          {journeys.map((j) => {
            const artifactBadges = badges(j);
            return (
              <li
                key={j.journey_id}
                className="rounded-xl border border-subtle/30 bg-panel/40 overflow-hidden"
              >
                <div className="flex items-center justify-between px-5 py-4 gap-4">
                  <a href={`/jobs/${j.journey_id}`} className="flex-1 space-y-0.5">
                    <div className="font-medium">
                      {j.company_name || "—"} — {j.job_title || "—"}
                    </div>
                    <div className="text-sm text-subtle flex items-center gap-2 flex-wrap">
                      {j.location && <span>{j.location} &middot;</span>}
                      {artifactBadges.length > 0 ? (
                        artifactBadges.map((b) => (
                          <span
                            key={b}
                            className="px-2 py-0.5 rounded-full border border-subtle/30 text-xs"
                          >
                            {b}
                          </span>
                        ))
                      ) : (
                        <span className="text-xs italic">no artifacts yet</span>
                      )}
                      <span>&middot; updated {formatDate(j.updated_at)}</span>
                    </div>
                  </a>

                  <div className="flex items-center gap-3 shrink-0">
                    <a
                      href={`/jobs/${j.journey_id}`}
                      className="text-sm text-accent hover:underline"
                    >
                      Details →
                    </a>
                    <button
                      onClick={() => deleteJourney(j.journey_id)}
                      disabled={deleting === j.journey_id}
                      className="text-sm text-err hover:underline disabled:opacity-50"
                    >
                      {deleting === j.journey_id ? "Deleting…" : "Delete"}
                    </button>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </main>
  );
}
