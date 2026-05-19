"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";

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

type EditingItem = { category: string; index: number };
type AddingItem = { category: string };
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
  const searchParams = useSearchParams();
  const profileId = params.id;

  const initialTab = (searchParams.get("tab") as Tab | null) ?? "overview";
  const [tab, setTab] = useState<Tab>(initialTab);
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
          profileId={profileId}
          playbook={playbook}
          onRemove={removePlaybookItem}
          busy={busy}
          onRefresh={loadAll}
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
  profileId,
  playbook,
  onRemove,
  busy,
  onRefresh,
}: {
  profileId: string;
  playbook: Playbook | null;
  onRemove: (category: string, index: number) => void;
  busy: string | null;
  onRefresh: () => void;
}) {
  const [draft, setDraft] = useState<Playbook | null>(playbook);
  const [editingItem, setEditingItem] = useState<EditingItem | null>(null);
  const [addingItem, setAddingItem] = useState<AddingItem | null>(null);
  const [editingTone, setEditingTone] = useState(false);
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  // Sync draft when playbook prop changes (e.g. after reload)
  useEffect(() => {
    setDraft(playbook);
    setEditingItem(null);
    setAddingItem(null);
    setEditingTone(false);
  }, [playbook]);

  async function savePlaybook(updated: Playbook) {
    setSaving(true);
    setLocalError(null);
    try {
      const r = await fetch(`/api/profiles/${profileId}/playbook`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updated),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      onRefresh();
    } catch (e: any) {
      setLocalError(e.message || "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  if (!draft) return <p className="text-subtle text-sm">No playbook yet.</p>;

  const isEmpty =
    draft.never_say.length === 0 &&
    draft.prefer_phrasing.length === 0 &&
    draft.recurring_hm_weaknesses.length === 0 &&
    !draft.tone_notes;

  function getItemLabel(cat: string, item: PlaybookItem | WeaknessItem) {
    if ("phrase" in item && item.phrase) return item.phrase;
    if ("weakness" in item && item.weakness) return item.weakness;
    return "";
  }

  function getItemReason(item: PlaybookItem | WeaknessItem) {
    if ("reason" in item && item.reason) return item.reason;
    if ("last_seen" in item && item.last_seen) return item.last_seen;
    return "";
  }

  function updateItem(cat: string, index: number, label: string, reason: string) {
    const updated = { ...draft! };
    const isWeakness = cat === "recurring_hm_weaknesses";
    const items = [...(updated[cat as keyof Playbook] as any[])];
    const existing = items[index];
    items[index] = isWeakness
      ? { ...existing, weakness: label }
      : { ...existing, phrase: label, reason };
    (updated as any)[cat] = items;
    setDraft(updated);
    return updated;
  }

  function addItem(cat: string, label: string, reason: string) {
    const updated = { ...draft! };
    const isWeakness = cat === "recurring_hm_weaknesses";
    const items = [...(updated[cat as keyof Playbook] as any[])];
    items.push(isWeakness ? { weakness: label } : { phrase: label, reason });
    (updated as any)[cat] = items;
    setDraft(updated);
    return updated;
  }

  return (
    <div className="space-y-4">
      {localError && (
        <p className="text-sm text-err border border-err/40 rounded px-3 py-2">{localError}</p>
      )}

      {isEmpty && !editingTone && (
        <p className="text-sm text-subtle">
          No learned guidance yet. The playbook populates automatically after each cover-letter
          session once you've revised a draft or the hiring-manager simulator has flagged
          recurring weaknesses.
        </p>
      )}

      {/* Tone notes */}
      <Section title="Tone notes">
        {editingTone ? (
          <ToneEditor
            value={draft.tone_notes}
            saving={saving}
            onSave={(val) => {
              const updated = { ...draft, tone_notes: val };
              setDraft(updated);
              setEditingTone(false);
              savePlaybook(updated);
            }}
            onCancel={() => setEditingTone(false)}
          />
        ) : (
          <div className="flex items-start gap-2">
            <p className="text-sm whitespace-pre-wrap rounded bg-panel/60 p-3 border border-subtle/20 flex-1 min-h-[2.5rem]">
              {draft.tone_notes || <span className="text-subtle italic">None</span>}
            </p>
            <button
              onClick={() => setEditingTone(true)}
              className="text-xs text-subtle hover:text-fg shrink-0 mt-3"
            >
              edit
            </button>
          </div>
        )}
      </Section>

      {LIST_CATEGORIES.map((cat) => {
        const items = draft[cat] as Array<PlaybookItem | WeaknessItem>;
        const isWeakness = cat === "recurring_hm_weaknesses";
        const isAdding = addingItem?.category === cat;

        return (
          <Section key={cat} title={CATEGORY_LABELS[cat]}>
            <ul className="space-y-2">
              {items.map((item, i) => {
                const isEditing = editingItem?.category === cat && editingItem.index === i;
                const label = getItemLabel(cat, item);
                const reason = getItemReason(item);
                const count = item.count ?? 0;
                const busyKey = `playbook-${cat}-${i}`;

                if (isEditing) {
                  return (
                    <li key={i}>
                      <ItemEditor
                        initialLabel={label}
                        initialReason={reason}
                        isWeakness={isWeakness}
                        saving={saving}
                        onSave={(l, r) => {
                          const updated = updateItem(cat, i, l, r);
                          setEditingItem(null);
                          savePlaybook(updated);
                        }}
                        onCancel={() => setEditingItem(null)}
                      />
                    </li>
                  );
                }

                return (
                  <li
                    key={i}
                    className="rounded bg-panel/60 p-3 border border-subtle/20 flex items-start justify-between gap-3"
                  >
                    <div className="text-sm min-w-0 flex-1">
                      <div className="break-words">{label || <span className="text-subtle italic">(empty)</span>}</div>
                      {reason && (
                        <div className="text-subtle text-xs mt-1 break-words">{reason}</div>
                      )}
                      {count > 0 && (
                        <div className="text-subtle text-xs mt-1">seen {count}×</div>
                      )}
                    </div>
                    <div className="flex gap-3 shrink-0">
                      <button
                        onClick={() => setEditingItem({ category: cat, index: i })}
                        disabled={!!busy || saving}
                        className="text-xs text-subtle hover:text-fg disabled:opacity-50"
                      >
                        edit
                      </button>
                      <button
                        onClick={() => onRemove(cat, i)}
                        disabled={busy === busyKey || saving}
                        className="text-xs text-subtle hover:text-err disabled:opacity-50"
                      >
                        {busy === busyKey ? "…" : "remove"}
                      </button>
                    </div>
                  </li>
                );
              })}

              {isAdding && (
                <li>
                  <ItemEditor
                    initialLabel=""
                    initialReason=""
                    isWeakness={isWeakness}
                    saving={saving}
                    onSave={(l, r) => {
                      if (!l.trim()) { setAddingItem(null); return; }
                      const updated = addItem(cat, l, r);
                      setAddingItem(null);
                      savePlaybook(updated);
                    }}
                    onCancel={() => setAddingItem(null)}
                  />
                </li>
              )}
            </ul>

            {!isAdding && (
              <button
                onClick={() => { setAddingItem({ category: cat }); setEditingItem(null); }}
                disabled={saving}
                className="mt-2 text-xs text-subtle hover:text-fg disabled:opacity-50"
              >
                + add
              </button>
            )}
          </Section>
        );
      })}

      {draft.updated_at && (
        <div className="text-xs text-subtle">
          Last synthesized {formatDate(draft.updated_at)}
        </div>
      )}
    </div>
  );
}

function ItemEditor({
  initialLabel,
  initialReason,
  isWeakness,
  saving,
  onSave,
  onCancel,
}: {
  initialLabel: string;
  initialReason: string;
  isWeakness: boolean;
  saving: boolean;
  onSave: (label: string, reason: string) => void;
  onCancel: () => void;
}) {
  const [label, setLabel] = useState(initialLabel);
  const [reason, setReason] = useState(initialReason);
  return (
    <div className="rounded bg-panel/60 p-3 border border-accent/30 space-y-2">
      <input
        autoFocus
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        placeholder={isWeakness ? "Concern…" : "Phrase…"}
        className="w-full text-sm bg-transparent border border-subtle/30 rounded px-2 py-1 focus:outline-none focus:border-accent"
      />
      {!isWeakness && (
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="Reason (optional)…"
          className="w-full text-sm bg-transparent border border-subtle/30 rounded px-2 py-1 focus:outline-none focus:border-accent"
        />
      )}
      <div className="flex gap-2">
        <button
          onClick={() => onSave(label, reason)}
          disabled={saving}
          className="text-xs px-3 py-1 rounded bg-accent text-bg font-medium hover:opacity-90 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        <button
          onClick={onCancel}
          disabled={saving}
          className="text-xs px-3 py-1 rounded border border-subtle/40 hover:text-err disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function ToneEditor({
  value,
  saving,
  onSave,
  onCancel,
}: {
  value: string;
  saving: boolean;
  onSave: (val: string) => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState(value);
  return (
    <div className="space-y-2">
      <textarea
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        className="w-full text-sm bg-transparent border border-accent/30 rounded px-2 py-1 focus:outline-none focus:border-accent resize-y"
      />
      <div className="flex gap-2">
        <button
          onClick={() => onSave(text)}
          disabled={saving}
          className="text-xs px-3 py-1 rounded bg-accent text-bg font-medium hover:opacity-90 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        <button
          onClick={onCancel}
          disabled={saving}
          className="text-xs px-3 py-1 rounded border border-subtle/40 hover:text-err disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
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
  const [viewMode, setViewMode] = useState<"proposed" | "diff">("proposed");

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
      <div className="flex items-center gap-1 self-start rounded-lg border border-subtle/30 p-0.5 w-fit text-xs">
        <button
          onClick={() => setViewMode("proposed")}
          className={
            "px-3 py-1 rounded-md font-medium transition-colors " +
            (viewMode === "proposed"
              ? "bg-accent text-bg"
              : "text-subtle hover:text-fg")
          }
        >
          Proposed
        </button>
        <button
          onClick={() => setViewMode("diff")}
          className={
            "px-3 py-1 rounded-md font-medium transition-colors " +
            (viewMode === "diff"
              ? "bg-accent text-bg"
              : "text-subtle hover:text-fg")
          }
        >
          Diff
        </button>
      </div>

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

          {viewMode === "proposed" ? (
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
          ) : (
            <div>
              <div className="text-xs uppercase tracking-widest text-subtle mb-1">
                Changes
              </div>
              <DiffView before={s.diff.before} after={s.diff.after} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

type DiffToken = { text: string; type: "equal" | "remove" | "add" };

function computeWordDiff(before: string, after: string): DiffToken[] {
  const a = before.split(/(\s+)/);
  const b = after.split(/(\s+)/);
  const m = a.length, n = b.length;

  // LCS table
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = 1; i <= m; i++)
    for (let j = 1; j <= n; j++)
      dp[i][j] = a[i - 1] === b[j - 1] ? dp[i - 1][j - 1] + 1 : Math.max(dp[i - 1][j], dp[i][j - 1]);

  const result: DiffToken[] = [];
  function backtrack(i: number, j: number) {
    if (i === 0 && j === 0) return;
    if (i > 0 && j > 0 && a[i - 1] === b[j - 1]) {
      backtrack(i - 1, j - 1);
      result.push({ text: a[i - 1], type: "equal" });
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      backtrack(i, j - 1);
      result.push({ text: b[j - 1], type: "add" });
    } else {
      backtrack(i - 1, j);
      result.push({ text: a[i - 1], type: "remove" });
    }
  }
  backtrack(m, n);
  return result;
}

function DiffView({ before, after }: { before: string; after: string }) {
  const tokens = computeWordDiff(before || "", after || "");
  return (
    <pre className="text-xs whitespace-pre-wrap rounded bg-panel/60 p-3 border border-subtle/20 max-h-64 overflow-y-auto leading-relaxed">
      {tokens.map((tok, i) => {
        if (tok.type === "equal") return <span key={i}>{tok.text}</span>;
        if (tok.type === "remove")
          return (
            <span
              key={i}
              style={{ backgroundColor: "rgba(239,68,68,0.18)", color: "rgb(248,113,113)" }}
              className="line-through"
            >
              {tok.text}
            </span>
          );
        return (
          <span
            key={i}
            style={{ backgroundColor: "rgba(34,197,94,0.18)", color: "rgb(74,222,128)" }}
          >
            {tok.text}
          </span>
        );
      })}
    </pre>
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
