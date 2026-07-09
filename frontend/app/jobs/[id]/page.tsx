"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

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

function formatDate(ts: number | null | undefined) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

function formatEvaluation(raw: string): string {
  try {
    const parsed = JSON.parse(raw);
    const score = parsed.overall_score != null ? `Score: ${parsed.overall_score}/10\n\n` : "";
    return `${score}${parsed.summary || ""}`.trim() || raw;
  } catch {
    return raw;
  }
}

export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const journeyId = params.id;

  const [journey, setJourney] = useState<Journey | null>(null);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!journeyId) return;
    fetch(`/api/journeys/${journeyId}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setJourney)
      .catch((e) => setError(e.message || "Failed to load job journey."))
      .finally(() => setLoading(false));
  }, [journeyId]);

  async function deleteJourney() {
    if (!confirm("Remove this job journey? Past sessions are not affected.")) return;
    setDeleting(true);
    try {
      const r = await fetch(`/api/journeys/${journeyId}`, { method: "DELETE" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      router.push("/jobs");
    } catch (e: any) {
      setError(e.message || "Delete failed.");
      setDeleting(false);
    }
  }

  if (loading) {
    return <main className="min-h-screen p-8 text-subtle">Loading…</main>;
  }

  if (!journey) {
    return (
      <main className="min-h-screen p-8 max-w-3xl mx-auto space-y-4">
        <p className="text-err">{error || "Job journey not found."}</p>
        <a href="/jobs" className="text-sm text-accent hover:underline">
          ← Back to jobs
        </a>
      </main>
    );
  }

  return (
    <main className="min-h-screen px-6 py-10 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {journey.company_name || "—"} — {journey.job_title || "—"}
          </h1>
          <div className="text-sm text-subtle">
            Last updated {formatDate(journey.updated_at)}
          </div>
        </div>
        <div className="flex items-center gap-4 shrink-0">
          <a href="/jobs" className="text-sm text-accent hover:underline">
            ← Jobs
          </a>
          <button
            onClick={deleteJourney}
            disabled={deleting}
            className="text-sm text-err hover:underline disabled:opacity-50"
          >
            {deleting ? "Deleting…" : "Delete"}
          </button>
        </div>
      </div>

      {error && (
        <p className="text-sm text-err border border-err/40 rounded px-3 py-2">{error}</p>
      )}

      <Section title="Job info">
        <div className="text-sm space-y-1 rounded bg-panel/60 p-3 border border-subtle/20">
          <InfoRow label="Job title" value={journey.job_title} />
          <InfoRow label="Company" value={journey.company_name} />
          <InfoRow label="Location" value={journey.location} />
          <InfoRow
            label="URL"
            value={
              journey.job_url ? (
                <a
                  href={journey.job_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-accent hover:underline break-all"
                >
                  {journey.job_url}
                </a>
              ) : (
                "—"
              )
            }
          />
          <InfoRow label="Source" value={journey.job_source_type} />
          <InfoRow label="Job ad language" value={journey.job_ad_language} />
        </div>
      </Section>

      <TextBlock title="Job description" text={journey.job_description} />
      <TextBlock title="Company description" text={journey.company_description} />
      <TextBlock title="Alignment strategy" text={journey.alignment_strategy} />
      <TextBlock title="Inferred role context" text={journey.inferred_role_context} />
      <TextBlock title="Positioning strategy" text={journey.positioning_strategy} />
      <TextBlock title="Cover letter" text={journey.cover_letter} />
      <TextBlock title="Interview briefing" text={journey.interview_briefing} />
      <TextBlock
        title="Evaluation summary"
        text={journey.evaluation_summary ? formatEvaluation(journey.evaluation_summary) : ""}
      />
    </main>
  );
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex gap-2">
      <span className="text-subtle w-36 shrink-0">{label}</span>
      <span className="min-w-0">{value || "—"}</span>
    </div>
  );
}

function TextBlock({ title, text }: { title: string; text: string }) {
  if (!text) return null;
  return (
    <Section title={title}>
      <pre className="text-sm whitespace-pre-wrap leading-relaxed rounded bg-panel/60 p-3 border border-subtle/20 max-h-96 overflow-y-auto">
        {text}
      </pre>
    </Section>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="text-xs font-semibold uppercase tracking-widest text-subtle mb-2">
        {title}
      </h2>
      {children}
    </section>
  );
}
