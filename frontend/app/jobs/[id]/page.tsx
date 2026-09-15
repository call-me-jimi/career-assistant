"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

type Interview = {
  interview_id: string;
  interview_type: string;
  type_label: string;
  label: string;
  context: string;
  briefing: string;
  evaluation_summary: string;
  briefing_at: number | null;
  evaluation_at: number | null;
  created_at: number;
};

type Feedback = {
  feedback_id: string;
  interview_ids: string[];
  stage: string;
  outcome: string;
  source: string;
  feedback_text: string;
  created_at: number;
};

type CalibrationPair = {
  interview_id: string | null;
  assistant_said: {
    overall_score: number | null;
    decision: string;
    summary: string;
    weaknesses: string[];
    improvements: string[];
  };
  employer_said: string;
  stage: string;
  source: string;
  created_at: number;
};

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
  job_screenshot_path: string;
  job_source_type: string;
  alignment_strategy: string;
  inferred_role_context: string;
  positioning_strategy: string;
  cover_letter: string;
  interview_briefing: string;
  evaluation_summary: string;
  export_folder: string;
  cover_letter_at: number | null;
  interview_briefing_at: number | null;
  evaluation_summary_at: number | null;
  created_at: number;
  updated_at: number;
  interviews: Interview[];
  feedback: Feedback[];
  calibration: CalibrationPair[];
};

const STAGES: [string, string][] = [
  ["unknown", "Not sure"],
  ["application", "After applying"],
  ["screening", "After the screening call"],
  ["interview", "After an interview round"],
  ["final", "After the final round"],
  ["offer", "At offer stage"],
];

const OUTCOMES: [string, string][] = [
  ["rejected", "Rejected"],
  ["ghosted", "No response"],
  ["withdrawn", "I withdrew"],
  ["offer", "Offer"],
];

const SOURCES: [string, string][] = [
  ["", "Not sure who"],
  ["recruiter", "Recruiter"],
  ["hiring_manager", "Hiring manager"],
  ["ats", "Automated reply"],
  ["other", "Someone else"],
];

const EMPTY_DRAFT = {
  feedback_text: "",
  stage: "unknown",
  outcome: "rejected",
  source: "",
  interview_ids: [] as string[],
};

function labelOf(options: [string, string][], value: string) {
  return options.find(([v]) => v === value)?.[1] || value;
}

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

function describeRound(iv: Interview) {
  return iv.label ? `${iv.type_label} — ${iv.label}` : iv.type_label;
}

export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const journeyId = params.id;

  const [journey, setJourney] = useState<Journey | null>(null);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState(EMPTY_DRAFT);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    const r = await fetch(`/api/journeys/${journeyId}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    setJourney(await r.json());
  }, [journeyId]);

  useEffect(() => {
    if (!journeyId) return;
    load()
      .catch((e) => setError(e.message || "Failed to load job journey."))
      .finally(() => setLoading(false));
  }, [journeyId, load]);

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

  async function saveFeedback() {
    setSaving(true);
    setError(null);
    try {
      const r = await fetch(`/api/journeys/${journeyId}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => null);
        throw new Error(body?.detail || `HTTP ${r.status}`);
      }
      setDraft(EMPTY_DRAFT);
      setAdding(false);
      await load();
    } catch (e: any) {
      setError(e.message || "Could not save the feedback.");
    } finally {
      setSaving(false);
    }
  }

  async function removeFeedback(feedbackId: string) {
    if (!confirm("Remove this feedback entry?")) return;
    setError(null);
    try {
      const r = await fetch(`/api/journeys/${journeyId}/feedback/${feedbackId}`, {
        method: "DELETE",
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await load();
    } catch (e: any) {
      setError(e.message || "Delete failed.");
    }
  }

  function toggleRound(interviewId: string) {
    setDraft((d) => ({
      ...d,
      interview_ids: d.interview_ids.includes(interviewId)
        ? d.interview_ids.filter((i) => i !== interviewId)
        : [...d.interview_ids, interviewId],
    }));
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

  const rounds = journey.interviews;
  const roundById = new Map(rounds.map((iv) => [iv.interview_id, iv]));

  return (
    <main className="min-h-screen px-6 py-10 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {journey.company_name || "—"} — {journey.job_title || "—"}
          </h1>
          <div className="text-sm text-subtle">
            Started {formatDate(journey.created_at)} &middot; Last updated{" "}
            {formatDate(journey.updated_at)}
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
          <InfoRow label="Export folder" value={journey.export_folder} />
        </div>
      </Section>

      <Section title="Job page snapshot">
        {journey.job_screenshot_path ? (
          <a
            href={`/media/screenshots/${journey.job_screenshot_path}`}
            target="_blank"
            rel="noreferrer"
            className="block rounded border border-subtle/20 overflow-hidden hover:border-accent"
            title="Open full-size snapshot"
          >
            <img
              src={`/media/screenshots/${journey.job_screenshot_path}`}
              alt="Snapshot of the job posting as it appeared when captured"
              className="w-full max-h-96 object-cover object-top"
            />
          </a>
        ) : (
          <p className="text-sm text-subtle italic">
            No snapshot was captured for this job page.
          </p>
        )}
      </Section>

      <TextBlock
        title="Job ad"
        text={journey.job_description}
        emptyText="The job ad was not captured for this journey."
      />
      <TextBlock title="Company description" text={journey.company_description} />
      <TextBlock title="Alignment strategy" text={journey.alignment_strategy} />
      <TextBlock title="Inferred role context" text={journey.inferred_role_context} />
      <TextBlock title="Positioning strategy" text={journey.positioning_strategy} />
      <TextBlock
        title="Cover letter"
        text={journey.cover_letter}
        generatedAt={journey.cover_letter_at}
      />

      <Section title="Interview rounds">
        {rounds.length ? (
          <div className="space-y-2">
            {rounds.map((iv) => (
              <RoundCard key={iv.interview_id} iv={iv} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-subtle italic">
            No interview rounds have been prepared for this job yet.
          </p>
        )}
      </Section>

      {/* Pre-v0.9.0 journeys kept a single briefing and evaluation on the job itself.
          Once rounds exist they carry their own, so showing these too would duplicate. */}
      {rounds.length === 0 && (
        <>
          <TextBlock
            title="Interview briefing"
            text={journey.interview_briefing}
            generatedAt={journey.interview_briefing_at}
          />
          <TextBlock
            title="Evaluation summary"
            text={
              journey.evaluation_summary ? formatEvaluation(journey.evaluation_summary) : ""
            }
            generatedAt={journey.evaluation_summary_at}
          />
        </>
      )}

      <Section title="Feedback from the company">
        <div className="space-y-2">
          {journey.feedback.map((entry) => (
            <FeedbackEntry
              key={entry.feedback_id}
              entry={entry}
              rounds={entry.interview_ids
                .map((id) => roundById.get(id))
                .filter((iv): iv is Interview => Boolean(iv))}
              onRemove={() => removeFeedback(entry.feedback_id)}
            />
          ))}

          {journey.feedback.length === 0 && !adding && (
            <p className="text-sm text-subtle italic">
              Nothing recorded yet. If the company told you anything about why they decided
              the way they did, add it here — later applications learn from it.
            </p>
          )}

          {adding ? (
            <div className="rounded border border-accent/30 p-3 space-y-3">
              <textarea
                autoFocus
                value={draft.feedback_text}
                onChange={(e) => setDraft({ ...draft, feedback_text: e.target.value })}
                rows={4}
                placeholder="Paste what they said, in their words."
                className="w-full text-sm bg-transparent border border-accent/30 rounded px-2 py-1 focus:outline-none focus:border-accent resize-y"
              />

              <div className="grid gap-2 sm:grid-cols-3">
                <Picker
                  label="When"
                  options={STAGES}
                  value={draft.stage}
                  onChange={(v) => setDraft({ ...draft, stage: v })}
                />
                <Picker
                  label="Outcome"
                  options={OUTCOMES}
                  value={draft.outcome}
                  onChange={(v) => setDraft({ ...draft, outcome: v })}
                />
                <Picker
                  label="Who said it"
                  options={SOURCES}
                  value={draft.source}
                  onChange={(v) => setDraft({ ...draft, source: v })}
                />
              </div>

              {rounds.length > 0 && (
                <div className="space-y-1">
                  <div className="text-xs text-subtle">
                    Which rounds does this cover? Leave all unticked if it is about the
                    application as a whole — that is the usual case.
                  </div>
                  <div className="flex flex-wrap gap-x-4 gap-y-1">
                    {rounds.map((iv) => (
                      <label
                        key={iv.interview_id}
                        className="flex items-center gap-1.5 text-sm cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={draft.interview_ids.includes(iv.interview_id)}
                          onChange={() => toggleRound(iv.interview_id)}
                        />
                        {describeRound(iv)}
                      </label>
                    ))}
                  </div>
                </div>
              )}

              {!journey.profile_id && (
                <p className="text-xs text-subtle">
                  This job is not linked to a profile, so the feedback will be kept here but
                  will not inform future applications.
                </p>
              )}

              <div className="flex gap-2">
                <button
                  onClick={saveFeedback}
                  disabled={saving}
                  className="text-xs px-3 py-1 rounded bg-accent text-bg font-medium hover:opacity-90 disabled:opacity-50"
                >
                  {saving ? "Saving…" : "Save"}
                </button>
                <button
                  onClick={() => {
                    setAdding(false);
                    setDraft(EMPTY_DRAFT);
                  }}
                  disabled={saving}
                  className="text-xs px-3 py-1 rounded border border-subtle/40 hover:text-err disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <button
              onClick={() => setAdding(true)}
              className="text-xs px-3 py-1 rounded border border-subtle/40 hover:border-accent hover:text-accent"
            >
              Add feedback
            </button>
          )}
        </div>
      </Section>

      {journey.calibration.length > 0 && (
        <Section title="Assistant said / they said">
          <div className="space-y-2">
            {journey.calibration.map((pair, i) => (
              <CalibrationCard
                key={`${pair.interview_id || "job"}-${i}`}
                pair={pair}
                round={pair.interview_id ? roundById.get(pair.interview_id) : undefined}
              />
            ))}
          </div>
        </Section>
      )}
    </main>
  );
}

function RoundCard({ iv }: { iv: Interview }) {
  return (
    <div className="rounded bg-panel/60 p-3 border border-subtle/20 space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium">{describeRound(iv)}</span>
        <span className="text-xs text-subtle shrink-0">{formatDate(iv.created_at)}</span>
      </div>
      <div className="flex flex-wrap gap-x-4 text-xs text-subtle">
        <span>
          {iv.briefing ? `Briefing prepared ${formatDate(iv.briefing_at)}` : "No briefing yet"}
        </span>
        <span>
          {iv.evaluation_summary
            ? `Evaluated ${formatDate(iv.evaluation_at)}`
            : "Not evaluated yet"}
        </span>
      </div>
      {iv.briefing && <Collapsible title="Briefing" text={iv.briefing} />}
      {iv.evaluation_summary && (
        <Collapsible title="Evaluation" text={formatEvaluation(iv.evaluation_summary)} />
      )}
    </div>
  );
}

function FeedbackEntry({
  entry,
  rounds,
  onRemove,
}: {
  entry: Feedback;
  rounds: Interview[];
  onRemove: () => void;
}) {
  const meta = [
    labelOf(SOURCES, entry.source),
    labelOf(STAGES, entry.stage),
    labelOf(OUTCOMES, entry.outcome),
  ].filter(Boolean);

  return (
    <div className="rounded bg-panel/60 p-3 border border-subtle/20 space-y-1">
      <div className="flex items-baseline justify-between gap-3 text-xs text-subtle">
        <span>{meta.join(" · ")}</span>
        <div className="flex items-center gap-3 shrink-0">
          <span>{formatDate(entry.created_at)}</span>
          <button onClick={onRemove} className="text-err hover:underline">
            Remove
          </button>
        </div>
      </div>
      <div className="text-xs text-subtle">
        {rounds.length
          ? `About: ${rounds.map(describeRound).join(", ")}`
          : "About the application as a whole"}
      </div>
      {entry.feedback_text ? (
        <p className="text-sm whitespace-pre-wrap leading-relaxed">{entry.feedback_text}</p>
      ) : (
        <p className="text-sm text-subtle italic">No reason was given.</p>
      )}
    </div>
  );
}

function CalibrationCard({ pair, round }: { pair: CalibrationPair; round?: Interview }) {
  const said = pair.assistant_said;
  const verdict = [
    said.overall_score != null ? `${said.overall_score}/10` : "",
    said.decision,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="rounded border border-subtle/20 p-3 space-y-2">
      <div className="text-sm font-medium">
        {round ? describeRound(round) : "The application as a whole"}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <div className="text-xs uppercase tracking-widest text-subtle">
            The assistant said
          </div>
          {verdict && <div className="text-sm">{verdict}</div>}
          {said.weaknesses.length > 0 && (
            <ul className="text-sm list-disc pl-4 space-y-0.5">
              {said.weaknesses.map((w, i) => (
                <li key={i}>{String(w)}</li>
              ))}
            </ul>
          )}
        </div>
        <div className="space-y-1">
          <div className="text-xs uppercase tracking-widest text-subtle">They said</div>
          <p className="text-sm whitespace-pre-wrap leading-relaxed">{pair.employer_said}</p>
        </div>
      </div>
    </div>
  );
}

function Collapsible({ title, text }: { title: string; text: string }) {
  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-accent hover:underline">{title}</summary>
      <pre className="mt-2 text-sm whitespace-pre-wrap leading-relaxed rounded bg-panel/60 p-3 border border-subtle/20 max-h-96 overflow-y-auto">
        {text}
      </pre>
    </details>
  );
}

function Picker({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: [string, string][];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-xs text-subtle">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-panel2 border border-border rounded px-2 py-1 text-sm"
      >
        {options.map(([v, text]) => (
          <option key={v} value={v}>
            {text}
          </option>
        ))}
      </select>
    </label>
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

function TextBlock({
  title,
  text,
  generatedAt,
  emptyText,
}: {
  title: string;
  text: string;
  generatedAt?: number | null;
  emptyText?: string;
}) {
  if (!text && !emptyText) return null;
  return (
    <Section title={title}>
      {text && generatedAt && (
        <div className="text-xs text-subtle mb-1">Generated {formatDate(generatedAt)}</div>
      )}
      {text ? (
        <pre className="text-sm whitespace-pre-wrap leading-relaxed rounded bg-panel/60 p-3 border border-subtle/20 max-h-96 overflow-y-auto">
          {text}
        </pre>
      ) : (
        <p className="text-sm text-subtle italic">{emptyText}</p>
      )}
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
