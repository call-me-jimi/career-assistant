"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Brand from "../../../components/Brand";

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
  /* When the round happened. The page used to render `created_at` — the moment
     the tool made the row — which disagreed with the date shown on the tracker. */
  scheduled_at: number | null;
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

type JobEvent = {
  event_id: string;
  kind: string;
  occurred_at: number;
  text: string;
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
  applied_at: number | null;
  on_hold_at: number | null;
  rejected_at: number | null;
  dropped_at: number | null;
  offer_at: number | null;
  created_at: number;
  updated_at: number;
  status: string;
  waiting_days: number | null;
  interviews: Interview[];
  events: JobEvent[];
  feedback: Feedback[];
  calibration: CalibrationPair[];
};

type Profile = { profile_id: string; name: string };

const STATUS_META: Record<string, { label: string; pill: string }> = {
  draft: { label: "Not sent", pill: "text-subtle border-border" },
  applied: { label: "Applied", pill: "text-accent border-accent/40 bg-accent/10" },
  silent: { label: "No reply yet", pill: "text-subtle border-border" },
  in_progress: { label: "In Progress", pill: "text-warn border-warn/40 bg-warn/10" },
  on_hold: { label: "On hold", pill: "text-hold border-hold/40 bg-hold/10" },
  offer: { label: "Offer", pill: "text-ok border-ok/40 bg-ok/10" },
  rejected: { label: "Rejected", pill: "text-err border-err/35 bg-err/10" },
  dropped: { label: "Withdrawn", pill: "text-subtle border-border line-through" },
};

const SOURCES: [string, string][] = [
  ["", "Not sure who"],
  ["recruiter", "Recruiter"],
  ["hiring_manager", "Hiring manager"],
  ["ats", "Automated reply"],
  ["other", "Someone else"],
];

const OUTCOME_DATES: [keyof Journey, string, string][] = [
  ["on_hold_at", "Put on hold", "hold"],
  ["rejected_at", "Rejected", "err"],
  ["dropped_at", "Withdrawn", "subtle"],
  ["offer_at", "Offer", "ok"],
];

function formatDate(ts: number | null | undefined) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
  });
}

function toDateInput(ts: number) {
  const d = new Date(ts * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function fromDateInput(value: string): number | null {
  if (!value) return null;
  const [y, m, d] = value.split("-").map(Number);
  if (!y || !m || !d) return null;
  return new Date(y, m - 1, d, 12, 0, 0).getTime() / 1000;
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

function labelOf(options: [string, string][], value: string) {
  return options.find(([v]) => v === value)?.[1] || value;
}

/* ---------- the timeline ---------- */

type Entry = {
  at: number;
  tone: "accent" | "warn" | "err" | "ok" | "hold" | "subtle";
  title: React.ReactNode;
  detail?: React.ReactNode;
  quote?: string;
  attribution?: string;
};

/* Everything that happened to this application, in the order it happened. What an
   employer said sits on the day they said it, next to the outcome it explains —
   not in a section at the bottom of the page. */
function buildTimeline(journey: Journey): Entry[] {
  const entries: Entry[] = [];

  if (journey.applied_at) {
    entries.push({
      at: journey.applied_at,
      tone: "accent",
      title: <b>Applied</b>,
      detail: journey.cover_letter
        ? `Cover letter generated ${formatDate(journey.cover_letter_at)}.`
        : "No cover letter on file.",
    });
  }

  for (const iv of journey.interviews) {
    if (!iv.scheduled_at) continue;
    const bits = [
      iv.briefing ? `Briefing prepared ${formatDate(iv.briefing_at)}` : "No briefing",
      iv.evaluation_summary ? `Evaluated ${formatDate(iv.evaluation_at)}` : "Not evaluated",
    ];
    entries.push({
      at: iv.scheduled_at,
      tone: "warn",
      title: <b>{describeRound(iv)}</b>,
      detail: bits.join(" · "),
    });
  }

  for (const ev of journey.events) {
    entries.push({ at: ev.occurred_at, tone: "subtle", title: ev.text });
  }

  const roundById = new Map(journey.interviews.map((iv) => [iv.interview_id, iv]));
  for (const f of journey.feedback) {
    const covers = f.interview_ids
      .map((id) => roundById.get(id))
      .filter((iv): iv is Interview => Boolean(iv))
      .map(describeRound);
    entries.push({
      at: f.created_at,
      tone: "hold",
      title: (
        <>
          <b>They said why</b>
          {f.source && <span className="text-subtle"> — {labelOf(SOURCES, f.source)}</span>}
        </>
      ),
      quote: f.feedback_text,
      attribution: covers.length ? `About: ${covers.join(", ")}` : "About the application",
    });
  }

  for (const [field, label, tone] of OUTCOME_DATES) {
    const at = journey[field] as number | null;
    if (at) entries.push({ at, tone: tone as Entry["tone"], title: <b>{label}</b> });
  }

  return entries.sort((a, b) => a.at - b.at);
}

/* ---------- page ---------- */

export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const journeyId = params.id;

  const [journey, setJourney] = useState<Journey | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [tab, setTab] = useState<"timeline" | "artifacts" | "posting">("timeline");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const r = await fetch(`/api/journeys/${journeyId}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    setJourney(await r.json());
  }, [journeyId]);

  useEffect(() => {
    if (!journeyId) return;
    load()
      .catch((e) => setError(e.message || "Failed to load this application."))
      .finally(() => setLoading(false));
    fetch("/api/profiles")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setProfiles(d.profiles ?? []))
      .catch(() => {});
  }, [journeyId, load]);

  const timeline = useMemo(() => (journey ? buildTimeline(journey) : []), [journey]);

  async function post(path: string, body?: unknown) {
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.json();
    } catch {
      setError("That didn't work.");
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function logOutcome(kind: string) {
    if (await post(`/api/journeys/${journeyId}/outcome`, { kind })) await load();
  }

  async function duplicate() {
    const copy = await post(`/api/journeys/${journeyId}/duplicate`);
    if (copy) router.push(`/jobs/${copy.journey_id}`);
  }

  async function launch(assistantType: string) {
    const data = await post("/api/sessions", {
      assistant_type: assistantType,
      journey_id: journeyId,
    });
    if (data) window.location.href = `/session?id=${data.session_id}`;
  }

  async function remove() {
    if (!confirm("Remove this application and everything on it? Past sessions are not affected."))
      return;
    setBusy(true);
    try {
      const r = await fetch(`/api/journeys/${journeyId}`, { method: "DELETE" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      router.push("/jobs");
    } catch {
      setError("Could not remove it.");
      setBusy(false);
    }
  }

  if (loading) return <main className="min-h-screen p-8 text-subtle">Loading…</main>;

  if (!journey) {
    return (
      <main className="min-h-screen p-8 max-w-3xl mx-auto space-y-4">
        <p className="text-err">{error || "Application not found."}</p>
        <a href="/jobs" className="text-sm text-accent hover:underline">
          ← Back to applications
        </a>
      </main>
    );
  }

  const meta = STATUS_META[journey.status] ?? STATUS_META.draft;
  const profileName = profiles.find((p) => p.profile_id === journey.profile_id)?.name;
  const roundCount = journey.interviews.length;
  const artifactCount =
    (journey.cover_letter ? 1 : 0) +
    journey.interviews.filter((iv) => iv.briefing).length +
    journey.interviews.filter((iv) => iv.evaluation_summary).length;

  return (
    <main className="min-h-screen">
      <header className="h-14 px-6 flex items-center justify-between border-b border-border">
        <div className="flex items-center gap-4 min-w-0">
          <Brand />
          <span className="h-5 w-px bg-border shrink-0" />
          <a href="/jobs" className="text-sm text-subtle hover:text-accent shrink-0">
            Applications
          </a>
        </div>
        <button
          onClick={remove}
          disabled={busy}
          className="text-xs px-2.5 py-1 rounded border border-err/40 text-err hover:bg-err/10 disabled:opacity-50"
        >
          Delete
        </button>
      </header>

      <div className="max-w-4xl mx-auto px-6 py-8 space-y-6">
        <div className="space-y-3">
          <div className="flex items-start justify-between gap-6 flex-wrap">
            <div className="min-w-0">
              <h1 className="text-2xl font-semibold tracking-tight">
                {journey.company_name || "—"} — {journey.job_title || "—"}
              </h1>
              <div className="mt-1.5 flex items-center gap-2.5 flex-wrap text-sm text-subtle">
                {journey.location && <span>{journey.location}</span>}
                {journey.job_source_type && <span>· {journey.job_source_type}</span>}
                <span
                  className={`inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full border ${meta.pill}`}
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-current" />
                  {meta.label}
                </span>
                {profileName && (
                  <span className="text-xs px-2 py-0.5 rounded-full border border-hold/30 bg-hold/10 text-hold">
                    CV: {profileName}
                  </span>
                )}
                {journey.waiting_days !== null && (
                  <span className="text-xs">waiting {journey.waiting_days}d</span>
                )}
              </div>
            </div>

            <div className="flex gap-1.5 flex-wrap shrink-0">
              <Action onClick={() => launch("interview_prep")} disabled={busy}>
                Prep a round
              </Action>
              <Action onClick={() => launch("interview_evaluator")} disabled={busy}>
                Evaluate a round
              </Action>
              {!journey.on_hold_at && (
                <Action onClick={() => logOutcome("on_hold")} disabled={busy}>
                  On hold
                </Action>
              )}
              {!journey.dropped_at && (
                <Action onClick={() => logOutcome("withdrawn")} disabled={busy}>
                  Withdraw
                </Action>
              )}
              <Action onClick={duplicate} disabled={busy}>
                Apply again
              </Action>
            </div>
          </div>

          <div className="flex gap-6 border-b border-border">
            <Tab on={tab === "timeline"} onClick={() => setTab("timeline")}>
              Timeline
            </Tab>
            <Tab on={tab === "artifacts"} onClick={() => setTab("artifacts")} count={artifactCount}>
              Artifacts
            </Tab>
            <Tab on={tab === "posting"} onClick={() => setTab("posting")}>
              Posting
            </Tab>
          </div>
        </div>

        {error && (
          <p className="text-sm text-err border border-err/40 rounded px-3 py-2">{error}</p>
        )}

        {tab === "timeline" && (
          <Timeline
            journey={journey}
            entries={timeline}
            roundCount={roundCount}
            onChanged={load}
            onError={() => setError("That didn't work.")}
          />
        )}

        {tab === "artifacts" && <Artifacts journey={journey} />}

        {tab === "posting" && <Posting journey={journey} />}
      </div>
    </main>
  );
}

/* ---------- header bits ---------- */

function Action({
  children,
  onClick,
  disabled,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="text-xs px-2.5 py-1 rounded border border-border text-subtle hover:border-accent hover:text-accent disabled:opacity-50"
    >
      {children}
    </button>
  );
}

function Tab({
  children,
  on,
  onClick,
  count,
}: {
  children: React.ReactNode;
  on: boolean;
  onClick: () => void;
  count?: number;
}) {
  return (
    <button
      onClick={onClick}
      className={`text-sm pb-2.5 -mb-px border-b-2 ${
        on ? "text-text border-accent" : "text-subtle border-transparent hover:text-text"
      }`}
    >
      {children}
      {count !== undefined && count > 0 && (
        <span className="ml-1.5 text-[11px] text-subtle">{count}</span>
      )}
    </button>
  );
}

/* ---------- timeline ---------- */

const TONE_NODE: Record<Entry["tone"], string> = {
  accent: "bg-accent border-accent",
  warn: "bg-warn border-warn",
  err: "bg-err border-err",
  ok: "bg-ok border-ok",
  hold: "bg-hold border-hold",
  subtle: "bg-bg border-subtle",
};

function Timeline({
  journey,
  entries,
  roundCount,
  onChanged,
  onError,
}: {
  journey: Journey;
  entries: Entry[];
  roundCount: number;
  onChanged: () => Promise<void>;
  onError: () => void;
}) {
  const [adding, setAdding] = useState<"note" | "said" | null>(null);

  if (entries.length === 0 && !adding) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-subtle italic">
          Nothing has happened yet. Set a submission date on the applications table, or add what
          you know here.
        </p>
        <AddButtons onPick={setAdding} />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        {entries.map((e, i) => (
          <div key={i} className="grid grid-cols-[86px_20px_1fr] gap-3 items-start py-2">
            <div className="text-xs font-mono text-subtle text-right pt-1 tabular-nums">
              {formatDate(e.at)}
            </div>
            <div className="relative flex justify-center">
              {i < entries.length - 1 && (
                <span className="absolute top-3 -bottom-4 w-px bg-border" />
              )}
              <span
                className={`relative mt-1.5 w-2.5 h-2.5 rounded-full border-2 ${TONE_NODE[e.tone]}`}
              />
            </div>
            <div className="min-w-0">
              <div className="text-sm">{e.title}</div>
              {e.detail && <div className="text-xs text-subtle mt-0.5">{e.detail}</div>}
              {e.quote && (
                <blockquote className="mt-2 border-l-2 border-hold bg-panel rounded-r px-3 py-2 text-sm leading-relaxed whitespace-pre-wrap">
                  {e.quote}
                  {e.attribution && (
                    <span className="block mt-1.5 text-xs text-subtle">{e.attribution}</span>
                  )}
                </blockquote>
              )}
            </div>
          </div>
        ))}
      </div>

      {adding ? (
        <AddToTimeline
          journeyId={journey.journey_id}
          kind={adding}
          hasRounds={roundCount > 0}
          onDone={async () => {
            setAdding(null);
            await onChanged();
          }}
          onCancel={() => setAdding(null)}
          onError={onError}
        />
      ) : (
        <AddButtons onPick={setAdding} />
      )}
    </div>
  );
}

function AddButtons({ onPick }: { onPick: (kind: "note" | "said") => void }) {
  return (
    <div className="flex gap-2 pl-[106px]">
      <button
        onClick={() => onPick("note")}
        className="text-xs px-2.5 py-1 rounded border border-border text-subtle hover:border-accent hover:text-accent"
      >
        + Note
      </button>
      <button
        onClick={() => onPick("said")}
        className="text-xs px-2.5 py-1 rounded border border-border text-subtle hover:border-accent hover:text-accent"
      >
        + Something they said
      </button>
    </div>
  );
}

/* A round that was not recorded still belongs on the timeline, and a recruiter's
   aside mid-process is feedback with no outcome attached. */
function AddToTimeline({
  journeyId,
  kind,
  hasRounds,
  onDone,
  onCancel,
  onError,
}: {
  journeyId: string;
  kind: "note" | "said";
  hasRounds: boolean;
  onDone: () => Promise<void>;
  onCancel: () => void;
  onError: () => void;
}) {
  const [date, setDate] = useState(toDateInput(Date.now() / 1000));
  const [text, setText] = useState("");
  const [source, setSource] = useState("");
  const [saving, setSaving] = useState(false);

  async function save() {
    if (!text.trim()) return;
    setSaving(true);
    const [path, body] =
      kind === "note"
        ? [
            `/api/journeys/${journeyId}/events`,
            { occurred_at: fromDateInput(date), text: text.trim() },
          ]
        : [
            `/api/journeys/${journeyId}/feedback`,
            {
              feedback_text: text.trim(),
              source,
              stage: hasRounds ? "interview" : "application",
            },
          ];
    try {
      const r = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await onDone();
    } catch {
      onError();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="ml-[106px] rounded border border-accent/40 bg-panel p-3 space-y-2.5">
      <div className="flex gap-2 flex-wrap items-end">
        {kind === "note" && (
          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-widest text-subtle">When</span>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="bg-bg border border-border rounded px-2 py-1 text-xs"
            />
          </label>
        )}
        {kind === "said" && (
          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-widest text-subtle">Who</span>
            <select
              value={source}
              onChange={(e) => setSource(e.target.value)}
              className="bg-bg border border-border rounded px-2 py-1 text-xs"
            >
              {SOURCES.map(([v, label]) => (
                <option key={v} value={v}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <textarea
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={kind === "said" ? 3 : 2}
        placeholder={
          kind === "note"
            ? "What happened — a call, a round you didn't record, a message you sent."
            : "Paste their words. Don't paraphrase — this is what later applications learn from."
        }
        className="w-full text-sm bg-bg border border-border rounded px-2 py-1.5 resize-y leading-relaxed"
      />

      <div className="flex gap-2">
        <button
          onClick={save}
          disabled={saving || !text.trim()}
          className="text-xs px-3 py-1 rounded border border-accent text-accent bg-accent/10 hover:bg-accent/20 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        <button
          onClick={onCancel}
          disabled={saving}
          className="text-xs px-3 py-1 rounded border border-border text-subtle hover:text-err disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

/* ---------- artifacts ---------- */

function Artifacts({ journey }: { journey: Journey }) {
  const hasRounds = journey.interviews.length > 0;

  return (
    <div className="space-y-3">
      <ArtifactBlock
        title="Cover letter"
        at={journey.cover_letter_at}
        text={journey.cover_letter}
      />

      {journey.interviews.map((iv) => (
        <div key={iv.interview_id} className="space-y-3">
          {iv.briefing && (
            <ArtifactBlock
              title={`Briefing — ${describeRound(iv)}`}
              at={iv.briefing_at}
              text={iv.briefing}
            />
          )}
          {iv.evaluation_summary && (
            <ArtifactBlock
              title={`Evaluation — ${describeRound(iv)}`}
              at={iv.evaluation_at}
              text={formatEvaluation(iv.evaluation_summary)}
            />
          )}
        </div>
      ))}

      {/* Pre-v0.9.0 applications kept one briefing and evaluation on the job itself. */}
      {!hasRounds && (
        <>
          <ArtifactBlock
            title="Interview briefing"
            at={journey.interview_briefing_at}
            text={journey.interview_briefing}
          />
          <ArtifactBlock
            title="Evaluation"
            at={journey.evaluation_summary_at}
            text={
              journey.evaluation_summary ? formatEvaluation(journey.evaluation_summary) : ""
            }
          />
        </>
      )}

      {journey.calibration.length > 0 && (
        <section className="pt-3 space-y-2">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-subtle">
            The assistant said / they said
          </h2>
          {journey.calibration.map((pair, i) => (
            <CalibrationCard key={i} pair={pair} />
          ))}
        </section>
      )}

      {!journey.cover_letter && !hasRounds && !journey.interview_briefing && (
        <p className="text-sm text-subtle italic">
          Nothing generated for this application yet.
        </p>
      )}
    </div>
  );
}

function ArtifactBlock({
  title,
  at,
  text,
}: {
  title: string;
  at: number | null;
  text: string;
}) {
  if (!text) return null;
  return (
    <details className="rounded border border-border bg-panel/60">
      <summary className="cursor-pointer px-3 py-2 text-sm flex items-baseline justify-between gap-3">
        <span className="font-medium">{title}</span>
        <span className="text-xs text-subtle shrink-0">{formatDate(at)}</span>
      </summary>
      <pre className="px-3 pb-3 text-sm whitespace-pre-wrap leading-relaxed max-h-96 overflow-y-auto">
        {text}
      </pre>
    </details>
  );
}

function CalibrationCard({ pair }: { pair: CalibrationPair }) {
  const said = pair.assistant_said;
  const verdict = [
    said.overall_score != null ? `${said.overall_score}/10` : "",
    said.decision,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="rounded border border-border p-3 grid gap-3 sm:grid-cols-2">
      <div className="space-y-1">
        <div className="text-[10px] uppercase tracking-widest text-subtle">
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
        <div className="text-[10px] uppercase tracking-widest text-subtle">They said</div>
        <p className="text-sm whitespace-pre-wrap leading-relaxed">{pair.employer_said}</p>
      </div>
    </div>
  );
}

/* ---------- posting ---------- */

function Posting({ journey }: { journey: Journey }) {
  return (
    <div className="space-y-4">
      <div className="text-sm space-y-1 rounded bg-panel/60 p-3 border border-border">
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
              ""
            )
          }
        />
        <InfoRow label="Source" value={journey.job_source_type} />
        <InfoRow label="Job ad language" value={journey.job_ad_language} />
        <InfoRow label="Export folder" value={journey.export_folder} />
      </div>

      {journey.job_screenshot_path && (
        <a
          href={`/media/screenshots/${journey.job_screenshot_path}`}
          target="_blank"
          rel="noreferrer"
          className="block rounded border border-border overflow-hidden hover:border-accent"
          title="Open full-size snapshot"
        >
          <img
            src={`/media/screenshots/${journey.job_screenshot_path}`}
            alt="The job posting as it appeared when captured"
            className="w-full max-h-96 object-cover object-top"
          />
        </a>
      )}

      <ArtifactBlock title="Job ad" at={null} text={journey.job_description} />
      <ArtifactBlock title="Company description" at={null} text={journey.company_description} />
      <ArtifactBlock title="Alignment strategy" at={null} text={journey.alignment_strategy} />
      <ArtifactBlock title="Inferred role context" at={null} text={journey.inferred_role_context} />
      <ArtifactBlock title="Positioning strategy" at={null} text={journey.positioning_strategy} />
    </div>
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
