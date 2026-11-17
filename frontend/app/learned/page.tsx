"use client";

import { useCallback, useEffect, useState } from "react";
import Brand from "../../components/Brand";

type Item = {
  phrase?: string;
  reason?: string;
  weakness?: string;
  theme?: string;
  evidence?: string;
  count?: number;
  shared?: boolean;
  profile_id?: string;
};

type Playbook = {
  never_say: Item[];
  prefer_phrasing: Item[];
  recurring_hm_weaknesses: Item[];
  employer_feedback_themes: Item[];
  employer_strengths: Item[];
  employer_feedback_stats: { replies?: number; unspecific?: number; updated_at?: number };
  tone_notes: string;
  updated_at: number | null;
  shared: Record<string, Item[]>;
};

type Profile = { profile_id: string; name: string };

type Calibration = {
  advanced: { n: number; mean: number | null };
  rejected: { n: number; mean: number | null };
};

/* Two sources, never mixed on the page: what real employers wrote (evidence, relearned on
   each recorded reply) and what the tool found itself while drafting (the simulated hiring
   manager, your edits). */
type Category =
  | "employer_strengths"
  | "employer_feedback_themes"
  | "recurring_hm_weaknesses"
  | "never_say"
  | "prefer_phrasing";

const EMPLOYER_CATEGORIES: [Category, string, string][] = [
  ["employer_strengths", "What they valued", "Keep leading with these."],
  ["employer_feedback_themes", "What held you back", "The most common reasons first."],
];
const SIMULATED_CATEGORIES: [Category, string, string][] = [
  [
    "recurring_hm_weaknesses",
    "Recurring concerns",
    "What the simulated hiring manager keeps finding.",
  ],
  ["never_say", "Phrasings to avoid", "Consistently revised out of your drafts."],
  ["prefer_phrasing", "Phrasings to keep", "Consistently kept."],
];

function labelOf(item: Item): string {
  return item.theme || item.weakness || item.phrase || "";
}

function detailOf(item: Item): string {
  return item.evidence || item.reason || "";
}

export default function LearnedPage() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [playbook, setPlaybook] = useState<Playbook | null>(null);
  const [calibration, setCalibration] = useState<Calibration | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch("/api/profiles")
      .then((r) => r.json())
      .then((d) => {
        const rows: Profile[] = d.profiles ?? [];
        setProfiles(rows);
        if (rows.length) setActive(rows[0].profile_id);
      })
      .catch(() => setError("Could not load your profiles."));
  }, []);

  const load = useCallback(async (profileId: string) => {
    const [p, c] = await Promise.all([
      fetch(`/api/profiles/${profileId}/playbook`).then((r) => r.json()),
      fetch(`/api/profiles/${profileId}/calibration`).then((r) => r.json()),
    ]);
    setPlaybook(p);
    setCalibration(c);
  }, []);

  useEffect(() => {
    if (!active) return;
    load(active).catch(() => setError("Could not load what this profile has learned."));
  }, [active, load]);

  async function toggleShare(category: string, index: number, shared: boolean) {
    if (!active) return;
    setBusy(true);
    setError(null);
    try {
      const r = await fetch(
        `/api/profiles/${active}/playbook/${category}/${index}/share`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ shared }),
        },
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await load(active);
    } catch {
      setError("Could not change that.");
    } finally {
      setBusy(false);
    }
  }

  const activeName = profiles.find((p) => p.profile_id === active)?.name ?? "";
  const sharedCount = playbook
    ? Object.values(playbook.shared ?? {}).reduce((n, xs) => n + xs.length, 0)
    : 0;

  return (
    <main className="min-h-screen">
      <header className="h-14 px-6 flex items-center justify-between border-b border-border">
        <div className="flex items-center gap-4">
          <Brand />
          <span className="h-5 w-px bg-border" />
          <div className="font-semibold">Learned</div>
        </div>
        <a href="/jobs" className="text-sm text-subtle hover:text-accent">
          Applications
        </a>
      </header>

      <div className="max-w-3xl mx-auto p-6 space-y-6">
        <p className="text-sm text-subtle max-w-2xl">
          What the assistants have learned about you, per CV, from two sources kept apart: what
          real employers wrote to you, relearned each time you record a reply, and what the tool
          noticed itself while drafting — the simulated hiring manager and your own edits. Only
          the first is evidence. Promote a lesson and every profile reads it from the next draft
          onward.
        </p>

        {profiles.length > 1 && (
          <div className="flex gap-1.5 flex-wrap">
            {profiles.map((p) => (
              <button
                key={p.profile_id}
                onClick={() => setActive(p.profile_id)}
                aria-pressed={active === p.profile_id}
                className={`text-xs px-3 py-1 rounded-full border ${
                  active === p.profile_id
                    ? "border-accent text-accent bg-accent/10"
                    : "border-border text-subtle hover:text-text"
                }`}
              >
                {p.name}
              </button>
            ))}
          </div>
        )}

        {error && (
          <p className="text-sm text-err border border-err/40 rounded px-3 py-2">{error}</p>
        )}

        {playbook && sharedCount > 0 && (
          <p className="text-sm text-subtle border-l-2 border-ok bg-panel rounded-r px-3 py-2">
            <span className="text-ok">◆</span>{" "}
            <b className="text-text">
              {sharedCount} learning{sharedCount === 1 ? "" : "s"} from another CV
            </b>{" "}
            {sharedCount === 1 ? "is" : "are"} also read by {activeName}, because you promoted{" "}
            {sharedCount === 1 ? "it" : "them"}.
          </p>
        )}

        {playbook && (
          <EmployerGroup playbook={playbook}>
            {EMPLOYER_CATEGORIES.map(([key, title, hint]) => (
              <CategorySection
                key={key}
                category={key}
                title={title}
                hint={hint}
                playbook={playbook}
                profiles={profiles}
                activeName={activeName}
                busy={busy}
                onShare={toggleShare}
              />
            ))}
          </EmployerGroup>
        )}

        {playbook && (
          <SimulatedGroup
            empty={
              !playbook.tone_notes &&
              SIMULATED_CATEGORIES.every(
                ([k]) =>
                  (playbook[k] ?? []).length === 0 && (playbook.shared?.[k] ?? []).length === 0,
              ) &&
              (!calibration || calibration.advanced.n + calibration.rejected.n === 0)
            }
          >
            {SIMULATED_CATEGORIES.map(([key, title, hint]) => (
              <CategorySection
                key={key}
                category={key}
                title={title}
                hint={hint}
                playbook={playbook}
                profiles={profiles}
                activeName={activeName}
                busy={busy}
                onShare={toggleShare}
              />
            ))}
            {playbook.tone_notes && (
              <section className="space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-widest text-subtle">
                  Tone notes
                </h3>
                <p className="text-sm rounded border border-border bg-panel p-3 leading-relaxed">
                  {playbook.tone_notes}
                </p>
              </section>
            )}
            {calibration && <CalibrationPanel calibration={calibration} />}
          </SimulatedGroup>
        )}
      </div>
    </main>
  );
}

/* What real employers wrote: solid accent frame, and how many replies it rests on. */
function EmployerGroup({ playbook, children }: { playbook: Playbook; children: React.ReactNode }) {
  const stats = playbook.employer_feedback_stats ?? {};
  const replies = stats.replies ?? 0;
  const unspecific = stats.unspecific ?? 0;
  const empty = EMPLOYER_CATEGORIES.every(
    ([k]) => (playbook[k] ?? []).length === 0 && (playbook.shared?.[k] ?? []).length === 0,
  );
  return (
    <section className="rounded-lg border border-accent/40 bg-accent/5 p-4 space-y-4">
      <header className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="text-[11px] px-2 py-0.5 rounded-full border border-accent/40 bg-accent/10 text-accent">
            Real employers
          </span>
          <h2 className="text-sm font-semibold">What employers wrote to you</h2>
        </div>
        <p className="text-xs text-subtle">
          Learned again from every reply you record under Applications, mostly rejections. A
          rejection on its own teaches nothing: only what they wrote about you counts.
        </p>
        {replies > 0 && (
          <p className="text-xs text-subtle">
            From {replies} {replies === 1 ? "reply" : "replies"},{" "}
            {unspecific === 0
              ? "each with a specific reason"
              : `${unspecific} without a specific reason`}
            {stats.updated_at
              ? ` · updated ${new Date(stats.updated_at * 1000).toLocaleDateString(undefined, {
                  day: "numeric",
                  month: "long",
                })}`
              : ""}
          </p>
        )}
      </header>
      {empty ? (
        <p className="text-sm text-subtle italic">
          Nothing yet. Record what an employer wrote to you, for example with a rejection under
          Applications, and this updates within a minute.
        </p>
      ) : (
        children
      )}
    </section>
  );
}

/* The tool's own findings: dashed and muted, so they never read as evidence. */
function SimulatedGroup({ empty, children }: { empty: boolean; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-dashed border-border p-4 space-y-4">
      <header className="space-y-1">
        <div className="flex items-center gap-2">
          <span className="text-[11px] px-2 py-0.5 rounded-full border border-dashed border-border text-subtle">
            Simulated
          </span>
          <h2 className="text-sm font-semibold">What the tool noticed while drafting</h2>
        </div>
        <p className="text-xs text-subtle">
          The simulated hiring manager&apos;s verdicts and the edits you made to drafts. Useful,
          but a guess — not what an employer said.
        </p>
      </header>
      {empty ? (
        <p className="text-sm text-subtle italic">
          Nothing yet. This fills in as you finish cover letters and practise interviews.
        </p>
      ) : (
        children
      )}
    </section>
  );
}

function CategorySection({
  category,
  title,
  hint,
  playbook,
  profiles,
  activeName,
  busy,
  onShare,
}: {
  category: Category;
  title: string;
  hint: string;
  playbook: Playbook;
  profiles: Profile[];
  activeName: string;
  busy: boolean;
  onShare: (category: string, index: number, shared: boolean) => void;
}) {
  const own = playbook[category] ?? [];
  const inherited = playbook.shared?.[category] ?? [];
  if (own.length === 0 && inherited.length === 0) return null;
  return (
    <section className="space-y-2">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-xs font-semibold uppercase tracking-widest text-subtle">{title}</h3>
        <span className="text-xs text-subtle">{hint}</span>
      </div>

      {own.map((item, i) => (
        <div
          key={`own-${i}`}
          className={`rounded border p-3 space-y-2 ${
            item.shared ? "border-ok/30 bg-ok/5" : "border-border bg-panel"
          }`}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="text-sm">{labelOf(item)}</div>
            {item.count ? (
              <span className="shrink-0 text-[11px] text-subtle tabular-nums">
                {item.count === 1 ? "mentioned once" : `${item.count} employers`}
              </span>
            ) : null}
          </div>
          {detailOf(item) && (
            <div className="text-xs text-subtle border-l border-border pl-2.5">
              {detailOf(item)}
            </div>
          )}
          <div className="flex items-center justify-between gap-3">
            <span className="text-[11px] text-subtle">
              {item.shared ? "Read by every CV." : `Only ${activeName} uses this.`}
            </span>
            <button
              onClick={() => onShare(category, i, !item.shared)}
              disabled={busy}
              className={`text-[11px] px-2.5 py-0.5 rounded-full border disabled:opacity-50 ${
                item.shared
                  ? "border-ok/40 text-ok bg-ok/10"
                  : "border-border text-subtle hover:border-accent hover:text-accent"
              }`}
            >
              {item.shared ? "✓ Shared" : "Use for all profiles"}
            </button>
          </div>
        </div>
      ))}

      {inherited.map((item, i) => (
        <div key={`shared-${i}`} className="rounded border border-border border-dashed p-3 space-y-1">
          <div className="text-sm">{labelOf(item)}</div>
          {detailOf(item) && (
            <div className="text-xs text-subtle border-l border-border pl-2.5">
              {detailOf(item)}
            </div>
          )}
          <div className="text-[11px] text-subtle">
            Learned by{" "}
            {profiles.find((p) => p.profile_id === item.profile_id)?.name ?? "another CV"}, shared
            with this one.
          </div>
        </div>
      ))}
    </section>
  );
}

/* The most useful thing the app can tell you about its own evaluator, and it
   needs no new data — just its past verdicts split by what actually happened. */
function CalibrationPanel({ calibration }: { calibration: Calibration }) {
  const { advanced, rejected } = calibration;
  if (advanced.n === 0 && rejected.n === 0) return null;

  const gap =
    advanced.mean !== null && rejected.mean !== null
      ? Math.round((advanced.mean - rejected.mean) * 10) / 10
      : null;

  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-widest text-subtle">
        Is the evaluator honest?
      </h3>
      <div className="rounded border border-border bg-panel p-4 space-y-3">
        <Bar label="Rounds that advanced" stat={advanced} tone="bg-ok" />
        <Bar label="Rounds that were rejected" stat={rejected} tone="bg-err" />
        {gap !== null && (
          <p className="text-xs text-subtle leading-relaxed">
            <b className="text-text">{Math.abs(gap).toFixed(1)} points apart.</b>{" "}
            {Math.abs(gap) < 1
              ? "The evaluator barely separates rounds that worked from rounds that didn't — read its verdicts with that in mind."
              : "The evaluator does distinguish the two, so its verdicts carry some signal."}
          </p>
        )}
      </div>
    </section>
  );
}

function Bar({
  label,
  stat,
  tone,
}: {
  label: string;
  stat: { n: number; mean: number | null };
  tone: string;
}) {
  return (
    <div className="grid grid-cols-[150px_1fr_54px] gap-3 items-center text-xs">
      <span className="text-subtle">{label}</span>
      <span className="h-1.5 rounded-full bg-panel2 overflow-hidden">
        <span
          className={`block h-full rounded-full ${tone}`}
          style={{ width: `${((stat.mean ?? 0) / 10) * 100}%` }}
        />
      </span>
      <span className="text-right tabular-nums">
        {stat.mean ?? "—"} <span className="text-subtle">({stat.n})</span>
      </span>
    </div>
  );
}
