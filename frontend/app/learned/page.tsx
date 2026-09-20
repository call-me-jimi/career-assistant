"use client";

import { useCallback, useEffect, useState } from "react";
import Brand from "../../components/Brand";

type Item = {
  phrase?: string;
  reason?: string;
  weakness?: string;
  theme?: string;
  evidence?: string;
  shared?: boolean;
  profile_id?: string;
};

type Playbook = {
  never_say: Item[];
  prefer_phrasing: Item[];
  recurring_hm_weaknesses: Item[];
  employer_feedback_themes: Item[];
  tone_notes: string;
  updated_at: number | null;
  shared: Record<string, Item[]>;
};

type Profile = { profile_id: string; name: string };

type Calibration = {
  advanced: { n: number; mean: number | null };
  rejected: { n: number; mean: number | null };
};

/* Ordered by how much a lesson is worth reading: what real employers said first,
   then what the simulated hiring manager kept finding, then wording. */
const CATEGORIES: [keyof Playbook & string, string, string][] = [
  [
    "employer_feedback_themes",
    "What employers said",
    "Themes across the rejections you recorded.",
  ],
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
          What the assistants have picked up, per CV. A lesson belongs to the profile that
          earned it — promote one and every profile reads it from the next draft onward.
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

        {playbook &&
          CATEGORIES.map(([key, title, hint]) => {
            const own = (playbook[key] as Item[]) ?? [];
            const inherited = playbook.shared?.[key] ?? [];
            if (own.length === 0 && inherited.length === 0) return null;
            return (
              <section key={key} className="space-y-2">
                <div className="flex items-baseline justify-between gap-3">
                  <h2 className="text-xs font-semibold uppercase tracking-widest text-subtle">
                    {title}
                  </h2>
                  <span className="text-xs text-subtle">{hint}</span>
                </div>

                {own.map((item, i) => (
                  <div
                    key={`own-${i}`}
                    className={`rounded border p-3 space-y-2 ${
                      item.shared ? "border-ok/30 bg-ok/5" : "border-border bg-panel"
                    }`}
                  >
                    <div className="text-sm">{labelOf(item)}</div>
                    {detailOf(item) && (
                      <div className="text-xs text-subtle border-l border-border pl-2.5">
                        {detailOf(item)}
                      </div>
                    )}
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-[11px] text-subtle">
                        {item.shared
                          ? "Read by every CV."
                          : `Only ${activeName} uses this.`}
                      </span>
                      <button
                        onClick={() => toggleShare(key, i, !item.shared)}
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
                  <div
                    key={`shared-${i}`}
                    className="rounded border border-border border-dashed p-3 space-y-1"
                  >
                    <div className="text-sm">{labelOf(item)}</div>
                    {detailOf(item) && (
                      <div className="text-xs text-subtle border-l border-border pl-2.5">
                        {detailOf(item)}
                      </div>
                    )}
                    <div className="text-[11px] text-subtle">
                      Learned by{" "}
                      {profiles.find((p) => p.profile_id === item.profile_id)?.name ??
                        "another CV"}
                      , shared with this one.
                    </div>
                  </div>
                ))}
              </section>
            );
          })}

        {playbook && playbook.tone_notes && (
          <section className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-widest text-subtle">
              Tone notes
            </h2>
            <p className="text-sm rounded border border-border bg-panel p-3 leading-relaxed">
              {playbook.tone_notes}
            </p>
          </section>
        )}

        {calibration && <CalibrationPanel calibration={calibration} />}

        {playbook &&
          sharedCount === 0 &&
          CATEGORIES.every(([key]) => ((playbook[key] as Item[]) ?? []).length === 0) && (
            <p className="text-sm text-subtle italic">
              Nothing learned for {activeName} yet. Record what an employer told you on a
              rejection and this fills in — the assistants only learn from what you paste.
            </p>
          )}
      </div>
    </main>
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
      <h2 className="text-xs font-semibold uppercase tracking-widest text-subtle">
        Is the evaluator honest?
      </h2>
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
