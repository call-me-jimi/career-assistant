"use client";

import { useEffect, useState } from "react";

type ProfileSummary = {
  profile_id: string;
  name: string;
  applicant_name: string | null;
  created_at: number;
  updated_at: number;
  pending_suggestion_count?: number;
};

type ProfileDetail = ProfileSummary & {
  cv_text: string;
  candidate_profile: any;
};

function formatDate(ts: number) {
  return new Date(ts * 1000).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function ProfilesPage() {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [expanded, setExpanded] = useState<ProfileDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/profiles")
      .then((r) => r.json())
      .then((d) => setProfiles(d.profiles))
      .catch(() => setError("Could not load profiles."));
  }, []);

  async function loadDetail(profile_id: string) {
    if (expanded?.profile_id === profile_id) {
      setExpanded(null);
      return;
    }
    setLoadingDetail(profile_id);
    try {
      const r = await fetch(`/api/profiles/${profile_id}`);
      if (!r.ok) throw new Error();
      setExpanded(await r.json());
    } catch {
      setError("Could not load profile detail.");
    } finally {
      setLoadingDetail(null);
    }
  }

  async function deleteProfile(profile_id: string) {
    if (!confirm("Delete this profile? This cannot be undone.")) return;
    setDeleting(profile_id);
    try {
      const r = await fetch(`/api/profiles/${profile_id}`, { method: "DELETE" });
      if (!r.ok) throw new Error();
      setProfiles((prev) => prev.filter((p) => p.profile_id !== profile_id));
      if (expanded?.profile_id === profile_id) setExpanded(null);
    } catch {
      setError("Could not delete profile.");
    } finally {
      setDeleting(null);
    }
  }

  return (
    <main className="min-h-screen">
      <header className="h-14 px-6 flex items-center justify-between border-b border-border">
        <div className="font-semibold">Profiles</div>
        <a href="/" className="text-xs text-accent hover:underline">← Home</a>
      </header>

      <div className="max-w-3xl mx-auto p-6 space-y-6">
      <p className="text-sm text-subtle">
        Your saved candidate profiles — each one pairs a CV with a structured candidate profile the
        assistant builds over time. Select a profile when starting a session to give the assistant
        context about you.
      </p>

      {error && <p className="text-sm text-err">{error}</p>}

      {profiles.length === 0 && !error && (
        <p className="text-subtle text-sm">No profiles saved yet.</p>
      )}

      <ul className="space-y-3">
        {profiles.map((p) => {
          const isExpanded = expanded?.profile_id === p.profile_id;
          return (
            <li
              key={p.profile_id}
              className="rounded-xl border border-subtle/30 bg-panel/40 overflow-hidden"
            >
              <div className="flex items-center justify-between px-5 py-4 gap-4">
                <button
                  className="flex-1 text-left space-y-0.5"
                  onClick={() => loadDetail(p.profile_id)}
                >
                  <div className="font-medium flex items-center gap-2">
                    <span>{p.name}</span>
                    {(p.pending_suggestion_count ?? 0) > 0 && (
                      <a
                        href={`/profiles/${p.profile_id}?tab=suggestions`}
                        className="px-2 py-0.5 rounded-full bg-accent text-bg text-xs font-semibold hover:opacity-80"
                        title="The assistant proposed edits to your candidate profile. Click to review and apply or reject them."
                        onClick={(e) => e.stopPropagation()}
                      >
                        {p.pending_suggestion_count} profile update
                        {p.pending_suggestion_count === 1 ? "" : "s"} to review
                      </a>
                    )}
                  </div>
                  <div className="text-sm text-subtle">
                    {p.applicant_name ?? "—"} &middot; saved {formatDate(p.created_at)}
                  </div>
                </button>

                <div className="flex items-center gap-3 shrink-0">
                  <a
                    href={`/profiles/${p.profile_id}`}
                    className="text-sm text-accent hover:underline"
                  >
                    Details →
                  </a>
                  <button
                    onClick={() => loadDetail(p.profile_id)}
                    className="text-sm text-accent hover:underline"
                  >
                    {loadingDetail === p.profile_id
                      ? "Loading…"
                      : isExpanded
                      ? "Collapse"
                      : "Review"}
                  </button>
                  <button
                    onClick={() => deleteProfile(p.profile_id)}
                    disabled={deleting === p.profile_id}
                    className="text-sm text-err hover:underline disabled:opacity-50"
                  >
                    {deleting === p.profile_id ? "Deleting…" : "Delete"}
                  </button>
                </div>
              </div>

              {isExpanded && expanded && (
                <div className="border-t border-subtle/20 px-5 py-4 space-y-4">
                  <section>
                    <h2 className="text-xs font-semibold uppercase tracking-widest text-subtle mb-2">
                      CV Text
                    </h2>
                    <pre className="text-sm whitespace-pre-wrap leading-relaxed max-h-64 overflow-y-auto rounded bg-panel/60 p-3 border border-subtle/20">
                      {expanded.cv_text || "—"}
                    </pre>
                  </section>

                  <section>
                    <h2 className="text-xs font-semibold uppercase tracking-widest text-subtle mb-2">
                      Candidate Profile
                    </h2>
                    <pre className="text-sm whitespace-pre-wrap leading-relaxed max-h-64 overflow-y-auto rounded bg-panel/60 p-3 border border-subtle/20">
                      {expanded.candidate_profile
                        ? typeof expanded.candidate_profile === "string"
                          ? expanded.candidate_profile
                          : JSON.stringify(expanded.candidate_profile, null, 2)
                        : "—"}
                    </pre>
                  </section>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      </div>
    </main>
  );
}
