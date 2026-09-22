"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import Brand from "../components/Brand";

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

const NAV_LINKS = [
  { href: "/jobs", label: "Applications" },
  { href: "/learned", label: "Learned" },
  { href: "/profiles", label: "Profiles" },
  { href: "/dashboard", label: "Dashboard" },
  { href: "/settings", label: "Settings" },
];

const iconProps = {
  width: 19,
  height: 19,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

function DocumentIcon() {
  return (
    <svg {...iconProps}>
      <path d="M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7z" />
      <path d="M14 3v4h4" />
      <path d="M9.5 13h5M9.5 16.5h3" />
    </svg>
  );
}

function QuestionBubbleIcon() {
  return (
    <svg {...iconProps}>
      <path d="M20 4H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3v4l4.5-4H20a1 1 0 0 0 1-1V5a1 1 0 0 0-1-1z" />
      <path d="M10.2 8.4a1.9 1.9 0 0 1 3.6.8c0 1.3-1.8 1.5-1.8 2.8" />
      <path d="M12 13.9v.1" />
    </svg>
  );
}

function WaveformIcon() {
  return (
    <svg {...iconProps} strokeWidth={1.7}>
      <path d="M4 10.5v3M8 7v10M12 4.5v15M16 8.5v7M20 11v2" />
    </svg>
  );
}

function CompassIcon() {
  return (
    <svg {...iconProps}>
      <circle cx="12" cy="12" r="9" />
      <path d="M15.2 8.8 13.6 13.6 8.8 15.2l1.6-4.8z" />
    </svg>
  );
}

/** The three stages of a single application. Named, not numbered: the
 *  order is the natural one, but any of them can be the starting point. */
const TRACK: {
  type: AssistantType;
  title: string;
  phase: string;
  short: string;
  long: string;
  Icon: () => JSX.Element;
}[] = [
  {
    type: "cover_letter",
    title: "Cover Letter",
    phase: "Apply",
    short: "A letter for one role, not a template.",
    long: "Drafted for the specific role, then put through a simulated hiring-manager critique. Optional Q&A round.",
    Icon: DocumentIcon,
  },
  {
    type: "interview_prep",
    title: "Interview Prep",
    phase: "Prepare",
    short: "Walk in knowing what they'll ask.",
    long: "Likely questions, the stories worth rehearsing, and where a hiring manager will probe for doubt.",
    Icon: QuestionBubbleIcon,
  },
  {
    type: "interview_evaluator",
    title: "Interview Evaluator",
    phase: "Review",
    short: "Hear how the last one actually went.",
    long: "Your recording, transcribed locally, then scored: strengths, weaknesses, and a question-by-question breakdown.",
    Icon: WaveformIcon,
  },
];

const CARD_BASE =
  "relative z-10 rounded-2xl border border-subtle/30 text-left transition " +
  "hover:border-accent hover:-translate-y-0.5 motion-reduce:transform-none " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent " +
  "focus-visible:ring-offset-2 focus-visible:ring-offset-bg " +
  "disabled:opacity-50 disabled:cursor-not-allowed";

/* The shape of the search, pooled across profiles. Each one is a way into the
   table, already filtered — the number is both the summary and the door. */
type Summary = {
  total: number;
  applied: number;
  in_progress: number;
  quiet: number;
  on_hold: number;
  offer: number;
  rejected: number;
  withdrawn: number;
  draft: number;
  quiet_after_days: number;
};

/* Every status a journey can be in, so the row reads as a breakdown rather than
   a sample. Labels and tones track STATUS_META on the jobs page — the tile and
   the table it opens should not disagree about what a status is called.
   `{d}` is the configured quiet threshold, not a hardcoded 30. */
const COUNTERS: [keyof Summary, string, string, string][] = [
  ["applied", "Applied", "applied", "text-accent"],
  ["in_progress", "In progress", "in_progress", "text-warn"],
  ["quiet", "No reply {d}d+", "silent", "text-subtle"],
  ["on_hold", "On hold", "on_hold", "text-hold"],
  ["offer", "Offer", "offer", "text-ok"],
  ["rejected", "Rejected", "rejected", "text-err"],
  ["withdrawn", "Withdrawn", "dropped", "text-subtle"],
];

export default function LandingPage() {
  const router = useRouter();
  const [loading, setLoading] = useState<AssistantType | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [language, setLanguage] = useState("English");
  const [hasPendingUpdates, setHasPendingUpdates] = useState(false);
  const [summary, setSummary] = useState<Summary | null>(null);

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

    fetch("/api/journeys/summary")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setSummary(d))
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
    <div className="min-h-screen flex flex-col">
      <header className="flex flex-wrap items-center justify-between gap-6 border-b border-subtle/30 bg-panel/50 px-7 py-3.5">
        <Brand />

        <nav className="flex items-center gap-5">
          {NAV_LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="inline-flex items-center gap-1.5 rounded text-sm text-subtle hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
            >
              {link.label}
              {link.label === "Profiles" && hasPendingUpdates && (
                <span
                  className="h-1.5 w-1.5 rounded-full bg-accent"
                  title="You have profile updates to review."
                  aria-label="Profile updates to review"
                />
              )}
            </a>
          ))}
        </nav>
      </header>

      <main className="flex flex-1 items-center justify-center px-6 py-14">
        <div className="w-full max-w-5xl space-y-11">
          <div className="space-y-2.5 text-center">
            <h1 className="text-5xl font-semibold tracking-tight text-balance">
              Personal Career Assistant
            </h1>
            <p className="text-lg text-subtle">
              Specialised assistants for the hard parts of your job search.
            </p>
          </div>

          {summary && summary.total > 0 && (
            <div className="space-y-3.5">
              <div className="flex items-center gap-3.5">
                <p className="whitespace-nowrap font-mono text-[11px] uppercase tracking-[0.14em] text-subtle">
                  Application overview
                </p>
                <span className="h-px flex-1 bg-subtle/30" />
                <a
                  href="/jobs"
                  className="whitespace-nowrap rounded text-sm text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
                >
                  All {summary.total} applications →
                </a>
              </div>

              <div className="grid grid-cols-2 gap-px sm:grid-cols-4 lg:grid-cols-7">
                {COUNTERS.map(([key, label, filter, tone]) => (
                  <a
                    key={key}
                    href={`/jobs?status=${filter}`}
                    className="rounded-lg border border-subtle/25 bg-panel px-3.5 py-2.5 transition hover:border-accent hover:bg-panel2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
                  >
                    <div
                      className={`text-[22px] font-semibold leading-none tabular-nums ${tone}`}
                    >
                      {summary[key]}
                    </div>
                    <div className="mt-1 text-xs text-subtle">
                      {label.replace("{d}", String(summary.quiet_after_days))}
                    </div>
                  </a>
                ))}
              </div>
            </div>
          )}

          <div className="space-y-3.5">
            <div className="flex items-center gap-3.5">
              <p className="whitespace-nowrap font-mono text-[11px] uppercase tracking-[0.14em] text-subtle">
                Three stages of one application — start at any of them
              </p>
              <span className="h-px flex-1 bg-subtle/30" />
              {/* A parameter of the session you're about to start, not an app
                  preference — so it lives with the Start buttons. */}
              <span className="flex items-center gap-2">
                <label
                  htmlFor="language"
                  className="whitespace-nowrap font-mono text-[10.5px] uppercase tracking-[0.12em] text-subtle"
                >
                  Language
                </label>
                <select
                  id="language"
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  disabled={loading !== null}
                  className="rounded-lg border border-subtle/30 bg-panel2 px-2.5 py-1.5 text-sm disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
                >
                  {LANGUAGES.map((l) => (
                    <option key={l} value={l}>
                      {l}
                    </option>
                  ))}
                </select>
              </span>
            </div>

            <div className="relative grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
              {/* Sits behind the opaque cards, so it shows only in the gaps. */}
              <span
                aria-hidden
                className="absolute left-[8%] right-[8%] top-11 hidden h-px lg:block"
                style={{
                  background:
                    "linear-gradient(90deg, transparent, rgba(122,162,255,0.28) 12%, rgba(122,162,255,0.28) 88%, transparent)",
                }}
              />

              {TRACK.map((a) => (
                <button
                  key={a.type}
                  onClick={() => startSession(a.type)}
                  disabled={loading !== null}
                  className={`${CARD_BASE} group flex flex-col gap-3.5 bg-panel p-6 hover:bg-panel2`}
                >
                  <div className="flex items-center justify-between">
                    <span className="grid h-10 w-10 place-items-center rounded-xl bg-accent/10 text-accent transition group-hover:bg-accent/20">
                      <a.Icon />
                    </span>
                    <span className="font-mono text-[10.5px] uppercase tracking-[0.14em] text-subtle transition group-hover:text-accent">
                      {a.phase}
                    </span>
                  </div>

                  <div className="text-xl font-semibold tracking-tight">
                    {a.title}
                  </div>

                  {/* One-line promise by default; the detail cross-fades in on
                      hover inside a fixed-height box, so cards never resize. */}
                  <div className="relative h-16 text-sm leading-snug">
                    <span className="absolute inset-0 opacity-90 transition-opacity group-hover:opacity-0 group-focus-visible:opacity-0">
                      {a.short}
                    </span>
                    <span className="absolute inset-0 text-subtle opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
                      {a.long}
                    </span>
                  </div>

                  <div className="mt-auto text-sm text-accent">
                    {loading === a.type ? "Starting…" : "Start →"}
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Not a stage of an application — available with or without one. */}
          <button
            onClick={() => startSession("career_advisor")}
            disabled={loading !== null}
            className={`${CARD_BASE} group grid w-full grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2.5 bg-panel/50 p-5 hover:bg-panel sm:grid-cols-[auto_1fr_auto]`}
          >
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-accent/10 text-accent transition group-hover:bg-accent/20">
              <CompassIcon />
            </span>
            <span className="flex flex-col gap-0.5">
              <span className="text-xl font-semibold tracking-tight">
                Career Advisor
              </span>
              <span className="text-sm text-subtle">
                Talk through your experience any time, with or without a job on
                the table. Ask for a SWOT summary whenever you want one.
              </span>
            </span>
            <span className="col-start-2 whitespace-nowrap text-sm text-accent sm:col-start-3">
              {loading === "career_advisor"
                ? "Starting…"
                : "Talk to your Career Advisor →"}
            </span>
          </button>

          {error && (
            <p className="text-center text-sm text-err whitespace-pre-wrap">
              {error}
            </p>
          )}
        </div>
      </main>
    </div>
  );
}
