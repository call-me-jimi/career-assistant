"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Brand from "../../components/Brand";

type Interview = {
  interview_id: string;
  interview_type: string;
  type_label: string;
  label: string;
  briefing: string;
  evaluation_summary: string;
  scheduled_at: number | null;
  created_at: number;
};

type JobEvent = {
  event_id: string;
  kind: string;
  occurred_at: number;
  text: string;
};

type Journey = {
  journey_id: string;
  profile_id: string | null;
  job_url: string;
  job_title: string;
  company_name: string;
  location: string;
  cover_letter: string;
  interview_briefing: string;
  evaluation_summary: string;
  notes: string;
  next_step: string;
  applied_at: number | null;
  on_hold_at: number | null;
  rejected_at: number | null;
  dropped_at: number | null;
  offer_at: number | null;
  next_step_at: number | null;
  updated_at: number;
  status: string;
  interviews: Interview[];
  events: JobEvent[];
};

type InterviewType = { slug: string; label: string; hint: string };

/* Status is derived server-side by derive_status(); the UI only renders it. */
const STATUS_META: Record<string, { label: string; pill: string }> = {
  draft: { label: "Not sent", pill: "text-subtle border-border" },
  applied: { label: "Applied", pill: "text-accent border-accent/40 bg-accent/10" },
  in_progress: { label: "In Progress", pill: "text-warn border-warn/40 bg-warn/10" },
  on_hold: { label: "On hold", pill: "text-hold border-hold/40 bg-hold/10" },
  offer: { label: "Offer", pill: "text-ok border-ok/40 bg-ok/10" },
  rejected: { label: "Rejected", pill: "text-err border-err/35 bg-err/10" },
  dropped: { label: "Dropped out", pill: "text-subtle border-border line-through" },
};
const STATUS_ORDER = Object.keys(STATUS_META);

/* The four outcome dates, in the order the status ladder consults them. */
const OUTCOME_FIELDS: [keyof Journey, string][] = [
  ["on_hold_at", "On hold"],
  ["rejected_at", "Rejection"],
  ["dropped_at", "Dropped out"],
  ["offer_at", "Offer"],
];

/* What the row menu can log. `kind` goes straight to POST /outcome, which picks
   the date column — the UI never names a column, so the two can't disagree. */
type OutcomeKind = "rejected" | "offer" | "on_hold" | "withdrawn";

const OUTCOME_META: Record<
  OutcomeKind,
  { menu: string; dateLabel: string; ask: string; asksWho: boolean }
> = {
  rejected: {
    menu: "Log a rejection",
    dateLabel: "Rejected on",
    ask: "Did they say why?",
    asksWho: true,
  },
  offer: {
    menu: "Log an offer",
    dateLabel: "Offer made on",
    ask: "Anything they said worth keeping?",
    asksWho: true,
  },
  on_hold: {
    menu: "Put on hold",
    dateLabel: "On hold since",
    ask: "Did they say why?",
    asksWho: true,
  },
  withdrawn: {
    menu: "Withdraw",
    dateLabel: "Withdrew on",
    ask: "Why did you withdraw?",
    asksWho: false,
  },
};

const OUTCOME_ORDER: OutcomeKind[] = ["rejected", "offer", "on_hold", "withdrawn"];

const SOURCES: [string, string][] = [
  ["", "Not sure who"],
  ["recruiter", "Recruiter"],
  ["hiring_manager", "Hiring manager"],
  ["ats", "Automated reply"],
  ["other", "Someone else"],
];

type RowPanel = { kind: "outcome"; outcome: OutcomeKind } | { kind: "schedule" } | null;

/* Progress strip: ten interview columns collapse into six aligned slots. */
const SLOT_LABELS = ["Applied", "Screening", "Manager", "Deep dive", "Final", "Decision"];
const SLOT_OF: Record<string, number> = {
  recruiter: 1,
  screening: 1,
  hiring_manager: 2,
  technical: 3,
  case_study: 3,
  panel: 3,
  team_peer: 3,
  mixed: 3,
  other: 3,
  leadership: 4,
  final: 4,
};
const SEG_END: Record<string, string> = {
  rejected: "bg-err border-err",
  offer: "bg-ok border-ok",
  on_hold: "bg-hold border-hold",
  dropped: "bg-subtle border-subtle",
};

/* ---------- dates ---------- */

function formatDate(ts: number | null | undefined) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleDateString(undefined, {
    year: "2-digit",
    month: "short",
    day: "2-digit",
  });
}

function toDateInput(ts: number | null | undefined) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/* Noon local, so a timezone offset can never shift the day. */
function fromDateInput(value: string): number | null {
  if (!value) return null;
  const [y, m, d] = value.split("-").map(Number);
  if (!y || !m || !d) return null;
  return new Date(y, m - 1, d, 12, 0, 0).getTime() / 1000;
}

/* Why the pill reads what it reads. Presentation only — the status itself
   comes from the backend, this just names the date it read. */
function explain(j: Journey): string {
  const dated = j.interviews.filter((iv) => iv.scheduled_at);
  switch (j.status) {
    case "rejected":
      return `Rejection date ${formatDate(j.rejected_at)} is set. Terminal — clear it to reopen.`;
    case "offer":
      return `Offer date ${formatDate(j.offer_at)} is set.`;
    case "dropped":
      return `Dropped-out date ${formatDate(j.dropped_at)} is set.`;
    case "on_hold":
      return `On-hold date ${formatDate(j.on_hold_at)} is set, and no interview is dated after it.`;
    case "in_progress":
      return (
        (j.on_hold_at ? `On hold ${formatDate(j.on_hold_at)}, lifted by a later round. ` : "") +
        `${dated.length} interview date${dated.length === 1 ? "" : "s"} set. ` +
        "No rejection, hold or drop-out."
      );
    case "applied":
      return `Submission date ${formatDate(j.applied_at)} is set and nothing else.`;
    default:
      return "No submission date yet.";
  }
}

/* ---------- page ---------- */

export default function JobsPage() {
  const [journeys, setJourneys] = useState<Journey[]>([]);
  const [types, setTypes] = useState<InterviewType[]>([]);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetch("/api/journeys").then((r) => r.json()),
      fetch("/api/interview-types").then((r) => r.json()),
    ])
      .then(([j, t]) => {
        setJourneys(j.journeys);
        setTypes(t.types);
      })
      .catch(() => setError("Could not load applications."))
      .finally(() => setLoading(false));
  }, []);

  const splice = useCallback((updated: Journey) => {
    setJourneys((prev) =>
      prev.map((j) => (j.journey_id === updated.journey_id ? { ...j, ...updated } : j))
    );
  }, []);

  const refresh = useCallback(
    async (journeyId: string) => {
      const r = await fetch(`/api/journeys/${journeyId}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      splice(await r.json());
    },
    [splice]
  );

  /* Returns whether it worked, so a panel knows whether to close itself. */
  const call = useCallback(async (fn: () => Promise<void>) => {
    setError(null);
    try {
      await fn();
      return true;
    } catch {
      setError("Could not save that change.");
      return false;
    }
  }, []);

  const patchJourney = useCallback(
    (journeyId: string, body: Record<string, unknown>) =>
      call(async () => {
        const r = await fetch(`/api/journeys/${journeyId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        splice(await r.json());
      }),
    [call, splice]
  );

  /* The date and what they said in one call — see POST /journeys/{id}/outcome.
     The response is the journey with its status already recomputed. */
  const logOutcome = useCallback(
    (journeyId: string, body: Record<string, unknown>) =>
      call(async () => {
        const r = await fetch(`/api/journeys/${journeyId}/outcome`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        splice(await r.json());
      }),
    [call, splice]
  );

  const scheduleRound = useCallback(
    (journeyId: string, body: Record<string, unknown>) =>
      call(async () => {
        const r = await fetch(`/api/journeys/${journeyId}/interviews`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        await refresh(journeyId);
      }),
    [call, refresh]
  );

  async function addApplication() {
    setError(null);
    try {
      const r = await fetch("/api/journeys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_title: "", company_name: "" }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const created: Journey = await r.json();
      setJourneys((prev) => [created, ...prev]);
      setOpen((prev) => new Set(prev).add(created.journey_id));
      setQuery("");
      setStatus("all");
    } catch {
      setError("Could not add an application.");
    }
  }

  async function deleteJourney(journeyId: string) {
    if (!confirm("Remove this application? Past sessions are not affected.")) return;
    setError(null);
    try {
      const r = await fetch(`/api/journeys/${journeyId}`, { method: "DELETE" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setJourneys((prev) => prev.filter((j) => j.journey_id !== journeyId));
    } catch {
      setError("Could not remove the application.");
    }
  }

  function toggle(journeyId: string) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(journeyId)) next.delete(journeyId);
      else next.add(journeyId);
      return next;
    });
  }

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return journeys.filter((j) => {
      if (status !== "all" && j.status !== status) return false;
      if (!q) return true;
      return `${j.job_title} ${j.company_name} ${j.location} ${j.notes}`
        .toLowerCase()
        .includes(q);
    });
  }, [journeys, query, status]);

  const stats = useMemo(() => {
    const dated = (j: Journey) => j.interviews.filter((iv) => iv.scheduled_at);
    return {
      applied: journeys.filter((j) => j.applied_at).length,
      interviewed: journeys.filter((j) => dated(j).length > 0).length,
      late: journeys.filter((j) =>
        dated(j).some((iv) => (SLOT_OF[iv.interview_type] ?? 3) >= 3)
      ).length,
      offers: journeys.filter((j) => j.offer_at).length,
      live: journeys.filter((j) =>
        ["draft", "applied", "in_progress", "on_hold"].includes(j.status)
      ).length,
    };
  }, [journeys]);

  return (
    <main className="min-h-screen">
      <header className="h-14 px-6 flex items-center justify-between border-b border-border">
        <div className="flex items-center gap-4">
          <Brand />
          <span className="h-5 w-px bg-border" />
          <div className="font-semibold">Jobs</div>
        </div>
        <span className="text-sm text-subtle">
          {shown.length} of {journeys.length} &middot; {stats.live} live
        </span>
      </header>

      <div className="max-w-[1400px] mx-auto p-6 space-y-5">
        <p className="text-sm text-subtle max-w-2xl">
          Every application, with the dates that drive it. Status is not something you set — it
          follows from the dates below, so it can never disagree with them.
        </p>

        <Funnel stats={stats} />

        {error && (
          <p className="text-sm text-err border border-err/40 rounded px-3 py-2">{error}</p>
        )}

        <div className="flex items-center gap-2 flex-wrap">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search title, company or notes…"
            className="flex-1 min-w-[180px] bg-panel2 border border-border rounded px-2 py-1 text-sm"
          />
          <div className="flex gap-1 flex-wrap">
            {["all", ...STATUS_ORDER].map((key) => (
              <button
                key={key}
                onClick={() => setStatus(key)}
                aria-pressed={status === key}
                className={`text-xs px-2.5 py-1 rounded-full border ${
                  status === key
                    ? "border-accent text-accent bg-accent/10"
                    : "border-border text-subtle hover:text-text"
                }`}
              >
                {key === "all" ? "All" : STATUS_META[key].label}
              </button>
            ))}
          </div>
          <button
            onClick={addApplication}
            className="text-xs px-3 py-1.5 rounded border border-accent text-accent bg-accent/10 hover:bg-accent/20"
          >
            + Application
          </button>
        </div>

        {loading && <p className="text-sm text-subtle">Loading…</p>}

        {!loading && journeys.length === 0 && (
          <p className="text-sm text-subtle">
            No applications yet. Run an assistant on a job, or add one by hand.
          </p>
        )}

        {!loading && journeys.length > 0 && shown.length === 0 && (
          <p className="text-sm text-subtle">No applications match.</p>
        )}

        {shown.length > 0 && (
          <div className="overflow-x-auto border border-border rounded-xl">
            <table className="w-full min-w-[1180px] border-collapse">
              <thead>
                <tr className="bg-panel">
                  {[
                    "Title",
                    "Company",
                    "Location",
                    "Status",
                    "Progress",
                    "Submission",
                    "Outcome",
                    "Next step",
                    "Artifacts",
                    "",
                  ].map((h, i) => (
                    <th
                      key={h || `sp${i}`}
                      className={`text-left text-[10px] uppercase tracking-widest text-subtle font-semibold px-3 py-2 border-b border-border whitespace-nowrap ${
                        i === 0 ? "sticky left-0 bg-panel z-20" : ""
                      }`}
                    >
                      {h === "Status" ? (
                        <>
                          Status <span className="text-accent tracking-normal">ƒ(dates)</span>
                        </>
                      ) : (
                        h
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {shown.map((j) => (
                  <Row
                    key={j.journey_id}
                    journey={j}
                    types={types}
                    isOpen={open.has(j.journey_id)}
                    onToggle={() => toggle(j.journey_id)}
                    onPatch={(body) => patchJourney(j.journey_id, body)}
                    onRefresh={() => call(() => refresh(j.journey_id))}
                    onDelete={() => deleteJourney(j.journey_id)}
                    onOutcome={(body) => logOutcome(j.journey_id, body)}
                    onSchedule={(body) => scheduleRound(j.journey_id, body)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
}

/* ---------- the funnel ---------- */

function Funnel({
  stats,
}: {
  stats: { applied: number; interviewed: number; late: number; offers: number };
}) {
  const steps: [string, number, string][] = [
    ["Applied", stats.applied, "submission date set"],
    ["Interviewed", stats.interviewed, "at least one dated round"],
    ["Late rounds", stats.late, "technical, case or final"],
    ["Offers", stats.offers, "offer date set"],
  ];
  const top = stats.applied || 1;

  return (
    <div className="flex gap-0.5 flex-wrap">
      {steps.map(([label, value, hint], i) => (
        <div
          key={label}
          className="flex-1 min-w-[130px] relative overflow-hidden bg-panel border border-border rounded px-4 py-3"
        >
          <div className="text-[10px] uppercase tracking-widest text-subtle">{label}</div>
          <div className="text-2xl font-semibold tabular-nums leading-none mt-1">{value}</div>
          <div className="text-xs text-subtle mt-1">{hint}</div>
          <span
            className={`absolute bottom-0 left-0 h-[3px] origin-left ${
              i === steps.length - 1 ? "bg-subtle" : "bg-accent"
            }`}
            style={{ width: `${Math.max((value / top) * 100, 1.5)}%` }}
          />
        </div>
      ))}
    </div>
  );
}

/* ---------- a row ---------- */

function Row({
  journey,
  types,
  isOpen,
  onToggle,
  onPatch,
  onRefresh,
  onDelete,
  onOutcome,
  onSchedule,
}: {
  journey: Journey;
  types: InterviewType[];
  isOpen: boolean;
  onToggle: () => void;
  onPatch: (body: Record<string, unknown>) => void;
  onRefresh: () => void;
  onDelete: () => void;
  onOutcome: (body: Record<string, unknown>) => Promise<boolean>;
  onSchedule: (body: Record<string, unknown>) => Promise<boolean>;
}) {
  const meta = STATUS_META[journey.status] ?? STATUS_META.draft;
  const outcome = OUTCOME_FIELDS.find(([field]) => journey[field]);
  const cellPad = "px-3 py-2 border-b border-border align-middle";
  const [panel, setPanel] = useState<RowPanel>(null);

  return (
    <>
      <tr className="group hover:bg-panel2/40">
        <td className={`${cellPad} sticky left-0 bg-bg group-hover:bg-panel2 z-10 border-r border-border`}>
          <div className="flex items-center gap-1.5 w-[250px]">
            <button
              onClick={onToggle}
              aria-expanded={isOpen}
              aria-label={isOpen ? "Collapse" : "Expand"}
              className={`shrink-0 text-[10px] text-subtle hover:text-accent transition-transform ${
                isOpen ? "rotate-90 text-accent" : ""
              }`}
            >
              ▶
            </button>
            <EditableText
              value={journey.job_title}
              placeholder="Job title"
              empty="Untitled role"
              onSave={(v) => onPatch({ job_title: v })}
            />
          </div>
        </td>
        <td className={cellPad}>
          <div className="w-[170px]">
            <EditableText
              value={journey.company_name}
              placeholder="Company"
              onSave={(v) => onPatch({ company_name: v })}
            />
          </div>
        </td>
        <td className={cellPad}>
          <div className="w-[120px]">
            <EditableText
              value={journey.location}
              placeholder="Location"
              className="text-subtle"
              onSave={(v) => onPatch({ location: v })}
            />
          </div>
        </td>
        <td className={cellPad}>
          <span
            title={explain(journey)}
            className={`inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full border cursor-help whitespace-nowrap ${meta.pill}`}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-current" />
            {meta.label}
          </span>
        </td>
        <td className={cellPad}>
          <Strip journey={journey} />
        </td>
        <td className={cellPad}>
          <DateCell value={journey.applied_at} onSave={(v) => onPatch({ applied_at: v })} />
        </td>
        <td className={cellPad}>
          {outcome ? (
            <span className="text-xs whitespace-nowrap tabular-nums" title="Change it in the row's Dates pane">
              <span className="block text-[9px] uppercase tracking-widest text-subtle">
                {outcome[1]}
              </span>
              {formatDate(journey[outcome[0]] as number)}
            </span>
          ) : (
            <button onClick={onToggle} className="text-xs text-subtle hover:text-accent">
              — open —
            </button>
          )}
        </td>
        <td className={cellPad}>
          <div className="flex flex-col">
            {journey.next_step_at && (
              <EditableText
                value={journey.next_step}
                placeholder="What's next"
                empty="Follow up"
                className="text-[9px] uppercase tracking-widest text-subtle"
                onSave={(v) => onPatch({ next_step: v })}
              />
            )}
            <DateCell
              value={journey.next_step_at}
              onSave={(v) => onPatch({ next_step_at: v })}
            />
          </div>
        </td>
        <td className={cellPad}>
          <div className="flex gap-1">
            <Chip on={!!journey.cover_letter} code="CL" name="Cover letter" id={journey.journey_id} />
            <Chip
              on={journey.interviews.some((iv) => iv.briefing) || !!journey.interview_briefing}
              code="BR"
              name="Briefing"
              id={journey.journey_id}
            />
            <Chip
              on={
                journey.interviews.some((iv) => iv.evaluation_summary) ||
                !!journey.evaluation_summary
              }
              code="EV"
              name="Evaluation"
              id={journey.journey_id}
            />
          </div>
        </td>
        <td className={cellPad}>
          <RowMenu
            journey={journey}
            onPick={setPanel}
            onOpenDetail={onToggle}
            onDelete={onDelete}
          />
        </td>
      </tr>

      {panel && (
        <tr>
          <td colSpan={10} className="bg-panel border-b border-border p-0">
            {panel.kind === "outcome" ? (
              <OutcomePanel
                journey={journey}
                outcome={panel.outcome}
                onSave={onOutcome}
                onClose={() => setPanel(null)}
              />
            ) : (
              <SchedulePanel
                journey={journey}
                types={types}
                onSave={onSchedule}
                onClose={() => setPanel(null)}
              />
            )}
          </td>
        </tr>
      )}

      {isOpen && (
        <tr>
          <td colSpan={10} className="bg-panel border-b border-border p-0">
            <Drawer
              journey={journey}
              types={types}
              onPatch={onPatch}
              onRefresh={onRefresh}
            />
          </td>
        </tr>
      )}
    </>
  );
}

/* ---------- row menu ---------- */

/* Fixed-positioned rather than absolute: the table scrolls horizontally, and an
   absolutely-positioned menu is clipped by that overflow container. */
function RowMenu({
  journey,
  onPick,
  onOpenDetail,
  onDelete,
}: {
  journey: Journey;
  onPick: (panel: RowPanel) => void;
  onOpenDetail: () => void;
  onDelete: () => void;
}) {
  const [at, setAt] = useState<{ top: number; right: number } | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!at) return;
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setAt(null);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setAt(null);
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [at]);

  function open(e: React.MouseEvent<HTMLButtonElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    setAt({ top: r.bottom + 4, right: window.innerWidth - r.right });
  }

  function pick(panel: RowPanel) {
    setAt(null);
    onPick(panel);
  }

  return (
    <>
      <button
        onClick={open}
        aria-haspopup="menu"
        aria-expanded={!!at}
        aria-label="Actions"
        className={`text-xs px-1.5 rounded text-subtle hover:text-accent ${
          at ? "text-accent" : "opacity-0 group-hover:opacity-100 focus:opacity-100"
        }`}
      >
        ⋯
      </button>

      {at && (
        <div
          ref={ref}
          role="menu"
          style={{ position: "fixed", top: at.top, right: at.right }}
          className="z-50 w-56 rounded-lg border border-border bg-panel2 p-1 shadow-xl"
        >
          <div className="px-2.5 pt-2 pb-1 text-[9px] uppercase tracking-widest text-subtle">
            Just for the record
          </div>
          <MenuItem onClick={() => pick({ kind: "schedule" })}>
            Schedule an interview
          </MenuItem>
          {OUTCOME_ORDER.map((kind) => (
            <MenuItem key={kind} onClick={() => pick({ kind: "outcome", outcome: kind })}>
              {OUTCOME_META[kind].menu}
            </MenuItem>
          ))}

          <div className="my-1 h-px bg-border" />
          <MenuItem onClick={onOpenDetail}>Dates &amp; notes</MenuItem>
          <MenuItem href={`/jobs/${journey.journey_id}`}>Open full detail</MenuItem>
          <MenuItem danger onClick={onDelete}>
            Delete from record
          </MenuItem>
        </div>
      )}
    </>
  );
}

function MenuItem({
  children,
  onClick,
  href,
  danger,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  href?: string;
  danger?: boolean;
}) {
  const cls = `block w-full text-left px-2.5 py-1.5 rounded text-sm ${
    danger ? "text-err hover:bg-err/10" : "hover:bg-accent/15 hover:text-accent"
  }`;
  return href ? (
    <a role="menuitem" href={href} className={cls}>
      {children}
    </a>
  ) : (
    <button role="menuitem" onClick={onClick} className={cls}>
      {children}
    </button>
  );
}

/* ---------- capture panels ---------- */

/* The date and the reason in one panel. They are one call on the server too —
   the feedback row reads its outcome from the date this same request writes, so
   capturing half of it would record a rejection as an open application. */
function OutcomePanel({
  journey,
  outcome,
  onSave,
  onClose,
}: {
  journey: Journey;
  outcome: OutcomeKind;
  onSave: (body: Record<string, unknown>) => Promise<boolean>;
  onClose: () => void;
}) {
  const meta = OUTCOME_META[outcome];
  const [date, setDate] = useState(toDateInput(Date.now() / 1000));
  const [source, setSource] = useState("");
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);

  async function save(withText: boolean) {
    setSaving(true);
    const ok = await onSave({
      kind: outcome,
      date: fromDateInput(date),
      feedback_text: withText ? text : "",
      source: withText && meta.asksWho ? source : "",
    });
    setSaving(false);
    if (ok) onClose();
  }

  return (
    <div className="p-4 space-y-3 border-l-2 border-accent">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-semibold">
          {journey.company_name || "This application"}{" "}
          <span className="font-normal text-subtle">— {meta.menu.toLowerCase()}</span>
        </span>
        <span className="text-[10px] uppercase tracking-widest text-subtle">
          {journey.interviews.length} round{journey.interviews.length === 1 ? "" : "s"}
        </span>
      </div>

      <div className="flex flex-wrap gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-widest text-subtle">
            {meta.dateLabel}
          </span>
          <input
            type="date"
            autoFocus
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="bg-bg border border-accent rounded px-2 py-1 text-xs"
          />
        </label>

        {meta.asksWho && (
          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-widest text-subtle">
              Who told you
            </span>
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

      <label className="block space-y-1">
        <span className="text-[10px] uppercase tracking-widest text-subtle">{meta.ask}</span>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
          placeholder="Paste their words — don't paraphrase. This is what later applications learn from."
          className="w-full text-sm bg-bg border border-border rounded px-2 py-1.5 resize-y leading-relaxed"
        />
      </label>

      {!journey.profile_id && text.trim() && (
        <p className="text-xs text-subtle">
          This job is not linked to a profile, so what they said will be kept here but will not
          inform future applications.
        </p>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={() => save(true)}
          disabled={saving || !date}
          className="text-xs px-3 py-1.5 rounded border border-accent text-accent bg-accent/10 hover:bg-accent/20 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        <button
          onClick={() => save(false)}
          disabled={saving || !date}
          className="text-xs px-3 py-1.5 rounded border border-border text-subtle hover:text-text disabled:opacity-50"
        >
          {outcome === "withdrawn" ? "No reason" : "They gave no reason"}
        </button>
        <button
          onClick={onClose}
          disabled={saving}
          className="text-xs px-3 py-1.5 rounded border border-border text-subtle hover:text-err disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function SchedulePanel({
  journey,
  types,
  onSave,
  onClose,
}: {
  journey: Journey;
  types: InterviewType[];
  onSave: (body: Record<string, unknown>) => Promise<boolean>;
  onClose: () => void;
}) {
  const [type, setType] = useState("screening");
  const [date, setDate] = useState(toDateInput(Date.now() / 1000));
  const [label, setLabel] = useState("");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    const ok = await onSave({
      interview_type: type,
      scheduled_at: fromDateInput(date),
      label: label.trim(),
    });
    setSaving(false);
    if (ok) onClose();
  }

  return (
    <div className="p-4 space-y-3 border-l-2 border-accent">
      <div className="text-sm font-semibold">
        {journey.company_name || "This application"}{" "}
        <span className="font-normal text-subtle">— schedule an interview</span>
      </div>

      <div className="flex flex-wrap gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-widest text-subtle">Round</span>
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="bg-bg border border-border rounded px-2 py-1 text-xs max-w-[190px]"
          >
            {types.map((t) => (
              <option key={t.slug} value={t.slug}>
                {t.label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-widest text-subtle">Date</span>
          <input
            type="date"
            autoFocus
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="bg-bg border border-accent rounded px-2 py-1 text-xs"
          />
        </label>

        <label className="flex flex-col gap-1 flex-1 min-w-[160px]">
          <span className="text-[10px] uppercase tracking-widest text-subtle">
            Label — optional
          </span>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="With Tobias, VP Eng"
            className="bg-bg border border-border rounded px-2 py-1 text-xs"
          />
        </label>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={save}
          disabled={saving || !date}
          className="text-xs px-3 py-1.5 rounded border border-accent text-accent bg-accent/10 hover:bg-accent/20 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        <button
          onClick={onClose}
          disabled={saving}
          className="text-xs px-3 py-1.5 rounded border border-border text-subtle hover:text-err disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function Chip({ on, code, name, id }: { on: boolean; code: string; name: string; id: string }) {
  const cls = on
    ? "border-accent/40 text-accent bg-accent/10"
    : "border-border text-subtle/60";
  const chip = (
    <span
      title={on ? name : `${name} — not generated`}
      className={`w-7 h-5 grid place-items-center text-[9px] tracking-wider rounded border ${cls}`}
    >
      {code}
    </span>
  );
  return on ? <a href={`/jobs/${id}`}>{chip}</a> : chip;
}

/* ---------- progress strip ---------- */

function Strip({ journey }: { journey: Journey }) {
  const bySlot: Interview[][] = [[], [], [], [], [], []];
  journey.interviews.forEach((iv) => {
    if (iv.scheduled_at) bySlot[SLOT_OF[iv.interview_type] ?? 3].push(iv);
  });
  const outcome = OUTCOME_FIELDS.find(([field]) => journey[field]);

  return (
    <div className="flex gap-0.5 w-[108px]">
      {SLOT_LABELS.map((slotLabel, i) => {
        let cls = "border-border";
        let tip = `${slotLabel} · not reached`;

        if (i === 0 && journey.applied_at) {
          cls = "bg-accent border-accent";
          tip = `Applied · ${formatDate(journey.applied_at)}`;
        } else if (i === 5 && outcome) {
          cls = SEG_END[journey.status] ?? "bg-accent border-accent";
          tip = `Decision · ${outcome[1]} ${formatDate(journey[outcome[0]] as number)}`;
        } else if (i > 0 && i < 5 && bySlot[i].length) {
          cls = "bg-accent border-accent";
          tip = `${slotLabel} · ${bySlot[i]
            .map(
              (iv) =>
                `${iv.label ? `${iv.type_label} (${iv.label})` : iv.type_label} ${formatDate(
                  iv.scheduled_at
                )}`
            )
            .join(" · ")}`;
        }

        return <span key={slotLabel} title={tip} className={`flex-1 h-4 rounded-sm border ${cls}`} />;
      })}
    </div>
  );
}

/* ---------- drawer ---------- */

function Drawer({
  journey,
  types,
  onPatch,
  onRefresh,
}: {
  journey: Journey;
  types: InterviewType[];
  onPatch: (body: Record<string, unknown>) => void;
  onRefresh: () => void;
}) {
  const [notes, setNotes] = useState(journey.notes);
  const [saved, setSaved] = useState(false);
  const [eventDate, setEventDate] = useState("");
  const [eventText, setEventText] = useState("");

  useEffect(() => setNotes(journey.notes), [journey.notes]);

  async function mutate(url: string, init: RequestInit) {
    const r = await fetch(url, init);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    onRefresh();
  }

  const json = (body: unknown): RequestInit => ({
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  async function addRound() {
    await mutate(
      `/api/journeys/${journey.journey_id}/interviews`,
      json({ interview_type: "screening" })
    );
  }

  async function patchRound(interviewId: string, body: Record<string, unknown>) {
    await mutate(`/api/journeys/${journey.journey_id}/interviews/${interviewId}`, {
      ...json(body),
      method: "PATCH",
    });
  }

  async function addEvent() {
    const occurred = fromDateInput(eventDate);
    if (!eventText.trim() || !occurred) return;
    await mutate(
      `/api/journeys/${journey.journey_id}/events`,
      json({ occurred_at: occurred, text: eventText.trim() })
    );
    setEventDate("");
    setEventText("");
  }

  async function removeEvent(eventId: string) {
    await mutate(`/api/journeys/${journey.journey_id}/events/${eventId}`, {
      method: "DELETE",
    });
  }

  return (
    <div className="grid gap-px bg-border md:grid-cols-[minmax(280px,1.05fr)_minmax(190px,0.7fr)_minmax(300px,1.4fr)]">
      {/* every date that drives the status, in the order it happens */}
      <section className="bg-panel p-4 space-y-2.5 min-w-0">
        <Heading>Dates</Heading>

        <DateRow
          label="Submission"
          value={journey.applied_at}
          onSave={(v) => onPatch({ applied_at: v })}
        />

        <SubHeading>Interview rounds</SubHeading>
        {journey.interviews.length === 0 && (
          <p className="text-xs text-subtle italic">
            None yet — a round with a date makes this In Progress.
          </p>
        )}
        {journey.interviews.map((iv) => (
          <div key={iv.interview_id} className="flex items-center gap-2">
            <select
              value={iv.interview_type}
              onChange={(e) => patchRound(iv.interview_id, { interview_type: e.target.value })}
              className="bg-panel2 border border-border rounded px-1.5 py-0.5 text-xs max-w-[150px]"
            >
              {types.map((t) => (
                <option key={t.slug} value={t.slug}>
                  {t.label}
                </option>
              ))}
            </select>
            <DateCell
              value={iv.scheduled_at}
              onSave={(v) => patchRound(iv.interview_id, { scheduled_at: v })}
            />
            {iv.label && <span className="text-xs text-subtle truncate">{iv.label}</span>}
          </div>
        ))}
        <button
          onClick={addRound}
          className="self-start text-xs px-2.5 py-1 rounded border border-border text-subtle hover:border-accent hover:text-accent"
        >
          + Round
        </button>

        <SubHeading>Outcome</SubHeading>
        {OUTCOME_FIELDS.map(([field, label]) => (
          <DateRow
            key={field}
            label={label}
            value={journey[field] as number | null}
            onSave={(v) => onPatch({ [field]: v })}
            onClear={journey[field] ? () => onPatch({ [field]: null }) : undefined}
          />
        ))}
      </section>

      <section className="bg-panel p-4 space-y-1 min-w-0">
        <Heading>Artifacts</Heading>
        <ArtifactRow name="Cover letter" has={!!journey.cover_letter} id={journey.journey_id} />
        <ArtifactRow
          name="Briefing"
          has={journey.interviews.some((iv) => iv.briefing) || !!journey.interview_briefing}
          id={journey.journey_id}
        />
        <ArtifactRow
          name="Evaluation"
          has={
            journey.interviews.some((iv) => iv.evaluation_summary) ||
            !!journey.evaluation_summary
          }
          id={journey.journey_id}
        />
        <a
          href={`/jobs/${journey.journey_id}`}
          className="inline-block pt-2 text-[10px] tracking-wider text-accent hover:underline"
        >
          FULL DETAIL →
        </a>
      </section>

      <section className="bg-panel p-4 space-y-2 min-w-0">
        <div className="flex items-center justify-between">
          <Heading>Notes</Heading>
          {saved && <span className="text-[10px] tracking-widest text-ok">SAVED</span>}
        </div>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          onBlur={() => {
            if (notes === journey.notes) return;
            onPatch({ notes });
            setSaved(true);
            setTimeout(() => setSaved(false), 1200);
          }}
          rows={4}
          placeholder="What happened, what they said, what to remember."
          className="w-full text-sm bg-bg border border-border rounded px-2 py-1.5 resize-y leading-relaxed"
        />

        <Heading>Events</Heading>
        {journey.events.length === 0 && (
          <p className="text-xs text-subtle italic">Nothing logged yet.</p>
        )}
        <div className="space-y-1.5">
          {journey.events.map((ev) => (
            <div key={ev.event_id} className="flex gap-2.5 text-xs group/ev">
              <span className="text-subtle tabular-nums whitespace-nowrap">
                {formatDate(ev.occurred_at)}
              </span>
              <span className="flex-1 leading-relaxed">{ev.text}</span>
              <button
                onClick={() => removeEvent(ev.event_id)}
                className="text-subtle hover:text-err opacity-0 group-hover/ev:opacity-100"
                aria-label="Remove event"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
        <div className="flex gap-1.5">
          <input
            type="date"
            value={eventDate}
            onChange={(e) => setEventDate(e.target.value)}
            className="bg-bg border border-border rounded px-1.5 py-1 text-xs"
          />
          <input
            value={eventText}
            onChange={(e) => setEventText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addEvent()}
            placeholder="Sent a follow-up message…"
            className="flex-1 min-w-0 bg-bg border border-border rounded px-2 py-1 text-xs"
          />
          <button
            onClick={addEvent}
            className="text-xs px-2.5 py-1 rounded border border-border text-subtle hover:border-accent hover:text-accent"
          >
            Add
          </button>
        </div>
      </section>
    </div>
  );
}

function Heading({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-[10px] font-semibold uppercase tracking-widest text-subtle">
      {children}
    </h3>
  );
}

function SubHeading({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 pt-1 text-[10px] uppercase tracking-widest text-subtle">
      {children}
      <span className="flex-1 h-px bg-border" />
    </div>
  );
}

function ArtifactRow({ name, has, id }: { name: string; has: boolean; id: string }) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm py-1">
      <span>{name}</span>
      {has ? (
        <a href={`/jobs/${id}`} className="text-[10px] tracking-wider text-accent hover:underline">
          OPEN →
        </a>
      ) : (
        <span className="text-xs text-subtle">not generated</span>
      )}
    </div>
  );
}

function DateRow({
  label,
  value,
  onSave,
  onClear,
}: {
  label: string;
  value: number | null;
  onSave: (v: number | null) => void;
  onClear?: () => void;
}) {
  return (
    <div className="flex items-center gap-2.5 text-sm">
      <span className="w-24 shrink-0 text-subtle text-xs">{label}</span>
      <DateCell value={value} onSave={onSave} />
      {onClear && (
        <button
          onClick={onClear}
          className="text-subtle hover:text-err text-xs"
          aria-label={`Clear ${label.toLowerCase()}`}
        >
          ✕
        </button>
      )}
    </div>
  );
}

/* ---------- click-to-edit primitives ---------- */

function DateCell({
  value,
  onSave,
}: {
  value: number | null | undefined;
  onSave: (v: number | null) => void;
}) {
  const [editing, setEditing] = useState(false);

  if (editing) {
    return (
      <input
        type="date"
        autoFocus
        defaultValue={toDateInput(value)}
        onBlur={(e) => {
          setEditing(false);
          const next = fromDateInput(e.target.value);
          if (next !== (value ?? null)) onSave(next);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") setEditing(false);
        }}
        className="bg-panel2 border border-accent rounded px-1.5 py-0.5 text-xs"
      />
    );
  }

  return (
    <button
      onClick={() => setEditing(true)}
      className={`text-xs tabular-nums whitespace-nowrap hover:text-accent ${
        value ? "" : "text-subtle italic"
      }`}
    >
      {value ? formatDate(value) : "— set —"}
    </button>
  );
}

function EditableText({
  value,
  placeholder,
  empty,
  className = "",
  onSave,
}: {
  value: string;
  placeholder: string;
  empty?: string;
  className?: string;
  onSave: (v: string) => void;
}) {
  const [editing, setEditing] = useState(false);

  if (editing) {
    return (
      <input
        autoFocus
        defaultValue={value}
        placeholder={placeholder}
        onBlur={(e) => {
          setEditing(false);
          if (e.target.value !== value) onSave(e.target.value.trim());
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") setEditing(false);
        }}
        className="w-full bg-panel2 border border-accent rounded px-1.5 py-0.5 text-sm"
      />
    );
  }

  return (
    <button
      onClick={() => setEditing(true)}
      title="Click to edit"
      className={`block w-full text-left truncate hover:text-accent ${className} ${
        value ? "" : "text-subtle italic"
      }`}
    >
      {value || empty || placeholder}
    </button>
  );
}
