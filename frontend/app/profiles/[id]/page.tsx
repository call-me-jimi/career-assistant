"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

type ProfileDetail = {
  profile_id: string;
  name: string;
  cv_text: string;
  candidate_profile: any;
  created_at: number;
  updated_at: number;
};

type PlaybookItem = { phrase?: string; reason?: string; count?: number };
type WeaknessItem = { weakness?: string; count?: number; last_seen?: string };

type Playbook = {
  never_say: PlaybookItem[];
  prefer_phrasing: PlaybookItem[];
  recurring_hm_weaknesses: WeaknessItem[];
  tone_notes: string;
  updated_at: number | null;
};

type Suggestion = {
  id: number;
  profile_id: string;
  kind: string;
  diff: { before: string; after: string; rationale: string };
  confidence: number;
  status: string;
  created_at: number;
};

type Tab = "overview" | "playbook" | "suggestions";

const LIST_CATEGORIES: ("never_say" | "prefer_phrasing" | "recurring_hm_weaknesses")[] = [
  "never_say",
  "prefer_phrasing",
  "recurring_hm_weaknesses",
];

const CATEGORY_LABELS: Record<(typeof LIST_CATEGORIES)[number], string> = {
  never_say: "Never say",
  prefer_phrasing: "Prefer phrasing",
  recurring_hm_weaknesses: "Recurring HM concerns",
};

function formatDate(ts: number | null | undefined) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

export default function ProfileDetailPage() {
  const params = useParams<{ id: string }>();
  const profileId = params.id;

  const [tab, setTab] = useState<Tab>("overview");
  const [profile, setProfile] = useState<ProfileDetail | null>(null);
  const [playbook, setPlaybook] = useState<Playbook | null>(null);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function loadAll() {
    setLoading(true);
    setError(null);
    try {
      const [pRes, pbRes, sRes] = await Promise.all([
        fetch(`/api/profiles/${profileId}`),
        fetch(`/api/profiles/${profileId}/playbook`),
        fetch(`/api/profiles/${profileId}/suggestions`),
      ]);
      if (!pRes.ok) throw new Error(`profile: HTTP ${pRes.status}`);
      if (!pbRes.ok) throw new Error(`playbook: HTTP ${pbRes.status}`);
      if (!sRes.ok) throw new Error(`suggestions: HTTP ${sRes.status}`);
      setProfile(await pRes.json());
      setPlaybook(await pbRes.json());
      const sJson = await sRes.json();
      setSuggestions(sJson.suggestions || []);
    } catch (e: any) {
      setError(e.message || "Failed to load profile.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (profileId) loadAll();
  }, [profileId]);

  async function approveSuggestion(id: number) {
    setBusy(`approve-${id}`);
    try {
      const r = await fetch(`/api/profiles/${profileId}/suggestions/${id}/approve`, {
        method: "POST",
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await loadAll();
    } catch (e: any) {
      setError(e.message || "Approve failed.");
    } finally {
      setBusy(null);
    }
  }

  async function rejectSuggestion(id: number) {
    setBusy(`reject-${id}`);
    try {
      const r = await fetch(`/api/profiles/${profileId}/suggestions/${id}/reject`, {
        method: "POST",
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setSuggestions((prev) => prev.filter((s) => s.id !== id));
    } catch (e: any) {
      setError(e.message || "Reject failed.");
    } finally {
      setBusy(null);
    }
  }

  async function removePlaybookItem(category: string, index: number) {
    setBusy(`playbook-${category}-${index}`);
    try {
      const r = await fetch(
        `/api/profiles/${profileId}/playbook/${category}/${index}`,
        { method: "DELETE" },
      );
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await loadAll();
    } catch (e: any) {
      setError(e.message || "Remove failed.");
    } finally {
      setBusy(null);
    }
  }

  if (loading) {
    return <main className="min-h-screen p-8 text-subtle">Loading…</main>;
  }

  if (!profile) {
    return (
      <main className="min-h-screen p-8 max-w-3xl mx-auto space-y-4">
        <p className="text-err">{error || "Profile not found."}</p>
        <a href="/profiles" className="text-sm text-accent hover:underline">
          ← Back to profiles
        </a>
      </main>
    );
  }

  return (
    <main className="min-h-screen px-6 py-10 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{profile.name}</h1>
          <div className="text-sm text-subtle">
            Last updated {formatDate(profile.updated_at)}
          </div>
        </div>
        <a href="/profiles" className="text-sm text-accent hover:underline">
          ← Profiles
        </a>
      </div>

      {error && (
        <p className="text-sm text-err border border-err/40 rounded px-3 py-2">{error}</p>
      )}

      <nav className="flex gap-2 border-b border-subtle/30">
        <TabButton active={tab === "overview"} onClick={() => setTab("overview")}>
          Overview
        </TabButton>
        <TabButton active={tab === "playbook"} onClick={() => setTab("playbook")}>
          Playbook
        </TabButton>
        <TabButton active={tab === "suggestions"} onClick={() => setTab("suggestions")}>
          Suggestions
          {suggestions.length > 0 && (
            <span className="ml-2 px-2 py-0.5 rounded-full bg-accent text-bg text-xs font-semibold">
              {suggestions.length}
            </span>
          )}
        </TabButton>
      </nav>

      {tab === "overview" && <OverviewTab profile={profile} />}
      {tab === "playbook" && (
        <PlaybookTab
          playbook={playbook}
          onRemove={removePlaybookItem}
          busy={busy}
        />
      )}
      {tab === "suggestions" && (
        <SuggestionsTab
          suggestions={suggestions}
          onApprove={approveSuggestion}
          onReject={rejectSuggestion}
          busy={busy}
        />
      )}
    </main>
  );
}

function TabButton({
  active,
  children,
  onClick,
}: {
  active: boolean;
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={
        "px-4 py-2 text-sm font-medium border-b-2 -mb-px " +
        (active
          ? "border-accent text-accent"
          : "border-transparent text-subtle hover:text-fg")
      }
    >
      {children}
    </button>
  );
}

function OverviewTab({ profile }: { profile: ProfileDetail }) {
  const cp =
    typeof profile.candidate_profile === "string"
      ? profile.candidate_profile
      : JSON.stringify(profile.candidate_profile, null, 2);
  return (
    <div className="space-y-4">
      <Section title="Candidate Profile">
        <pre className="text-sm whitespace-pre-wrap leading-relaxed rounded bg-panel/60 p-3 border border-subtle/20 max-h-96 overflow-y-auto">
          {cp || "—"}
        </pre>
      </Section>
      <Section title="CV Text">
        <pre className="text-sm whitespace-pre-wrap leading-relaxed rounded bg-panel/60 p-3 border border-subtle/20 max-h-96 overflow-y-auto">
          {profile.cv_text || "—"}
        </pre>
      </Section>
    </div>
  );
}

function PlaybookTab({
  playbook,
  onRemove,
  busy,
}: {
  playbook: Playbook | null;
  onRemove: (category: string, index: number) => void;
  busy: string | null;
}) {
  if (!playbook) return <p className="text-subtle text-sm">No playbook yet.</p>;

  const isEmpty =
    playbook.never_say.length === 0 &&
    playbook.prefer_phrasing.length === 0 &&
    playbook.recurring_hm_weaknesses.length === 0 &&
    !playbook.tone_notes;

  return (
    <div className="space-y-4">
      {isEmpty && (
        <p className="text-sm text-subtle">
          No learned guidance yet. The playbook populates automatically after each cover-letter
          session once you've revised a draft or the hiring-manager simulator has flagged
          recurring weaknesses.
        </p>
      )}

      {playbook.tone_notes && (
        <Section title="Tone notes">
          <p className="text-sm whitespace-pre-wrap rounded bg-panel/60 p-3 border border-subtle/20">
            {playbook.tone_notes}
          </p>
        </Section>
      )}

      {LIST_CATEGORIES.map((cat) => {
        const items = playbook[cat] as Array<PlaybookItem | WeaknessItem>;
        if (!items || items.length === 0) return null;
        return (
          <Section key={cat} title={CATEGORY_LABELS[cat]}>
            <ul className="space-y-2">
              {items.map((item, i) => {
                const label =
                  "phrase" in item && item.phrase
                    ? `"${item.phrase}"`
                    : "weakness" in item && item.weakness
                    ? item.weakness
                    : "(empty)";
                const reason =
                  ("reason" in item && item.reason) ||
                  ("last_seen" in item && item.last_seen) ||
                  "";
                const count = item.count ?? 0;
                const busyKey = `playbook-${cat}-${i}`;
                return (
                  <li
                    key={i}
                    className="rounded bg-panel/60 p-3 border border-subtle/20 flex items-start justify-between gap-3"
                  >
                    <div className="text-sm min-w-0 flex-1">
                      <div className="break-words">{label}</div>
                      {reason && (
                        <div className="text-subtle text-xs mt-1 break-words">{reason}</div>
                      )}
                      {count > 0 && (
                        <div className="text-subtle text-xs mt-1">seen {count}×</div>
                      )}
                    </div>
                    <button
                      onClick={() => onRemove(cat, i)}
                      disabled={busy === busyKey}
                      className="text-xs text-subtle hover:text-err disabled:opacity-50 shrink-0"
                    >
                      {busy === busyKey ? "Removing…" : "remove"}
                    </button>
                  </li>
                );
              })}
            </ul>
          </Section>
        );
      })}

      {playbook.updated_at && (
        <div className="text-xs text-subtle">
          Last synthesized {formatDate(playbook.updated_at)}
        </div>
      )}
    </div>
  );
}

function SuggestionsTab({
  suggestions,
  onApprove,
  onReject,
  busy,
}: {
  suggestions: Suggestion[];
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
  busy: string | null;
}) {
  if (suggestions.length === 0) {
    return (
      <p className="text-subtle text-sm">
        No pending suggestions. The assistant queues proposed edits here after it spots a
        consistent pattern across your cover-letter revisions.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {suggestions.map((s) => (
        <div
          key={s.id}
          className="rounded-xl border border-subtle/30 bg-panel/40 p-4 space-y-3"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="text-sm">
              <div className="font-medium">Proposed edit to your profile statement</div>
              <div className="text-subtle text-xs">
                Confidence: {s.confidence} signal{s.confidence === 1 ? "" : "s"} · created{" "}
                {formatDate(s.created_at)}
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => onApprove(s.id)}
                disabled={busy === `approve-${s.id}`}
                className="text-sm px-3 py-1 rounded bg-accent text-bg font-medium hover:opacity-90 disabled:opacity-50"
              >
                {busy === `approve-${s.id}` ? "Applying…" : "Apply"}
              </button>
              <button
                onClick={() => onReject(s.id)}
                disabled={busy === `reject-${s.id}`}
                className="text-sm px-3 py-1 rounded border border-subtle/40 hover:text-err disabled:opacity-50"
              >
                {busy === `reject-${s.id}` ? "…" : "Reject"}
              </button>
            </div>
          </div>

          {s.diff.rationale && (
            <p className="text-sm text-subtle italic">{s.diff.rationale}</p>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <div className="text-xs uppercase tracking-widest text-subtle mb-1">
                Current
              </div>
              <pre className="text-xs whitespace-pre-wrap rounded bg-panel/60 p-3 border border-subtle/20 max-h-64 overflow-y-auto">
                {s.diff.before || "—"}
              </pre>
            </div>
            <div>
              <div className="text-xs uppercase tracking-widest text-accent mb-1">
                Proposed
              </div>
              <pre className="text-xs whitespace-pre-wrap rounded bg-panel/60 p-3 border border-accent/30 max-h-64 overflow-y-auto">
                {s.diff.after || "—"}
              </pre>
            </div>
          </div>
        </div>
      ))}
    </div>
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
